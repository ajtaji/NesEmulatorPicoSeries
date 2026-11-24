"""Connect banked PRG storage to Anvil's existing mapper windows."""

import re


RDRAM_CART_RESERVE = 0x80200000


def stage_storage(name: str, source: str) -> str:
    if name != "mappers":
        return source
    resident = "    MapCopy(@NesMapPrg(0)+slot*8192,CartPrg+bank*8192,8192)\n"
    banked = """    CompilerIf #GAME_MAPPER=5 Or #GAME_MAPPER=228
      If NesPrgBankLoad(@NesMapPrg(0)+slot*8192,bank)=0
        WorkerError=22
        ProcedureReturn
      EndIf
    CompilerElse
""" + resident + "    CompilerEndIf\n"
    if source.count(resident) != 1:
        raise ValueError("mapper PRG storage hook changed")
    return source.replace(resident, banked)


def check_storage_layout(compiler_log: str) -> None:
    """Reject program statics overlapping the first reserved VI framebuffer."""
    match = re.search(r"VR4300: image .*?, variables to \$([0-9A-Fa-f]+);", compiler_log)
    if not match:
        raise ValueError("PureMetal Forge did not report the N64 static memory extent")
    end = int(match[1], 16)
    if end > RDRAM_CART_RESERVE:
        raise ValueError(f"N64 program statics end at ${end:08X}, overlapping the VI framebuffer pool")
