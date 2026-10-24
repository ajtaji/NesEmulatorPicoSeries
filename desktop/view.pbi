; What the window shows: the game texture and the debug panes (CPU, PPU, OAM, APU, Mapper, ROMs).
; Every read here is side-effect free: CHR from the current window, nametables by the same routing as
; PpuRead without its mapper hooks, CPU memory without touching I/O ($2000-$5FFF).
EnableExplicit

Structure ViewTexture
  sprite.GLSprite
  *pixels                      ; RGBA, w*h*4
EndStructure

Global UiScale.f=1.0                 ; the desktop's scale (DPI), set by the program
Global ViewGame.ViewTexture, ViewNames.ViewTexture, ViewPatterns.ViewTexture, ViewSprites.ViewTexture, ViewSprites16.ViewTexture
Global Dim View565.l(65536)          ; RGB565 -> RGBA
Global ViewCurrentRom$, ViewMemPage.i, ViewPatPalette.i, ViewRomsTop.i, ViewRomsFolder$
Global NewList ViewRomFiles.s()
Global ViewCpuTestResult$, ViewCpuTestFailed.i

; ---------------------------------------------------------------- textures
Procedure ViewTextureMake(*t.ViewTexture,w.i,h.i)
  *t\sprite\Width=w : *t\sprite\Height=h
  *t\pixels=AllocateMemory(w*h*4)
  glGenTextures_(1,@*t\sprite\TextureID) : glBindTexture_(#GL_TEXTURE_2D,*t\sprite\TextureID)
  glTexParameteri_(#GL_TEXTURE_2D,#GL_TEXTURE_MIN_FILTER,#GL_NEAREST)
  glTexParameteri_(#GL_TEXTURE_2D,#GL_TEXTURE_MAG_FILTER,#GL_NEAREST)
  glTexParameteri_(#GL_TEXTURE_2D,#GL_TEXTURE_WRAP_S,#GL_CLAMP_TO_EDGE)
  glTexParameteri_(#GL_TEXTURE_2D,#GL_TEXTURE_WRAP_T,#GL_CLAMP_TO_EDGE)
  glTexImage2D_(#GL_TEXTURE_2D,0,#GL_RGBA,w,h,0,#GL_RGBA,#GL_UNSIGNED_BYTE,*t\pixels)
EndProcedure
; The engine's sprite draw samples a Windows texture bottom-up (its images come from DIBs), so rows are
; written in that order there; Linux reads them top-down.
Procedure.i ViewRow(*t.ViewTexture,y.i)
  CompilerIf #PB_Compiler_OS=#PB_OS_Windows
    ProcedureReturn *t\pixels+(*t\sprite\Height-1-y)**t\sprite\Width*4
  CompilerElse
    ProcedureReturn *t\pixels+y**t\sprite\Width*4
  CompilerEndIf
EndProcedure
Procedure ViewTextureUpload(*t.ViewTexture)
  glBindTexture_(#GL_TEXTURE_2D,*t\sprite\TextureID)
  glTexSubImage2D_(#GL_TEXTURE_2D,0,0,0,*t\sprite\Width,*t\sprite\Height,#GL_RGBA,#GL_UNSIGNED_BYTE,*t\pixels)
EndProcedure
Procedure ViewTextureDraw(*t.ViewTexture,x.f,y.f,scale.f)
  DrawGLSprite(@*t\sprite,x,y,0.0,scale,1.0,1.0,1.0,1.0,#True,-1,-1,-1,-1,#True)
EndProcedure

Procedure.l ViewRgba(c565.i)
  ProcedureReturn View565(c565&$FFFF)
EndProcedure
; An NES colour (0-63) as RGBA, from the core's own palette table.
Procedure.l ViewNesColour(index.i)
  ProcedureReturn View565(Rgb64(index&63))
EndProcedure

Procedure ViewInit()
  Protected c.i, r.i, g.i, b.i
  For c=0 To 65535
    r=((c>>11)&31)*255/31 : g=((c>>5)&63)*255/63 : b=(c&31)*255/31
    View565(c)=r|(g<<8)|(b<<16)|$FF000000
  Next
  ViewTextureMake(@ViewGame,256,240)
  ViewTextureMake(@ViewNames,512,480)
  ViewTextureMake(@ViewPatterns,256,128)
  ViewTextureMake(@ViewSprites,128,32)     ; 64 sprites, 16 a row
  ViewTextureMake(@ViewSprites16,128,64)   ; the same, 8x16
EndProcedure

; ---------------------------------------------------------------- side-effect-free reads
Procedure.i ViewPeek(addr.i)          ; CPU space; -1 where reading would touch a device
  Protected v.i, keep.i
  addr&$FFFF
  If addr<$2000 : ProcedureReturn M(addr&$7FF) : EndIf
  If addr<$6000 : ProcedureReturn -1 : EndIf
  keep=NesOpenBus : v=NesReadSlow(addr) : NesOpenBus=keep
  ProcedureReturn v&255
EndProcedure
Procedure.i ViewPeekByte(addr.i)
  Protected v.i=ViewPeek(addr)
  If v<0 : v=0 : EndIf
  ProcedureReturn v
EndProcedure
Procedure.i ViewChr(addr.i)           ; pattern memory through the current CHR window
  ProcedureReturn PeekA(Chr+(addr&$1FFF))
EndProcedure
Procedure.i ViewNt(addr.i)
  addr=$2000|(addr&$FFF)
  If CartMapper=5 : ProcedureReturn M5NtRead(addr) : EndIf
  If CartMapper=68 And ExtraFlags : ProcedureReturn ExtraNtRead(addr) : EndIf
  If MapManaged : ProcedureReturn MapCiram(PpuNtAddr(addr)) : EndIf
  ProcedureReturn Nt(PpuNtAddr(addr))
EndProcedure

; ---------------------------------------------------------------- the game
Procedure ViewDrawGame(x.f,y.f,scale.f)
  Protected i.i, *dst.Long, yy.i, xx.i
  For yy=0 To 239
    *dst=ViewRow(@ViewGame,yy)
    For xx=0 To 255
      *dst\l=View565(DisplayFrame565(yy*256+xx)) : *dst+4
    Next
  Next
  ViewTextureUpload(@ViewGame)
  Neon_Box(x-2,y-2,256*scale+4,240*scale+4,0,0,0)
  ViewTextureDraw(@ViewGame,x,y,scale)
EndProcedure

; ---------------------------------------------------------------- panes
Procedure.f ViewLine(x.f,y.f,t$,r.f=-1,g.f=0,b.f=0)
  If r<0 : r=Neon_C_TextR : g=Neon_C_TextG : b=Neon_C_TextB : EndIf
  Neon_Text(*Neon_FontMono,x,y,t$,r,g,b)
  ProcedureReturn y+GLFontLineHeight(*Neon_FontMono)
EndProcedure
Procedure.s Hex2(v.i)
  ProcedureReturn RSet(Hex(v&255),2,"0")
EndProcedure
Procedure.s Hex4(v.i)
  ProcedureReturn RSet(Hex(v&$FFFF),4,"0")
EndProcedure

Declare LoadRom(path$)        ; the program's (nes_desktop.pb)

; Runs both CPU suites on a clean machine, then reloads the game (the tests overwrite RAM and registers).
Procedure ViewRunCpuTests()
  Protected t.q=ElapsedMilliseconds()
  MachineStart("")
  If CpuTestsRun()
    ViewCpuTestResult$=Str(CpuTestChecks)+" checks (Anvil core "+Str(CpuTestCore)+", mappers "+Str(CpuTestMapper)+", opcodes "+Str(CpuTestAll)+"), 0 failures: PASS"
    ViewCpuTestFailed=0
  Else
    ViewCpuTestResult$=Str(CpuTestChecks)+" checks, "+Str(CpuTestFailures)+" failures: FAIL"
    ViewCpuTestFailed=1
  EndIf
  ViewCpuTestResult$+"  ("+Str(ElapsedMilliseconds()-t)+" ms)"
  LoadRom(ViewCurrentRom$)
EndProcedure

Procedure ViewCpu(x.f,y.f,w.f,h.f)
  Protected p.i, f$, i.i, a.i, row$, v.i, lh.f, s.f=UiScale, bottom.f
  lh=GLFontLineHeight(*Neon_FontMono)
  p=CpuStatus()
  f$=Mid("NV-BDIZC",1,8) : row$=""
  For i=0 To 7
    If p&(128>>i) : row$+Mid("NV-BDIZC",i+1,1) : Else : row$+"." : EndIf
  Next
  Neon_Panel(x,y,w,h,"6502 CPU",Neon_C_AccR,Neon_C_AccG,Neon_C_AccB)
  y+34*s : x+12*s
  y=ViewLine(x,y,"PC $"+Hex4(PC)+"   A $"+Hex2(A)+"   X $"+Hex2(X)+"   Y $"+Hex2(Y)+"   S $"+Hex2(S))
  y=ViewLine(x,y,"P  $"+Hex2(p)+" "+row$+"   cycles "+Str(CpuCycles)+"   instructions "+Str(NesInstructions))
  y=ViewLine(x,y,"NMI "+Str(WorkerNmi)+"   IRQ line "+Str(Bool(WorkerIrq|MapIrq))+"   frame "+Str(WorkerFrames)+"   line "+Str(PpuLine)+" dot "+Str(PpuDot),Neon_C_DimR,Neon_C_DimG,Neon_C_DimB)
  y+6*s
  ; disassembly from PC
  Neon_Text(*Neon_FontSmall,x,y,"DISASSEMBLY",Neon_C_AmbR,Neon_C_AmbG,Neon_C_AmbB) : y+lh
  a=PC
  For i=0 To 15
    If i=0
      y=ViewLine(x,y,"> "+DisLine(a,@ViewPeekByte()),Neon_C_GrnR,Neon_C_GrnG,Neon_C_GrnB)
    Else
      y=ViewLine(x,y,"  "+DisLine(a,@ViewPeekByte()))
    EndIf
    a=(a+DisLength(ViewPeekByte(a)))&$FFFF
  Next
  y+6*s
  ; memory
  Neon_Text(*Neon_FontSmall,x,y,"MEMORY  $"+Hex4(ViewMemPage*256),Neon_C_AmbR,Neon_C_AmbG,Neon_C_AmbB)
  If Neon_Button(x+200*s,y-2*s,28*s,20*s,"<") : ViewMemPage=(ViewMemPage-1)&255 : EndIf
  If Neon_Button(x+232*s,y-2*s,28*s,20*s,">") : ViewMemPage=(ViewMemPage+1)&255 : EndIf
  If Neon_Button(x+266*s,y-2*s,44*s,20*s,"zp") : ViewMemPage=0 : EndIf
  If Neon_Button(x+314*s,y-2*s,60*s,20*s,"stack") : ViewMemPage=1 : EndIf
  If Neon_Button(x+378*s,y-2*s,44*s,20*s,"PC") : ViewMemPage=PC>>8 : EndIf
  y+lh+4*s
  bottom=y+16*lh
  For i=0 To 15
    a=ViewMemPage*256+i*16
    row$=Hex4(a)+" "
    For p=0 To 15
      v=ViewPeek(a+p)
      If v<0 : row$+" --" : Else : row$+" "+Hex2(v) : EndIf
    Next
    y=ViewLine(x,y,row$)
  Next
  ; the CPU test suites (desktop/cpu_tests.pbi), the same ones desktop/nes_check.exe prints
  y+8*s
  Neon_Text(*Neon_FontSmall,x,y,"TESTS",Neon_C_AmbR,Neon_C_AmbG,Neon_C_AmbB)
  If Neon_Button(x+200*s,y-2*s,120*s,20*s,"Run tests") : ViewRunCpuTests() : EndIf
  y+lh+4*s
  If ViewCpuTestResult$<>""
    If ViewCpuTestFailed
      y=ViewLine(x,y,ViewCpuTestResult$,Neon_C_RedR,Neon_C_RedG,Neon_C_RedB)
      ForEach CpuTestFailLines()
        If y>bottom+40*lh : Break : EndIf
        y=ViewLine(x,y,"  "+CpuTestFailLines(),Neon_C_RedR,Neon_C_RedG,Neon_C_RedB)
      Next
    Else
      y=ViewLine(x,y,ViewCpuTestResult$,Neon_C_GrnR,Neon_C_GrnG,Neon_C_GrnB)
    EndIf
  EndIf
EndProcedure

Procedure ViewPpu(x.f,y.f,w.f,h.f)
  Protected y0.f=y, s.f=UiScale, t.i, row.i, col.i, ty.i, tx.i, tile.i, attr.i, pal.i, lo.i, hi.i, px.i, py.i, c.i
  Protected base.i, *dst.Long, sc.f, i.i, lh.f, bgTable.i, sz.f
  lh=GLFontLineHeight(*Neon_FontMono)
  Neon_Panel(x,y,w,h,"PPU",Neon_C_VioR,Neon_C_VioG,Neon_C_VioB)
  y+32*s : x+10*s
  y=ViewLine(x,y,"CTRL $"+Hex2(PpuCtrl)+"  MASK $"+Hex2(PpuMask)+"  STATUS $"+Hex2(PpuStatus)+"  V $"+Hex4(PpuV)+"  T $"+Hex4(PpuT)+"  fine X "+Str(PpuFineX))
  ; the four nametables, 512 x 480
  bgTable=(PpuCtrl&16)<<8
  For t=0 To 3
    For ty=0 To 29
      For tx=0 To 31
        tile=ViewNt(t*$400+ty*32+tx)
        attr=ViewNt(t*$400+$3C0+(ty>>2)*8+(tx>>2))
        pal=((attr>>(((ty&2)<<1)|(tx&2)))&3)*4
        For row=0 To 7
          lo=ViewChr(bgTable+tile*16+row) : hi=ViewChr(bgTable+tile*16+row+8)
          py=(t>>1)*240+ty*8+row : px=(t&1)*256+tx*8
          *dst=ViewRow(@ViewNames,py)+px*4
          For col=0 To 7
            c=((lo>>(7-col))&1)|(((hi>>(7-col))&1)<<1)
            If c : c=Pal(pal+c) : Else : c=Pal(0) : EndIf
            *dst\l=ViewNesColour(c) : *dst+4
          Next
        Next
      Next
    Next
  Next
  ViewTextureUpload(@ViewNames)
  ; what is left below this line, less the three labels, the gaps and the two rows of palette boxes,
  ; shared out: the pattern tables up to 2x (a third of the room at most), the nametables the rest
  base=h-(y-(y0+32*s))-32*s-3*lh-3*8*s-40*s
  sc=(w-20*s)/256.0 : If sc>2.0*s : sc=2.0*s : EndIf
  If 128*sc>base/3 : sc=(base/3)/128.0 : EndIf
  sz=(w-20*s)/512.0
  If 480*sz>base-128*sc : sz=(base-128*sc)/480.0 : EndIf
  Neon_Text(*Neon_FontSmall,x,y,"NAMETABLES ($2000 $2400 / $2800 $2C00)",Neon_C_AmbR,Neon_C_AmbG,Neon_C_AmbB) : y+lh
  ViewTextureDraw(@ViewNames,x,y,sz) : y+480*sz+8*s
  ; the two pattern tables in the chosen palette
  For t=0 To 1
    For i=0 To 255
      For row=0 To 7
        lo=ViewChr(t*$1000+i*16+row) : hi=ViewChr(t*$1000+i*16+row+8)
        *dst=ViewRow(@ViewPatterns,(i>>4)*8+row)+(t*128+(i&15)*8)*4
        For col=0 To 7
          c=((lo>>(7-col))&1)|(((hi>>(7-col))&1)<<1)
          If c : c=Pal(ViewPatPalette*4+c) : Else : c=Pal(0) : EndIf
          *dst\l=ViewNesColour(c) : *dst+4
        Next
      Next
    Next
  Next
  ViewTextureUpload(@ViewPatterns)
  Neon_Text(*Neon_FontSmall,x,y,"PATTERN TABLES ($0000 / $1000) - palette "+Str(ViewPatPalette),Neon_C_AmbR,Neon_C_AmbG,Neon_C_AmbB)
  If Neon_Button(x+w-90*s,y-3*s,64*s,20*s,"palette") : ViewPatPalette=(ViewPatPalette+1)&7 : EndIf
  y+lh
  ViewTextureDraw(@ViewPatterns,x,y,sc) : y+128*sc+8*s
  ; the 32 palette entries
  Neon_Text(*Neon_FontSmall,x,y,"PALETTES (background 0-3, sprites 4-7)",Neon_C_AmbR,Neon_C_AmbG,Neon_C_AmbB) : y+lh
  For i=0 To 31
    c=ViewNesColour(Pal(i))
    px=i%16 : py=i/16 : lo=c&255 : hi=(c>>8)&255 : col=(c>>16)&255
    Neon_Box(x+px*20*s,y+py*20*s,18*s,18*s,lo/255.0,hi/255.0,col/255.0)
  Next
EndProcedure

Procedure ViewOam(x.f,y.f,w.f,h.f)
  Protected s.f=UiScale, i.i, row$, lh.f, t.i, tile.i, attr.i, base.i, row.i, col.i, lo.i, hi.i, c.i, *dst.Long, tall.i, r.i
  Protected *tex.ViewTexture, sc.f
  lh=GLFontLineHeight(*Neon_FontMono)
  Neon_Panel(x,y,w,h,"Sprites (OAM)",Neon_C_GrnR,Neon_C_GrnG,Neon_C_GrnB)
  y+32*s : x+10*s
  tall=Bool(PpuCtrl&32)
  y=ViewLine(x,y,"size 8x"+Str(8+tall*8)+"   OAMADDR $"+Hex2(PpuOamAddr)+"   pattern $"+Hex4((PpuCtrl&8)<<9))
  ; each sprite in its own palette, 16 to a row: 8x8, or 8x16 (both tiles) when PPUCTRL says so
  *tex=@ViewSprites : If tall : *tex=@ViewSprites16 : EndIf
  For i=0 To 63
    tile=Oam(i*4+1) : attr=Oam(i*4+2)
    If tall : base=(tile&1)*$1000+(tile&$FE)*16 : Else : base=((PpuCtrl&8)<<9)+tile*16 : EndIf
    For row=0 To 7+tall*8
      lo=ViewChr(base+(row&7)+(row>>3)*16) : hi=ViewChr(base+(row&7)+(row>>3)*16+8)
      *dst=ViewRow(*tex,(i>>4)*(8+tall*8)+row)+((i&15)*8)*4
      For col=0 To 7
        c=((lo>>(7-col))&1)|(((hi>>(7-col))&1)<<1)
        If c : c=ViewNesColour(Pal(16+(attr&3)*4+c)) : Else : c=$FF202020 : EndIf
        *dst\l=c : *dst+4
      Next
    Next
  Next
  ViewTextureUpload(*tex)
  sc=3*s
  ViewTextureDraw(*tex,x,y,sc) : y+(32+tall*32)*sc+8*s
  Neon_Text(*Neon_FontSmall,x,y,"#   Y    TILE ATTR X",Neon_C_AmbR,Neon_C_AmbG,Neon_C_AmbB) : y+lh
  For r=0 To 15
    row$=""
    For t=0 To 3
      i=t*16+r
      row$+RSet(Str(i),2," ")+" "+RSet(Str(Oam(i*4)),3," ")+"  $"+Hex2(Oam(i*4+1))+" $"+Hex2(Oam(i*4+2))+" "+RSet(Str(Oam(i*4+3)),3," ")+"   "
    Next
    y=ViewLine(x,y,row$)
  Next
EndProcedure

Procedure ViewApu(x.f,y.f,w.f,h.f)
  Protected s.f=UiScale, lh.f, c.i, i.i, v.i, mid.f, ph.f, x0.f, n.i
  Protected Dim nm$(3)
  nm$(0)="Pulse 1" : nm$(1)="Pulse 2" : nm$(2)="Triangle" : nm$(3)="Noise"
  lh=GLFontLineHeight(*Neon_FontMono)
  Neon_Panel(x,y,w,h,"APU",Neon_C_AmbR,Neon_C_AmbG,Neon_C_AmbB)
  y+32*s : x+10*s
  y=ViewLine(x,y,"enable $"+Hex2(ApuEnable)+"   frame step "+Str(ApuFrameStep)+"  "+StringField("4-step|5-step",1+ApuFive,"|")+"   IRQ "+Str(ApuFrameIrq)+"   samples "+Str(ApuSamples))
  y+4*s
  For c=0 To 3
    y=ViewLine(x,y,LSet(nm$(c),9)+" $"+Hex2(ApuReg(c*4))+" $"+Hex2(ApuReg(c*4+1))+" $"+Hex2(ApuReg(c*4+2))+" $"+Hex2(ApuReg(c*4+3))+"   period "+RSet(Str(ApuPeriod(c)),5," ")+"   length "+RSet(Str(ApuLength(c)),3," ")+"   on "+Str((ApuEnable>>c)&1))
  Next
  y=ViewLine(x,y,"DMC       $"+Hex2(ApuReg(16))+" $"+Hex2(ApuReg(17))+" $"+Hex2(ApuReg(18))+" $"+Hex2(ApuReg(19))+"   bytes "+Str(DmcBytes)+"   address $"+Hex4(DmcAddress)+"   level "+Str(DmcLevel)+"   IRQ "+Str(DmcIrq))
  y+8*s
  ; the last 512 samples the APU produced
  Neon_Text(*Neon_FontSmall,x,y,"OUTPUT (last 512 samples, 48 kHz)",Neon_C_AmbR,Neon_C_AmbG,Neon_C_AmbB) : y+lh
  ph=160*s : mid=y+ph/2
  Neon_Box(x,y,w-20*s,ph,0.08,0.09,0.10)
  Neon_Box(x,mid,w-20*s,1,Neon_C_LineR,Neon_C_LineG,Neon_C_LineB)
  n=512 : x0=x
  For i=0 To n-1
    v=Pcm((ApuSamples-n+i)&4095)
    Neon_Box(x0+i*(w-20*s)/n,mid-v*(ph/2)/32768.0,2*s,2*s,Neon_C_AccR,Neon_C_AccG,Neon_C_AccB)
  Next
  y+ph+8*s
  CompilerIf #PB_Compiler_OS=#PB_OS_Windows
    If ExpChip=1
      y=ViewLine(x,y,"VRC6:  pulse "+Str(V6Volume(0))+"/"+Str(V6Duty(0))+" on "+Str(V6Enable(0))+"   pulse "+Str(V6Volume(1))+"/"+Str(V6Duty(1))+" on "+Str(V6Enable(1))+"   saw rate "+Str(V6Rate)+" on "+Str(V6Enable(2))+"   sample "+Str(ExpSample))
    ElseIf ExpChip=2
      y=ViewLine(x,y,"N163:  channels "+Str(((N1Sound($7F)>>4)&7)+1)+"   muted "+Str(N1Mute)+"   sample "+Str(ExpSample)+"   peak "+Str(ExpPeak))
    EndIf
    y=ViewLine(x,y,"sound card: "+StringField("off|on",1+SoundOn,"|")+"   queued "+Str(SoundQueued)+"   underruns "+Str(SoundUnderruns)+"   muted "+Str(SoundMuted),Neon_C_DimR,Neon_C_DimG,Neon_C_DimB)
  CompilerEndIf
EndProcedure

Procedure ViewMapper(x.f,y.f,w.f,h.f)
  Protected s.f=UiScale, lh.f, i.i, row$
  lh=GLFontLineHeight(*Neon_FontMono)
  Neon_Panel(x,y,w,h,"Cartridge / mapper",Neon_C_RedR,Neon_C_RedG,Neon_C_RedB)
  y+32*s : x+10*s
  y=ViewLine(x,y,"mapper "+Str(CartMapper)+"   submapper "+Str(CartSubmapper)+"   PRG "+Str(MapPrgBytes/1024)+" KiB   CHR "+Str(MapChrBytes/1024)+" KiB"+StringField(" ROM| RAM",1+MapChrRam,"|"))
  y=ViewLine(x,y,"mirroring "+Str(PpuMirroring)+"   four-screen "+Str(MapFourScreen)+"   battery "+Str(MapBattery)+"   bus conflicts "+Str(CartConflicts))
  y=ViewLine(x,y,"PRG-RAM "+Str(MapRamBytes/1024)+" KiB  enabled "+Str(MapRamEnable)+"  protected "+Str(MapRamProtect))
  y+6*s
  row$="PRG slots ($8000 $A000 $C000 $E000):" : For i=0 To 3 : row$+" "+Str(MapPrgSlots(i)) : Next : y=ViewLine(x,y,row$)
  row$="CHR slots (1 KiB each):" : For i=0 To 7 : row$+" "+Str(MapChrSlots(i)) : Next : y=ViewLine(x,y,row$)
  row$="nametable slots:" : For i=0 To 3 : row$+" "+Str(MapNtSlots(i)) : Next : y=ViewLine(x,y,row$)
  row$="registers:" : For i=0 To 7 : row$+" $"+Hex2(MapRegs(i)) : Next : y=ViewLine(x,y,row$)
  y=ViewLine(x,y,"select $"+Hex2(MapSelect)+"   shift $"+Hex2(MapShift)+"   control $"+Hex2(MapControl))
  y+6*s
  y=ViewLine(x,y,"IRQ: latch "+Str(MapIrqLatch)+"  count "+Str(MapIrqCount)+"  reload "+Str(MapReload)+"  enabled "+Str(MapIrqEnable)+"  line "+Str(MapIrq))
  y=ViewLine(x,y,"IRQ clocks "+Str(MapIrqClocks)+"   assertions "+Str(MapIrqAssertions)+"   A12 "+Str(MapA12))
  If CartMapper=5
    y+6*s
    y=ViewLine(x,y,"MMC5: PRG mode "+Str(M5PrgMode)+"  CHR mode "+Str(M5ChrMode)+"  ExRAM mode "+Str(M5ExMode)+"  NT $"+Hex2(M5NtConfig))
    y=ViewLine(x,y,"      scanline "+Str(M5Scanline)+"  target "+Str(M5IrqTarget)+"  in frame "+Str(M5InFrame)+"  pending "+Str(M5Pending)+"  split $"+Hex2(M5Split))
  ElseIf CartMapper=24 Or CartMapper=26
    y+6*s
    y=ViewLine(x,y,"VRC6: PRG 16K "+Str(VrcPrg16)+"  PRG 8K "+Str(VrcPrg8)+"   IRQ latch "+Str(VrcIrqLatch)+"  count "+Str(VrcIrqCounter)+"  enabled "+Str(VrcIrqEnable)+"  "+StringField("scanline|cycle",1+VrcIrqMode,"|")+" mode  prescaler "+Str(VrcPrescaler))
  ElseIf CartMapper=19
    y+6*s
    y=ViewLine(x,y,"N163: PRG "+Str(N1Prg(0))+" "+Str(N1Prg(1))+" "+Str(N1Prg(2))+"   IRQ count $"+Hex4(N1IrqCounter)+"  enabled "+Str(N1IrqEnable)+"   sound address $"+Hex2(N1Address))
    row$="      nametable banks:" : For i=0 To 3 : If N1NtBank(i)<0 : row$+" CIRAM" : Else : row$+" "+Str(N1NtBank(i)) : EndIf : Next : y=ViewLine(x,y,row$)
  EndIf
EndProcedure

; ---------------------------------------------------------------- the ROM picker
Procedure ViewRomsRefresh(folder$)
  Protected d.i, n$
  If folder$="" : ProcedureReturn : EndIf
  ViewRomsFolder$=folder$
  ClearList(ViewRomFiles())
  d=ExamineDirectory(#PB_Any,folder$,"*.nes")
  If d
    While NextDirectoryEntry(d)
      If DirectoryEntryType(d)=#PB_DirectoryEntry_File : AddElement(ViewRomFiles()) : ViewRomFiles()=DirectoryEntryName(d) : EndIf
    Wend
    FinishDirectory(d)
  EndIf
  SortList(ViewRomFiles(),#PB_Sort_Ascending|#PB_Sort_NoCase)
  ViewRomsTop=0
EndProcedure
Procedure ViewOpenRomDialog()
  Protected f$=OpenFileRequester("Open an NES game",ViewRomsFolder$,"NES games (*.nes)|*.nes|All files|*.*",0)
  If f$<>"" : ViewCurrentRom$=f$ : LoadRom(f$) : EndIf
EndProcedure
Procedure ViewRoms(x.f,y.f,w.f,h.f)
  Protected s.f=UiScale, f$, sel.i
  Neon_Panel(x,y,w,h,"Games",Neon_C_AccR,Neon_C_AccG,Neon_C_AccB)
  y+32*s : x+10*s
  If Neon_Button(x,y,110*s,24*s,"Open file...") : ViewOpenRomDialog() : EndIf
  If Neon_Button(x+118*s,y,120*s,24*s,"Choose folder...")
    f$=PathRequester("Choose a folder of NES games",ViewRomsFolder$)
    If f$<>"" : ViewRomsRefresh(f$) : EndIf
  EndIf
  Neon_Text(*Neon_FontSmall,x+250*s,y+4*s,Neon_FitText(*Neon_FontSmall,ViewRomsFolder$,w-270*s),Neon_C_DimR,Neon_C_DimG,Neon_C_DimB)
  y+32*s
  Neon_ListBegin(7,x,y,w-20*s,h-76*s,22*s,@ViewRomsTop)
  ForEach ViewRomFiles()
    sel=Bool(ViewRomsFolder$+ViewRomFiles()=ViewCurrentRom$)
    If Neon_ListItem(ViewRomFiles(),0,sel)
      ViewCurrentRom$=ViewRomsFolder$+ViewRomFiles() : LoadRom(ViewCurrentRom$)
    EndIf
  Next
  Neon_ListEnd()
EndProcedure

Procedure ViewDrawPanel(tab.i,x.f,y.f,w.f,h.f)
  Select tab
    Case 0 : ViewCpu(x,y,w,h)
    Case 1 : ViewPpu(x,y,w,h)
    Case 2 : ViewOam(x,y,w,h)
    Case 3 : ViewApu(x,y,w,h)
    Case 4 : ViewMapper(x,y,w,h)
    Case 5 : ViewRoms(x,y,w,h)
  EndSelect
EndProcedure
