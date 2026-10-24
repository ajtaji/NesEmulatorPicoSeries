; PureMetal NES for the desktop: the same emulation as the boards (desktop/core, generated from Anvil's
; portable core by tools/port_desktop.py), drawn with the Neon Arcade Display Engine.
;
; Build (PowerShell, from the repository root):
;   & "C:\Program Files\PureBasic\Compilers\pbcompilerc.exe" desktop\nes_desktop.pb /EXE desktop\PureMetalNES.exe /THREAD /DPIAWARE /OPTIMIZER
;   (the engine is found at C:/Embedded Compiler/Neon-Arcade-Dispay-Engine/ unless
;    /CONSTANT GL_ENGINE_DIR$=<path>/ says otherwise; the trailing slash matters)
; Run:  desktop\PureMetalNES.exe [game.nes] [--mute] [--pal|--ntsc] [--cpu-tests] [--tab N] [--shot window.png --seconds S]
;       (--shot saves the window after S seconds, default 5, and closes: for checks without a person)
;
; Keys: arrows = D-pad, X = A, Z = B, Enter = Start, Shift, Tab or Space = Select. A gamepad works too.
;       Player 2: I/J/K/L = D-pad, H = A, G = B, Y = Start, T = Select, or the second gamepad.
;       F5 run/pause, F6 step one instruction, F7 step one frame, F8 reset, F11 full screen, M mute.
EnableExplicit

