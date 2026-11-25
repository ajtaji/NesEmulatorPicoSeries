"""Adapt Anvil's threaded 2A03 interpreter for PureMetal Forge on VR4300."""

import re

from stage_bus import read_direct
from stage_fill import stage_fill
from stage_thread import stage_thread


def cache_window_registers(source: str) -> str:
    """Keep private 2A03 state in the VR4300 backend's register locals."""
    # The bus and operand fetchers still need the live PC, address state,
    # open bus and cycle budget during a CPU window.
    state = ("A", "X", "Y", "FN", "FZ", "FC", "FV", "NesInstructions")
    flags = state[3:7]
    local = {name: "Window" + name for name in state}
    names = re.compile(r"(?<![$#?])\b(" + "|".join(state) + r")\b")

    def local_names(text: str) -> str:
        return names.sub(lambda match: local[match[0]], text)

    def copy_state(fields: tuple[str, ...], *, to_locals: bool) -> str:
        pairs = ((local[name], name) if to_locals else (name, local[name]) for name in fields)
        return "".join(f"  {dst} = {src}\n" for dst, src in pairs)

    signature = "Procedure.i CpuRun(n.i)\n"
    head, found, body = source.partition(signature)
    if not found or body.count("Done:\n") != 1 or body.count("  NesRunStart = CpuCycles\n") != 1:
        raise ValueError("2A03 execution window boundaries are missing")

    # CpuNZ is only called from CpuRun. Interrupt entry and the status
    # procedures keep their original globals for use between run windows.
    head, count = re.subn(r"^Macro CpuNZ\(v\)\n.*?^EndMacro",
                          lambda match: local_names(match[0]), head, flags=re.M | re.S)
    if count != 1:
        raise ValueError("2A03 NZ flag macro is missing")
    body = local_names(body)
    body, reads = re.subn(r"^  Tmp = CpuStatus\(\).*\n",
                          lambda match: copy_state(flags, to_locals=False) + match[0],
                          body, flags=re.M)
    set_status = "  CpuSetStatus(Tmp)\n"
    if reads != body.count("CpuStatus(") or body.count(set_status) != body.count("CpuSetStatus("):
        raise ValueError("2A03 status access needs synchronization with the register cache")
    body = body.replace(set_status, set_status + copy_state(flags, to_locals=True))
    body = body.replace("  NesRunStart = CpuCycles\n",
                        copy_state(state, to_locals=True) + "  NesRunStart = CpuCycles\n")
    body = body.replace("Done:\n", "Done:\n" + copy_state(state, to_locals=False))
    declarations = "  Protected " + ", ".join(local[name] + ".i" for name in state) + "\n"
    return head + signature + declarations + body


