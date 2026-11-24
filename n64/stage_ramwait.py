"""Find polling pairs in immutable 32 KiB PRG views."""

from itertools import combinations

from stage_poll import poll_bank_size

# Actions: LDA, LDX, LDY, CMP, CPX, CPY, BIT. Addressing modes:
# zero page, zero page indexed by X/Y, absolute, absolute indexed by X/Y.
READS = {
    0xA5: (1, 0), 0xB5: (1, 1), 0xAD: (1, 3), 0xBD: (1, 4), 0xB9: (1, 5),
    0xA6: (2, 0), 0xB6: (2, 2), 0xAE: (2, 3), 0xBE: (2, 5),
    0xA4: (3, 0), 0xB4: (3, 1), 0xAC: (3, 3), 0xBC: (3, 4),
    0xC5: (4, 0), 0xD5: (4, 1), 0xCD: (4, 3), 0xDD: (4, 4), 0xD9: (4, 5),
    0xE4: (5, 0), 0xEC: (5, 3),
    0xC4: (6, 0), 0xCC: (6, 3),
    0x24: (7, 0), 0x2C: (7, 3),
}
WINDOW_CYCLES = 128


def phase_period(read_cycles, branch_cycles, at_branch):
    """Cycles and retired instructions to repeat a scheduled window phase."""
    phase, spent, retired = at_branch, 0, 0
    for _ in range(2):
        remaining = WINDOW_CYCLES
        while remaining > 0:
            charge = branch_cycles if phase else read_cycles
            phase = not phase
            remaining -= charge
            spent += charge
            retired += 1
        if phase == at_branch:
            return spent, retired
    raise ValueError("128-cycle polling window has no repeating phase")


def wait_lookup(sites):
    # Use a bounded, collision-free hash when the sparse PRG sites fit in
    # a small table. Verify the full view-relative key on every lookup.
    for size in (64, 128, 256, 512):
        if len(sites) > size // 2:
            continue
        mask = size - 1
        for first, second in combinations(range(1, 21), 2):
            indices = {(key ^ (key >> first) ^ (key >> second)) & mask: key for key in sites}
            if len(indices) != len(sites):
                continue
            lines = [
                "Procedure.i NesRamWaitRule(site.i)",
                "  Protected row.i",
                f"  row=?NesRamWaitHash+(((site!(site>>{first})!(site>>{second}))&{mask})<<3)",
                "  If PeekL(row)=site : ProcedureReturn PeekL(row+4) : EndIf",
                "  ProcedureReturn 0",
                "EndProcedure",
                "DataSection",
                "NesRamWaitHash:",
            ]
            for index in range(size):
                key = indices.get(index, -1)
                lines.append(f"  Data.l {key},{sites.get(key,0)}")
            lines.append("EndDataSection")
            return lines
    lines = ["Procedure.i NesRamWaitRule(site.i)", "  Select site"]
    lines += [f"    Case {offset} : ProcedureReturn {rule}" for offset, rule in sorted(sites.items())]
    return lines + ["  EndSelect", "  ProcedureReturn 0", "EndProcedure"]


def ram_wait_source(program, mapper):
    sites = {}
    span = poll_bank_size(mapper)
    if not span:
        return "", False
    if len(program) % span:
        raise ValueError("RAM polling requires complete PRG bank windows")
    for bank in range(0, len(program), span):
        view = program[bank:bank + span]
        for start, opcode in enumerate(view):
            read = READS.get(opcode)
            if read is None:
                continue
            action, mode = read
            length = 2 if mode < 3 else 3
            branch = start + length
            if branch + 1 >= span:
                continue
            if (view[branch] & 31) != 0x10 or view[branch + 1] != 256 - length - 2:
                continue
            operand = view[start + 1]
            if length == 3:
                operand |= view[start + 2] << 8
                if operand >= 0x2000 and (mode == 3 or operand <= 0xFF00):
                    continue
            target = 0x8000 + start
            origin = (0x8000 + branch + 2) & 0xFFFF
            crosses_page = ((target ^ origin) & 0xFF00) != 0
            rule = operand | (action << 16) | (mode << 19) | ((view[branch] >> 5) << 22)
            rule |= int(crosses_page) << 25
            sites[bank + start] = rule
            sites[bank + branch] = rule | (1 << 26)
    if not sites:
        return "", False
    lines = wait_lookup(sites)
    lines += ["DataSection", "NesRamWaitPeriods:"]
    for read_cycles in range(3, 6):
        for branch_cycles in range(3, 5):
            for at_branch in (False, True):
                spent, retired = phase_period(read_cycles, branch_cycles, at_branch)
                lines += [f"  Data.u {spent},{retired}"]
    lines += ["EndDataSection"]
    return "\n".join(lines) + "\n", True
