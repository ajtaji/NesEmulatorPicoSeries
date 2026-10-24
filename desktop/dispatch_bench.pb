; Which opcode dispatch is faster on the PC: labels-as-values (desktop/core/cpu2a03.pbi, a computed goto in
; the C backend - what the window runs) or a table of procedure pointers (desktop/core/cpu2a03_procs.pbi,
; generated from the same opcode bodies by tools/gen_desktop_cpu_procs.py). Both run the same games for the
; same frames; the last frame's CRC must agree, or the comparison is void. Then a CPU-only loop in RAM,
; with no PPU or APU work, which isolates the dispatch. Best of three runs each.
;   & "C:\Program Files\PureBasic\Compilers\pbcompilerc.exe" desktop\dispatch_bench.pb /CONSOLE /OPTIMIZER /OUTPUT desktop\dispatch_bench.exe
; Run:  desktop\dispatch_bench.exe [frames] game.nes [game.nes ...]
EnableExplicit
XIncludeFile "host.pbi"
XIncludeFile "core/core.pbi"
XIncludeFile "core/cpu2a03_procs.pbi"
XIncludeFile "machine.pbi"

Prototype.i BenchRunner(n.i)
Global BenchMs.i, BenchCrc$

Procedure.i BenchFrames(rom$, frames.i, run.BenchRunner)
  Protected start.i, f.i, t.q
  If MachineStart(rom$)=0 : ProcedureReturn -1 : EndIf
  t=ElapsedMilliseconds()
  For f=1 To frames
    start=DisplayFrames
    While DisplayFrames=start And Stopped=0 And WorkerError=0
      run(MapperCpuBudget())
      NesSync()
    Wend
    If Stopped Or WorkerError : Break : EndIf
  Next
  BenchMs=ElapsedMilliseconds()-t
  BenchCrc$=Fingerprint(@DisplayFrame565(0),61440*2,#PB_Cipher_CRC32)
  ProcedureReturn NesInstructions
EndProcedure

; LDX #0 / LDA $10,X / ADC #3 / STA $0600,X / EOR $20 / ASL A / INX / BNE / JMP: RAM only.
Procedure.i BenchCpuOnly(run.BenchRunner, cycles.i)
  Protected i.i, t.q
  MachineStart("")
  NesIdleEnabled=0
  For i=0 To 17 : M($300+i)=PeekA(?BenchLoop+i) : Next
  PC=$300 : Stopped=0 : NesInstructions=0
  t=ElapsedMilliseconds()
  For i=1 To cycles/100000
    run(100000)
  Next
  BenchMs=ElapsedMilliseconds()-t
  NesIdleEnabled=1
  ProcedureReturn NesInstructions
EndProcedure

UseCRC32Fingerprint()
OpenConsole()
Define frames.i=Val(ProgramParameter(0)), k.i, r.i, ms.i, best.i, instr.i, crc.s, crcGoto.s, ipsGoto.i, ipsProc.i
Define label$, run.BenchRunner, i.i
If frames<=0 : frames=1200 : EndIf
PrintN("dispatch: labels-as-values (computed goto) vs procedure-pointer table, best of 3")
For k=1 To CountProgramParameters()-1
  PrintN(GetFilePart(ProgramParameter(k))+", "+Str(frames)+" frames:")
  For r=0 To 1
    If r=0 : run=@CpuRun() : label$="  goto table " : Else : run=@CpuRunProc() : label$="  proc table " : EndIf
    best=0
    For i=1 To 3
      instr=BenchFrames(ProgramParameter(k),frames,run) : ms=BenchMs : crc=BenchCrc$
      If best=0 Or ms<best : best=ms : EndIf
    Next
    If instr<0 : PrintN("  refused: "+RomStatus$) : Break : EndIf
    PrintN(label$+Str(best)+" ms  "+StrF(frames*1000.0/(best+1),0)+" fps  "+StrF(instr/1000.0/(best+1),2)+" M instr/s  crc "+crc)
    If r=0 : crcGoto=crc : ipsGoto=instr*1000/(best+1) : Else : ipsProc=instr*1000/(best+1) : EndIf
  Next
  If crc<>crcGoto : PrintN("  FRAMES DIFFER - comparison void") : Else : PrintN("  same last frame; proc/goto = "+StrF(ipsProc*100.0/ipsGoto,1)+"%") : EndIf
Next
PrintN("CPU only (RAM loop, 200M cycles):")
For r=0 To 1
  If r=0 : run=@CpuRun() : label$="  goto table " : Else : run=@CpuRunProc() : label$="  proc table " : EndIf
  best=0
  For i=1 To 3
    instr=BenchCpuOnly(run,200000000) : ms=BenchMs
    If best=0 Or ms<best : best=ms : EndIf
  Next
  PrintN(label$+Str(best)+" ms  "+StrF(instr/1000.0/(best+1),2)+" M instr/s")
Next

DataSection
  BenchLoop:
  Data.a $A2,$00, $B5,$10, $69,$03, $9D,$00,$06, $45,$20, $0A, $E8, $D0,$F3, $4C,$00,$03
EndDataSection
