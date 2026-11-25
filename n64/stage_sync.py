"""Call the PPU/APU directly from the single-threaded Nintendo 64 host."""

import re


REGISTER_ACCESS = """XIncludeFile "../n64/status.n64"
Procedure.i NesReadRegister(addr.i, stamp.i)
  Protected result.i
  CompilerIf #NES_PREDICTABLE_IRQ
    If addr<$4000 And (addr&7)=2
      If stamp>NesStatusHorizon
        WorkerAdvance(stamp)
        NesSetStatusHorizon(stamp)
      EndIf
      ProcedureReturn PpuRegRead(2)
    EndIf
  CompilerEndIf
  WorkerAdvance(stamp)
  If addr<$4000
    result=PpuRegRead(addr&7)
    {read_notice}
  ElseIf addr=$4015
    result=ApuReadStatus()
  EndIf
  ProcedureReturn result
EndProcedure

CompilerIf #NES_BG_EXPANDED
XIncludeFile "../n64/nametable.n64"
CompilerEndIf

Procedure NesWriteRegister(addr.i, value.i, stamp.i)
  CompilerIf #NES_PREDICTABLE_IRQ
    ; Blanking permits deferred CHR and nametable writes. Palette writes
    ; can also defer during vblank, after the last visible palette capture.
    ; Stop before prerender can reload the scroll address.
    If {window}
      NesStatusHorizon=-1
      If stamp>NesCpuHorizon
        WorkerAdvance(stamp)
        NesSetCpuHorizon(stamp)
      EndIf
      If {bound}
        If (stamp-WorkerClock)*(3+#GAME_PAL)>=(PpuPreLine-PpuLine)*341-PpuDot
          WorkerAdvance(stamp)
        EndIf
      EndIf
    Else
      WorkerAdvance(stamp)
    EndIf
  CompilerElse
    WorkerAdvance(stamp)
  CompilerEndIf
  QResult=0
  If addr<$4000
    PpuRegWrite(addr&7,value)
    CompilerIf #GAME_MAPPER<>0 And #GAME_MAPPER<>1 And #GAME_MAPPER<>2 And #GAME_MAPPER<>66
      MapperRegNotice(addr&7)
    CompilerEndIf
    CompilerIf #GAME_MAPPER=5
      M5PpuNotice(addr,value)
    CompilerEndIf
  Else
    ApuWrite(addr,value)
  EndIf
  QSent+=1 : QComplete=QSent
EndProcedure

CompilerIf #NES_BG_EXPANDED
XIncludeFile "../n64/portloops.n64"
CompilerEndIf

"""


def stage_sync(name: str, source: str, mapper: int, chain_nrom: bool = False) -> str:
    if name == "bridge":
        # All existing timestamp expressions here are straight-line arithmetic.
        source, count = re.subn(r"\bNesRpc\(0,0,0,([^()\n]+)\)", r"WorkerAdvance(\1)", source)
        if count != 7:
            raise ValueError(f"{name}: single-thread tick call sites changed")
        window = "      CpuNow() : WorkerAdvance(CpuCycles+AccessPhase)\n      MapperWrite(addr,value,CpuCycles+AccessPhase)"
        if source.count(window) != 1:
            raise ValueError("managed mapper write changed")
        source = source.replace(window, """      CpuNow()
      CompilerIf #GAME_MAPPER=1
        ; Intermediate shift bits have no bus output. At a commit, synchronize
        ; before CHR, mirroring or an active DMC reader can see a new mapping.
        If addr>=$8000
          If value&128
            If NesReaderActive() : WorkerAdvance(CpuCycles+AccessPhase) : EndIf
          ElseIf MapShift&1
            If addr<$E000 Or NesReaderActive() : WorkerAdvance(CpuCycles+AccessPhase) : EndIf
          EndIf
        EndIf
      CompilerElse
        WorkerAdvance(CpuCycles+AccessPhase)
      CompilerEndIf
      MapperWrite(addr,value,CpuCycles+AccessPhase)""")
        declarations = "Declare WorkerCommand(command.i, addr.i, value.i, stamp.i)"
        if source.count(declarations) != 1:
            raise ValueError("worker API declarations changed")
        source = source.replace(declarations, declarations + "\nDeclare WorkerAdvance(stamp.i)"
                                "\nDeclare.i NesReadRegister(addr.i, stamp.i)"
                                "\nDeclare NesWriteRegister(addr.i, value.i, stamp.i)")
        read = "NesRpc(1,addr,0,CpuCycles+AccessPhase)"
        if source.count(read) != 2:
            raise ValueError("synchronous register read sites changed")
        source = source.replace(read, "NesReadRegister(addr,CpuCycles+AccessPhase)")
        write = "NesPost(2,addr,value,CpuCycles+AccessPhase)"
        if source.count(write) != 2:
            raise ValueError("synchronous register write sites changed")
        source = source.replace(write, "NesWriteRegister(addr,value,CpuCycles+AccessPhase)")
    if name == "worker":
        advance = "  dt=stamp-WorkerClock"
        if source.count(advance) != 1:
            raise ValueError("worker clock entry changed")
        horizons = "  NesStatusHorizon=-1 : NesCpuHorizon=-1"
        if mapper == 1 or chain_nrom:
            horizons += " : NesChainLimit=-1"
        source = source.replace(advance, horizons + "\n" + advance)
        worker = "Procedure WorkerCommand(command.i, addr.i, value.i, stamp.i)"
        if source.count(worker) != 1:
            raise ValueError("worker command procedure changed")
        if mapper == 1:
            window = "addr<$4000 And (addr&7)=7 And (((PpuMask&24)=0 And (PpuV&$3FFF)<$3F00) Or (PpuLine>=240 And PpuLine<PpuPreLine))"
            bound = "((PpuMask&24)<>0 Or (PpuV&$3FFF)>=$3F00) And stamp>WorkerClock"
        else:
            window = "addr<$4000 And (addr&7)=7 And (PpuV&$3FFF)<$3F00 And ((PpuMask&24)=0 Or (PpuLine>=240 And PpuLine<PpuPreLine))"
            bound = "(PpuMask&24)<>0 And stamp>WorkerClock"
        read_notice = "" if mapper == 1 else "MapperRegNotice(addr&7)"
        access = REGISTER_ACCESS.format(window=window, bound=bound, read_notice=read_notice)
        if mapper == 1:
            # MMC1 has no CPU timer or PPU register observer.
            tick = "    If ExtraManaged(CartMapper) : ExtraCpuTicks(dt) : EndIf\n"
            if source.count(tick) != 1:
                raise ValueError("extra mapper CPU clock site changed")
            source = source.replace(tick, "")
        source = source.replace(worker, access + worker)
    return source