def stage_cpu(source: str, mapper: int, program: bytes = b"", has_waits: bool = False, chain_nrom: bool = False, mmc1_20k: bool = False, runtime: bool = False) -> str:
    # Keep the opcode bodies and the set of legal opcodes in the guest core.
    # Forge has no .Label or computed Goto lowering on VR4300.
    initialize = re.search(r"^  If Ready = 0\n.*?^  EndIf\n", source, re.M | re.S)
    if initialize is None:
        raise ValueError("2A03 dispatch initializer is missing")
    opcodes = dict(re.findall(r"Dispatch\(\$([0-9A-F]{2})\) = \?(Op[0-9A-F]{2})",
                             initialize.group()))
    bodies = set(re.findall(r"^(Op[0-9A-F]{2}):", source, re.M))
    if set(opcodes.values()) != bodies or any(label != "Op" + opcode
                                              for opcode, label in opcodes.items()):
        raise ValueError("2A03 dispatch initializer does not match its opcode bodies")
    source = source[:initialize.start()] + source[initialize.end():]

    old_tail = re.search(r"^Macro CpuDispatchNext\(\)\n.*?^EndMacro", source, re.M | re.S)
    old_fetch = re.search(r"^SlowFetch:\n.*?\n(?=Illegal:)", source, re.M | re.S)
    if old_tail is None or old_fetch is None:
        raise ValueError("2A03 dispatch entry points are missing")
    names = ["__ul_cpurun_" + opcodes.get(f"{opcode:02X}", "Illegal").lower()
             for opcode in range(256)]
    table = "\n".join("    .word " + ", ".join(names[i:i + 4])
                      for i in range(0, len(names), 4))
    direct = read_direct("nes_cpu", "__ul_cpurun_nesopcodeslow", mapper)
    fetch = """SlowFetch:
  ASM
    la $t3, global_pc
    ld $a1, 0($t3)
""" + direct + """
nes_opcode_dispatch:
    addiu $a1, $a1, 1
    andi $a1, $a1, 0xFFFF
    sd $a1, 0($t3)
    sll $t0, $a0, 2
    la $t1, nes_opcode_table
    addu $t0, $t0, $t1
    lw $t0, 0($t0)
    jr $t0
    nop
    .align 2
nes_opcode_table:
""" + table + """
  EndASM
NesOpcodeSlow:
  Tmp = NesRead(PC)
  ASM
    la $t0, global_tmp
    ld $a0, 0($t0)
    la $t3, global_pc
    b nes_opcode_dispatch
    ld $a1, 0($t3)
  EndASM
"""
    source = source[:old_fetch.start()] + fetch + source[old_fetch.end():]
    source = (source[:old_tail.start()] + "Macro CpuDispatchNext()\n  Goto SlowFetch\nEndMacro"
              + source[old_tail.end():])
    source = source.replace("Global Dim Dispatch.Label(256)\n", "")
    source = source.replace(
        "; Each opcode owns its tail. Assembly only implements computed dispatch;\n"
        "; operands and instruction semantics remain in checked PureMetal source.",
        "; The VR4300 dispatch table points to the existing PureMetal opcode handlers.")
    for opcode, reg in (("8C", "Y"), ("8D", "A"), ("8E", "X")):
        write = f"  NesWrite(Ea, {reg})\n"
        handler = (f"Op{opcode}: ; ${opcode} ST{reg} abs\n"
                   "  AccessPhase = 3\n  CpuFetchAddress()\n" + write)
        if source.count(handler) != 1:
            raise ValueError(f"2A03 absolute ST{reg} handler changed")
        entry = "NesStoreAbsolute:\n" if mapper == 1 and opcode == "8D" else ""
        source = source.replace(handler, handler.replace(write, entry + f"""  CompilerIf #NES_BG_EXPANDED
    NesWriteAbsolute(Ea,{reg},${opcode})
  CompilerElse
    NesWrite(Ea,{reg})
  CompilerEndIf
"""))
    declaration = "Declare NesWriteAbsolute(addr.i, value.i, writeOp.i)"
    source = f"CompilerIf #NES_BG_EXPANDED\n{declaration}\nCompilerEndIf\n" + source
    # MMC5 and mapper 234 can attach read side effects to the PRG window.
    if mapper in (5, 234):
        return cache_window_registers(source)
    if mapper == 1 or chain_nrom:
        # Only the scheduler's complete 128-cycle CPU window can continue.
        budget = "  If n <= 0\n"
        if source.count(budget) != 1:
            raise ValueError("2A03 CPU budget guard changed")
        source = source.replace(budget, "  If n<>128 : NesChainLimit=-1 : EndIf\n" + budget)
    if mapper == 1:
        source = source.replace("NesPollPtr=PrgBias+PC", "NesPollPtr=PC")
        source = re.sub(r"PeekA\((NesPollPtr(?:\+\d+)?)\)", r"PeekA(NesMmc1Pointer(\1))", source)
    return stage_fill(stage_thread(source, mapper, has_waits, chain_nrom, mmc1_20k), program, runtime and mapper in (0, 1))
