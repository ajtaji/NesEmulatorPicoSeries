"""Thread ordinary 2A03 instructions through fixed VR4300 registers.

The portable interpreter owns device and mapper accesses. This span reads
instructions from ordinary PRG and data from PRG or mirrored internal RAM.
A rejected instruction goes to its original handler with the opcode fetched
and the PC advanced exactly once. State is published at a fallback or the
end of the CPU cycle window, before the scheduler checks IRQ and NMI.
"""

import re


def native_handlers():
    handlers = {}

    def handler(op, length, cycles, body, phase=None):
        code = [f"nes_native_{op:02x}:", *body, f"addiu $a1, $a1, {length}"]
        if phase is not None:
            code.append(f"addiu $v0, $zero, {phase}")
        code += ["b nes_thread_check", f"daddiu $a2, $a2, -{cycles}"]
        handlers[op] = "\n".join(code)

    def operand(op, mode, *, write=False):
        if mode == "imm":
            return ["lbu $v1, 1($t0)"]
        if mode.startswith("zp"):
            code = ["lbu $t0, 1($t0)"]
            if mode != "zp":
                index = "$a5" if mode == "zpx" else "$a6"
                code += [f"addu $t0, $t0, {index}", "andi $t0, $t0, 0xFF"]
            code += ["addu $t0, $t0, $s1"]
        else:
            code = ["lbu $t1, 1($t0)", "lbu $t2, 2($t0)", "sll $t2, $t2, 8",
                    "or $t1, $t1, $t2"]
            if mode in ("ind_x", "ind_y"):
                code = ["lbu $t1, 1($t0)"]
                if mode == "ind_x":
                    code += ["addu $t1, $t1, $a5", "andi $t1, $t1, 0xFF"]
                code += ["addu $t2, $s1, $t1",
                        "addiu $t1, $t1, 1", "andi $t1, $t1, 0xFF", "addu $t0, $s1, $t1",
                        "lbu $t1, 0($t2)", "lbu $t2, 0($t0)", "sll $t2, $t2, 8",
                        "or $t1, $t1, $t2"]
            indexed = mode in ("absx", "absy", "ind_y")
            if indexed:
                index = "$a5" if mode == "absx" else "$a6"
                code += [f"addu $t0, $t1, {index}", "andi $t0, $t0, 0xFFFF"]
                if not write:
                    code += ["xor $t2, $t1, $t0", "srl $t2, $t2, 8", "sltu $t2, $zero, $t2"]
            else:
                code += ["or $t0, $t1, $zero"]
            if write:
                code += ["sltiu $t1, $t0, 0x2000", "beq $t1, $zero, nes_thread_slow",
                         "andi $t0, $t0, 0x7FF", "addu $t0, $t0, $s1"]
            else:
                rom = f"nes_native_{op:02x}_rom"
                read = f"nes_native_{op:02x}_read"
                code += ["andi $t1, $t0, 0x8000", f"bne $t1, $zero, {rom}",
                         "sltiu $t1, $t0, 0x2000", "beq $t1, $zero, nes_thread_slow", "nop",
                         "andi $t0, $t0, 0x7FF", f"b {read}",
                         "addu $t0, $t0, $s1", rom + ":", "addu $t0, $t0, $a3", read + ":"]
                if indexed:
                    code += ["dsubu $a2, $a2, $t2"]
        if not write:
            code += ["lbu $v1, 0($t0)"]
        return code

    modes = {"imm": (2, 2), "zp": (2, 3), "zpx": (2, 4), "zpy": (2, 4),
             "abs": (3, 4), "absx": (3, 4), "absy": (3, 4), "ind_y": (2, 5), "ind_x": (2, 6)}

    def value_op(op, mode, code):
        length, cycles = modes[mode]
        phase = {"ind_x": 5, "ind_y": 4}.get(mode, 3 if mode.startswith("abs") else None)
        handler(op, length, cycles, operand(op, mode) + code, phase)

    def nz(reg):
        return [f"or $a7, {reg}, $zero", f"or $t8, {reg}, $zero"]

    for reg, ops in (
        ("$a4", {0xA9: "imm", 0xA5: "zp", 0xB5: "zpx", 0xAD: "abs",
                 0xBD: "absx", 0xB9: "absy", 0xB1: "ind_y", 0xA1: "ind_x"}),
        ("$a5", {0xA2: "imm", 0xA6: "zp", 0xB6: "zpy", 0xAE: "abs", 0xBE: "absy"}),
        ("$a6", {0xA0: "imm", 0xA4: "zp", 0xB4: "zpx", 0xAC: "abs", 0xBC: "absx"}),
    ):
        for op, mode in ops.items():
            value_op(op, mode, [f"or {reg}, $v1, $zero", *nz(reg)])

    for reg, ops in (
        ("$a4", {0x85: "zp", 0x95: "zpx", 0x8D: "abs", 0x9D: "absx", 0x99: "absy",
                 0x81: "ind_x", 0x91: "ind_y"}),
        ("$a5", {0x86: "zp", 0x96: "zpy", 0x8E: "abs"}),
        ("$a6", {0x84: "zp", 0x94: "zpx", 0x8C: "abs"}),
    ):
        for op, mode in ops.items():
            length, cycles = modes[mode]
            phase = 3 if mode == "abs" else None
            if mode in ("absx", "absy"):
                cycles += 1
                phase = 4
            if mode in ("ind_x", "ind_y"):
                cycles = 6
                phase = 5
            handler(op, length, cycles, operand(op, mode, write=True) +
                    [f"sb {reg}, 0($t0)", f"or $v1, {reg}, $zero"], phase)

    alu_modes = ("imm", "zp", "zpx", "abs", "absx", "absy", "ind_y", "ind_x")
    alu_offsets = (0x09, 0x05, 0x15, 0x0D, 0x1D, 0x19, 0x11, 0x01)
    for page, instruction in ((0x00, "or"), (0x20, "and"), (0x40, "xor")):
        for offset, mode in zip(alu_offsets, alu_modes):
            value_op(page + offset, mode, [f"{instruction} $a4, $a4, $v1", *nz("$a4")])
    for page in (0x60, 0xE0):
        subtract = page == 0xE0
        code = ["srl $t1, $t9, 8", "andi $t1, $t1, 1"]
        if subtract:
            code += ["xori $t1, $t1, 1", "subu $t0, $a4, $v1", "subu $t0, $t0, $t1"]
        else:
            code += ["addu $t0, $a4, $v1", "addu $t0, $t0, $t1"]
        code += ["xor $t1, $a4, $v1", "xor $t2, $a4, $t0"]
        if not subtract:
            code += ["nor $t1, $t1, $zero"]
        code += ["and $t1, $t1, $t2", "la $t2, global_fv", "sd $t1, 0($t2)"]
        code += ["nor $t9, $t0, $zero" if subtract else "or $t9, $t0, $zero"]
        if subtract:
            code += [*nz("$t0"), "andi $a4, $t0, 0xFF"]
        else:
            code += ["andi $a4, $t0, 0xFF", *nz("$a4")]
        for offset, mode in zip(alu_offsets, alu_modes):
            value_op(page + offset, mode, code)
    for reg, ops in (("$a4", (0xC9, 0xC5, 0xCD)), ("$a5", (0xE0, 0xE4, 0xEC)),
                     ("$a6", (0xC0, 0xC4, 0xCC))):
        for op, mode in zip(ops, ("imm", "zp", "abs")):
            value_op(op, mode, [f"subu $a7, {reg}, $v1", "or $t8, $a7, $zero",
                                "nor $t9, $a7, $zero"])
    for op, mode in ((0xD5, "zpx"), (0xDD, "absx"), (0xD9, "absy"),
                     (0xD1, "ind_y"), (0xC1, "ind_x")):
        value_op(op, mode, ["subu $a7, $a4, $v1", "or $t8, $a7, $zero", "nor $t9, $a7, $zero"])
    for op, mode in ((0x24, "zp"), (0x2C, "abs")):
        value_op(op, mode, ["and $a7, $a4, $v1", "or $t8, $v1, $zero",
                            "sll $t1, $v1, 1", "la $t2, global_fv", "sd $t1, 0($t2)"])
    for op, dst, src in ((0x8A, "$a4", "$a5"), (0x98, "$a4", "$a6"),
                         (0xAA, "$a5", "$a4"), (0xA8, "$a6", "$a4")):
        handler(op, 1, 2, [f"or {dst}, {src}, $zero", *nz(dst)])
    for op, reg, change in ((0xE8, "$a5", 1), (0xCA, "$a5", -1),
                            (0xC8, "$a6", 1), (0x88, "$a6", -1)):
        handler(op, 1, 2, [f"addiu {reg}, {reg}, {change}", f"andi {reg}, {reg}, 255", *nz(reg)])
    handler(0xEA, 1, 2, [])
    handler(0x18, 1, 2, ["or $t9, $zero, $zero"])
    handler(0x38, 1, 2, ["ori $t9, $zero, 0x100"])
    for op, code in (
        (0x0A, ["sll $t9, $a4, 1", "andi $a4, $t9, 0xFF"]),
        (0x4A, ["sll $t9, $a4, 8", "srl $a4, $a4, 1"]),
        (0x2A, ["srl $t0, $t9, 8", "andi $t0, $t0, 1", "sll $t9, $a4, 1",
                "or $t9, $t9, $t0", "andi $a4, $t9, 0xFF"]),
        (0x6A, ["srl $t0, $t9, 1", "andi $t0, $t0, 0x80", "sll $t9, $a4, 8",
                "srl $a4, $a4, 1", "or $a4, $a4, $t0"]),
    ):
        handler(op, 1, 2, [*code, *nz("$a4")])
    handler(0x48, 1, 3, ["la $t0, global_s", "ld $t1, 0($t0)", "addu $t2, $s1, $t1",
                         "sb $a4, 0x100($t2)", "addiu $t1, $t1, -1", "andi $t1, $t1, 0xFF",
                         "sd $t1, 0($t0)"])
    handler(0x68, 1, 4, ["la $t0, global_s", "ld $t1, 0($t0)", "addiu $t1, $t1, 1",
                         "andi $t1, $t1, 0xFF", "sd $t1, 0($t0)", "addu $t2, $s1, $t1",
                         "lbu $a4, 0x100($t2)", *nz("$a4")])
    handler(0x9A, 1, 2, ["la $t0, global_s", "sd $a5, 0($t0)"])
    handler(0xBA, 1, 2, ["la $t0, global_s", "ld $a5, 0($t0)", *nz("$a5")])
    for op, mode, change in ((0xC6, "zp", -1), (0xD6, "zpx", -1),
                             (0xE6, "zp", 1), (0xF6, "zpx", 1)):
        length, cycles = modes[mode]
        handler(op, length, cycles + 2, operand(op, mode, write=True) +
                ["lbu $v1, 0($t0)", f"addiu $v1, $v1, {change}", "andi $v1, $v1, 0xFF",
                 "sb $v1, 0($t0)", *nz("$v1")])
    # A branch that is not taken never reaches the portable core's
    # operand read. Fetch the displacement only on the taken path.
    for op, flag, mask, take_when_set, idle_offsets in (
        (0x10, "$t8", 0x80, False, ()), (0x30, "$t8", 0x80, True, ()),
        (0x90, "$t9", 0x100, False, ()), (0xB0, "$t9", 0x100, True, ()),
        (0x50, "$t2", 0x80, False, ()), (0x70, "$t2", 0x80, True, ()),
        (0xD0, "$a7", 0xFF, True, (-6,)), (0xF0, "$a7", 0xFF, False, (-7, -4)),
    ):
        label = f"nes_native_{op:02x}"
        branch = "beq" if take_when_set else "bne"
        overflow = ["la $t2, global_fv", "ld $t2, 0($t2)"] if flag == "$t2" else []
        code = [label + ":", *overflow, f"andi $t1, {flag}, {mask}",
                f"{branch} $t1, $zero, {label}_not_taken",
                "addiu $t1, $a1, 2", "lb $t2, 1($t0)"]
        for offset in idle_offsets:
            code += [f"addiu $t0, $zero, {offset}", "beq $t2, $t0, nes_thread_slow", "nop"]
        code += [
            "andi $v1, $t2, 0xFF", "addu $a1, $t1, $t2", "andi $a1, $a1, 0xFFFF",
            "xor $t2, $a1, $t1", "srl $t2, $t2, 8", "sltu $t2, $zero, $t2",
            "daddiu $a2, $a2, -3", "b nes_thread_check", "dsubu $a2, $a2, $t2",
            label + "_not_taken:", "or $a1, $t1, $zero",
            "b nes_thread_check", "daddiu $a2, $a2, -2",
        ]
        handlers[op] = "\n".join(code)

    handlers[0x4C] = """nes_native_4c:
lbu $t1, 1($t0)
lbu $t2, 2($t0)
sll $t0, $t2, 8
or $t1, $t1, $t0
beq $a1, $t1, nes_thread_slow
nop
or $v1, $t2, $zero
or $a1, $t1, $zero
addiu $v0, $zero, 2
b nes_thread_check
daddiu $a2, $a2, -3"""
    handlers[0x20] = """nes_native_20:
lbu $t1, 1($t0)
lbu $v1, 2($t0)
sll $t0, $v1, 8
or $a0, $t0, $t1
addiu $a1, $a1, 2
la $t1, global_s
ld $t2, 0($t1)
addu $t0, $s1, $t2
srl $t2, $a1, 8
sb $t2, 0x100($t0)
ld $t2, 0($t1)
addiu $t2, $t2, -1
andi $t2, $t2, 0xFF
addu $t0, $s1, $t2
sb $a1, 0x100($t0)
addiu $t2, $t2, -1
andi $t2, $t2, 0xFF
sd $t2, 0($t1)
or $a1, $a0, $zero
addiu $v0, $zero, 5
b nes_thread_check
daddiu $a2, $a2, -6"""
    handlers[0x60] = """nes_native_60:
la $t0, global_s
ld $t2, 0($t0)
addiu $t2, $t2, 1
andi $t2, $t2, 0xFF
addu $t1, $s1, $t2
lbu $a0, 0x100($t1)
addiu $t2, $t2, 1
andi $t2, $t2, 0xFF
sd $t2, 0($t0)
addu $t1, $s1, $t2
lbu $t2, 0x100($t1)
sll $t2, $t2, 8
or $a1, $a0, $t2
addiu $a1, $a1, 1
andi $a1, $a1, 0xFFFF
b nes_thread_check
daddiu $a2, $a2, -6"""
    return handlers


