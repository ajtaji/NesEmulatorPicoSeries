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


def stage_cpu_asm(source: str) -> str:
    """The runtime-MMC3 build: CpuRun is the assembly core in cpu6502.n64.

    The compiled interpreter's CpuRun (every opcode handler) leaves the build;
    its globals, the status procedures and the MMC3 interrupt entry stay.
    """
    signature = "Procedure.i CpuRun(n.i)\n"
    head, found, body = source.partition(signature)
    end = "\nEndProcedure"
    if not found or body.count(end) != 1:
        raise ValueError("2A03 CpuRun is no longer the last procedure of the shared core")
    tail = body[body.index(end) + len(end):]
    source = head + 'XIncludeFile "../n64/cpu6502.n64"\n' + tail
    source = source.replace("Global Dim Dispatch.Label(256)\n", "")
    source, count = re.subn(r"^Procedure\.i CpuInterrupt\(vector\.i\)\n.*?^EndProcedure",
                            'XIncludeFile "../n64/mmc3_cpu_interrupt.n64"', source, flags=re.M | re.S)
    if count != 1:
        raise ValueError("2A03 interrupt entry changed")
    return "Declare CpuEndWindow()\nDeclare.i NesMmc3IrqPending()\n" + source


def trace_reference(source: str) -> str:
    """The checking build of the reference core: fold the state after every instruction.

    The calls preserve every register of the threaded span and add no state.
    """
    # The fold must see NesInstructions (t3 in the threaded span) counting the instruction just completed, as the
    # compiled opcodes' CpuNextOp does. The MMC1 / MMC3 threads count at the dispatch, so their check sees it; the
    # generic thread (every other mapper's reference: NROM, UxROM, CNROM, AxROM, Color Dreams, GxROM...) counts at
    # the check itself, in the branch's delay slot - there the fold goes after that count. Folded before it, a
    # threaded instruction after a compiled one carried the compiled one's count and the fold-once rule dropped it.
    generic = "nes_thread_check:\n    blez $a2, nes_thread_end\n    daddiu $t3, $t3, 1\n"
    for label in (generic if source.count(generic) == 1 else "nes_thread_check:\n", "nes_thread_end:\n"):
        if source.count(label) != 1:
            raise ValueError(f"reference core label {label.strip()} changed")
        source = source.replace(label, label + "    jal nescputracestep\n    nop\n")
    count = "  NesInstructions = NesInstructions + 1\n"
    macro = "Macro CpuNextOp(c)\n  CpuTick(c)\n" + count
    if source.count(macro) != 1:
        raise ValueError("reference CpuNextOp changed")
    source = source.replace(macro, macro + "  NesCpuTraceGlobals()\n")
    return "Declare NesCpuTraceGlobals()\n" + source


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
        threaded_store = mapper == 1 or (mapper == 4 and runtime)
        entry = "NesStoreAbsolute:\n" if threaded_store and opcode == "8D" else ""
        source = source.replace(handler, handler.replace(write, entry + f"""  CompilerIf #NES_BG_EXPANDED
    NesWriteAbsolute(Ea,{reg},${opcode})
  CompilerElse
    NesWrite(Ea,{reg})
  CompilerEndIf
"""))
    declaration = "Declare NesWriteAbsolute(addr.i, value.i, writeOp.i)"
    source = f"CompilerIf #NES_BG_EXPANDED\n{declaration}\nCompilerEndIf\n" + source
    if runtime and mapper == 4:
        # The MMC3 span covers every legal opcode and can return rejected
        # opcodes to the same portable dispatch table. Skip the boot table.
        boot_lookup = """    sd $a1, 0($t3)
    sll $t0, $a0, 2
    la $t1, nes_opcode_table
    addu $t0, $t0, $t1
    lw $t0, 0($t0)
    jr $t0
    nop
    .align 2"""
        direct_entry = """    b nes_thread_enter
    sd $a1, 0($t3)
    .word 0,0,0,0,0,0
    .align 2"""
        if source.count(boot_lookup) != 1:
            raise ValueError("runtime MMC3 CPU boot dispatch changed")
        source = source.replace(boot_lookup, direct_entry)
        source, count = re.subn(r"^Procedure\.i CpuInterrupt\(vector\.i\)\n.*?^EndProcedure",
                                'XIncludeFile "../n64/mmc3_cpu_interrupt.n64"', source,
                                flags=re.M | re.S)
        if count != 1:
            raise ValueError("2A03 interrupt entry changed")
        # While a mapper IRQ is pending, the scheduler may run multiple
        # instructions with I set. Poll immediately when an instruction clears it.
        for opcode in ("28", "40", "58"):
            op = re.compile(rf"(^Op{opcode}:.*?)(^  CpuNextOp\()", re.M | re.S)
            source, count = op.subn(r"\1  If FI=0 And NesMmc3IrqPending() : CpuEndWindow() : EndIf\n\2", source)
            if count != 1:
                raise ValueError(f"2A03 IRQ unmask opcode {opcode} changed")
        source = "Declare CpuEndWindow()\nDeclare.i NesMmc3IrqPending()\n" + source
    # MMC5 and mapper 234 can attach read side effects to the PRG window.
    if mapper in (5, 234):
        return cache_window_registers(source)
    if mapper == 1 or chain_nrom:
        # Only the scheduler's complete 128-cycle CPU window can continue.
        budget = "  If n <= 0\n"
        if source.count(budget) != 1:
            raise ValueError("2A03 CPU budget guard changed")
        source = source.replace(budget, "  If n<>128 : NesChainLimit=-1 : EndIf\n" + budget)
    if mapper == 4:
        # The polling and countdown shortcuts read their own code: through the bank mapped at PC
        # (NesMmc3Bias, PrgBias is the linear start of PRG), with every byte they read inside PC's
        # 8 KB slot, as the RP2350's paged core does.
        count = source.count("    NesPollPtr=PrgBias+PC\n")
        if count != 4:
            raise ValueError(f"2A03 polling shortcuts changed ({count})")
        source = source.replace("    NesPollPtr=PrgBias+PC\n", "    NesPollPtr=NesMmc3Pointer(PC)\n")
        source, count = re.subn(r"And PC<=\$FFF([0-9A-F])\b", r"And PC<=$FFF\1 And (PC&$1FFF)<=$1FF\1", source)
        if count != 4:
            raise ValueError(f"2A03 polling shortcut bounds changed ({count})")
    if mapper == 1:
        source = source.replace("NesPollPtr=PrgBias+PC", "NesPollPtr=PC")
        source = re.sub(r"PeekA\((NesPollPtr(?:\+\d+)?)\)", r"PeekA(NesMmc1Pointer(\1))", source)
    return stage_fill(stage_thread(source, mapper, has_waits, chain_nrom, mmc1_20k, runtime),
                      program, runtime and mapper in (0, 1))
