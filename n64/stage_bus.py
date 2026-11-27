"""Specialize the guest bus for the cartridge built into the N64 ROM."""

import re


MMC3_READ_LOWER = """    sltiu $t0, $a1, 0x4000
    bnez $t0, nes_mmc3_read_peripheral
    addiu $t0, $a1, -0x4015
    sltiu $t0, $t0, 3
    bnez $t0, nes_mmc3_read_peripheral
    sltiu $t0, $a1, 0x6000
    la $t1, global_nesopenbus
    la $t2, global_mapramenable
    bnez $t0, nes_mmc3_read_open
    andi $a1, $a1, 0x1FFF
    ld $t2, 0($t2)
    beqz $t2, nes_mmc3_read_open
    nop
    la $t0, global_mapram
    addu $t0, $t0, $a1
    lbu $a0, 0($t0)
    jr $ra
    sd $a0, 0($t1)
nes_mmc3_read_open:
    ld $a0, 0($t1)
    andi $a0, $a0, 0xFF
    jr $ra
    sd $a0, 0($t1)
nes_mmc3_read_peripheral:
    j nesreadperipheral
    or $a0, $a1, $zero"""


def stage_runtime_mmc3_bus(source: str) -> str:
    """Replace generic decoding after the synchronized I/O hooks are staged."""
    pattern = r"^Procedure\.i NesReadSlow\(addr\.i\)\n.*?^  ElseIf addr=\$4016\n(.*?)^EndProcedure"
    replacement = r"Procedure.i NesReadPeripheral(addr.i)\n  Protected v.i\n  If addr=$4016\n\1EndProcedure"
    source, count = re.subn(pattern, replacement, source, flags=re.M | re.S)
    if count != 1:
        raise ValueError("MMC3 peripheral read source changed")
    tail = "nes_direct_nesread_slow:\n    j nesreadslow\n    nop"
    if source.count(tail) != 1:
        raise ValueError("MMC3 direct read fallback changed")
    source, count = re.subn(r"^Procedure NesWrite\(addr\.i, value\.i\)\n.*?^EndProcedure",
                            'XIncludeFile "../n64/mmc3_cpu_write.n64"', source,
                            flags=re.M | re.S)
    if count != 1:
        raise ValueError("MMC3 CPU write source changed")
    return source.replace("Declare.i NesReadSlow(addr.i)\n", "Declare.i NesReadPeripheral(addr.i)\n").replace(
        tail, "nes_direct_nesread_slow:\n" + MMC3_READ_LOWER)


