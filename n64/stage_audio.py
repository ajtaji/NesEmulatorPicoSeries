"""Stage single-CPU bus and APU timing paths for the Nintendo 64."""

import re


SYNCHRONOUS_BRIDGE = """Procedure.i NesPost(command.i, addr.i, value.i, stamp.i)
  WorkerCommand(command,addr,value,stamp)
  QSent=QSent+1 : QComplete=QSent
  ProcedureReturn QSent
EndProcedure
Procedure.i NesRpc(command.i, addr.i, value.i, stamp.i)
  NesPost(command,addr,value,stamp)
  NesRpcCalls=NesRpcCalls+1
  ProcedureReturn QResult
EndProcedure"""


def replace(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise ValueError(f"N64 audio staging expected a single occurrence of {old!r}")
    return source.replace(old, new)


def stage_audio(name: str, source: str) -> str:
    if name == "bridge":
        shared = re.search(r"^Procedure\.i NesPost\(.*?^Procedure\.i NesRpc\(.*?^EndProcedure",
                           source, re.M | re.S)
        if not shared:
            raise ValueError("N64 synchronous bridge expected NesPost and NesRpc")
        return replace(source, shared[0], SYNCHRONOUS_BRIDGE)
    if name == "worker":
        # Preserve command deadlines and mapper/APU/PPU order. The N64 build
        # has no second worker to wait for or per-command timing display.
        source = replace(source, "Procedure PpuSync(stamp.i)\n  Protected dt.i, timer.i",
                         "Procedure PpuSync(stamp.i)\n  Protected dt.i")
        source = replace(source, "    timer=NesHostUs()\n    PpuAdvance(dt)\n"
                         "    WorkerPpuUs=WorkerPpuUs+NesHostUs()-timer\n", "    PpuAdvance(dt)\n")
        source = replace(source, "Procedure WorkerAdvance(stamp.i)\n  Protected dt.i, timer.i",
                         "Procedure WorkerAdvance(stamp.i)\n  Protected dt.i")
        source = replace(source, "    timer=NesHostUs()\n    If ExtraManaged(CartMapper)",
                         "    If ExtraManaged(CartMapper)")
        source = replace(source, "    WorkerApuUs=WorkerApuUs+NesHostUs()-timer\n", "")
        source = replace(source, "      timer=NesHostUs()\n      PpuAdvance(dt)\n"
                         "      WorkerPpuUs=WorkerPpuUs+NesHostUs()-timer\n", "      PpuAdvance(dt)\n")
        return replace(source, "  QResult=0\n  If command=1", "  QResult=0\n  If command=0 : ProcedureReturn : EndIf\n  If command=1")
    if name == "apu":
        source = replace(source, "  Protected c.i, feedback.i, period.i, ticks.i",
                         "  Protected c.i, feedback.i, period.i, ticks.i, timer.i, tap.i, lfsr.i")
        source = replace(source, "    ApuTimer(c)=ApuTimer(c)-dt\n"
                         "    If ApuTimer(c)<=0\n"
                         "      period=2*(ApuPeriod(c)+1) : ticks=1+NesDiv(0-ApuTimer(c),period)\n"
                         "      ApuTimer(c)=ApuTimer(c)+ticks*period\n"
                         "      ApuSeq(c)=(ApuSeq(c)+ticks)&7\n"
                         "    EndIf",
                         "    timer=ApuTimer(c)-dt\n"
                         "    If timer<=0\n"
                         "      period=2*(ApuPeriod(c)+1) : ticks=1\n"
                         "      If period=2\n"
                         "        ticks=1+((0-timer)>>1)\n"
                         "      ElseIf timer+period<=0\n"
                         "        ticks=1+(0-timer)/period\n"
                         "      EndIf\n"
                         "      timer=timer+ticks*period : ApuSeq(c)=(ApuSeq(c)+ticks)&7\n"
                         "    EndIf\n"
                         "    ApuTimer(c)=timer")
        source = replace(source, "    period=ApuPeriod(2)+1 : ticks=1+NesDiv(0-ApuTimer(2),period)\n"
                         "    ApuTimer(2)=ApuTimer(2)+ticks*period",
                         "    period=ApuPeriod(2)+1 : timer=ApuTimer(2) : ticks=1\n"
                         "    If period=1\n"
                         "      ticks=1-timer\n"
                         "    ElseIf timer+period<=0\n"
                         "      ticks=1+(0-timer)/period\n"
                         "    EndIf\n"
                         "    ApuTimer(2)=timer+ticks*period")
        source = replace(source, "  While ApuTimer(3)<=0\n"
                         "    ApuTimer(3)=ApuTimer(3)+NoiseTable(ApuReg(14)&15)\n"
                         "    If ApuReg(14)&$80\n"
                         "      feedback=(NoiseShift!(NoiseShift>>6))&1\n"
                         "    Else\n"
                         "      feedback=(NoiseShift!(NoiseShift>>1))&1\n"
                         "    EndIf\n"
                         "    NoiseShift=(NoiseShift>>1)|(feedback<<14)\n"
                         "  Wend",
                         "  If ApuTimer(3)<=0\n"
                         "    timer=ApuTimer(3) : period=NoiseTable(ApuReg(14)&15) : lfsr=NoiseShift\n"
                         "    tap=1 : If ApuReg(14)&$80 : tap=6 : EndIf\n"
                         "    Repeat\n"
                         "      timer=timer+period : feedback=(lfsr!(lfsr>>tap))&1\n"
                         "      lfsr=(lfsr>>1)|(feedback<<14)\n"
                         "    Until timer>0\n"
                         "    ApuTimer(3)=timer : NoiseShift=lfsr\n"
                         "  EndIf")
    return source
