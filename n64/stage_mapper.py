"""Back Anvil's mapper windows with VR4300 cartridge RAM."""

import re


WINDOWS = {
    "MAP_PRG": ("NesMapPrg", 32768),
    "MAP_CHR": ("NesMapChr", 8192),
    "MAP_PATTERN": ("NesMapPattern", 8192),
    "M5_SPRITE_PATTERN": ("NesMapMmc5Sprites", 8192),
    "EXTRA_CHR_RAM": ("NesMapExtraChrRam", 8192),
    "EXTRA_CHR_PATTERN": ("NesMapExtraPattern", 8192),
}

MAP_COPY = """Procedure MapCopy(dst.i,src.i,bytes.i)
  ; Canonicalize the KSEG0 pointers before using native memory operations.
  ; Use aligned transfers when available and byte transfers otherwise.
  ASM
    beq $a2, $zero, nes_map_copy_done
    sll $a0, $a0, 0
    sll $a1, $a1, 0
    or $t0, $a0, $a1
    or $t0, $t0, $a2
    andi $t0, $t0, 7
    bne $t0, $zero, nes_map_copy_bytes
    nop
nes_map_copy_words:
    ld $t0, 0($a1)
    sd $t0, 0($a0)
    daddiu $a1, $a1, 8
    daddiu $a0, $a0, 8
    addiu $a2, $a2, -8
    bne $a2, $zero, nes_map_copy_words
    nop
    b nes_map_copy_done
    nop
nes_map_copy_bytes:
    lbu $t0, 0($a1)
    sb $t0, 0($a0)
    daddiu $a1, $a1, 1
    daddiu $a0, $a0, 1
    addiu $a2, $a2, -1
    bne $a2, $zero, nes_map_copy_bytes
    nop
nes_map_copy_done:
  EndASM
EndProcedure"""


def stage_mapper(name: str, source: str) -> str:
    for constant, (array, size) in WINDOWS.items():
        source = re.sub(rf"^#{constant}=\$[0-9A-F]+$",
                        f"Global Dim {array}.a({size})", source, flags=re.M)
        source = re.sub(rf"#{constant}\b", f"@{array}(0)", source)
    if name == "mappers":
        source, count = re.subn(r"^Procedure MapCopy\([^\n]+\n.*?^EndProcedure",
                                MAP_COPY, source, count=1, flags=re.M | re.S)
        if count != 1:
            raise ValueError("Anvil mapper copy procedure is missing")
    return source
