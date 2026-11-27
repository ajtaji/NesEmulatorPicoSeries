"""The NMI's timing in the shared core's N64 builds outside the hot unit (design note N.77).

The hot unit (unit/ppu.n64, unit/ppu_cold.n64, unit/window.n64, cpu6502.n64's window ends) takes the NMI by the
documented rules; this stage gives the shared core's reference scheduler (the other-mappers run loop in nes.n64 and
the staged worker) the same rules, in its own compiled form, so the two schedulers are two implementations of one rule:
  R3  PPUCTRL bit 7 set while the vblank flag is set: the edge at once (NesNmiAt = the write's cycle);
  R4  a $2002 read one dot before the set (line 241 dot 0) reads 0 and makes no flag or NMI that frame; a read on the
      set dot or one after (dots 1-2) reads 1 and the frame's NMI is not taken;
  R5  the edge is detected in the first cycle whose read point + 1 dot is at or after the set; the NMI is taken at the
      first instruction boundary >= that cycle + 2 (NesNmiDue), and every CPU window ends there (NesNmiCap).
The rules and their hand-derived checks: the bench's probe cart carts/nmiprobe.s. The shared sources are not
changed: other targets build them as they are.
"""


def _replace(source: str, old: str, new: str, what: str) -> str:
    if source.count(old) != 1:
        raise ValueError(f"the NMI timing stage: {what} changed")
    return source.replace(old, new)


def stage_nmi(name: str, source: str, unit: bool, dmc_deadline: bool) -> str:
    if unit:
        return source           # the hot unit has the rules in assembly
    if name == "ppu":
        clock = "NesNmiClock()"     # the worker's clocks are declared after this file: read through the worker
        source = "Declare NesNmiDueSet(clock.i)\nDeclare.i NesNmiClock()\n" + source
        # R5 at the set: the edge's detection cycle from the dots the advance still has past it
        source = _replace(source, """      If PpuLine=241 And edge=1
        PpuStatus=PpuStatus|$80
        If PpuCtrl&$80
          WorkerNmi=WorkerNmi+1
        EndIf
""", f"""      If PpuLine=241 And edge=1
        If NesVblSuppress
          NesVblSuppress=0                    ; a $2002 read one dot before: no flag, no NMI this frame (R4)
        Else
          PpuStatus=PpuStatus|$80
          If PpuCtrl&$80
            WorkerNmi=WorkerNmi+1
            CompilerIf #GAME_PAL
              NesNmiAt=0                      ; PAL: taken at the window's end, as before
            CompilerElse
              NesNmiAt={clock}+cycles-(dots+1)/3   ; the stamp less the whole cycles the advance has past the set + 1 dot
            CompilerEndIf
          EndIf
        EndIf
""", "the vblank set in PpuAdvanceReference")
        source = _replace(source, """  Wend
  WorkerDot=PpuLine*341+PpuDot
EndProcedure
""", f"""  Wend
  WorkerDot=PpuLine*341+PpuDot
  NesNmiDueSet({clock}+cycles)
EndProcedure
""", "the end of PpuAdvanceReference")
        # R3: the edge when enabled during vblank; any change of bit 7 moves the due
        source = _replace(source, """    If (previous&$80)=0 And (value&$80)<>0 And (PpuStatus&$80)<>0
      WorkerNmi=WorkerNmi+1
    EndIf
""", f"""    If (previous&$80)=0 And (value&$80)<>0 And (PpuStatus&$80)<>0
      WorkerNmi=WorkerNmi+1 : NesNmiAt={clock}   ; the edge now: the write's cycle (the PPU was synced to it)
    EndIf
    If (previous!value)&$80 : NesNmiDueSet({clock}) : EndIf
""", "the PPUCTRL write")
        # R4 at a $2002 read
        source = _replace(source, """  If addr=2
    v=(PpuStatus&$E0)|(PpuBus&31)
""", f"""  If addr=2
    If PpuLine=241 And PpuDot<3
      If PpuDot=0 : NesVblSuppress=1 : Else : NesSeenNmi=WorkerNmi : EndIf
      NesNmiDueSet({clock})
    EndIf
    v=(PpuStatus&$E0)|(PpuBus&31)
""", "the $2002 read")
    if name == "worker":
        clock = "PpuClock" if dmc_deadline else "WorkerClock"   # the clock the PPU stands at (stage_sync's WorkerAdvance)
        source += f"""
; NesNmiClock(): the CPU cycle the PPU stands at ({clock}: the clock stage_sync's WorkerAdvance advances it by)
Procedure.i NesNmiClock()
  ProcedureReturn {clock}
EndProcedure
; NesNmiDueSet(clock): NesNmiDue, the first instruction boundary the next NMI may be taken at, the PPU standing at
; (PpuLine, PpuDot) at the given CPU cycle (design note N.77; the hot unit's u_nmidue in compiled form): an edge counted
; and not taken: NesNmiAt + 2; else, NMI on, NTSC, not suppressed and the set ahead: the predicted detection cycle,
; clock + ceil(((241 - line) x 341 - dot) / 3), + 2; else never.
Procedure NesNmiDueSet(clock.i)
  If WorkerNmi<>NesSeenNmi
    NesNmiDue=NesNmiAt+2
  ElseIf (PpuCtrl&$80)<>0 And NesVblSuppress=0 And #GAME_PAL=0 And (PpuLine<241 Or (PpuLine=241 And PpuDot=0))
    NesNmiDue=clock+((241-PpuLine)*341-PpuDot+2)/3+2
  Else
    NesNmiDue=$7FFFFFFFFFFFFFFF
  EndIf
EndProcedure
; NesNmiCap(n): a CPU window of at most n cycles that ends at the first boundary at or after NesNmiDue (at least 1).
Procedure.i NesNmiCap(n.i)
  Protected d.i
  d=NesNmiDue-CpuCycles-NesStall
  If d<n
    n=d : If n<1 : n=1 : EndIf
  EndIf
  ProcedureReturn n
EndProcedure
"""
    return source