CompilerIf Not Defined(GL_ENGINE_DIR$, #PB_Constant)
  #GL_ENGINE_DIR$ = "C:/Embedded Compiler/Neon-Arcade-Dispay-Engine/"
CompilerEndIf
XIncludeFile #GL_ENGINE_DIR$ + "GlTypes.pbi"
XIncludeFile #GL_ENGINE_DIR$ + "GlUtilities.pbi"
XIncludeFile #GL_ENGINE_DIR$ + "GlMath.pbi"
XIncludeFile #GL_ENGINE_DIR$ + "GlSpriteFunctions.pbi"
XIncludeFile #GL_ENGINE_DIR$ + "GlUI.pbi"
XIncludeFile #GL_ENGINE_DIR$ + "GlUIChrome.pbi"

XIncludeFile "host.pbi"
XIncludeFile "core/core.pbi"
XIncludeFile "machine.pbi"
XIncludeFile "sound.pbi"
XIncludeFile "disasm.pbi"
XIncludeFile "cpu_tests.pbi"
XIncludeFile "view.pbi"

; ---------------------------------------------------------------- state
Global Win.i, Gl.i, PhysW.i, PhysH.i
Global Running.i, Quit.i, Paused.i=1
Global KeyCode.i, KeyChar.i, Wheel.i
Global Dim KeyHeld.i(256)
Global PadCount.i, PadMask.i
Global EmuAccum.d, EmuLastUs.q, EmuFrameUs.d=1000000.0/60.0988
Global FpsShown.d, FpsFrames.i, FpsSince.q, IpsShown.i, IpsInstr.i
Global ActiveTab.i, RomStatusLine$, LastRomFolder$
Global LastDraw.q
Global ShotFile$, ShotAtMs.q

; ---------------------------------------------------------------- fonts and size
Procedure BuildFonts()
  *Neon_FontUI    = Neon_CreateFontPx("Segoe UI", Round(14*UiScale,#PB_Round_Nearest))
  *Neon_FontSmall = Neon_CreateFontPx("Segoe UI", Round(12*UiScale,#PB_Round_Nearest))
  *Neon_FontBold  = Neon_CreateFontPx("Segoe UI", Round(15*UiScale,#PB_Round_Nearest), #PB_Font_Bold)
  *Neon_FontMono  = Neon_CreateFontPx("Consolas", Round(13*UiScale,#PB_Round_Nearest))
  GLFontSetSnapToPixel(*Neon_FontUI,#True) : GLFontSetSnapToPixel(*Neon_FontSmall,#True)
  GLFontSetSnapToPixel(*Neon_FontBold,#True) : GLFontSetSnapToPixel(*Neon_FontMono,#True)
EndProcedure

Procedure MeasureWindow()
  CompilerIf #PB_Compiler_OS=#PB_OS_Windows
    Protected client.RECT
    GetClientRect_(WindowID(Win),@client)
    PhysW=client\right-client\left : PhysH=client\bottom-client\top
  CompilerElse
    PhysW=WindowWidth(Win,#PB_Window_InnerCoordinate)*Linux_DPIScale
    PhysH=WindowHeight(Win,#PB_Window_InnerCoordinate)*Linux_DPIScale
  CompilerEndIf
  If PhysW<1 : PhysW=1 : EndIf
  If PhysH<1 : PhysH=1 : EndIf
  ResizeGadget(Gl,0,0,WindowWidth(Win,#PB_Window_InnerCoordinate),WindowHeight(Win,#PB_Window_InnerCoordinate))
  GL_ViewportX=0 : GL_ViewportY=0 : GL_ViewportW=PhysW : GL_ViewportH=PhysH
  Util_BaseWidth=PhysW : Util_BaseHeight=PhysH
  Util_WinWidth=WindowWidth(Win,#PB_Window_InnerCoordinate) : Util_WinHeight=WindowHeight(Win,#PB_Window_InnerCoordinate)
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

; One gamepad's buttons, NES bit order (A B Select Start Up Down Left Right).
Procedure.i ReadPad(pad.i)
  Protected m.i, ax.i, ay.i
  If PadCount>pad And ExamineJoystick(pad)
    ax=JoystickAxisX(pad) : ay=JoystickAxisY(pad)
    If ax<0 : m|64 : ElseIf ax>0 : m|128 : EndIf
    If ay<0 : m|16 : ElseIf ay>0 : m|32 : EndIf
    If JoystickButton(pad,1) : m|1 : EndIf
    If JoystickButton(pad,2) Or JoystickButton(pad,3) : m|2 : EndIf
    If JoystickButton(pad,7) : m|4 : EndIf
    If JoystickButton(pad,8) : m|8 : EndIf
  EndIf
  ProcedureReturn m
EndProcedure

; A real pad cannot press both opposite directions; several games misbehave if it does.
Procedure.i PadClean(m.i)
  If (m&48)=48 : m&~48 : EndIf
  If (m&192)=192 : m&~192 : EndIf
  ProcedureReturn m
EndProcedure

; The two controllers. Player 1: X = A, Z = B, Tab/Shift/Space = Select, Enter = Start, arrows, the first
; gamepad. Player 2: H = A, G = B, T = Select, Y = Start, I/J/K/L, the second gamepad.
Procedure ReadController()
  Protected m.i
  If KeyHeld(#PB_Shortcut_X) : m|1 : EndIf
  If KeyHeld(#PB_Shortcut_Z) : m|2 : EndIf
  If KeyHeld(#PB_Shortcut_Tab) Or KeyHeld(#PB_Shortcut_Shift) Or KeyHeld(#PB_Shortcut_Space) : m|4 : EndIf
  If KeyHeld(#PB_Shortcut_Return) : m|8 : EndIf
  If KeyHeld(#PB_Shortcut_Up) : m|16 : EndIf
  If KeyHeld(#PB_Shortcut_Down) : m|32 : EndIf
  If KeyHeld(#PB_Shortcut_Left) : m|64 : EndIf
  If KeyHeld(#PB_Shortcut_Right) : m|128 : EndIf
  NesController=PadClean(m|ReadPad(0))
  m=0
  If KeyHeld(#PB_Shortcut_H) : m|1 : EndIf
  If KeyHeld(#PB_Shortcut_G) : m|2 : EndIf
  If KeyHeld(#PB_Shortcut_T) : m|4 : EndIf
  If KeyHeld(#PB_Shortcut_Y) : m|8 : EndIf
  If KeyHeld(#PB_Shortcut_I) : m|16 : EndIf
  If KeyHeld(#PB_Shortcut_K) : m|32 : EndIf
  If KeyHeld(#PB_Shortcut_J) : m|64 : EndIf
  If KeyHeld(#PB_Shortcut_L) : m|128 : EndIf
  NesController2=PadClean(m|ReadPad(1))
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

  mx=WindowMouseX(Win) : my=WindowMouseY(Win)
  CompilerIf #PB_Compiler_OS=#PB_OS_Windows
    mx=mx*PhysW/Util_WinWidth : my=my*PhysH/Util_WinHeight
    If GetActiveWindow()=Win : down=Bool(GetAsyncKeyState_(#VK_LBUTTON)&$8000) : EndIf
  CompilerElse
    down=Bool(GetGadgetAttribute(Gl,#PB_OpenGL_Buttons)&#PB_OpenGL_LeftButton)
  CompilerEndIf
  Neon_ChromeBeginFrame(mx,my,down,Wheel,KeyCode,KeyChar,dt)
  Wheel=0 : KeyCode=0 : KeyChar=0

  SetGadgetAttribute(Gl,#PB_OpenGL_SetContext,#True)
  glBindFramebuffer(#GL_FRAMEBUFFER,0)
  glDisable_(#GL_SCISSOR_TEST)
  glViewport_(GL_ViewportX,GL_ViewportY,GL_ViewportW,GL_ViewportH)
  glClearColor_(Neon_C_BgR,Neon_C_BgG,Neon_C_BgB,1.0)
  glClear_(#GL_COLOR_BUFFER_BIT)
  glEnable_(#GL_BLEND) : glBlendFunc_(#GL_SRC_ALPHA,#GL_ONE_MINUS_SRC_ALPHA)

  s=UiScale : toolH=Round(40*s,#PB_Round_Nearest)
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
  ActiveTab=Neon_TabStrip(1,panelX,toolH+6*s,side,30*s,"CPU|PPU|OAM|APU|Mapper|ROMs",ActiveTab)
  ViewDrawPanel(ActiveTab,panelX,toolH+40*s,side,PhysH-toolH-46*s)

  Neon_ChromeEndFrame()
  If ShotFile$<>"" And now>=ShotAtMs : SaveWindowShot(ShotFile$) : Quit=1 : EndIf
  SetGadgetAttribute(Gl,#PB_OpenGL_FlipBuffers,#True)
EndProcedure

; ---------------------------------------------------------------- main
Procedure Main()
  Protected ev.i, rom$, et.i, k.i, runTests.i
  UiScale=DesktopResolutionX() : If UiScale<1 : UiScale=1 : EndIf
  Gl=OpenGLWindow("PureMetal NES",1280,800,#PB_Window_SystemMenu|#PB_Window_ScreenCentered|#PB_Window_SizeGadget|#PB_Window_MinimizeGadget|#PB_Window_MaximizeGadget)
  If Gl=0 : MessageRequester("PureMetal NES","OpenGL could not be started.") : End 1 : EndIf
  Win=Util_MainWindowID
  BuildFonts()
  MeasureWindow()
  GL_SetVSync(1)
  DisInit()
  ViewInit()
  SoundBegin()
  PadCount=InitJoystick()
  For k=0 To CountProgramParameters()-1
    Select LCase(ProgramParameter(k))
      Case "--mute" : SoundMuted=1
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
        Case #PB_Event_SizeWindow, #PB_Event_MaximizeWindow, #PB_Event_RestoreWindow : MeasureWindow()
        Case #PB_Event_Menu
          If EventMenu()=1001 : KeyCode=#PB_Shortcut_Escape : EndIf
        Case #PB_Event_Gadget
          If EventGadget()=Gl
            et=EventType()
            Select et
              Case #PB_EventType_KeyDown
                k=GetGadgetAttribute(Gl,#PB_OpenGL_Key) : KeyCode=k
                If k>=0 And k<256 : KeyHeld(k)=1 : EndIf
                Select k
                  Case #PB_Shortcut_F5 : Paused=1-Paused : EmuLastUs=NesHostUs()
                  Case #PB_Shortcut_F6 : StepInstruction()
                  Case #PB_Shortcut_F7 : StepFrame()
                  Case #PB_Shortcut_F8 : LoadRom(ViewCurrentRom$)
                  Case #PB_Shortcut_F11 : GL_ToggleFullscreen() : MeasureWindow()
                  Case #PB_Shortcut_M : SoundMuted=1-SoundMuted
                EndSelect
              Case #PB_EventType_KeyUp
                k=GetGadgetAttribute(Gl,#PB_OpenGL_Key)
                If k>=0 And k<256 : KeyHeld(k)=0 : EndIf
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