def assembly(text):
    return "\n".join(line if line.endswith(":") else "    " + line for line in text.splitlines())


def table(labels):
    return "\n".join("    .word " + ", ".join(labels[i:i + 4]) for i in range(0, len(labels), 4))


def stage_thread(source: str) -> str:
    old_table = re.search(r"^nes_opcode_table:\n(?P<words>(?:    \.word .*\n)+)", source, re.M)
    if old_table is None:
        raise ValueError("VR4300 opcode table is missing")
    portable = re.findall(r"__ul_cpurun_\w+", old_table["words"])
    if len(portable) != 256:
        raise ValueError("VR4300 opcode table has wrong size")
    handlers = native_handlers()
    if any(portable[op] == "__ul_cpurun_illegal" for op in handlers):
        raise ValueError("Native opcode table covers an unsupported guest instruction")
    boot_table = ["nes_thread_enter" if op in handlers else portable[op] for op in range(256)]
    thread_table = [f"nes_native_{op:02x}" if op in handlers else "nes_thread_slow" for op in range(256)]
    # a0: decoded opcode, a1: guest PC, v1: open bus. t0 through t2 are
    # scratch. s0 and s1 hold the dispatch table and RAM base during the
    # span and are restored before returning to PureMetal code.
    live = (("left", "$a2"), ("prgbias", "$a3"), ("a", "$a4"), ("x", "$a5"),
            ("y", "$a6"), ("fz", "$a7"), ("fn", "$t8"), ("fc", "$t9"),
            ("nesinstructions", "$t3"), ("accessphase", "$v0"))
    load = "\n".join(f"la $t1, global_{name}\nld {reg}, 0($t1)" for name, reg in live)
    publish = (("pc", "$a1"), ("nesopenbus", "$v1")) + tuple(r for r in live if r[0] != "prgbias")
    store = "\n".join(f"la $t1, global_{name}\nsd {reg}, 0($t1)" for name, reg in publish)
    thread = f"""nes_thread_enter:
addiu $t0, $a1, -1
andi $t0, $t0, 0xFFFF
addiu $t1, $t0, -32768
sltiu $t1, $t1, 0x7FFD
beq $t1, $zero, nes_thread_portable
nop
daddiu $sp, $sp, -16
sd $s0, 0($sp)
sd $s1, 8($sp)
la $s0, nes_thread_table
la $s1, global_m
or $a1, $t0, $zero
{load}
b nes_thread_dispatch
addu $t0, $a3, $a1
nes_thread_check:
blez $a2, nes_thread_end
daddiu $t3, $t3, 1
addiu $t1, $a1, -32768
sltiu $t1, $t1, 0x7FFD
beq $t1, $zero, nes_thread_fetch
addu $t0, $a3, $a1
lbu $a0, 0($t0)
nes_thread_dispatch:
sll $t1, $a0, 2
addu $t1, $t1, $s0
lw $t1, 0($t1)
jr $t1
or $v1, $a0, $zero
nes_thread_slow:
addiu $a1, $a1, 1
andi $a1, $a1, 0xFFFF
la $t0, nes_thread_portable
b nes_thread_flush
nop
nes_thread_fetch:
la $t0, __ul_cpurun_slowfetch
b nes_thread_flush
nop
nes_thread_end:
la $t0, __ul_cpurun_done
nes_thread_flush:
{store}
ld $s0, 0($sp)
ld $s1, 8($sp)
jr $t0
daddiu $sp, $sp, 16
nes_thread_portable:
sll $t1, $a0, 2
la $t2, nes_thread_portable_table
addu $t1, $t1, $t2
lw $t1, 0($t1)
jr $t1
nop
"""
    body = (
        "nes_opcode_table:\n" + table(boot_table) + "\n" + assembly(thread) + "\n" +
        "\n".join(assembly(code) for code in handlers.values()) + "\n" +
        "nes_thread_portable_table:\n" + table(portable) + "\n" +
        "nes_thread_table:\n" + table(thread_table) + "\n"
    )
    return source[:old_table.start()] + body + source[old_table.end():]
