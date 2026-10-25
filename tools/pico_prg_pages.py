"""RP2350 optional 8 KiB PRG pages; preserve flat fetches when disabled."""
import re

def paged_fetch(text,name):
    scope=name.split(".")[0]
    def patch(m):
        return m[1]+"bl picoprgfetchbias"
    # Absolute operand pairs can straddle two independently mapped pages.
    text=text.replace('ldr r1, =$ffff\n', 'lsls r1, r0, #19\n    lsrs r1, r1, #19\n    ldr r3, =$1fff\n').replace('cmp r0, r1\n    beq __cpu_ias_', 'cmp r1, r3\n    beq __cpu_ias_').replace('cmp r0, r1\n    beq __cpu_fetch_address_slow', 'cmp r1, r3\n    beq __cpu_fetch_address_slow')
    return re.sub(r"(?m)^([ \t]*)ldr r1, =global_prgbias\n[ \t]*ldr r1, \[r1\]",patch,text)


def thumb2_dispatch(text,kind):
    """The opcode fetch and dispatch at the end of every instruction, in the Cortex-M33's Thumb-2 (the RP2350
    only; the RP2040 keeps the Thumb-1 form): compare and index the high register r8 (the guest PC)
    directly, wrap it with uxth, extract the PRG slot with ubfx, and jump with ldr pc from the scaled
    table entry - 10 instructions where Thumb-1 takes 18 (mov through low registers, two shifts for the
    16-bit wrap, ldr then bx)."""
    old=re.compile(r'(?m)^      mov r0, r8\n      ldr r1, =\$8000\n      cmp r0, r1\n      blo (__ul_cpurun\w+_slowfetch)\n'
                   r'(?:.*\n)*?      ldr r1, \[r1, r2\]\n      bx r1\n')
    found=old.findall(text)
    assert len(found)==1,(kind,len(found))
    if kind=='flat':
        bias='      ldr r1, =global_prgbias\n      ldr r1, [r1]\n'
        table='global_dispatch'
    else:
        bias='      ubfx r3, r8, #13, #2\n      ldr r1, =global_picoprgbiases\n      ldr r1, [r1, r3, lsl #2]\n'
        table='global_dispatchpaged'
    new=('      cmp r8, #$8000\n      blo '+found[0]+'\n'+bias+
         '      ldrb r2, [r1, r8]\n      add r8, r8, #1\n      uxth r8, r8\n'
         '      ldr r1, ='+table+'\n      ldr pc, [r1, r2, lsl #2]\n')
    return old.sub(lambda m:new,text,count=1)


def dual_cpu(text):
    """Select flat/paged computed dispatch once per window, not per fetch."""
    begin=text.index('ProcedureRAM.i CpuRun(n.i)')
    prefix,body=text[:begin],text[begin:]
    prefix=prefix.replace('Global PrgBase.i, PrgBias.i','Global PrgBase.i, PrgBias.i\nGlobal PicoPrgPaged.i,PagedReady.i\nGlobal Dim DispatchPaged.Label(256)')
    flat=body.replace('CpuRun(n.i)','CpuRunFlat(n.i)').replace('__ul_cpurun_', '__ul_cpurunflat_')
    paged=paged_fetch(body,'cpu2a03.pico')
    paged=paged.replace('bl picoprgfetchbias', 'lsrs r3, r0, #11\n    movs r1, #12\n    ands r3, r1\n    ldr r1, =global_picoprgbiases\n    ldr r1, [r1, r3]')
    paged=paged.replace('CpuRun(n.i)','CpuRunPaged(n.i)').replace('__ul_cpurun_', '__ul_cpurunpaged_')
    paged=paged.replace('__cpu_', '__pg_cpu_')
    # The batched loops (status polls, countdowns) read their own code from ROM. Paged, PrgBias is
    # the flat cartridge base, not the bank mapped at PC: take the slot's bias, as the fetches do
    # (PicoPrgBiases is declared after the CPU, so in assembly), and keep every byte the batch reads
    # inside PC's 8 KiB page.
    rom_ptr=('    ASM Uses PC\n      mov r0, r8\n      lsrs r3, r0, #11\n      movs r1, #12\n      ands r3, r1\n'
             '      ldr r1, =global_picoprgbiases\n      ldr r1, [r1, r3]\n      adds r1, r1, r0\n'
             '      ldr r2, =global_nespollptr\n      str r1, [r2]\n    EndASM\n')
    count=paged.count('    NesPollPtr=PrgBias+PC\n')
    assert count>=4, count
    paged=paged.replace('    NesPollPtr=PrgBias+PC\n', rom_ptr)
    paged=re.sub(r'And PC<=\$FFF([0-9A-F])\b', r'And PC<=$FFF\1 And (PC&$1FFF)<=$1FF\1', paged)
    paged=re.sub(r'\bDispatch\b','DispatchPaged',paged).replace('global_dispatch','global_dispatchpaged')
    paged=re.sub(r'\bReady\b','PagedReady',paged)
    for macro in ['DispatchNext','NextOp']:
        paged=re.sub(r'\b'+macro+r'\b','Paged'+macro,paged)
    prefix,flat,paged=prefix,thumb2_dispatch(flat,'flat'),thumb2_dispatch(paged,'paged')
    wrapper="""\nProcedureRAM.i CpuRun(n.i)
  If PicoPrgPaged : ProcedureReturn CpuRunPaged(n) : EndIf
  ProcedureReturn CpuRunFlat(n)
EndProcedure
"""
    return prefix+flat+'\n'+paged+wrapper
