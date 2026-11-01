; PureMetal NES for the desktop: the same emulation as the boards (desktop/core, generated from Anvil's
; portable core by tools/port_desktop.py), drawn with the Neon Arcade Display Engine. Everything the OS gives
; (window, input, clock, sound, full screen, gamepads) comes through the engine, so this one source builds on
; Windows and Linux; see engine.pbi for where the engine is found, and README.md for both builds.
;
; Build (Windows, PowerShell, from the repository root):
;   & <PureBasic>\Compilers\pbcompilerc.exe desktop\nes_desktop.pb /EXE desktop\PureMetalNES.exe /THREAD /DPIAWARE /OPTIMIZER
; Build (Linux, in desktop/):  pbcompilerc nes_desktop.pb -t -z -o PureMetalNES
; Run:  desktop\PureMetalNES.exe [game.nes] [--mute] [--pal|--ntsc] [--cpu-tests] [--tab N] [--shot window.png --seconds S] [--pointer-test log.txt] [--fullscreen-test log.txt [--fullscreen-shot f.png]]
;       (--shot saves the window after S seconds, default 5, and closes: for checks without a person)
;
; Keys: arrows = D-pad, X = A, Z = B, Enter = Start, Shift, Tab or Space = Select. A gamepad works too.
;       Player 2: I/J/K/L = D-pad, H = A, G = B, Y = Start, T = Select, or the second gamepad.
;       F5 run/pause, F6 step one instruction, F7 step one frame, F8 reset, F11 full screen (Esc leaves it), M mute.
;       Every binding is in controls.pbi's table; the Controls tab shows it.
EnableExplicit

XIncludeFile "engine.pbi"
XIncludeFile "host.pbi"
XIncludeFile "core/core.pbi"
XIncludeFile "machine.pbi"
XIncludeFile "sound.pbi"
XIncludeFile "disasm.pbi"
XIncludeFile "cpu_tests.pbi"
XIncludeFile "controls.pbi"
XIncludeFile "view.pbi"

