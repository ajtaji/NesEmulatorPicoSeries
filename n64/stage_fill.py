"""Fuse consecutive RAM stores in a counted 2A03 clear loop."""

import re


# The native span has already fetched STA into a0 and holds guest PC and
# remaining budget in a1/a2. Keep t0 intact for the real STA at the end.
# Every skipped iteration includes a taken branch and leaves at least one
# cycle for that next store, which publishes the exact bus value and phase.
FILL_LOOP = """nes_native_9d:
    andi $t1, $a1, 0x8000
    beq $t1, $zero, nes_ram_fill_single
    sltiu $t1, $a2, 41
    bne $t1, $zero, nes_ram_fill_single
    andi $t1, $a1, 0x3FFF
    sltiu $t1, $t1, 0x3FFB
    beq $t1, $zero, nes_ram_fill_single
    nop
    lbu $t1, 3($t0)
    xori $t1, $t1, 0xE8
    bne $t1, $zero, nes_ram_fill_single
    lbu $t2, 4($t0)
    xori $t2, $t2, 0xD0
    bne $t2, $zero, nes_ram_fill_single
    lbu $t1, 5($t0)
    xori $t1, $t1, 0xFA
    bne $t1, $zero, nes_ram_fill_single
    lbu $t2, 2($t0)
    lbu $t1, 1($t0)
    sll $t2, $t2, 8
    or $t1, $t1, $t2
    addiu $t2, $zero, 0x2000
    subu $t2, $t2, $t1
    subu $t2, $t2, $a5
    blez $t2, nes_ram_fill_single
    xori $v1, $a5, 0xFF
    sltu $a0, $t2, $v1
    beq $a0, $zero, nes_ram_fill_check_budget
    nop
    or $v1, $t2, $zero
nes_ram_fill_check_budget:
    addiu $a0, $a1, 6
    xor $a0, $a0, $a1
    srl $a0, $a0, 8
    sltu $t2, $zero, $a0
    addiu $t2, $t2, 10
    daddiu $a0, $a2, -1
    ddivu $a0, $t2
    mflo $a0
    sltu $t2, $v1, $a0
    beq $t2, $zero, nes_ram_fill_count
    nop
    or $a0, $v1, $zero
nes_ram_fill_count:
    sltiu $v1, $a0, 4
    bne $v1, $zero, nes_ram_fill_single
    addiu $t2, $a1, 6
    xor $t2, $t2, $a1
    srl $t2, $t2, 8
    sltu $t2, $zero, $t2
    addiu $t2, $t2, 10
    dmultu $a0, $t2
    mflo $v1
    dsubu $a2, $a2, $v1
    dsll $v1, $a0, 1
    daddu $v1, $v1, $a0
    daddu $t3, $t3, $v1
    addu $t1, $t1, $a5
    addu $a5, $a5, $a0
    or $a7, $a5, $zero
    or $t8, $a5, $zero
nes_ram_fill_loop:
    andi $t2, $t1, 0x7FF
    addu $t2, $t2, $s1
    sb $a4, 0($t2)
    addiu $a0, $a0, -1
    bne $a0, $zero, nes_ram_fill_loop
    addiu $t1, $t1, 1
nes_ram_fill_single:
    ori $a0, $zero, 0x9D
    or $v1, $a0, $zero
"""


def stage_fill(source: str, program: bytes) -> str:
    if not re.search(rb"\x9d.[\x00-\x1f]\xe8\xd0\xfa", program, re.S):
        return source
    marker = "nes_native_9d:\n"
    if source.count(marker) != 1:
        raise ValueError("native RAM fill entry changed")
    return source.replace(marker, FILL_LOOP)