def read_direct(label: str, fallback: str, mapper: int, *, pair: bool = False) -> str:
    """Emit a read from a1, returning in a0 and clobbering t0 through t2."""
    low_limit = 0x1FFF if pair else 0x2000
    instructions = [
        "andi $t0, $a1, 0x8000",
        f"beq $t0, $zero, {label}_lower",
        f"sltiu $t0, $a1, {low_limit}",
    ]
    if mapper == 5:
        instructions += [f"b {fallback}", "nop"]
    elif mapper in (1, 4):
        window = 0x4000 if mapper == 1 else 0x2000
        slot_mask = 0x8000 - window
        if pair:
            instructions += [f"andi $t2, $a1, {window-1}", f"xori $t2, $t2, {window-1}",
                             f"beq $t2, $zero, {fallback}", "nop"]
        instructions += [f"andi $t1, $a1, {slot_mask}", f"srl $t1, $t1, {window.bit_length()-4}",
                         f"la $t2, global_nesmmc{'1' if mapper == 1 else '3'}bias", "addu $t1, $t1, $t2",
                         "ld $t1, 0($t1)", "addu $t1, $t1, $a1"]
        if pair:
            instructions += ["lbu $t2, 0($t1)", f"b {label}_finish", "lbu $a0, 1($t1)"]
        else:
            instructions += [f"b {label}_finish", "lbu $a0, 0($t1)"]
    else:
        # Mapper 234 can switch the ROM bank on reads starting at $FF80.
        # A two-byte $FFFF fetch crosses over to CPU RAM.
        prg_limit = 0xFFFF if pair else None
        if mapper == 234:
            prg_limit = 0xFF7F if pair else 0xFF80
        if prg_limit is not None:
            instructions += [
                f"ori $t2, $zero, {prg_limit}",
                "sltu $t2, $a1, $t2",
                f"beq $t2, $zero, {fallback}",
                "nop",
            ]
        instructions += [
            "la $t1, global_prgbias",
            "ld $t1, 0($t1)",
            # The word addition sign-extends the resulting KSEG0 address.
            "addu $t1, $t1, $a1",
        ]
        if pair:
            instructions += ["lbu $t2, 0($t1)", f"b {label}_finish", "lbu $a0, 1($t1)"]
        else:
            instructions += [f"b {label}_finish", "lbu $a0, 0($t1)"]

    instructions += [
        f"{label}_lower:",
        f"beq $t0, $zero, {fallback}",
        "andi $t2, $a1, 0x7FF",
        "la $t1, global_m",
        "addu $t0, $t1, $t2",
    ]
    if pair:
        instructions += [
            "lbu $t2, 0($t0)",
            "addiu $t0, $a1, 1",
            "andi $t0, $t0, 0x7FF",
            "addu $t0, $t1, $t0",
        ]
    instructions += [
        "lbu $a0, 0($t0)",
        f"{label}_finish:",
        "la $t1, global_nesopenbus",
        "sd $a0, 0($t1)",
    ]
    if pair:
        instructions += ["sll $a0, $a0, 8", "or $a0, $a0, $t2"]
    return "\n".join(line if line.endswith(":") else "    " + line for line in instructions)


def stage_bus(source: str, mapper: int, unit: bool = False) -> str:
    # the unit build (any mapper) reads PRG through the four 8 KB banks' biases (NesMmc3Pointer, global_nesmmc3bias),
    # which every module keeps current through the common MapperPrg: read_direct's MMC3 shape
    if unit:
        mapper = 4
    if mapper in (1, 4):
        pointer = "NesMmc1Pointer" if mapper == 1 else "NesMmc3Pointer"
        source = source.replace("PeekA(PrgBase+addr-$8000)", f"PeekA({pointer}(addr))")
        source = source.replace("PeekA(WorkerPrgBase+addr-$8000)", f"PeekA({pointer}(addr))")
    reads = [
        ("NesRead", ".i", "addr.i", """    andi $a1, $a0, 0xFFFF""",
         """    jr $ra
    nop""", "nesreadslow"),
        ("CpuFetchByte", ".i", "", """    la $t3, global_pc
    ld $a1, 0($t3)""", """    addiu $a1, $a1, 1
    andi $a1, $a1, 0xFFFF
    jr $ra
    sd $a1, 0($t3)""", "cpufetchbyteslow"),
        ("CpuFetchAddress", "", "", """    la $t3, global_pc
    ld $a1, 0($t3)""", """    la $t0, global_ea
    sd $a0, 0($t0)
    addiu $a1, $a1, 2
    andi $a1, $a1, 0xFFFF
    jr $ra
    sd $a1, 0($t3)""", "cpufetchaddressslow"),
    ]
    for name, result, args, setup, finish, slow in reads:
        label = "nes_direct_" + name.lower()
        fallback = label + "_slow"
        direct = read_direct(label, fallback, mapper, pair=name == "CpuFetchAddress")
        implementation = f"""ProcedureNaked{result} {name}({args})
  ASM
{setup}
{direct}
{finish}
{fallback}:
    j {slow}
    nop
  EndASM
EndProcedure"""
        source, count = re.subn(rf"^Procedure{re.escape(result)} {name}\([^\n]*\)\n.*?^EndProcedure",
                                implementation, source, flags=re.M | re.S)
        if count != 1:
            raise ValueError(f"Anvil bus procedure {name} is missing")
    return source
