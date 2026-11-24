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
    MapperRegNotice(addr&7)
  ElseIf addr=$4015
    result=ApuReadStatus()
  EndIf
  ProcedureReturn result
EndProcedure

Procedure NesWriteRegister(addr.i, value.i, stamp.i)
  CompilerIf #NES_PREDICTABLE_IRQ
    ; CHR and nametable writes can advance the address immediately while
    ; the raster has no fetches. During vblank cap the deferred interval
    ; before prerender, where the PPU can reload its scroll registers.
    If addr<$4000 And (addr&7)=7 And (PpuV&$3FFF)<$3F00 And ((PpuMask&24)=0 Or (PpuLine>=240 And PpuLine<PpuPreLine))
      NesStatusHorizon=-1
      If stamp>NesCpuHorizon
        WorkerAdvance(stamp)
        NesSetCpuHorizon(stamp)
      EndIf
      If (PpuMask&24)<>0 And stamp>WorkerClock
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
    CompilerIf #GAME_MAPPER<>0 And #GAME_MAPPER<>2 And #GAME_MAPPER<>66
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

"""


def stage_sync(name: str, source: str) -> str:
    if name == "bridge":
        # All existing timestamp expressions here are straight-line arithmetic.
        source, count = re.subn(r"\bNesRpc\(0,0,0,([^()\n]+)\)", r"WorkerAdvance(\1)", source)
        if count != 7:
            raise ValueError(f"{name}: single-thread tick call sites changed")
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
        source = source.replace(advance, "  NesStatusHorizon=-1 : NesCpuHorizon=-1\n" + advance)
        worker = "Procedure WorkerCommand(command.i, addr.i, value.i, stamp.i)"
        if source.count(worker) != 1:
            raise ValueError("worker command procedure changed")
        source = source.replace(worker, REGISTER_ACCESS + worker)
    return source