; ---------------------------------------------------------------- state
Global Win.i, Gl.i, PhysW.i, PhysH.i
Global Running.i, Quit.i, Paused.i=1
Global KeyCode.i, KeyChar.i, Wheel.i, MouseDown.i
Global NewMap KeyHeld.i()          ; by key code (#PB_Shortcut_: Windows virtual keys, Linux X keysyms)
Global PadMask.i
Global EmuAccum.d, EmuLastUs.q, EmuFrameUs.d=1000000.0/60.0988
Global FpsShown.d, FpsFrames.i, FpsSince.q, IpsShown.i, IpsInstr.i
Global ActiveTab.i, RomStatusLine$, LastRomFolder$
Global LastDraw.q
Global ShotFile$, ShotAtMs.q

; ---------------------------------------------------------------- fonts and size
Procedure BuildFonts()
  *Neon_FontUI    = Neon_CreateFontPx("Segoe UI", Round(14*Neon_UIScale,#PB_Round_Nearest))
  *Neon_FontSmall = Neon_CreateFontPx("Segoe UI", Round(12*Neon_UIScale,#PB_Round_Nearest))
  *Neon_FontBold  = Neon_CreateFontPx("Segoe UI", Round(15*Neon_UIScale,#PB_Round_Nearest), #PB_Font_Bold)
  *Neon_FontMono  = Neon_CreateFontPx("Consolas", Round(13*Neon_UIScale,#PB_Round_Nearest))
  GLFontSetSnapToPixel(*Neon_FontUI,#True) : GLFontSetSnapToPixel(*Neon_FontSmall,#True)
  GLFontSetSnapToPixel(*Neon_FontBold,#True) : GLFontSetSnapToPixel(*Neon_FontMono,#True)
EndProcedure

Procedure MeasureWindow()
  Protected scale.f
  GL_ClientPixels(Win,@PhysW,@PhysH)
  If PhysW<1 : PhysW=1 : EndIf
  If PhysH<1 : PhysH=1 : EndIf
  ResizeGadget(Gl,0,0,WindowWidth(Win,#PB_Window_InnerCoordinate),WindowHeight(Win,#PB_Window_InnerCoordinate))
  GL_ViewportX=0 : GL_ViewportY=0 : GL_ViewportW=PhysW : GL_ViewportH=PhysH
  Util_BaseWidth=PhysW : Util_BaseHeight=PhysH
  Util_WinWidth=WindowWidth(Win,#PB_Window_InnerCoordinate) : Util_WinHeight=WindowHeight(Win,#PB_Window_InnerCoordinate)
  ; The engine's hosting rule (GlUIChrome.pbi 5a): the window draws 1:1 on its physical pixels, so the scale is
  ; physical / logical, Neon_UIScale carries it (the chrome's own tabs, rows and buttons are sized by it) and
  ; the fonts are built at it - again whenever it changes (another monitor).
  scale=1.0 : If Util_WinWidth>0 : scale=PhysW/Util_WinWidth : EndIf
  If scale<1 : scale=1 : EndIf
  If scale<>Neon_UIScale Or *Neon_FontUI=0 : Neon_UIScale=scale : BuildFonts() : EndIf
EndProcedure

; ---------------------------------------------------------------- the machine
Procedure LoadRom(path$)
  Paused=1
  If MachineStart(path$)
    RomStatusLine$=RomFileName$+"  -  mapper "+Str(CartMapper)+", PRG "+Str(MapPrgBytes/1024)+" KiB, CHR "+Str(MapChrBytes/1024)+" KiB"
    If MapChrRam : RomStatusLine$+" RAM" : EndIf
    If MachinePal : RomStatusLine$+",  PAL 50 Hz ("+MachinePalWhy$+")" : Else : RomStatusLine$+",  NTSC 60 Hz" : EndIf
    EmuFrameUs=1000000.0/60.0988 : If MachinePal : EmuFrameUs=1000000.0/50.0070 : EndIf
    If path$="" : RomStatusLine$="Built-in demo (no game loaded)" : EndIf
    LastRomFolder$=GetPathPart(path$)
    Paused=0 : EmuAccum=0 : EmuLastUs=NesHostUs() : AudioReset()
  Else
    RomStatusLine$="Not loaded: "+RomStatus$
    MachineStart("")
  EndIf
  ViewRomsRefresh(LastRomFolder$)
EndProcedure

; One gamepad's buttons, NES bit order (A B Select Start Up Down Left Right). The engine's GL_JoyRead reads
; any game controller (Windows' joystick API, Linux's /dev/input/jsN): buttons 1-32 in bits 0-31, the stick
; 0-65535 (a direction past half way), the d-pad as the hat (hundredths of a degree, $FFFF centred).
Procedure.i ReadPad(pad.i)
  Protected m.i, j.GLJoyState, pov.i
  If GL_JoyRead(pad,@j)
    If j\Axis[0]<16384 : m|64 : ElseIf j\Axis[0]>49151 : m|128 : EndIf
    If j\Axis[1]<16384 : m|16 : ElseIf j\Axis[1]>49151 : m|32 : EndIf
    pov=j\POV
    If pov<>$FFFF
      If pov>=31500 Or pov<=4500 : m|16 : EndIf
      If pov>=4500 And pov<=13500 : m|128 : EndIf
      If pov>=13500 And pov<=22500 : m|32 : EndIf
      If pov>=22500 And pov<=31500 : m|64 : EndIf
    EndIf
    ForEach CtlPads()
      If CtlPads()\player=pad+1 And CtlPads()\button>0
        If j\Buttons&(1<<(CtlPads()\button-1)) : m|CtlPads()\bit : EndIf
      EndIf
    Next
  EndIf
  ProcedureReturn m
EndProcedure

; A real pad cannot press both opposite directions; several games misbehave if it does.
Procedure.i PadClean(m.i)
  If (m&48)=48 : m&~48 : EndIf
  If (m&192)=192 : m&~192 : EndIf
  ProcedureReturn m
EndProcedure

; The two controllers, from the key table in controls.pbi (the Controls pane shows the same table).
Procedure ReadController()
  NesController=PadClean(CtlKeysHeld(1,KeyHeld())|ReadPad(0))
  NesController2=PadClean(CtlKeysHeld(2,KeyHeld())|ReadPad(1))
EndProcedure

; Run whole frames to keep pace with real time (NTSC 60.0988 Hz, PAL 50.0070 Hz); never more than three per pass.
Procedure Emulate()
  Protected now.q, due.i, n.i
  now=NesHostUs()
  If EmuLastUs=0 : EmuLastUs=now : EndIf
  If Paused Or Stopped Or WorkerError : EmuLastUs=now : ProcedureReturn : EndIf
  EmuAccum+(now-EmuLastUs) : EmuLastUs=now
  If EmuAccum>EmuFrameUs*4 : EmuAccum=EmuFrameUs*4 : EndIf
  ReadController()
  While EmuAccum>=EmuFrameUs And n<3
    MachineRunFrame() : EmuAccum-EmuFrameUs : n+1 : FpsFrames+1
    If Stopped Or WorkerError : Break : EndIf
  Wend
  ; keep the sound card fed: one more frame when its queue runs low
  If SoundOn And SoundPump()<#SOUND_SAMPLES And n<3 And ApuSamples-AudioReadCursor<#SOUND_SAMPLES
    MachineRunFrame() : FpsFrames+1 : EmuAccum-EmuFrameUs
  EndIf
EndProcedure

Procedure StepInstruction()
  Paused=1
  CpuRun(1) : NesSync()
EndProcedure
Procedure StepFrame()
  Paused=1 : ReadController() : MachineRunFrame()
EndProcedure

; The window's back buffer as a PNG (read before the flip).
Procedure SaveWindowShot(file$)
  Protected *buf=AllocateMemory(PhysW*PhysH*4), img.i, x.i, y.i, c.l
  glReadPixels_(0,0,PhysW,PhysH,#GL_RGBA,#GL_UNSIGNED_BYTE,*buf)
  img=CreateImage(#PB_Any,PhysW,PhysH,24)
  StartDrawing(ImageOutput(img))
  For y=0 To PhysH-1
    For x=0 To PhysW-1
      c=PeekL(*buf+((PhysH-1-y)*PhysW+x)*4)
      Plot(x,y,RGB(c&255,(c>>8)&255,(c>>16)&255))
    Next
  Next
  StopDrawing()
  UsePNGImageEncoder()
  SaveImage(img,file$,#PB_ImagePlugin_PNG)
  FreeImage(img) : FreeMemory(*buf)
EndProcedure


; ---------------------------------------------------------------- --pointer-test
; The mouse and the controls at the desktop's scale, without the real pointer (it is shared): the chrome is
; driven with synthetic pointer positions in the units WindowMouseX/Y give a DPI-aware window (physical
; pixels, GlUIChrome.pbi 5a). For each point: move there, press, release, then check the click landed (or,
; outside a control, that nothing happened) and that Neon_MX/Neon_MY read the point back unbent.
Global SynthOn.i, SynthX.f, SynthY.f, SynthDown.i, SynthCase.i, SynthFrame.i, SynthFails.i, SynthLog$, SynthFile$
Global SynthBefore.i
Procedure.i SynthTarget(c.i, *x.Float, *y.Float)
  Protected s.f=Neon_UIScale, toolH.f, x0.f, y0.f, w.f, h.f, *row.Neon_TabRowLayout
  toolH=Round(40*s,#PB_Round_Nearest)
  If c<=3
    ; Pause, near the top: its top-left and bottom-right corners inside, then just right of it and just below
    x0=110*s : y0=6*s : w=72*s : h=toolH-12*s
  ElseIf c<=7
    ; Run tests, near the bottom of the CPU pane: the same four points
    x0=ViewRunTestsX : y0=ViewRunTestsY : w=ViewRunTestsW : h=ViewRunTestsH
  ElseIf c<=9
    ; the ROMs tab: its right-hand bottom inside (the row's last pixel is not the tab's), then right of it
    If FindMapElement(Neon_TabLayout(),"1")=0 : ProcedureReturn 0 : EndIf
    *row=@Neon_TabLayout()
    If c=8 : *x\f=*row\X(5)+*row\W(5)-2 : Else : *x\f=*row\X(5)+*row\W(5)+2 : EndIf
    *y\f=*row\Y+*row\H-3
    ProcedureReturn 1
  Else
    ProcedureReturn 0
  EndIf
  Select c%4
    Case 0 : *x\f=x0+2 : *y\f=y0+2
    Case 1 : *x\f=x0+w-2 : *y\f=y0+h-2
    Case 2 : *x\f=x0+w+2 : *y\f=y0+h-2
    Case 3 : *x\f=x0+w-2 : *y\f=y0+h+2
  EndSelect
  ProcedureReturn 1
EndProcedure
Procedure SynthStep()
  Protected x.f, y.f, hit.i, expect.i, what$, f.i
  If SynthTarget(SynthCase,@x,@y)=0
    SynthLog$+"pointer-test: "+Str(SynthCase)+" points, "+Str(SynthFails)+" failures, scale "+StrF(Neon_UIScale,2)+#LF$
    f=CreateFile(#PB_Any,SynthFile$) : If f : WriteString(f,SynthLog$) : CloseFile(f) : EndIf
    Quit=1 : ProcedureReturn
  EndIf
  SynthFrame+1
  Select SynthFrame
    Case 1 : SynthX=x : SynthY=y : SynthDown=0 : ActiveTab=0 : ViewCpuTestResult$="" : SynthBefore=Paused
    Case 2 : SynthDown=1
    Case 3 : SynthDown=0
    Case 4
      expect=Bool(SynthCase=0 Or SynthCase=1 Or SynthCase=4 Or SynthCase=5 Or SynthCase=8)
      If SynthCase<=3
        hit=Bool(Paused<>SynthBefore) : what$="Pause" : Paused=SynthBefore
      ElseIf SynthCase<=7
        hit=Bool(ViewCpuTestResult$<>"") : what$="Run tests"
      Else
        hit=Bool(ActiveTab=5) : what$="ROMs tab"
      EndIf
      ; the window keeps the pointer in whole pixels, as WindowMouseX/Y give it: read back within half a pixel
      If hit<>expect Or Abs(Neon_MX-x)>0.5 Or Abs(Neon_MY-y)>0.5 : SynthFails+1 : EndIf
      SynthLog$+what$+" at ("+StrF(x,1)+","+StrF(y,1)+"): clicked "+Str(hit)+", expected "+Str(expect)
      SynthLog$+", read back ("+StrF(Neon_MX,1)+","+StrF(Neon_MY,1)+")"+#LF$
      SynthCase+1 : SynthFrame=0
  EndSelect
EndProcedure


; ---------------------------------------------------------------- full screen
; A borderless window over the monitor the window is on (no display-mode change), by the engine
; (GL_FullscreenEnter / Leave): the windowed placement is kept and put back exactly on leaving. F11 or the Full
; screen button toggles it; Esc leaves it (the NES has no Esc of its own, so nothing the game uses is taken). In
; full screen only the picture is drawn, at the NES's own pixel aspect, centred, black around it; the pointer
; hides after two idle seconds.
Global FullScreen.i, FsMouseX.i, FsMouseY.i, FsMouseMs.q
Global FsGameX.f, FsGameY.f, FsGameW.f, FsGameH.f
Procedure FsShowCursor(show.i)
  GL_CursorShow(Win,Gl,show)
EndProcedure
Procedure EnterFullScreen()
  If FullScreen : ProcedureReturn : EndIf
  GL_FullscreenEnter(Win)
  FullScreen=1 : FsMouseMs=ElapsedMilliseconds()
  MeasureWindow()
EndProcedure
Procedure LeaveFullScreen()
  If FullScreen=0 : ProcedureReturn : EndIf
  GL_FullscreenLeave(Win)
  FullScreen=0 : FsShowCursor(1)
  MeasureWindow()
EndProcedure
; The picture's rectangle in full screen: the NES's pixel aspect (8:7 NTSC, about 1.386 PAL), a whole-number
; height scale when that loses less than a tenth of the screen's height, centred.
Procedure FsLayout()
  Protected par.f=8.0/7.0, sy.f, iy.i, w.f
  If MachinePal : par=1.3862 : EndIf
  w=256*par
  sy=PhysH/240.0 : If w*sy>PhysW : sy=PhysW/w : EndIf
  iy=Int(sy) : If iy>=1 And iy*240>=sy*240*0.9 : sy=iy : EndIf
  FsGameW=w*sy : FsGameH=240*sy
  FsGameX=(PhysW-FsGameW)/2 : FsGameY=(PhysH-FsGameH)/2
EndProcedure

; The window's actions, by the key table (controls.pbi): F5-F8, F11, Esc and M.
Procedure DoAction(action.i)
  Select action
    Case #CTL_RUNPAUSE : Paused=1-Paused : EmuLastUs=NesHostUs()
    Case #CTL_STEP : StepInstruction()
    Case #CTL_FRAME : StepFrame()
    Case #CTL_RESET : LoadRom(ViewCurrentRom$)
    Case #CTL_FULLSCREEN : If FullScreen : LeaveFullScreen() : Else : EnterFullScreen() : EndIf
    Case #CTL_LEAVEFULL : LeaveFullScreen()
    Case #CTL_MUTE : SoundMuted=1-SoundMuted
  EndSelect
EndProcedure

; A key pressed in the window: what the GL gadget's key-down event does, and what the tests press.
Procedure KeyPress(k.i)
  KeyCode=k : KeyHeld(Str(k))=1
  DoAction(CtlAction(k))
EndProcedure

; ---------------------------------------------------------------- --fullscreen-test
; Full screen by its own keys, without the real pointer: F11 and then Esc pressed through the window's key
; handler (KeyPress). Checked: the window covers its monitor, the picture has the NES's aspect and is centred,
; the window's own frame is saved, Esc leaves, and the windowed rectangle and canvas size come back exactly.
Global FsTestOn.i, FsTestFile$, FsTestStep.i, FsTestWait.i, FsTestFails.i, FsTestLog$, FsTestShot$
Global FsTestRect.GLHostRect, FsTestW.i, FsTestH.i
Procedure FsTestCheck(ok.i, what$)
  If ok=0 : FsTestFails+1 : FsTestLog$+"FAIL " : Else : FsTestLog$+"ok   " : EndIf
  FsTestLog$+what$+#LF$
EndProcedure
Procedure FsTestTick()
  Protected r.GLHostRect, m.GLHostRect, f.i, aspect.f, want.f
  FsTestWait+1 : If FsTestWait<30 : ProcedureReturn : EndIf
  FsTestWait=0 : FsTestStep+1
  Select FsTestStep
    Case 1
      GL_WindowRect(Win,@FsTestRect) : FsTestW=PhysW : FsTestH=PhysH
      FsTestLog$+"windowed: "+Str(FsTestRect\X)+","+Str(FsTestRect\Y)+" "+Str(FsTestRect\W)+"x"+Str(FsTestRect\H)+", canvas "+Str(PhysW)+"x"+Str(PhysH)+", scale "+StrF(Neon_UIScale,2)+#LF$
      KeyPress(#PB_Shortcut_F11) : KeyHeld(Str(#PB_Shortcut_F11))=0
    Case 2
      GL_WindowRect(Win,@r) : GL_FullscreenRect(@m)
      FsTestCheck(FullScreen,"F11 entered full screen")
      FsTestCheck(Bool(r\X=m\X And r\Y=m\Y And r\W=m\W And r\H=m\H),"the window covers its monitor "+Str(m\W)+"x"+Str(m\H)+" (window "+Str(r\X)+","+Str(r\Y)+" "+Str(r\W)+"x"+Str(r\H)+")")
      FsTestCheck(Bool(PhysW=m\W And PhysH=m\H),"the canvas is the whole monitor ("+Str(PhysW)+"x"+Str(PhysH)+")")
      want=256*(8.0/7.0)/240 : If MachinePal : want=256*1.3862/240 : EndIf
      aspect=FsGameW/FsGameH
      FsTestCheck(Bool(Abs(aspect-want)<0.002),"the picture "+StrF(FsGameW,1)+"x"+StrF(FsGameH,1)+" has the NES aspect "+StrF(want,4)+" ("+StrF(aspect,4)+")")
      FsTestCheck(Bool(Abs(FsGameX*2+FsGameW-PhysW)<=1 And Abs(FsGameY*2+FsGameH-PhysH)<=1),"the picture is centred at "+StrF(FsGameX,1)+","+StrF(FsGameY,1))
      If FsTestShot$<>"" : SaveWindowShot(FsTestShot$) : EndIf
      KeyPress(#PB_Shortcut_Escape) : KeyHeld(Str(#PB_Shortcut_Escape))=0
    Case 3
      GL_WindowRect(Win,@r)
      FsTestCheck(Bool(FullScreen=0),"Esc left full screen")
      FsTestCheck(Bool(r\X=FsTestRect\X And r\Y=FsTestRect\Y And r\W=FsTestRect\W And r\H=FsTestRect\H),"the windowed rectangle came back: "+Str(r\X)+","+Str(r\Y)+" "+Str(r\W)+"x"+Str(r\H))
      FsTestCheck(Bool(PhysW=FsTestW And PhysH=FsTestH),"the canvas size came back: "+Str(PhysW)+"x"+Str(PhysH))
      FsTestLog$+"fullscreen-test: "+Str(FsTestFails)+" failures"+#LF$
      f=CreateFile(#PB_Any,FsTestFile$) : If f : WriteString(f,FsTestLog$) : CloseFile(f) : EndIf
      Quit=1
  EndSelect
EndProcedure

; ---------------------------------------------------------------- one frame of the window
Procedure Tick()
  Protected now.q, dt.f, mx.i, my.i, down.b, s.f, toolH.f, x.f, gx.f, gy.f, gw.f, gh.f, scale.f, side.f
  Protected panelX.f, label$
  now=ElapsedMilliseconds() : dt=(now-LastDraw)/1000.0 : LastDraw=now
  If dt>0.25 : dt=0.25 : EndIf
  Emulate()
  If SoundOn : SoundPump() : EndIf
  If now-FpsSince>=1000
    FpsShown=FpsFrames*1000.0/(now-FpsSince) : FpsFrames=0
    IpsShown=(NesInstructions-IpsInstr)*1000/(now-FpsSince) : IpsInstr=NesInstructions
    FpsSince=now
  EndIf

  mx=WindowMouseX(Win) : my=WindowMouseY(Win) : down=MouseDown
  If SynthOn : mx=SynthX : my=SynthY : down=SynthDown : EndIf
  If mx<>FsMouseX Or my<>FsMouseY : FsMouseX=mx : FsMouseY=my : FsMouseMs=now : FsShowCursor(1) : EndIf
  If FullScreen And now-FsMouseMs>2000 : FsShowCursor(0) : EndIf
  Neon_ChromeBeginFrame(mx,my,down,Wheel,KeyCode,KeyChar,dt)
  Wheel=0 : KeyCode=0 : KeyChar=0

  SetGadgetAttribute(Gl,#PB_OpenGL_SetContext,#True)
  glBindFramebuffer(#GL_FRAMEBUFFER,0)
  glDisable_(#GL_SCISSOR_TEST)
  glViewport_(GL_ViewportX,GL_ViewportY,GL_ViewportW,GL_ViewportH)
  glClearColor_(Neon_C_BgR,Neon_C_BgG,Neon_C_BgB,1.0)
  glClear_(#GL_COLOR_BUFFER_BIT)
  glEnable_(#GL_BLEND) : glBlendFunc_(#GL_SRC_ALPHA,#GL_ONE_MINUS_SRC_ALPHA)

  If FullScreen
    ; only the picture, black around it
    glClearColor_(0,0,0,1.0) : glClear_(#GL_COLOR_BUFFER_BIT)
    FsLayout() : ViewUploadGame() : ViewDrawGameRect(FsGameX,FsGameY,FsGameW,FsGameH)
    Neon_ChromeEndFrame()
    If FsTestOn : FsTestTick() : EndIf
    SetGadgetAttribute(Gl,#PB_OpenGL_FlipBuffers,#True)
    ProcedureReturn
  EndIf

  s=Neon_UIScale : toolH=Round(40*s,#PB_Round_Nearest)
  ; toolbar
  Neon_Box(0,0,PhysW,toolH,Neon_C_HeadR,Neon_C_HeadG,Neon_C_HeadB)
  x=8*s
  If Neon_Button(x,6*s,96*s,toolH-12*s,"Open ROM...") : ViewOpenRomDialog() : EndIf : x+102*s
  label$="Pause" : If Paused : label$="Run" : EndIf
  If Neon_Button(x,6*s,72*s,toolH-12*s,label$+"  F5",Bool(Paused=0)) : Paused=1-Paused : EmuLastUs=NesHostUs() : EndIf : x+78*s
  If Neon_Button(x,6*s,80*s,toolH-12*s,"Step  F6") : StepInstruction() : EndIf : x+86*s
  If Neon_Button(x,6*s,88*s,toolH-12*s,"Frame  F7") : StepFrame() : EndIf : x+94*s
  If Neon_Button(x,6*s,82*s,toolH-12*s,"Reset  F8") : LoadRom(ViewCurrentRom$) : EndIf : x+88*s
  label$="Mute" : If SoundMuted : label$="Sound" : EndIf
  If Neon_Button(x,6*s,70*s,toolH-12*s,label$,SoundMuted) : SoundMuted=1-SoundMuted : EndIf : x+76*s
  label$=StringField("TV auto|NTSC|PAL",MachineTv+1,"|")
  If Neon_Button(x,6*s,76*s,toolH-12*s,label$,Bool(MachineTv<>0)) : MachineTv=(MachineTv+1)%3 : LoadRom(ViewCurrentRom$) : EndIf : x+82*s
  If Neon_Button(x,6*s,120*s,toolH-12*s,"Full screen  F11") : EnterFullScreen() : EndIf : x+126*s
  Neon_Text(*Neon_FontMono,x+8*s,toolH/2-8*s,StrD(FpsShown,1)+" fps   "+Str(IpsShown/1000)+"k instr/s   "+RomStatusLine$,Neon_C_DimR,Neon_C_DimG,Neon_C_DimB)

  ; the game, as large as fits beside the debug panel, square pixels, integer steps when it can
  side=Round(560*s,#PB_Round_Nearest)
  If side>PhysW*0.55 : side=PhysW*0.55 : EndIf
  gw=PhysW-side-24*s : gh=PhysH-toolH-24*s
  scale=gw/256.0 : If gh/240.0<scale : scale=gh/240.0 : EndIf
  If scale>=1.0 : scale=Int(scale) : EndIf
  gx=12*s+(gw-256*scale)/2 : gy=toolH+12*s+(gh-240*scale)/2
  ViewDrawGame(gx,gy,scale)
  If Stopped : Neon_Text(*Neon_FontBold,gx+8*s,gy+8*s,"CPU STOPPED: opcode $"+Hex(BadOpcode)+" at $"+Hex(PC),Neon_C_RedR,Neon_C_RedG,Neon_C_RedB) : EndIf

  ; the debug panel
  panelX=PhysW-side-6*s
  ActiveTab=Neon_TabStrip(1,panelX,toolH+6*s,side,30*s,"CPU|PPU|OAM|APU|Mapper|ROMs|Controls",ActiveTab)
  ViewDrawPanel(ActiveTab,panelX,toolH+40*s,side,PhysH-toolH-46*s)

  Neon_ChromeEndFrame()
  If ShotFile$<>"" And now>=ShotAtMs : SaveWindowShot(ShotFile$) : Quit=1 : EndIf
  If SynthOn And DisplayFrames>30 : SynthStep() : EndIf
  If FsTestOn And DisplayFrames>30 : FsTestTick() : EndIf
  SetGadgetAttribute(Gl,#PB_OpenGL_FlipBuffers,#True)
EndProcedure

; ---------------------------------------------------------------- main
Procedure Main()
  Protected ev.i, rom$, et.i, k.i, runTests.i
  GL_HostPrepare()    ; the engine's: before any window (Linux's X11 shield)
  Gl=OpenGLWindow("PureMetal NES",1280,800,#PB_Window_SystemMenu|#PB_Window_ScreenCentered|#PB_Window_SizeGadget|#PB_Window_MinimizeGadget|#PB_Window_MaximizeGadget)
  If Gl=0 : MessageRequester("PureMetal NES","OpenGL could not be started.") : End 1 : EndIf
  Win=Util_MainWindowID
  GL_HostScaleRead(Gl)
  ; The frame is drawn 1:1, not through DrawRetroCRT: the pointer must not be bent by the CRT curve
  ; (the engine's default is on; GlUIChrome.pbi 5a)
  UI_UseCRT=#False
  MeasureWindow()     ; and the fonts, at the window's scale
  GL_SetVSync(1)
  DisInit() : CtlInit()
  ViewInit()
  SoundBegin()
  For k=0 To CountProgramParameters()-1
    Select LCase(ProgramParameter(k))
      Case "--mute" : SoundMuted=1
      Case "--fullscreen-test" : k+1 : FsTestOn=1 : FsTestFile$=ProgramParameter(k)
      Case "--fullscreen-shot" : k+1 : FsTestShot$=ProgramParameter(k)
      Case "--pointer-test" : k+1 : SynthOn=1 : SynthFile$=ProgramParameter(k)
      Case "--cpu-tests" : runTests=1
      Case "--pal" : MachineTv=2
      Case "--ntsc" : MachineTv=1
      Case "--tab" : k+1 : ActiveTab=Val(ProgramParameter(k))
      Case "--shot" : k+1 : ShotFile$=ProgramParameter(k) : If ShotAtMs=0 : ShotAtMs=5000 : EndIf
      Case "--seconds" : k+1 : ShotAtMs=Val(ProgramParameter(k))*1000
      Default : rom$=ProgramParameter(k)
    EndSelect
  Next
  ViewCurrentRom$=rom$
  LoadRom(rom$)
  If runTests : ViewRunCpuTests() : EndIf
  If rom$="" : Paused=0 : EndIf
  FpsSince=ElapsedMilliseconds() : LastDraw=FpsSince
  If ShotFile$<>"" : ShotAtMs+FpsSince : EndIf
  Repeat
    Repeat
      ev=WindowEvent()
      Select ev
        Case #PB_Event_CloseWindow : Quit=1
        Case #PB_Event_SizeWindow, #PB_Event_MaximizeWindow, #PB_Event_RestoreWindow, #PB_Event_MoveWindow : MeasureWindow()
        Case #PB_Event_Menu
          If EventMenu()=1001 : KeyPress(#PB_Shortcut_Escape) : KeyHeld(Str(#PB_Shortcut_Escape))=0 : EndIf
        Case #PB_Event_Gadget
          If EventGadget()=Gl
            et=EventType()
            Select et
              Case #PB_EventType_KeyDown : KeyPress(GetGadgetAttribute(Gl,#PB_OpenGL_Key))
              Case #PB_EventType_KeyUp : KeyHeld(Str(GetGadgetAttribute(Gl,#PB_OpenGL_Key)))=0
              Case #PB_EventType_LeftButtonDown : MouseDown=1
              Case #PB_EventType_LeftButtonUp : MouseDown=0
              Case #PB_EventType_Input : KeyChar=GetGadgetAttribute(Gl,#PB_OpenGL_Input)
              Case #PB_EventType_MouseWheel : Wheel+GetGadgetAttribute(Gl,#PB_OpenGL_WheelDelta)
            EndSelect
          EndIf
        Case #PB_Event_WindowDrop
      EndSelect
    Until ev=0 Or Quit
    If Quit : Break : EndIf
    Tick()
  Until Quit
  SoundEnd()
EndProcedure
Main()

; IDE Options = PureBasic 6.41 (Windows - x64)
; CursorPosition = 16
; FirstLine = 14
; Folding = ----
; EnableXP
; DPIAware
; DisableDebugger
; Compiler = PureBasic 6.41 - C Backend (Windows - x64)