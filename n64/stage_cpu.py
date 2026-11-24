"""Adapt Anvil's threaded 2A03 interpreter for PureMetal Forge on VR4300."""

import re

from stage_bus import read_direct


def stage_cpu(source: str, mapper: int) -> str:
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
    return source.replace(
        "; Each opcode owns its tail. Assembly only implements computed dispatch;\n"
        "; operands and instruction semantics remain in checked PureMetal source.",
        "; The VR4300 dispatch table points to the existing PureMetal opcode handlers.")
