"""Stage VRC6 and Namco 163 on the shared Anvil mapper and APU hooks."""

from pathlib import Path

from port_desktop import MAPPER_PATCHES


EXPANSION_MAPPERS = frozenset((19, 24, 26))
SOURCE = Path(__file__).resolve().parents[1] / "desktop" / "mapper_konami_namco.pbi"

# Namco's renderer maps CHR ROM into Nt and tracks the ROM slots separately
# from CIRAM. CPU PPUDATA must read that same page and ignore writes to it.
NAMCO_NT = "    If CartMapper=19 And N1RomNametable(addr) : "
PPU_PATCHES = {
    "ppu_bus_read": [
        ("    If MapManaged : ProcedureReturn MapCiram(PpuNtAddr(addr)) : EndIf\n",
         NAMCO_NT + "ProcedureReturn Nt(addr&4095) : EndIf\n"
         "    If MapManaged : ProcedureReturn MapCiram(PpuNtAddr(addr)) : EndIf\n", 1),
    ],
    "ppu_bus_write": [
        ("    ntAddress=PpuNtAddr(addr)\n",
         NAMCO_NT + "ProcedureReturn : EndIf\n    ntAddress=PpuNtAddr(addr)\n", 1),
    ],
}


def apply_patches(name: str, source: str, patches) -> str:
    for old, new, count in patches:
        if source.count(old) != count:
            raise ValueError(f"{name}: expansion mapper source changed at {old!r}")
        source = source.replace(old, new)
    return source


def stage_expansion(name: str, source: str) -> str:
    return apply_patches(name, source, MAPPER_PATCHES.get(name, []) + PPU_PATCHES.get(name, []))


def expansion_source() -> str:
    source = SOURCE.read_text(encoding="utf-8")
    source = apply_patches(SOURCE.name, source, [
        ("EnableExplicit\n", "", 1),
        ("CopyMemory(CartChr+((value*1024)&(MapChrBytes-1)),@Nt(table*1024),1024)",
         "MapCopy(@Nt(table*1024),CartChr+((value*1024)&(MapChrBytes-1)),1024)", 1),
        ('Say("VRC6: this game uses a nametable mode that is not supported ($B003=") : Num(value) : Say(")") : Eol()',
         'LpmDebugPrint("VRC6: unsupported nametable mode ($B003="+Str(value)+")")', 1),
        ('Say("N163: this game maps CHR-RAM patterns, which are not drawn yet") : Eol()',
         'LpmDebugPrint("N163: CHR-RAM pattern banking is unsupported")', 1),
    ])
    return source + """
Procedure.i N1RomNametable(addr.i)
  ProcedureReturn N1NtBank((addr>>10)&3)>=0
EndProcedure
"""
