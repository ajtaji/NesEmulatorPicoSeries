"""Thread ordinary 2A03 instructions through fixed VR4300 registers.

Device and mapper side effects use the synchronized bus. This span fetches
instructions from ordinary PRG and, on MMC1, from enabled cartridge RAM
or mirrored internal RAM. Runtime MMC3 also reads ordinary cartridge RAM
operands. Low-strobe controller reads shift the latched bit.
A rejected instruction goes to its original handler with the opcode fetched
and the PC advanced exactly once. State is published at a fallback or the
end of the CPU cycle window, before the scheduler checks IRQ and NMI.
"""

import re


def native_handlers(mapper=0, mmc1_20k=False, runtime=False):
    handlers = {}
    common_reads = {}
    schedule_operands = runtime and mapper == 4
    ram_bias = "nesmmc1bias" if mmc1_20k else "nesmmc3bias" if runtime and mapper == 4 else None

    def handler(op, length, cycles, body, phase=None, *, advance_pc=True):
        code = [f"nes_native_{op:02x}:", *body]
        if advance_pc:
            code.append(f"addiu $a1, $a1, {length}")
        if phase is not None:
            code.append(f"addiu $v0, $zero, {phase}")
        code += ["b nes_thread_check", f"daddiu $a2, $a2, -{cycles}"]
        handlers[op] = "\n".join(code)

    def rom_address():
        if mapper == 1:
            # $a3 points at the two prebiased MMC1 PRG halves.
            return ["andi $t1, $t0, 0x4000", "srl $t1, $t1, 11", "addu $t1, $t1, $a3",
                    "ld $t1, 0($t1)", "addu $t0, $t0, $t1"]
        if mapper == 4:
            return ["andi $t1, $t0, 0x6000", "srl $t1, $t1, 10", "addu $t1, $t1, $a3",
                    "ld $t1, 0($t1)", "addu $t0, $t0, $t1"]
        return ["addu $t0, $t0, $a3"]

    def fetch_word(high_reg):
        # Both bytes are in the already-accepted ordinary fetch span.
        # Load the high byte first to separate its load and shift.
        low = "lbu $t1, 1($t0)"
        high = f"lbu {high_reg}, 2($t0)"
        return [high, low] if schedule_operands else [low, high]

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
            code = [*fetch_word("$t2"), "sll $t2, $t2, 8",
                    "or $t1, $t1, $t2"]
            if mode in ("ind_x", "ind_y"):
                code = ["lbu $t1, 1($t0)"]
                if mode == "ind_x":
                    code += ["addu $t1, $t1, $a5", "andi $t1, $t1, 0xFF"]
                code += ["addu $t2, $s1, $t1",
                         "addiu $t1, $t1, 1", "andi $t1, $t1, 0xFF", "addu $t0, $s1, $t1"]
                if schedule_operands:
                    code += ["lbu $t0, 0($t0)", "lbu $t1, 0($t2)", "sll $t0, $t0, 8",
                             "or $t1, $t1, $t0"]
                else:
                    code += ["lbu $t1, 0($t2)", "lbu $t2, 0($t0)", "sll $t2, $t2, 8",
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
                if mapper == 1 and op == 0x8d:
                    # Keep the resolved address for the normal bus handler.
                    code += ["andi $t1, $t0, 0x8000", "bne $t1, $zero, nes_native_mapper_serial",
                             "or $a0, $t0, $zero", "sltiu $t1, $t0, 0x2000",
                             "beq $t1, $zero, nes_absolute_store"]
                elif runtime and mapper == 4 and op == 0x8d:
                    code += ["sltiu $t1, $t0, 0x2000",
                             "beqz $t1, nes_native_mmc3_select", "nop"]
                else:
                    code += ["sltiu $t1, $t0, 0x2000", "beq $t1, $zero, nes_thread_slow"]
                code += ["andi $t0, $t0, 0x7FF", "addu $t0, $t0, $s1"]
            else:
                rom = f"nes_native_{op:02x}_rom"
                read = f"nes_native_{op:02x}_read"
                # Low-strobe controller reads only shift the latched snapshot.
                # A live read still goes through the asynchronous pad bridge.
                serial = mapper in (1, 4) and op in (0xad, 0xbd)
                io = f"nes_native_{op:02x}_io" if serial else "nes_thread_slow"
                lower = io
                lower_test = "nop"
                cartridge_ram = []
                if ram_bias:
                    # The lower half here excludes mirrored CPU RAM. Preserve
                    # t0 for controller I/O and t2 for an indexed page penalty.
                    # Disabled SRAM uses the original bus path to regain open bus.
                    lower = f"nes_native_{op:02x}_lower"
                    lower_test = "sltiu $t1, $t0, 0x6000"
                    cartridge_ram = [
                        lower + ":", f"bne $t1, $zero, {io}", "andi $t1, $t0, 0x1FFF",
                        f"ld $t0, global_mapramenable-global_{ram_bias}($a3)",
                        "beq $t0, $zero, nes_thread_slow", "nop",
                        "la $t0, global_mapram", f"b {read}", "addu $t0, $t0, $t1",
                    ]
                code += ["andi $t1, $t0, 0x8000", f"bne $t1, $zero, {rom}",
                         "sltiu $t1, $t0, 0x2000", f"beq $t1, $zero, {lower}", lower_test,
                         "andi $t0, $t0, 0x7FF", f"b {read}", "addu $t0, $t0, $s1",
                         *cartridge_ram, rom + ":", *rom_address(), read + ":"]
                if serial:
                    # Internal RAM and ordinary PRG already have host pointers.
                    # Both routes meet after reading the byte.
                    done = f"{io}_done"
                    code += ["lbu $v1, 0($t0)", f"b {done}", "nop", io + ":",
                             "addiu $t1, $t0, -0x4016", "sltiu $t0, $t1, 2",
                             "beq $t0, $zero, nes_thread_slow", "nop",
                             "la $t0, global_nesstrobe", "ld $t0, 0($t0)",
                             "bne $t0, $zero, nes_thread_slow", "nop",
                             f"beq $t1, $zero, {io}_port1", "nop", "la $t0, global_neslatch2",
                             f"b {io}_shift", "nop", f"{io}_port1:", "la $t0, global_neslatch",
                             f"{io}_shift:", "ld $t1, 0($t0)", "andi $v1, $t1, 1",
                             "ori $v1, $v1, 64", "srl $t1, $t1, 1", "ori $t1, $t1, 128",
                             "sd $t1, 0($t0)", done + ":"]
                if indexed:
                    code += ["dsubu $a2, $a2, $t2"]
                if serial:
                    return code
        if not write:
            code += ["lbu $v1, 0($t0)"]
            if mapper == 1 and mode in ("abs", "absx", "absy", "ind_x", "ind_y"):
                entry = f"nes_read_operand_{mode}"
                prefix = f"nes_native_{op:02x}_"
                body = [word.replace(prefix, entry + "_") for word in code[1:-1]]
                shared = [entry + ":", *body, "jr $ra", code[-1]]
                if common_reads.setdefault(entry, shared) != shared:
                    raise ValueError(f"Inconsistent MMC1 operand reader for {mode}")
                return [f"jal {entry}", code[0]]
        return code

    modes = {"imm": (2, 2), "zp": (2, 3), "zpx": (2, 4), "zpy": (2, 4),
             "abs": (3, 4), "absx": (3, 4), "absy": (3, 4), "ind_y": (2, 5), "ind_x": (2, 6)}

    def value_op(op, mode, code):
        length, cycles = modes[mode]
        phase = {"ind_x": 5, "ind_y": 4}.get(mode, 3 if mode.startswith("abs") else None)
        read = operand(op, mode)
        # The final native data load is past every bus fallback. Advance PC
        # in its load-use gap before executing the register-only operation.
        advance_early = schedule_operands and read[-1] in ("lbu $v1, 0($t0)", "lbu $v1, 1($t0)")
        if advance_early:
            read.append(f"addiu $a1, $a1, {length}")
        handler(op, length, cycles, read + code, phase, advance_pc=not advance_early)

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
    if mapper in (1, 4):
        # Ordinary RMW instructions only use this path for internal RAM. MMIO
        # and mapper addresses go through both bus writes in the portable core.
        for base, operation in (
            (0x06, ("sll $t9, $v1, 1", "andi $v1, $t9, 255")),
            (0x26, ("srl $t1, $t9, 8", "andi $t1, $t1, 1", "sll $t9, $v1, 1",
                    "or $t9, $t9, $t1", "andi $v1, $t9, 255")),
            (0x46, ("sll $t9, $v1, 8", "srl $v1, $v1, 1")),
            (0x66, ("srl $t1, $t9, 1", "andi $t1, $t1, 128", "sll $t9, $v1, 8",
                    "srl $v1, $v1, 1", "or $v1, $v1, $t1")),
        ):
            for offset, mode, cycles, phase in ((0, "zp", 5, None), (16, "zpx", 6, None),
                                                 (8, "abs", 6, 5), (24, "absx", 7, 6)):
                op = base + offset
                handler(op, modes[mode][0], cycles, operand(op, mode, write=True) +
                        ["lbu $v1, 0($t0)", *operation, "sb $v1, 0($t0)", *nz("$v1")], phase)
    if mapper == 4:
        for op, mode, cycles, phase, delta in (
            (0xCE, "abs", 6, 5, -1), (0xDE, "absx", 7, 6, -1),
            (0xEE, "abs", 6, 5, 1), (0xFE, "absx", 7, 6, 1),
        ):
            handler(op, modes[mode][0], cycles, operand(op, mode, write=True) +
                    ["lbu $v1, 0($t0)", f"addiu $v1, $v1, {delta}", "andi $v1, $v1, 255",
                     "sb $v1, 0($t0)", *nz("$v1")], phase)
    # A branch that is not taken never reaches the portable core's
    # operand read. Fetch the displacement only on the taken path.
    for op, flag, mask, take_when_set, idle_offsets in (
        (0x10, "$t8", 0x80, False, ()), (0x30, "$t8", 0x80, True, ()),
        (0x90, "$t9", 0x100, False, ()), (0xB0, "$t9", 0x100, True, ()),
        (0x50, "$t2", 0x80, False, ()), (0x70, "$t2", 0x80, True, ()),
        (0xD0, "$a7", 0xFF, True, (-6, -3)), (0xF0, "$a7", 0xFF, False, (-7, -4)),
    ):
        label = f"nes_native_{op:02x}"
        branch = "beq" if take_when_set else "bne"
        overflow = ["la $t2, global_fv", "ld $t2, 0($t2)"] if flag == "$t2" else []
        code = [label + ":", *overflow, f"andi $t1, {flag}, {mask}",
                f"{branch} $t1, $zero, {label}_not_taken",
                "addiu $t1, $a1, 2", "lb $t2, 1($t0)"]
        for offset in idle_offsets:
            if mapper not in (1, 4):
                code += [f"addiu $t0, $zero, {offset}", "beq $t2, $t0, nes_thread_slow", "nop"]
                continue
            # Only the documented polling shapes need the portable handler.
            # Crossing a physical bank must use the ordinary mapped-bus check.
            skip = f"{label}_skip_{-offset}"
            back = -offset - 2
            # The countdown (-3: DEX or DEY, then this BNE) has two possible first bytes; its
            # whole pattern is the decrement and this branch, so it always goes to the portable test.
            first = 0xa5 if offset == -4 else 0xad
            code += [f"addiu $t1, $zero, {offset}", f"bne $t2, $t1, {skip}",
                     "andi $t1, $a1, 0x8000", f"beq $t1, $zero, {skip}",
                     f"andi $t1, $a1, {0x3fff if mapper == 1 else 0x1fff}", f"sltiu $t1, $t1, {back}",
                     "bne $t1, $zero, nes_thread_slow", "nop"]
            if offset == -3:
                code += ["b nes_thread_slow", "nop"]
            else:
                code += [f"lbu $t1, -{back}($t0)",
                         f"xori $t1, $t1, {first}", "beq $t1, $zero, nes_thread_slow", "nop"]
            code += [skip + ":", "addiu $t1, $a1, 2"]
        code += [
            "andi $v1, $t2, 0xFF", "addu $a1, $t1, $t2", "andi $a1, $a1, 0xFFFF",
            "xor $t2, $a1, $t1", "srl $t2, $t2, 8", "sltu $t2, $zero, $t2",
            "daddiu $a2, $a2, -3", "b nes_thread_check", "dsubu $a2, $a2, $t2",
            label + "_not_taken:", "or $a1, $t1, $zero",
            "b nes_thread_check", "daddiu $a2, $a2, -2",
        ]
        handlers[op] = "\n".join(code)

    jump_word = "\n".join(fetch_word("$t2"))
    handlers[0x4C] = f"""nes_native_4c:
{jump_word}
sll $t0, $t2, 8
or $t1, $t1, $t0
beq $a1, $t1, nes_thread_slow
nop
or $v1, $t2, $zero
or $a1, $t1, $zero
addiu $v0, $zero, 2
b nes_thread_check
daddiu $a2, $a2, -3"""
    if mmc1_20k:
        # Batch repeated JMP-to-self instructions up to the current CPU budget.
        # The ordinary handler covers pending stalls and mutable I/O mappings.
        handlers[0x4C] = handlers[0x4C].replace("beq $a1, $t1, nes_thread_slow",
                                                 "beq $a1, $t1, nes_native_idle_jump")
        handlers[0x4C] += """
nes_native_idle_jump:
sltiu $t0, $a2, 129
beq $t0, $zero, nes_thread_slow
sltiu $t0, $a2, 4
bne $t0, $zero, nes_thread_slow
andi $t0, $a1, 0x8000
bne $t0, $zero, nes_idle_address_ok
sltiu $t0, $a1, 0x1ffe
beq $t0, $zero, nes_thread_slow
nop
nes_idle_address_ok:
ld $t1, global_nesidleenabled-global_nesmmc1bias($a3)
beq $t1, $zero, nes_thread_slow
ld $t1, global_nesstall-global_nesmmc1bias($a3)
bne $t1, $zero, nes_thread_slow
nop
la $t0, nes_idle_repeat_count
addu $t0, $t0, $a2
lbu $t0, 0($t0)
ld $t1, global_nesidlebatched-global_nesmmc1bias($a3)
sd $t0, global_nesidleextra-global_nesmmc1bias($a3)
daddu $t1, $t1, $t0
sd $t1, global_nesidlebatched-global_nesmmc1bias($a3)
sd $a1, global_ea-global_nesmmc1bias($a3)
daddu $t3, $t3, $t0
sll $t1, $t0, 1
addu $t1, $t1, $t0
dsubu $a2, $a2, $t1
or $v1, $t2, $zero
addiu $v0, $zero, 2
b nes_thread_check
daddiu $a2, $a2, -3
nes_idle_repeat_count:"""
        repeats = bytes(max(0, (budget - 1) // 3) for budget in range(132))
        handlers[0x4C] += "\n" + "\n".join(f".word 0x{repeats[i:i+4].hex()}" for i in range(0, 132, 4))
    stack_slot = "global_s-global_nesmmc3bias($a3)" if mapper == 4 else "0($t1)"
    stack_pointer = "" if mapper == 4 else "la $t1, global_s\n"
    jsr_address = ["addu $t0, $s1, $t2", "srl $v0, $a1, 8"]
    if schedule_operands:
        jsr_address.reverse()
    jsr_word = "\n".join(fetch_word("$v1"))
    jsr_stack_address = "\n".join(jsr_address)
    handlers[0x20] = f"""nes_native_20:
{jsr_word}
sll $t0, $v1, 8
or $a0, $t0, $t1
addiu $a1, $a1, 2
{stack_pointer}ld $t2, {stack_slot}
{jsr_stack_address}
sb $v0, 0x100($t0)
addiu $t2, $t2, -1
andi $t2, $t2, 0xFF
addu $t0, $s1, $t2
sb $a1, 0x100($t0)
addiu $t2, $t2, -1
andi $t2, $t2, 0xFF
sd $t2, {stack_slot}
or $a1, $a0, $zero
addiu $v0, $zero, 5
b nes_thread_check
daddiu $a2, $a2, -6"""
    stack_slot = "global_s-global_nesmmc3bias($a3)" if mapper == 4 else "0($t0)"
    stack_pointer = "" if mapper == 4 else "la $t0, global_s\n"
    handlers[0x60] = f"""nes_native_60:
{stack_pointer}ld $t2, {stack_slot}
addiu $t2, $t2, 1
andi $t2, $t2, 0xFF
addu $t1, $s1, $t2
lbu $a0, 0x100($t1)
addiu $t2, $t2, 1
andi $t2, $t2, 0xFF
sd $t2, {stack_slot}
addu $t1, $s1, $t2
lbu $t2, 0x100($t1)
sll $t2, $t2, 8
or $a1, $a0, $t2
addiu $a1, $a1, 1
andi $a1, $a1, 0xFFFF
b nes_thread_check
daddiu $a2, $a2, -6"""
    if mapper == 4 and runtime:
        handlers.update(mmc3_control_handlers())
    return handlers, ["\n".join(reader) for reader in common_reads.values()]


def mmc3_control_handlers():
    """Complete the runtime MMC3 opcode table with stack and control ops."""
    def state(name):
        return f"global_{name}-global_nesmmc3bias($a3)"

    stack = state("s")

    def push(value):
        return [f"addu $t1, $s1, $t2", f"sb {value}, 0x100($t1)",
                "addiu $t2, $t2, -1", "andi $t2, $t2, 0xFF"]

    def pop(value):
        return ["addiu $t2, $t2, 1", "andi $t2, $t2, 0xFF",
                "addu $t1, $s1, $t2", f"lbu {value}, 0x100($t1)"]

    status = ["andi $t0, $t8, 0x80", f"ld $t1, {state('fv')}",
              "andi $t1, $t1, 0x80", "srl $t1, $t1, 1", "or $t0, $t0, $t1",
              "ori $t0, $t0, 0x30", f"ld $t1, {state('fd')}",
              "sll $t1, $t1, 3", "or $t0, $t0, $t1", f"ld $t1, {state('fi')}",
              "sll $t1, $t1, 2", "or $t0, $t0, $t1", "srl $t1, $t9, 8",
              "andi $t1, $t1, 1", "or $t0, $t0, $t1", "andi $t1, $a7, 0xFF",
              "sltiu $t1, $t1, 1", "sll $t1, $t1, 1", "or $t0, $t0, $t1",
              f"sd $t0, {state('tmp')}"]
    restore_status = [
        f"sd $t0, {state('tmp')}", "or $t8, $t0, $zero", "sll $t1, $t0, 1",
        f"sd $t1, {state('fv')}", "andi $t9, $t0, 1", "sll $t9, $t9, 8",
        "andi $a7, $t0, 2", "xori $a7, $a7, 2", "srl $t1, $t0, 3",
        "andi $t1, $t1, 1", f"sd $t1, {state('fd')}", "srl $a0, $t0, 2",
        "andi $a0, $a0, 1", f"sd $a0, {state('fi')}",
    ]
    def code(op, lines):
        return "\n".join((f"nes_native_{op:02x}:", *lines))

    def finish(cycles):
        return ["b nes_thread_check", f"daddiu $a2, $a2, -{cycles}"]

    def implied(op, cycles, lines):
        return code(op, [*lines, "addiu $a1, $a1, 1", *finish(cycles)])

    def poll_irq(cycles, flag_in_a0=False):
        fallthrough = f"nes_mmc3_status_continue_{cycles}"
        return [
            *([f"bnez $a0, {fallthrough}", f"ld $t0, {state('mapirq')}"] if flag_in_a0
              else [f"ld $t0, {state('mapirq')}"]),
            f"beqz $t0, {fallthrough}", f"ld $t1, {state('budget')}",
            # CpuEndWindow clears Left before CpuNextOp charges this opcode.
            "dsubu $t1, $t1, $a2", f"sd $t1, {state('budget')}",
            "b nes_thread_end", f"daddiu $a2, $zero, -{cycles}",
            fallthrough + ":", *finish(cycles),
        ]

    return {
        0x08: implied(0x08, 3, [f"ld $t2, {stack}", *status, *push("$t0"), f"sd $t2, {stack}"]),
        0x78: implied(0x78, 2, ["addiu $t1, $zero, 1", f"sd $t1, {state('fi')}"]),
        0xB8: implied(0xB8, 2, [f"sd $zero, {state('fv')}"]),
        0xD8: implied(0xD8, 2, [f"sd $zero, {state('fd')}"]),
        0xF8: implied(0xF8, 2, ["addiu $t1, $zero, 1", f"sd $t1, {state('fd')}"]),
        0x00: code(0x00, [
            "addiu $a1, $a1, 2", "andi $a1, $a1, 0xFFFF",
            f"ld $t2, {stack}", "srl $t0, $a1, 8", *push("$t0"), *push("$a1"),
            *status, *push("$t0"), f"sd $t2, {stack}",
            "addiu $t0, $zero, 1", f"sd $t0, {state('fi')}",
            # Both vector bytes always use the ordinary top PRG window.
            "ld $t1, 24($a3)", "ori $t2, $zero, 0xFFFE", "addu $t1, $t1, $t2",
            "lbu $v1, 1($t1)", "lbu $t0, 0($t1)", "sll $t1, $v1, 8",
            "or $a1, $t0, $t1", *finish(7),
        ]),
        0x28: code(0x28, [
            f"ld $t2, {stack}", *pop("$t0"), f"sd $t2, {stack}", *restore_status,
            "addiu $a1, $a1, 1", *poll_irq(4, flag_in_a0=True),
        ]),
        0x40: code(0x40, [
            f"ld $t2, {stack}", *pop("$t0"), *restore_status,
            *pop("$a1"), f"sd $a1, {state('lo')}",
            *pop("$t0"), f"sd $t0, {state('hi')}", f"sd $t2, {stack}",
            "sll $t0, $t0, 8", "or $a1, $a1, $t0",
            *poll_irq(6, flag_in_a0=True),
        ]),
        0x58: code(0x58, [
            f"sd $zero, {state('fi')}", "addiu $a1, $a1, 1", *poll_irq(2),
        ]),
        0x6C: code(0x6C, [
            "lbu $t2, 2($t0)", "lbu $t1, 1($t0)", "sll $t2, $t2, 8",
            "or $t0, $t1, $t2", "sltiu $t1, $t0, 0x2000",
            "bnez $t1, nes_mmc3_jump_ind_ram", "andi $t1, $t0, 0x8000",
            # Device and SRAM reads retain the shared bus and timing path.
            "beqz $t1, nes_thread_slow", "andi $t1, $t0, 0x6000",
            "srl $t1, $t1, 10", "addu $t1, $t1, $a3", "ld $t1, 0($t1)",
            "b nes_mmc3_jump_ind_read", "or $t2, $t0, $zero",
            "nes_mmc3_jump_ind_ram:", "or $t1, $s1, $zero", "andi $t2, $t0, 0x7FF",
            "nes_mmc3_jump_ind_read:", f"sd $t0, {state('ea')}",
            # The high byte wraps within the first byte's guest page.
            "andi $t0, $t2, 0xFF00", "addiu $a0, $t2, 1",
            "andi $a0, $a0, 0xFF", "or $t0, $t0, $a0",
            "addu $t2, $t2, $t1", "addu $t0, $t0, $t1",
            "lbu $v1, 0($t0)", "lbu $t2, 0($t2)", "sll $t0, $v1, 8",
            "or $a1, $t2, $t0", "addiu $v0, $zero, 4", *finish(5),
        ]),
    }



def assembly(text):
    return "\n".join(line if line.endswith(":") else "    " + line for line in text.splitlines())


def table(labels):
    return "\n".join("    .word " + ", ".join(labels[i:i + 4]) for i in range(0, len(labels), 4))


# Inputs are guest PC in t0 and decoded opcode in a0. Return the aligned
# guest base in t0, the host bias in t1 and the safe fetch extent in t2.
EXEC_REGION = """andi $t1, $t0, 0x8000
bne $t1, $zero, nes_exec_prg
andi $t1, $t0, {prg_mask}
sltiu $t1, $t0, 0x2000
bne $t1, $zero, nes_exec_ram
andi $t1, $t0, 0x7ff
sltiu $t1, $t0, 0x6000
bne $t1, $zero, nes_thread_portable
nop
la $t1, global_mapramenable
ld $t1, 0($t1)
beq $t1, $zero, nes_thread_portable
andi $t1, $t0, 0x1fff
sltiu $t1, $t1, 0x1ffd
beq $t1, $zero, nes_thread_portable
ori $t0, $zero, 0x6000
la $t1, global_mapram
subu $t1, $t1, $t0
b nes_exec_entry
ori $t2, $zero, 0x1ffd
nes_exec_ram:
sltiu $t1, $t1, 0x7fd
beq $t1, $zero, nes_thread_portable
andi $t0, $t0, 0xf800
la $t1, global_m
subu $t1, $t1, $t0
b nes_exec_entry
ori $t2, $zero, 0x7fd
nes_exec_prg:
sltiu $t1, $t1, {prg_extent}
beq $t1, $zero, nes_thread_portable
andi $t0, $t0, {prg_base_mask}
andi $t1, $t0, {slot_mask}
srl $t1, $t1, {slot_shift}
la $t2, {bias}
addu $t1, $t1, $t2
ld $t1, 0($t1)
ori $t2, $zero, {prg_extent}
nes_exec_entry:"""


def chain_window(has_waits):
    """Continue only an armed 128-cycle window behind the device horizon."""
    possible_wait = """
andi $t1, $a1, 0x8000
beq $t1, $zero, nes_chain_begin
andi $t1, $a1, 255
la $t0, nespossiblewait
addu $t1, $t1, $t0
lbu $t1, 0($t1)
bne $t1, $zero, nes_chain_exit
nop
""" if has_waits else ""
    # At entry the live guest bus byte stays in v1. WorkerAdvance revokes
    # the scheduler's proof before it can change guest-visible device state.
    # NROM and MMC1 have no mapper IRQ. Recheck the APU IRQ against the I flag,
    # which an instruction may have changed since the scheduler armed us.
    # A possible wait PC returns to the full physical-bank lookup.
    # The NMI (design note N.77): a chained window (128 cycles and the instruction that ends it, at most 7) must end
    # before NesNmiDue, where the run loop takes the NMI; so no chain from a window end after NesNmiDue - 136 - nor after
    # NesFrameDue - 136, the frame's end, where the host samples the frame (N.78). Read live:
    # a PPUCTRL write in the window (it ends the window, then this test) may have just made the edge.
    return """la $t0, global_budget
ld $t1, 0($t0)
la $t0, global_nesrunstart
ld $t0, 0($t0)
daddu $t1, $t1, $t0
dsubu $a0, $t1, $a2
la $t0, global_neschainlimit
ld $t1, 0($t0)
slt $t0, $t1, $a0
bne $t0, $zero, nes_chain_exit
nop
la $t0, global_nesnmidue
ld $t1, 0($t0)
daddiu $t1, $t1, -136
slt $t0, $t1, $a0
bne $t0, $zero, nes_chain_exit
nop
la $t0, global_nesframedue
ld $t1, 0($t0)
daddiu $t1, $t1, -136
slt $t0, $t1, $a0
bne $t0, $zero, nes_chain_exit
nop
la $t0, global_workerirq
ld $t1, 0($t0)
beq $t1, $zero, nes_chain_noirq
nop
la $t0, global_fi
ld $t1, 0($t0)
beq $t1, $zero, nes_chain_exit
nop
nes_chain_noirq:
""" + possible_wait + """nes_chain_begin:
la $t0, global_cpucycles
sd $a0, 0($t0)
la $t0, global_nesrunstart
sd $a0, 0($t0)
addiu $a2, $zero, 128
la $t0, global_budget
sd $a2, 0($t0)
b nes_chain_fetch
nop
nes_chain_exit:
"""


def stage_thread(source: str, mapper: int = 0, has_waits: bool = False, chain_nrom: bool = False,
                 mmc1_20k: bool = False, runtime: bool = False) -> str:
    old_table = re.search(r"^nes_opcode_table:\n(?P<words>(?:    \.word .*\n)+)", source, re.M)
    if old_table is None:
        raise ValueError("VR4300 opcode table is missing")
    portable = re.findall(r"__ul_cpurun_\w+", old_table["words"])
    if len(portable) != 256:
        raise ValueError("VR4300 opcode table has wrong size")
    handlers, readers = native_handlers(mapper, mmc1_20k, runtime)
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
    banked = mapper in (1, 4)
    window = 0x4000 if mapper == 1 else 0x2000
    bias = "global_nesmmc1bias" if mapper == 1 else "global_nesmmc3bias"
    if banked:
        live = tuple(reg for reg in live if reg[0] != "prgbias")
    load = "\n".join(f"la $t1, global_{name}\nld {reg}, 0($t1)" for name, reg in live)
    if banked:
        load += f"\nla $a3, {bias}"
    if mapper == 4:
        # The bank-bias table and CPU scalars share the same small data range.
        load = "\n".join([f"la $a3, {bias}"] +
                         [f"ld {reg}, global_{name}-{bias}($a3)" for name, reg in live])

    # A mapper write exits the native span. Cache the bias of the current
    # contiguous region until the next opcode or its operands leave it. RAM
    # stays writable and each dispatch fetches the current instruction bytes.
    def rom_guard(pc, fallback, delay="nop"):
        return f"addiu $t1, {pc}, -32768\nsltiu $t1, $t1, 0x7FFD\nbeq $t1, $zero, {fallback}\n{delay}"

    entry_guard = rom_guard("$t0", "nes_thread_portable")
    first_dispatch = "b nes_thread_dispatch\naddu $t0, $a3, $a1"
    next_fetch = rom_guard("$a1", "nes_thread_fetch", "addu $t0, $a3, $a1")
    next_window = chain_window(has_waits) if mapper == 1 or chain_nrom else ""
    if chain_nrom:
        next_fetch = "nes_chain_fetch:\n" + next_fetch
    stack_size = 16
    save_region = ""
    restore_region = ""
    guest_pc = "or $a1, $t0, $zero"
    if banked:
        entry_guard = EXEC_REGION.format(prg_mask=window-1, prg_extent=window-3,
                                         prg_base_mask=0x10000-window,
                                         slot_mask=0x8000-window,
                                         slot_shift=window.bit_length()-4, bias=bias)
        stack_size = 48
        save_region = """sd $ra, 40($sp)
sd $s2, 16($sp)
sd $s3, 24($sp)
sd $s4, 32($sp)
or $s2, $t0, $zero
or $s3, $t1, $zero
or $s4, $t2, $zero"""
        restore_region = "ld $ra, 40($sp)\nld $s2, 16($sp)\nld $s3, 24($sp)\nld $s4, 32($sp)"
        guest_pc = "addiu $a1, $a1, -1\nandi $a1, $a1, 0xffff"
        first_dispatch = "b nes_thread_dispatch\naddu $t0, $a1, $s3"
        next_fetch = ("nes_chain_fetch:\nsubu $t1, $a1, $s2\nsltu $t1, $t1, $s4\n"
                      "beq $t1, $zero, nes_thread_fetch\naddu $t0, $a1, $s3")
    rebase = ""
    if mapper == 4:
        next_fetch = next_fetch.replace("nes_thread_fetch", "nes_thread_rebase")
        # Crossing into another ROM bank can keep the live CPU registers.
        # Border bytes still use the mapped bus for each operand.
        rebase = """nes_thread_rebase:
andi $t1, $a1, 0x8000
beqz $t1, nes_thread_fetch
andi $t1, $a1, 0x1fff
sltiu $t1, $t1, 0x1ffd
beqz $t1, nes_thread_fetch
andi $s2, $a1, 0xe000
andi $t1, $s2, 0x6000
srl $t1, $t1, 10
addu $t1, $t1, $a3
ld $s3, 0($t1)
ori $s4, $zero, 0x1ffd
addu $t0, $a1, $s3
b nes_thread_dispatch
lbu $a0, 0($t0)
"""
    check = "daddiu $t3, $t3, 1\n" + next_fetch
    dispatch_jump = "jr $t1\nor $v1, $a0, $zero"
    undo_charge = ""
    if banked:
        # The region subtraction fills the budget branch's delay slot. The
        # table load can publish open bus while the jump target is in flight.
        # Charge the opcode in the jump delay slot and undo it on fallback.
        check = next_fetch
        dispatch_jump = "or $v1, $a0, $zero\njr $t1\ndaddiu $t3, $t3, 1"
        undo_charge = "daddiu $t3, $t3, -1\n"
    publish = (("pc", "$a1"), ("nesopenbus", "$v1")) + tuple(r for r in live if r[0] != "prgbias")
    store = "\n".join(f"la $t1, global_{name}\nsd {reg}, 0($t1)" for name, reg in publish)
    if mapper == 4:
        store = "\n".join(f"sd {reg}, global_{name}-{bias}($a3)" for name, reg in publish)
    thread = f"""nes_thread_enter:
addiu $t0, $a1, -1
andi $t0, $t0, 0xFFFF
{entry_guard}
daddiu $sp, $sp, -{stack_size}
{save_region}
sd $s0, 0($sp)
sd $s1, 8($sp)
la $s0, nes_thread_table
la $s1, global_m
{guest_pc}
{load}
{first_dispatch}
nes_thread_check:
blez $a2, nes_thread_end
{check}
lbu $a0, 0($t0)
nes_thread_dispatch:
sll $t1, $a0, 2
addu $t1, $t1, $s0
lw $t1, 0($t1)
{dispatch_jump}
nes_thread_slow:
{undo_charge}addiu $a1, $a1, 1
andi $a1, $a1, 0xFFFF
la $t0, nes_thread_portable
b nes_thread_flush
nop
{rebase}nes_thread_fetch:
la $t0, __ul_cpurun_slowfetch
b nes_thread_flush
nop
nes_thread_end:
{next_window}la $t0, __ul_cpurun_done
nes_thread_flush:
{store}
ld $s0, 0($sp)
ld $s1, 8($sp)
{restore_region}
jr $t0
daddiu $sp, $sp, {stack_size}
nes_thread_portable:
sll $t1, $a0, 2
la $t2, nes_thread_portable_table
addu $t1, $t1, $t2
lw $t1, 0($t1)
jr $t1
nop
"""
    if mapper == 1:
        # An intermediate MMC1 bit changes only the write latch. Publish its
        # exact bus phase and end this CPU window as the portable store does.
        # A reset or fifth bit can affect a live mapping and uses the full bus.
        thread += """nes_native_mapper_serial:
andi $t1, $a4, 128
bne $t1, $zero, nes_absolute_store
nop
la $t0, global_mapshift
ld $t1, 0($t0)
andi $t2, $t1, 1
bne $t2, $zero, nes_absolute_store
nop
la $t0, global_budget
ld $t1, 0($t0)
dsubu $t1, $t1, $a2
sd $t1, 0($t0)
la $t2, global_nesrunstart
ld $t2, 0($t2)
daddu $t1, $t1, $t2
addiu $t1, $t1, 3
la $t0, global_maplastwrite
ld $t2, 0($t0)
sd $t1, 0($t0)
dsubu $t1, $t1, $t2
addiu $t1, $t1, -1
beq $t1, $zero, nes_native_serial_done
nop
la $t0, global_mapshift
ld $t1, 0($t0)
andi $t2, $a4, 1
sll $t2, $t2, 4
srl $t1, $t1, 1
or $t1, $t1, $t2
sd $t1, 0($t0)
nes_native_serial_done:
or $v1, $a4, $zero
addiu $v0, $zero, 3
addiu $a1, $a1, 3
b nes_thread_check
addiu $a2, $zero, -4
"""
    if mapper == 1 or (runtime and mapper == 4):
        # Rejoin STA after CpuFetchAddress with the high address byte on the
        # guest bus. The original store applies all side effects and retires once.
        thread += f"""nes_absolute_store:
sd $a0, global_ea-{bias}($a3)
srl $v1, $a0, 8
addiu $a1, $a1, 3
andi $a1, $a1, 0xffff
addiu $v0, $zero, 3
la $t0, __ul_cpurun_nesstoreabsolute
b nes_thread_flush
daddiu $t3, $t3, -1
"""
    if runtime and mapper == 4:
        # Same selector-only case as the runtime MMC3 bus. Mode changes and
        # device writes still use the synchronized CPU bus.
        thread += """nes_native_mmc3_select:
andi $t1, $t0, 0xe001
ori $t2, $zero, 0x8000
bne $t1, $t2, nes_absolute_store
or $a0, $t0, $zero
ld $t1, global_mapselect-global_nesmmc3bias($a3)
xor $t1, $t1, $a4
andi $t1, $t1, 0xc0
bnez $t1, nes_absolute_store
nop
sd $a4, global_mapselect-global_nesmmc3bias($a3)
or $v1, $a4, $zero
addiu $v0, $zero, 3
addiu $a1, $a1, 3
b nes_thread_check
daddiu $a2, $a2, -4
"""
    # Separate the threaded entry from the scheduler's hot instruction-cache
    # sets on the VR4300. The opcode table jumps over this unused space.
    cache_gap = "    .word 0,0,0,0,0,0,0,0\n" * 16 if runtime and mapper == 4 else ""
    body = (
        "nes_opcode_table:\n" + table(boot_table) + "\n" + cache_gap + assembly(thread) + "\n" +
        "\n".join(assembly(code) for code in (*handlers.values(), *readers)) + "\n" +
        "nes_thread_portable_table:\n" + table(portable) + "\n" +
        "nes_thread_table:\n" + table(thread_table) + "\n"
    )
    return source[:old_table.start()] + body + source[old_table.end():]
