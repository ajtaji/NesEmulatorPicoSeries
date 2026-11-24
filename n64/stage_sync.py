"""Call the PPU/APU directly from the single-threaded Nintendo 64 host."""

import re


REGISTER_READ = """Procedure.i NesReadRegister(addr.i, stamp.i)
  Protected result.i
  WorkerAdvance(stamp)
  If addr<$4000
    result=PpuRegRead(addr&7)
    MapperRegNotice(addr&7)
  ElseIf addr=$4015
    result=ApuReadStatus()
  EndIf
  ProcedureReturn result
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
                                "\nDeclare.i NesReadRegister(addr.i, stamp.i)")
        read = "NesRpc(1,addr,0,CpuCycles+AccessPhase)"
        if source.count(read) != 2:
            raise ValueError("synchronous register read sites changed")
        source = source.replace(read, "NesReadRegister(addr,CpuCycles+AccessPhase)")
    if name == "worker":
        worker = "Procedure WorkerCommand(command.i, addr.i, value.i, stamp.i)"
        if source.count(worker) != 1:
            raise ValueError("worker command procedure changed")
        source = source.replace(worker, REGISTER_READ + worker)
    return source

