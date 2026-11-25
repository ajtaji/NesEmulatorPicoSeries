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


def stage_mapper(name: str, source: str, mapper: int = 0, runtime: bool = False) -> str:
    for constant, (array, size) in WINDOWS.items():
        source = re.sub(rf"^#{constant}=\$[0-9A-F]+$",
                        f"Global Dim {array}.a({size})", source, flags=re.M)
        source = re.sub(rf"#{constant}\b", f"@{array}(0)", source)
    if name == "mappers":
        source, count = re.subn(r"^Procedure MapCopy\([^\n]+\n.*?^EndProcedure",
                                MAP_COPY, source, count=1, flags=re.M | re.S)
        mirror = "  MapMirrorMode=mode"
        if source.count(mirror) != 1:
            raise ValueError("mapper mirror update changed")
        source = source.replace(mirror, mirror + "\n  CompilerIf #NES_MMC1_ROWS\n    NesInvalidateMap()\n  CompilerEndIf")
        if runtime and mapper == 4:
            # Interior background fetches only take A12 low for four dots.
            # Advance through those unqualified transitions as one interval.
            anchor = "    edge=width\n"
            if source.count(anchor) != 1:
                raise ValueError("MMC3 sprite-edge scheduler changed")
            source = source.replace(anchor, """    If (PpuMask&24)<>0 And (PpuCtrl&16)<>0 And (line=261 Or line<240)
      If dot>=5 And dot<256 And MapA12 And (dot&7)>=5
        step=256-dot : If step>left : step=left : EndIf
        addr=dot+step : edge=((addr-1)&~7)+1
        If edge>dot
          MapLowSince=MapDots+edge-dot
          MapA12=Bool((addr&7)=0 Or (addr&7)>=5)
        EndIf
        dot=addr : left-step : MapDots+step
        Continue
      EndIf
    EndIf
""" + anchor)
            source = source.replace(
                "If CartMapper<>4 And MapA12<>0 And",
                "If MapA12<>0 And",
            )
            irq_anchor = "  ; New MMC3/RAMBO boards:"
            if source.count(irq_anchor) != 1:
                raise ValueError("MMC3 IRQ budget entry changed")
            source = source.replace(irq_anchor, """  ; A qualified rising edge needs ten low dots. If several edges
  ; remain, even consecutive qualified rises cannot assert the IRQ
  ; inside this interval. A CPU register write ends the window.
  distance=MapIrqCount
  If MapReload Or distance=0 : distance=MapIrqLatch+1 : EndIf
  If distance>1
    budget=((distance-1)*10)/3
    If budget>128 : budget=128 : EndIf
    ProcedureReturn budget
  EndIf
""" + irq_anchor)
        if mapper == 1:
            for procedure in ("MapperUpdate", "MapperWrite"):
                start = source.index(f"Procedure {procedure}(")
                end = source.index("EndProcedure", start) + len("EndProcedure")
                include = 'XIncludeFile "../n64/mmc1.n64"' if procedure == "MapperUpdate" else ""
                source = source[:start] + include + source[end:]
        chr_write = "  PokeA(CartChr+physical,value)"
        if source.count(chr_write) != 1:
            raise ValueError("mapper CHR write changed")
        source = source.replace(chr_write, """  CompilerIf #NES_MMC1_ROWS
    If PeekA(CartChr+physical)=value : ProcedureReturn : EndIf
    NesVideoSerial+=1 : NesVideoReset=NesVideoSerial
  CompilerEndIf
""" + chr_write)
        if count != 1:
            raise ValueError("Anvil mapper copy procedure is missing")
    return source
