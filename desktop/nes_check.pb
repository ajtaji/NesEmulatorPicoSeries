; Console checks of the desktop core. Build from the repository root (PowerShell):
;   & "C:\Program Files\PureBasic\Compilers\pbcompilerc.exe" desktop\nes_check.pb /CONSOLE /OUTPUT desktop\nes_check.exe
; Run:  desktop\nes_check.exe [rom.nes [frames]]
EnableExplicit
XIncludeFile "host.pbi"
XIncludeFile "core/core.pbi"
XIncludeFile "machine.pbi"
XIncludeFile "disasm.pbi"
XIncludeFile "cpu_tests.pbi"


UseCRC32Fingerprint()
OpenConsole()
DisInit()
MachineStart("")
If CpuTestsRun()
  PrintN("tests: "+Str(CpuTestChecks)+" checks (Anvil core "+Str(CpuTestCore)+", Anvil mappers "+Str(CpuTestMapper)+", opcode vectors "+Str(CpuTestAll)+", controllers "+Str(CpuTestPads)+"), 0 failures PASS")
Else
  PrintN("tests: "+Str(CpuTestChecks)+" checks (Anvil core "+Str(CpuTestCore)+", Anvil mappers "+Str(CpuTestMapper)+", opcode vectors "+Str(CpuTestAll)+", controllers "+Str(CpuTestPads)+"), "+Str(CpuTestFailures)+" failures FAIL")
  ForEach CpuTestFailLines() : PrintN("  "+CpuTestFailLines()) : Next
EndIf
; positional arguments (rom, frames, png); --pal / --ntsc anywhere
Global NewList CheckArgs.s()
Define rom$, frames.i, t.q, n.i, crc$, png$
For n=0 To CountProgramParameters()-1
  If Mid(ProgramParameter(n),1,2)<>"--" : AddElement(CheckArgs()) : CheckArgs()=ProgramParameter(n) : EndIf
Next
If SelectElement(CheckArgs(),0) : rom$=CheckArgs() : EndIf
If SelectElement(CheckArgs(),1) : frames=Val(CheckArgs()) : EndIf
If SelectElement(CheckArgs(),2) : png$=CheckArgs() : EndIf
If frames=0 : frames=600 : EndIf
For n=0 To CountProgramParameters()-1
  If LCase(ProgramParameter(n))="--pal" : MachineTv=2 : ElseIf LCase(ProgramParameter(n))="--ntsc" : MachineTv=1 : EndIf
Next
If MachineStart(rom$)=0 : PrintN("ROM refused: "+RomStatus$) : End 1 : EndIf
PrintN("tv="+StringField("NTSC|PAL",MachinePal+1,"|")+" "+MachinePalWhy$+" mapper="+Str(CartMapper)+" prg="+Str(MapPrgBytes)+" chr="+Str(MapChrBytes)+" "+RomFileName$)
t=ElapsedMilliseconds()
For n=1 To frames
  MachineRunFrame()
  If Stopped Or WorkerError : Break : EndIf
Next
t=ElapsedMilliseconds()-t
crc$=Fingerprint(@DisplayFrame565(0),61440*2,#PB_Cipher_CRC32)
PrintN("frames="+Str(DisplayFrames)+" ms="+Str(t)+" fps="+StrF(DisplayFrames*1000.0/(t+1),1)+" instr="+Str(NesInstructions)+" ips="+Str(NesInstructions*1000/(t+1))+" stopped="+Str(Stopped)+" bad="+Str(BadOpcode)+" err="+Str(WorkerError)+" pc="+Hex(PC)+" frame_crc="+crc$)
; [rom frames out.png]: the last frame as a PNG
If ExpChip
  PrintN("expansion sound: chip="+StringField("VRC6|N163",ExpChip,"|")+" peak="+Str(ExpPeak)+" sounding_samples="+Str(ExpSounding)+" of "+Str(ApuProduced))
EndIf
If png$<>""
  UsePNGImageEncoder()
  Define img.i=CreateImage(#PB_Any,256,240,24), px.i, py.i, pv.i
  StartDrawing(ImageOutput(img))
  For py=0 To 239
    For px=0 To 255
      pv=DisplayFrame565(py*256+px)
      Plot(px,py,RGB(((pv>>11)&31)*255/31,((pv>>5)&63)*255/63,(pv&31)*255/31))
    Next
  Next
  StopDrawing()
  SaveImage(img,png$,#PB_ImagePlugin_PNG)
  PrintN("saved "+png$)
EndIf
