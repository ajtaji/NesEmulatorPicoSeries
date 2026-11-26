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
    andi $t0, $a2, 31
    bnez $t0, nes_map_copy_words
    nop
nes_map_copy_blocks:
    ld $t0, 0($a1)
    sd $t0, 0($a0)
    ld $t0, 8($a1)
    sd $t0, 8($a0)
    ld $t0, 16($a1)
    sd $t0, 16($a0)
    ld $t0, 24($a1)
    sd $t0, 24($a0)
    daddiu $a1, $a1, 32
    addiu $a2, $a2, -32
    bnez $a2, nes_map_copy_blocks
    daddiu $a0, $a0, 32
    b nes_map_copy_done
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
    if name == "mapper_extra_bus" and mapper == 119:
        for procedure in ("ExtraChrRamMap", "ExtraChrRamWrite"):
            first = source.index(f"Procedure {procedure}(")
            last = source.index("EndProcedure", first) + len("EndProcedure")
            source = source[:first] + source[last:]
    if name == "mapper_extra_bus" and mapper in (64, 158):
        for procedure, replacement in (
            ("ExtraRamboWrite", 'XIncludeFile "../n64/mapper_mmc3_common.n64"'),
            ("ExtraRamboClock", ""),
        ):
            first = source.index(f"Procedure {procedure}(")
            last = source.index("EndProcedure", first) + len("EndProcedure")
            source = source[:first] + replacement + source[last:]
    if name == "mapper_extra_bus" and mapper in (6, 64, 69, 105, 158):
        start = source.index("Procedure ExtraCpuTicks(")
        end = source.index("EndProcedure", source.index("Procedure.i ExtraBudget(", start))
        end += len("EndProcedure")
        source = source[:start] + 'XIncludeFile "../n64/mapper_extra_irq.n64"' + source[end:]
    if name == "mapper_extra_bus" and mapper in (68, 118, 158):
        start = source.index("Procedure ExtraNtRefresh(")
        end = source.index("EndProcedure", start) + len("EndProcedure")
        source = source[:start] + 'XIncludeFile "../n64/mapper_nametable.n64"' + source[end:]
        if mapper == 68:
            start = source.index("Procedure.i ExtraNtRead(")
            end = source.index("EndProcedure", start) + len("EndProcedure")
            source = source[:start] + source[end:]
    if name == "mapper_extra_bus" and mapper == 234:
        start = source.index("Procedure ExtraReadNotice(")
        end = source.index("EndProcedure", start) + len("EndProcedure")
        source = source[:start] + "Declare ExtraReadNotice(addr.i,value.i)" + source[end:]
    if name == "mapper_extra":
        native_writes = ""
        if mapper in (9, 13, 41, 47, 71, 79, 118, 144, 148, 206, 228, 232, 234):
            native_writes = "mapper_discrete.n64"
        elif mapper in (6, 34, 68, 69, 105):
            native_writes = "mapper_board_regs.n64"
        if native_writes:
            start = source.index("Procedure.i ExtraMapperWrite(")
            end = source.index("EndProcedure", start) + len("EndProcedure")
            source = source[:start] + f'XIncludeFile "../n64/{native_writes}"' + source[end:]
        if mapper in (9, 13, 34, 41, 71, 79, 144, 148, 206, 228, 232, 234):
            start = source.index("Procedure.i ExtraMapperUpdate(")
            end = source.index("EndProcedure", start) + len("EndProcedure")
            source = source[:start] + 'XIncludeFile "../n64/mapper_discrete_update.n64"' + source[end:]
    if name == "mapper5" and mapper == 5:
        for procedure, replacement in (
            ("M5IrqUpdate", 'XIncludeFile "../n64/mapper5_cpu.n64"'),
            ("M5RamOffset", ""),
            ("M5PrgUpdate", ""),
            ("M5PrgRead", ""),
            ("M5Read", ""),
        ):
            first = re.search(rf"(?m)^Procedure(?:\.i)? {procedure}\(", source).start()
            last = source.index("EndProcedure", first) + len("EndProcedure")
            source = source[:first] + replacement + source[last:]
        first = source.index("Procedure M5PrgWrite(")
        last = source.index("EndProcedure", first) + len("EndProcedure")
        # Keep the battery store visible to stage_save, which adds its dirty hook.
        source = source[:first] + """CompilerIf #GAME_SAVE_BYTES>0
Procedure M5PrgWrite(addr.i,value.i)
  Protected offset.i=M5WritableOffset(addr)
  If offset<0 : ProcedureReturn : EndIf
  M5Ram(offset+(addr&8191))=value
  M5MirrorPrg(offset,addr,value)
EndProcedure
CompilerEndIf""" + source[last:]
        first = source.index("Procedure M5Write(")
        last = source.index("EndProcedure", first)
        video = source[first:last].replace("Procedure M5Write(", "Procedure M5WriteVideo(")
        video = "\n".join(
            line for line in video.split("\n")
            if not line.startswith(("  If addr>=$6000", "  If addr<$5016", "  If addr>=$5113",
                                    "    Case $5100", "    Case $5102", "    Case $5103",
                                    "    Case $5203", "    Case $5204", "    Case $5205",
                                    "    Case $5206", "    Case $5209", "    Case $520A"))
        )
        source = source[:first] + video + source[last:]
    if name == "mapper_extra" and mapper in (6, 64, 68, 69, 105, 158):
        start = source.index("Procedure.i ExtraMapperUpdate(")
        end = source.index("EndProcedure", start) + len("EndProcedure")
        source = source[:start] + 'XIncludeFile "../n64/mapper_complex_update.n64"' + source[end:]
    if name == "mappers":
        source, count = re.subn(r"^Procedure MapCopy\([^\n]+\n.*?^EndProcedure",
                                MAP_COPY, source, count=1, flags=re.M | re.S)
        if runtime and mapper == 4:
            for procedure, declaration in (
                ("MapperPrg", "Declare MapperPrg(slot.i,bank.i)"),
                ("MapperChr", "Declare MapperChr(slot.i,bank.i)"),
                ("MapperUpdate", "Declare MapperUpdate()"),
                ("MapperMirror", "Declare MapperMirror(mode.i)"),
                ("MapperWrite", "Declare MapperWrite(addr.i,value.i,stamp.i)"),
                ("MapperSpriteFetch", "Declare MapperSpriteFetch(line.i)"),
                ("MapperA12", "Declare MapperA12(addr.i,dot.i)"),
                ("MapperRegNotice", "Declare MapperRegNotice(reg.i)"),
                ("MapperChrWrite", "Declare MapperChrWrite(addr.i,value.i)"),
            ):
                first = source.index(f"Procedure {procedure}(")
                last = source.index("EndProcedure", first) + len("EndProcedure")
                source = source[:first] + declaration + source[last:]
            first = source.index("Procedure MapperClockIrq(")
            last = source.index("EndProcedure", first) + len("EndProcedure")
            source = source[:first] + "Declare MapperClockIrq()" + source[last:]
            first = source.index("Procedure MapperPpuTicks(")
            last = source.index("EndProcedure", first) + len("EndProcedure")
            source = source[:first] + ('XIncludeFile "../n64/mmc3_ticks.n64"\n'
                                       'XIncludeFile "../n64/mmc3_registers.n64"\n') + source[last:]
        else:
            for procedure, replacement in (
                ("MapperPrg", 'XIncludeFile "../n64/mapper_windows.n64"'),
                ("MapperChr", ""),
                ("MapperMirror", ""),
                ("MapperChrWrite", ""),
                ("MapperClockIrq", 'XIncludeFile "../n64/mapper_a12.n64"'),
                ("MapperA12", ""),
                ("MapperSpriteFetch", ""),
                ("MapperPpuTicks", ""),
                ("MapperRegNotice", ""),
            ):
                first = source.index(f"Procedure {procedure}(")
                last = source.index("EndProcedure", first) + len("EndProcedure")
                source = source[:first] + replacement + source[last:]
            first = source.index("Procedure.i MapperCpuBudget(")
            last = source.index("EndProcedure", first) + len("EndProcedure")
            source = (source[:first] + 'XIncludeFile "../n64/mapper_budget.n64"'
                      + source[last:])
            if mapper in (4, 47, 118, 119):
                first = source.index("  ElseIf ExtraMmc3(CartMapper)", source.index("Procedure MapperWrite("))
                last = source.index("EndProcedure", first)
                source = (source[:first] + "  ElseIf ExtraMmc3(CartMapper)\n"
                          "    NesWriteMmc3Common(addr,value)\n  EndIf\n" + source[last:])
                anchor = 'XIncludeFile "../n64/mapper_windows.n64"'
                source = source.replace(anchor, anchor + '\nXIncludeFile "../n64/mapper_mmc3_common.n64"')
                first = source.index("Procedure MapperUpdate(")
                last = source.index("EndProcedure", first) + len("EndProcedure")
                source = (source[:first] + 'XIncludeFile "../n64/mapper_mmc3_update.n64"'
                          + source[last:])
        if mapper == 1:
            for procedure in ("MapperUpdate", "MapperWrite"):
                start = source.index(f"Procedure {procedure}(")
                end = source.index("EndProcedure", start) + len("EndProcedure")
                include = 'XIncludeFile "../n64/mmc1.n64"' if procedure == "MapperUpdate" else ""
                source = source[:start] + include + source[end:]
        if count != 1:
            raise ValueError("Anvil mapper copy procedure is missing")
    return source
