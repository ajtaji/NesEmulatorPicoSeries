; The desktop machine: what Anvil's platform files (runtime.pi4, scheduler.pi4, selector.pi4's RomLoad)
; do on the Pi, for one thread on a PC. Include after core/core.pbi.
;   * A .nes file is read into memory and goes through Anvil's own header checks and mapper database
;     (core/rom_check.pbi), into the same cartridge globals RomLoad sets.
;   * The PPU draws each line into RenderTop (lines 0-119) and FrameBottom (120-239), RGB565, as on the
;     boards. At line 239 DisplayFrame copies the finished frame to DisplayFrame565 for the window.
EnableExplicit

Global Dim DisplayFrame565.u(61440)     ; the last finished frame, 256 x 240 RGB565
Global DisplayFrames.i                  ; frames finished since the cartridge was loaded
Global RomPrgViews.i                    ; UxROM's 32 KiB views of each 16 KiB bank + the fixed last one
Global RomFileName$
Global MachineTv.i                      ; 0 the header and file name decide, 1 NTSC, 2 PAL (the window's TV button)
Global MachinePal.i                     ; what the loaded game runs at: 0 NTSC, 1 PAL
Global MachinePalWhy$                   ; why: "header", "file name", "chosen"

Procedure CartSelect(number.i)
  If RomLoaded=0 : CartSelectBuiltin(number) : EndIf
EndProcedure
; The Thumb renderer's descriptor caches; this core draws without them (as on the Pi).
Procedure PpuUpdateDescriptor(addr.i)
EndProcedure
Procedure PpuUpdateAttribute(addr.i)
EndProcedure
Procedure CartPpuWriteNotice(addr.i,value.i)
EndProcedure
Procedure DisplayWaitLine(line.i)
EndProcedure
Procedure DisplayFrame()
  CopyMemory(RenderTop,@DisplayFrame565(0),61440)
  CopyMemory(FrameBottom,@DisplayFrame565(30720),61440)
  DisplayFrames+1
EndProcedure

; runtime.pi4's NesSync: the bus up to the CPU's time, DMC stalls charged, then NMI or IRQ.
Procedure NesSync()
  Protected stalls.i
  NesRpc(0,0,0,CpuCycles)
  stalls=WorkerDmcCycles-NesSeenDmc
  While stalls>0
    CpuCycles=CpuCycles+stalls : NesSeenDmc=WorkerDmcCycles
    NesRpc(0,0,0,CpuCycles) : stalls=WorkerDmcCycles-NesSeenDmc
  Wend
  If WorkerNmi<>NesSeenNmi
    NesSeenNmi=WorkerNmi : CpuInterrupt($FFFA)
  ElseIf (WorkerIrq|MapIrq)<>0 And FI=0
    CpuInterrupt($FFFE)
  EndIf
EndProcedure

; runtime.pi4's LoadCartridge: decode the CHR, start the mapper, load the APU and palette tables.
Procedure LoadCartridge()
  Protected i.i,bank.i
  CartSelect(0)
  For i=0 To 255
    PixelSpread(i)=(i&3)|(((i>>2)&3)<<8)|(((i>>4)&3)<<16)|(((i>>6)&3)<<24)
  Next
  RenderTop=@FrameTop(0) : FrameBottom=@FrameBottomStore(0)
  PrgBase=CartPrg : PrgBias=PrgBase-$8000 : WorkerPrgBase=PrgBase
  ChrWritable=CartChrRam
  If CartMapper=1 Or CartMapper=3 Or CartMapper=4 Or CartMapper=5 Or CartMapper=7 Or CartMapper=11 Or ExtraManaged(CartMapper)
    For bank=0 To MapChrBytes/8192-1
      Chr=CartChr+bank*8192 : Pattern=@Decoded(bank*8192)
      For i=0 To 8191 : If (i&8)=0 : PpuDecode(i) : EndIf : Next
    Next
    MapperInit()
  ElseIf CartChrRam
    Chr=@Decoded(0)+8192 : CartChr=Chr : Pattern=@Decoded(0)
  Else
    For bank=0 To CartChrBanks-1
      Chr=CartChr+bank*8192 : Pattern=@Decoded(0)+bank*8192
      For i=0 To 8191 : If (i&8)=0 : PpuDecode(i) : EndIf : Next
    Next
    Chr=CartChr : Pattern=@Decoded(0)
  EndIf
  For i=0 To 31 : LengthTable(i)=PeekA(?LengthData+i) : Next
  For i=0 To 15 : NoiseTable(i)=PeekU(?NoiseData+i*2) : DmcTable(i)=PeekU(?DmcData+i*2) : Next
  For i=0 To 30 : PulseMix(i)=PeekU(?PulseData+i*2) : Next
  For i=0 To 202 : TndMix(i)=PeekU(?TndData+i*2) : Next
  For i=0 To 511 : Rgb64(i)=PeekU(?RgbData+i*2) : Next
  PpuColours()
  DisplayFrames=0
EndProcedure

; selector.pi4's RomLoad, from a file: 1 when the cartridge is ready (then GuestReset, LoadCartridge,
; CpuReset), else 0 with RomStatus$ saying why.
; tools/pico_cartridge.py's pico_pal, for a file name: a PAL-only region tag - "(E)", "(Europe)", "(PAL)",
; "(Germany)"... - marks PAL, unless a group also names an NTSC region ("(UE)", "(USA, Europe)" run on both).
Procedure.i RomNamePal(name$)
  Protected i.i, j.i, group$, tag$, k.i, n.i, pal.i, ntsc.i
  name$=GetFilePart(name$,#PB_FileSystem_NoExtension)
  i=FindString(name$,"(")
  While i
    j=FindString(name$,")",i) : If j=0 : Break : EndIf
    group$=Mid(name$,i+1,j-i-1)
    n=CountString(group$,",")+1
    For k=1 To n
      tag$=Trim(StringField(group$,k,","))
      Select tag$
        Case "E","A","G","F","S","Sw","I","Nl","Uk","UK","EU","PAL","Europe","Australia","Germany","France","Spain","Sweden","Italy","Netherlands"
          pal=1
        Case "U","J","K","USA","Japan","Korea","NTSC"
          ntsc=1
        Default
          ; GoodNES's run-together regions ("UE", "JUE"): NTSC when U or J is among them
          If Len(tag$)>=2 And Len(tag$)=CountString(tag$,"J")+CountString(tag$,"U")+CountString(tag$,"E")+CountString(tag$,"A")+CountString(tag$,"G")+CountString(tag$,"F")+CountString(tag$,"S")+CountString(tag$,"K")
            If FindString(tag$,"U",1,#PB_String_CaseSensitive) Or FindString(tag$,"J",1,#PB_String_CaseSensitive) : ntsc=1 : EndIf
          EndIf
      EndSelect
    Next
    i=FindString(name$,"(",j)
  Wend
  ProcedureReturn Bool(pal<>0 And ntsc=0)
EndProcedure

; The TV system's timing (rp2040/runtime.pico NesTiming): pal 0 NTSC, 1 PAL. The APU's noise and DMC
; rates, the frame sequencer and the sample step, the PPU's lines and dots.
Procedure NesTiming(pal.i)
  Protected i.i
  CartPal=pal
  For i=0 To 15
    NoiseTable(i)=PeekU(?NoiseData+i*2) : DmcTable(i)=PeekU(?DmcData+i*2)
    If pal : NoiseTable(i)=PeekU(?MachineNoisePal+i*2) : DmcTable(i)=PeekU(?MachineDmcPal+i*2) : EndIf
  Next
  If pal
    PpuPreLine=311 : PpuLineCount=312 : PpuFrameDots=106392 : PpuOddToggle=0 : PpuWarmup=33132
    ApuSampleBase=34 : ApuFracStep=30607 : ApuFracDen=48000
    ApuStep1=8313 : ApuStep2=16627 : ApuStep3=24939 : ApuStep4=33253 : ApuStep5=41565
  Else
    PpuPreLine=261 : PpuLineCount=262 : PpuFrameDots=89342 : PpuOddToggle=1 : PpuWarmup=29658
    ApuSampleBase=37 : ApuFracStep=101 : ApuFracDen=352
    ApuStep1=7457 : ApuStep2=14913 : ApuStep3=22371 : ApuStep4=29829 : ApuStep5=37281
  EndIf
  PpuOdd=0 : PpuDotFrac=0 : ApuSampleLeft=ApuSampleBase : ApuSampleFrac=ApuFracStep
  DmcTimer=DmcTable(0)
  MachinePal=pal
EndProcedure
DataSection
  MachineNoisePal:   ; rp2350/cartridge.pico2's NoisePalData and DmcPalData
  Data.u 4,8,14,30,60,88,118,148,188,236,354,472,708,944,1890,3778
  MachineDmcPal:
  Data.u 398,354,316,298,276,236,210,198,176,148,132,118,98,78,66,50
EndDataSection

Procedure.i RomLoadFile(path$)
  Protected f.i,size.i,i.i,j.i,dst.i,ram.i,lo.i,hi.i
  RomLoaded=0 : RomStatus$=""
  f=ReadFile(#PB_Any,path$)
  If f=0 : RomStatus$="Cannot open "+GetFilePart(path$) : ProcedureReturn 0 : EndIf
  size=Lof(f)
  If size<16 Or ReadData(f,@RomHeader(0),16)<>16 : CloseFile(f) : RomStatus$="Cannot read iNES header" : ProcedureReturn 0 : EndIf
  If RomHeader(0)<>78 Or RomHeader(1)<>69 Or RomHeader(2)<>83 Or RomHeader(3)<>26 Or RomHeader(4)=0 Or (RomHeader(6)&4)<>0 Or ((RomHeader(7)&12)=8 And RomHeader(9)<>0)
    CloseFile(f) : RomValidateHeader(size) : ProcedureReturn 0
  EndIf
  RomPrgBytes=RomHeader(4)*16384 : RomChrBytes=RomHeader(5)*8192
  If RomPrgBytes>4194304 Or RomChrBytes>1048576 Or size<16+RomPrgBytes+RomChrBytes
    CloseFile(f) : RomStatus$="Truncated / oversized cartridge" : ProcedureReturn 0
  EndIf
  If RomRawPrg : FreeMemory(RomRawPrg) : EndIf
  If RomRawChr : FreeMemory(RomRawChr) : EndIf
  If RomPrgViews : FreeMemory(RomPrgViews) : RomPrgViews=0 : EndIf
  RomRawPrg=AllocateMemory(RomPrgBytes*2+32768)          ; room for a 16 KiB PRG's mirror
  RomRawChr=AllocateMemory(RomChrBytes+262144)           ; and for CHR RAM
  If ReadData(f,RomRawPrg,RomPrgBytes)<>RomPrgBytes Or (RomChrBytes>0 And ReadData(f,RomRawChr,RomChrBytes)<>RomChrBytes)
    CloseFile(f) : RomStatus$="ROM read failed" : ProcedureReturn 0
  EndIf
  CloseFile(f)
  RomResolveMetadata()
  If RomValidateHeader(size)=0 : ProcedureReturn 0 : EndIf
  If RomMapper=2
    ; immutable 32 KiB windows, exactly as rom_catalog.prg_views (and RomLoad on the Pi)
    RomPrgViews=AllocateMemory(RomHeader(4)*32768)
    For i=0 To RomHeader(4)-1
      dst=RomPrgViews+i*32768
      CopyMemory(RomRawPrg+i*16384,dst,16384)
      CopyMemory(RomRawPrg+RomPrgBytes-16384,dst+16384,16384)
    Next
    CartPrg=RomPrgViews : CartPrgBanks=RomHeader(4)
  Else
    CartPrg=RomRawPrg : CartPrgBanks=RomPrgBytes/32768
    If RomPrgBytes=16384
      CopyMemory(RomRawPrg,RomRawPrg+16384,16384) : CartPrgBanks=1
    EndIf
  EndIf
  MapRamBytes=8192
  If RomMapper=5
    lo=RomHeader(10)&15 : hi=RomHeader(10)>>4 : ram=0
    If lo>0 : ram=64<<lo : EndIf
    If hi>0 : ram=ram+(64<<hi) : EndIf
    MapRamBytes=ram
    If (RomHeader(7)&12)<>8 : MapRamBytes=RomHeader(8)*8192 : If MapRamBytes=0 : MapRamBytes=65536 : EndIf : EndIf
    If MapRamBytes>131072 : RomStatus$="MMC5 RAM exceeds 128 KiB" : ProcedureReturn 0 : EndIf
  EndIf
  MapPrgBytes=RomPrgBytes : MapChrBytes=RomChrBytes : MapChrRam=Bool(RomChrBytes=0)
  MapBattery=Bool((RomHeader(6)&2)<>0) : MapFourScreen=Bool((RomHeader(6)&8)<>0)
  If MapChrRam
    MapChrBytes=8192
    If RomMapper=13 : MapChrBytes=16384 : EndIf
    If RomMapper=6 : MapChrBytes=32768 : EndIf
    FillMemory(RomRawChr,MapChrBytes,0)
  EndIf
  CartSubmapper=RomSubmapper
  CartMapper=RomMapper : CartChr=RomRawChr : CartChrRam=Bool(RomChrBytes=0)
  CartChrBanks=RomChrBytes/8192 : If CartChrRam : CartChrBanks=2 : EndIf
  CartConflicts=Bool(((RomMapper=2 Or RomMapper=3 Or RomMapper=66) And RomSubmapper<>1) Or ((RomMapper=7 Or RomMapper=11) And RomSubmapper=2))
  If RomMapper=34 And RomChrBytes=0 : CartConflicts=1 : EndIf
  PpuMirroring=RomHeader(6)&1 : CartPrgSelected=0 : CartChrSelected=0
  RomFileName$=GetFilePart(path$) : RomLoaded=1
  CartPal=0 : MachinePalWhy$=""
  If RomHeaderPal : CartPal=1 : MachinePalWhy$="header" : ElseIf RomNamePal(RomFileName$) : CartPal=1 : MachinePalWhy$="file name" : EndIf
  ProcedureReturn 1
EndProcedure

; Power on with the cartridge in path$ ("" = Anvil's built-in demo), in Anvil's order: guest reset, load,
; cartridge start, CPU reset. 1 when running, else 0 with RomStatus$ saying why.
Procedure.i MachineStart(path$)
  GuestReset()
  RomLoaded=0
  If path$<>""
    If RomLoadFile(path$)=0 : ProcedureReturn 0 : EndIf
  EndIf
  If path$="" : CartPal=0 : EndIf
  If MachineTv=1 : CartPal=0 : MachinePalWhy$="chosen" : ElseIf MachineTv=2 : CartPal=1 : MachinePalWhy$="chosen" : EndIf
  LoadCartridge() : NesTiming(CartPal) : CpuReset()
  ProcedureReturn 1
EndProcedure

; Run the machine until the PPU finishes the next frame (or the CPU stops). The CPU runs in windows the
; mapper allows (MapperCpuBudget), each followed by NesSync, exactly as Anvil's compute loop.
Procedure.i MachineRunFrame()
  Protected start.i
  start=DisplayFrames
  While DisplayFrames=start And Stopped=0 And WorkerError=0
    CpuRun(MapperCpuBudget())
    NesSync()
  Wend
  ProcedureReturn DisplayFrames-start
EndProcedure
