"""Summarize ROM polling loops with no externally observable intermediate operations.

For each LDA or BIT of PPUSTATUS, follow immediate ALU instructions and branches for
each possible returned byte. A rule exists only when execution returns to the
same read. The host applies it only inside a device-proven stable interval.
"""


def poll_bank_size(mapper):
    # MMC1 and CNROM expose a copied CPU window. A wait must lie wholly
    # within a single physical 8 KiB slot, including its operand and branch.
    if mapper in (1, 3):
        return 8192
    if mapper in (0, 2, 66):
        return 32768
    return 0


def poll_rule(view, start, status, *, relocatable=False):
    base = 0x8000
    pc = base + start + 3
    bit_test = view[start] == 0x2c
    acc = status
    zero, negative = acc == 0, bool(acc & 128)
    compare = None
    cycles, retired = 4, 1  # final LDA of the same status register
    visited = set()
    while base <= pc <= base + len(view) - 3 and pc not in visited and retired < 32:
        if pc == base + start:
            carry = 0 if compare is None else ((compare + 256) << 16) | (1 << 25)
            return cycles | (retired << 8) | carry
        visited.add(pc)
        i = pc - base
        op, value = view[i], view[i + 1]
        if op in (0x29, 0x09, 0x49, 0xa9, 0xc9):
            if bit_test:
                return 0  # BIT leaves A unchanged, including across skipped iterations.
            if op == 0x29:
                acc &= value
            elif op == 0x09:
                acc |= value
            elif op == 0x49:
                acc ^= value
            elif op == 0xa9:
                acc = value
            else:
                compare = acc - value
            nz = compare if op == 0xc9 else acc
            zero, negative = (nz & 255) == 0, bool(nz & 128)
            pc += 2
            cycles += 2
        elif op in (0xf0, 0xd0, 0x30, 0x10, 0xb0, 0x90, 0x50, 0x70):
            if bit_test and op in (0xf0, 0xd0):
                return 0  # BIT Z depends on the live accumulator.
            if not bit_test and op in (0x50, 0x70):
                return 0  # LDA preserves the preexisting overflow flag.
            if op in (0xb0, 0x90) and compare is None:
                return 0
            take = {0xf0: zero, 0xd0: not zero, 0x30: negative, 0x10: not negative,
                    0xb0: compare is not None and compare >= 0,
                    0x90: compare is not None and compare < 0,
                    0x50: not (status & 64), 0x70: bool(status & 64)}[op]
            pc += 2
            cycles += 2
            if take:
                target = pc + (value if value < 128 else value - 256)
                cycles += 1 + ((target >> 8) != (pc >> 8))
                pc = target
        elif op == 0x4c and not relocatable:
            pc = value | view[i + 2] << 8
            cycles += 3
        elif op == 0xea:
            pc += 1
            cycles += 2
        else:
            return 0
        retired += 1
    return 0


def poll_source(program, mapper):
    tables, sites = {}, []
    span = poll_bank_size(mapper)
    if span:
        for bank in range(0, len(program), span):
            view = program[bank:bank + span]
            for i in range(len(view) - 3):
                if view[i] not in (0xad, 0x2c) or view[i + 1] & 7 != 2 or not 0x20 <= view[i + 2] < 0x40:
                    continue
                rules = tuple(poll_rule(view, i, value, relocatable=span == 8192) for value in range(256))
                if any(rules):
                    table = tables.setdefault(rules, len(tables))
                    sites.append((bank + i + 3, table))
    lines = ["Procedure.i NesPollRule(site.i, value.i)"]
    if sites:
        lines += ["  Select site"]
        for offset, table in sites:
            lines += [f"    Case {offset} : ProcedureReturn PeekL(?NesPollTable{table}+value*4)"]
        lines += ["  EndSelect"]
    lines += ["  ProcedureReturn 0", "EndProcedure"]
    if tables:
        lines += ["DataSection"]
        for rules, table in tables.items():
            lines += [f"NesPollTable{table}:"]
            for i in range(0, 256, 8):
                lines += ["  Data.l " + ",".join(map(str, rules[i:i + 8]))]
        lines += ["EndDataSection"]
    return "\n".join(lines) + "\n", bool(sites)


def stage_poll(source):
    original = "OpAD: ; $AD LDA abs\n  AccessPhase = 3\n  CpuFetchAddress()\n  A = NesRead(Ea)\n  CpuNZ(A)\n"
    if source.count(original) != 1:
        raise ValueError("LDA absolute handler changed")
    batch = """  CompilerIf #NES_HAS_POLLS
    If Left=0 And PC>=$8003 And NesStatusHorizon>CpuCycles+8
      NesLoopRule=NesCurrentPoll(A)
      If NesLoopRule
        NesLoopCost=NesLoopRule&255
        NesIdleExtra=(NesStatusHorizon-CpuCycles-4)/NesLoopCost
        If NesIdleExtra>0
          Left=Left-NesIdleExtra*NesLoopCost
          NesInstructions=NesInstructions+NesIdleExtra*((NesLoopRule>>8)&255)
          If NesLoopRule&$2000000 : FC=~(((NesLoopRule>>16)&511)-256) : EndIf
        EndIf
      EndIf
    EndIf
  CompilerEndIf
"""
    bit = ("Op2C: ; $2C BIT abs\n  AccessPhase = 3\n  CpuFetchAddress()\n"
           "  Value = NesRead(Ea)\n  FN = Value\n  FV = Value << 1\n  FZ = A & Value\n")
    if source.count(bit) != 1:
        raise ValueError("BIT absolute handler changed")
    return source.replace(original, original + batch).replace(
        bit, bit + batch.replace("NesCurrentPoll(A)", "NesCurrentPoll(Value)"))
