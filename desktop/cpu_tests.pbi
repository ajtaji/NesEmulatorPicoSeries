; The test suites on the desktop core:
;   * Anvil's own (anvil/Tests, ported to core/tests/ by tools/port_desktop.py), as the Pi runs them:
;     the core tests - the boards' 220 zero-page vectors, then the PPU's packed tile fetch against its
;     reference form - and the mapper tests, synthetic cartridges through every mapper.
;   * Both controllers through $4016/$4017.
;   * The desktop's 1200 opcode vectors (desktop/cpu_vectors.pbi, every documented opcode from random
;     states, py65 as the oracle). Each instruction runs alone (CpuRun(1)) at $0400.
EnableExplicit
XIncludeFile "core/tests/core.pbi"
XIncludeFile "core/tests/mappers.pbi"
XIncludeFile "cpu_vectors.pbi"

Global CpuTestChecks.i, CpuTestFailures.i, CpuTestCore.i, CpuTestMapper.i, CpuTestAll.i, CpuTestPads.i
Global NewList CpuTestFailLines.s()

Procedure CpuTestCheck(actual.i,expected.i,what$)
  CpuTestChecks+1
  If actual<>expected
    CpuTestFailures+1
    If ListSize(CpuTestFailLines())<40
      AddElement(CpuTestFailLines()) : CpuTestFailLines()=what$+": got $"+Hex(actual)+", expected $"+Hex(expected)
    EndIf
  EndIf
EndProcedure

; The desktop's vectors (layout: tools/gen_desktop_cpu_vectors.py).
Procedure CpuOpcodeVectorTests()
  Protected n.i, p.i, i.i, op.i, sp0.i, q.i, tag$
  For n=0 To #CPU_VECTOR_COUNT-1
    p=?CpuVectors+n*#CPU_VECTOR_BYTES
    op=PeekA(p) : tag$="op $"+RSet(Hex(op),2,"0")+" "+DisName$(op)+" #"+Str(n)
    FillMemory(@M(0),2048,0)
    For i=0 To 15
      M($F0+i)=PeekA(p+8+i)
      M($600+i)=PeekA(p+24+i)
      M($5F0+i)=PeekA(p+24+i)!$5A
    Next
    sp0=PeekA(p+7)
    For i=0 To 7 : M($100+((sp0+1+i)&255))=PeekA(p+40+i) : Next
    M($400)=op : M($401)=PeekA(p+1) : M($402)=PeekA(p+2)
    PC=$400 : A=PeekA(p+3) : X=PeekA(p+4) : Y=PeekA(p+5) : CpuSetStatus(PeekA(p+6)) : S=sp0
    q=p+48
    CpuTestCheck(CpuRun(1),PeekA(q+7),tag$+" cycles")
    CpuTestCheck(A,PeekA(q),tag$+" A") : CpuTestCheck(X,PeekA(q+1),tag$+" X") : CpuTestCheck(Y,PeekA(q+2),tag$+" Y")
    CpuTestCheck(CpuStatus()|$30,PeekA(q+3),tag$+" P") : CpuTestCheck(S,PeekA(q+4),tag$+" S")
    CpuTestCheck(PC,PeekA(q+5)|(PeekA(q+6)<<8),tag$+" PC")
    For i=0 To 15
      CpuTestCheck(M($600+i),PeekA(q+8+i),tag$+" data $"+Hex($600+i))
      CpuTestCheck(M($F0+i),PeekA(q+24+i),tag$+" zp $"+Hex($F0+i))
    Next
    For i=0 To 3 : CpuTestCheck(M($100+((sp0-2+i)&255)),PeekA(q+40+i),tag$+" stack") : Next
  Next
EndProcedure

; Both controllers through the bus, as a game reads them: strobe $4016, then eight reads of $4016 and
; $4017, A first; after eight, 1s (open bus bit 6 set on $4017). While strobed, each reads its A button.
Procedure ControllerTests()
  Protected pad1.i, pad2.i, i.i, n.i
  For n=0 To 15
    pad1=(n*$35+$5A)&255 : pad2=(n*$C3+$27)&255
    NesController=pad1 : NesController2=pad2
    NesWrite($4016,1)
    CpuTestCheck(NesRead($4016)&1,pad1&1,"controller 1 strobed")
    CpuTestCheck(NesRead($4017)&1,pad2&1,"controller 2 strobed")
    NesWrite($4016,0)
    For i=0 To 7
      CpuTestCheck(NesRead($4016)&1,(pad1>>i)&1,"controller 1 bit "+Str(i))
      CpuTestCheck(NesRead($4017)&1,(pad2>>i)&1,"controller 2 bit "+Str(i))
    Next
    CpuTestCheck(NesRead($4017)&1,1,"controller 2 after eight")
  Next
  NesController=0 : NesController2=0
EndProcedure

; All four suites, each from a clean machine; the caller restarts the machine afterwards.
Procedure.i CpuTestsRun()
  Protected keepIdle.i, before.i
  CpuTestChecks=0 : CpuTestFailures=0 : ClearList(CpuTestFailLines())
  keepIdle=NesIdleEnabled : NesIdleEnabled=0
  Checks=0 : Failures=0 : FirstCheck=0
  MachineStart("") : NesIdleEnabled=0 : CoreTests()
  CpuTestCore=Checks : CpuTestChecks+Checks : CpuTestFailures+Failures
  If Failures
    AddElement(CpuTestFailLines()) : CpuTestFailLines()="Anvil core tests: "+Str(Failures)+" failures, first check "+Str(FirstCheck)+" got $"+Hex(FirstGot)+" expected $"+Hex(FirstExpected)
  EndIf
  MapperChecks=0 : MapperFailures=0 : MapperFirstFail=0
  MachineStart("") : NesIdleEnabled=0 : MapperTests()
  CpuTestMapper=MapperChecks : CpuTestChecks+MapperChecks : CpuTestFailures+MapperFailures
  If MapperFailures
    AddElement(CpuTestFailLines()) : CpuTestFailLines()="Anvil mapper tests: "+Str(MapperFailures)+" failures, first check "+Str(MapperFirstFail)+" got $"+Hex(MapperGot)+" expected $"+Hex(MapperExpected)
  EndIf
  MachineStart("") : NesIdleEnabled=0
  before=CpuTestChecks : CpuOpcodeVectorTests() : CpuTestAll=CpuTestChecks-before
  MachineStart("") : before=CpuTestChecks : ControllerTests() : CpuTestPads=CpuTestChecks-before
  NesIdleEnabled=keepIdle
  ProcedureReturn Bool(CpuTestFailures=0)
EndProcedure
