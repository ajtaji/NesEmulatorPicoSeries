"""RP2350 optional 8 KiB PRG pages; preserve flat fetches when disabled."""
import re

def paged_fetch(text,name):
    scope=name.split(".")[0]
    def patch(m):
        return m[1]+"bl picoprgfetchbias"
    # Absolute operand pairs can straddle two independently mapped pages.
    text=text.replace('ldr r1, =$ffff\n', 'lsls r1, r0, #19\n    lsrs r1, r1, #19\n    ldr r3, =$1fff\n').replace('cmp r0, r1\n    beq __cpu_ias_', 'cmp r1, r3\n    beq __cpu_ias_').replace('cmp r0, r1\n    beq __cpu_fetch_address_slow', 'cmp r1, r3\n    beq __cpu_fetch_address_slow')
    return re.sub(r"(?m)^([ \t]*)ldr r1, =global_prgbias\n[ \t]*ldr r1, \[r1\]",patch,text)


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
    paged=re.sub(r'\bDispatch\b','DispatchPaged',paged).replace('global_dispatch','global_dispatchpaged')
    paged=re.sub(r'\bReady\b','PagedReady',paged)
    for macro in ['DispatchNext','NextOp']:
        paged=re.sub(r'\b'+macro+r'\b','Paged'+macro,paged)
    wrapper="""\nProcedureRAM.i CpuRun(n.i)
  If PicoPrgPaged : ProcedureReturn CpuRunPaged(n) : EndIf
  ProcedureReturn CpuRunFlat(n)
EndProcedure
"""
    return prefix+flat+'\n'+paged+wrapper
