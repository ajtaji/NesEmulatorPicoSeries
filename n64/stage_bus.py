"""Specialize the guest bus for the cartridge built into the N64 ROM."""

import re


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


def stage_bus(source: str, mapper: int) -> str:
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
