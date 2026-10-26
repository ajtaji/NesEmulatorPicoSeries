; The controls: every key, gamepad button and shortcut the window answers to, in ONE table. ReadController and
; the shortcut handler (nes_desktop.pb) and the Controls pane (ViewControls, below) all read it, so what the
; pane shows is what the input code does. Include after the engine, before view.pbi.
EnableExplicit

; The window's own shortcuts (CtlKeys entries with player 0; bit = the action).
#CTL_RUNPAUSE = 1
#CTL_STEP = 2
#CTL_FRAME = 3
#CTL_RESET = 4
#CTL_FULLSCREEN = 5
#CTL_MUTE = 6
#CTL_LEAVEFULL = 7

Structure CtlBinding
  player.i      ; 1 or 2: an NES controller; 0: the window's own shortcut
  bit.i         ; NES button bit (A 1, B 2, Select 4, Start 8, Up 16, Down 32, Left 64, Right 128) or #CTL_ action
  key.i         ; the key code KeyHeld() is indexed by (#PB_Shortcut_*, the Windows virtual-key code)
  name$         ; the key as the pane shows it
EndStructure
Structure CtlPadBinding
  player.i      ; 1 or 2: gamepad 1 is player 1's, gamepad 2 player 2's
  bit.i         ; NES button bit
  button.i      ; JoystickButton number; 0 = the stick / d-pad (the directions)
EndStructure
Global NewList CtlKeys.CtlBinding()
Global NewList CtlPads.CtlPadBinding()
Global Dim CtlButtonName$(7)
Global Dim CtlActionName$(15)

Procedure CtlInit()
  Protected p.i, b.i, k.i, n$
  ClearList(CtlKeys()) : ClearList(CtlPads())
  Restore CtlButtonNames
  For b=0 To 7 : Read.s n$ : CtlButtonName$(b)=n$ : Next
  Restore CtlKeyTable
  Repeat
    Read.i p : If p<0 : Break : EndIf
    Read.i b : Read.i k : Read.s n$
    AddElement(CtlKeys()) : CtlKeys()\player=p : CtlKeys()\bit=b : CtlKeys()\key=k : CtlKeys()\name$=n$
  ForEver
  Restore CtlPadTable
  Repeat
    Read.i p : If p<0 : Break : EndIf
    Read.i b : Read.i k
    AddElement(CtlPads()) : CtlPads()\player=p : CtlPads()\bit=b : CtlPads()\button=k
  ForEver
  Restore CtlActionNames
  Repeat
    Read.i b : If b<0 : Break : EndIf
    Read.s n$ : CtlActionName$(b)=n$
  ForEver
EndProcedure

; The NES buttons a player's keys hold now (keyboard only; the gamepad is ReadPad's).
Procedure.i CtlKeysHeld(player.i, Array held.i(1))
  Protected m.i
  ForEach CtlKeys()
    If CtlKeys()\player=player And CtlKeys()\key>=0 And CtlKeys()\key<=ArraySize(held())
      If held(CtlKeys()\key) : m|CtlKeys()\bit : EndIf
    EndIf
  Next
  ProcedureReturn m
EndProcedure

; The window action a key starts (0: none).
Procedure.i CtlAction(key.i)
  ForEach CtlKeys()
    If CtlKeys()\player=0 And CtlKeys()\key=key : ProcedureReturn CtlKeys()\bit : EndIf
  Next
  ProcedureReturn 0
EndProcedure

; One cell of the pane: the keys (or gamepad buttons) a player has for a button.
Procedure.s CtlKeyNames(player.i, bit.i)
  Protected t$
  ForEach CtlKeys()
    If CtlKeys()\player=player And CtlKeys()\bit=bit
      If t$<>"" : t$+" / " : EndIf
      t$+CtlKeys()\name$
    EndIf
  Next
  ProcedureReturn t$
EndProcedure
Procedure.s CtlPadNames(player.i, bit.i)
  Protected t$
  ForEach CtlPads()
    If CtlPads()\player=player And CtlPads()\bit=bit
      If CtlPads()\button=0
        t$="stick"
      ElseIf t$=""
        t$="button "+Str(CtlPads()\button)
      Else
        t$+" / "+Str(CtlPads()\button)
      EndIf
    EndIf
  Next
  ProcedureReturn t$
EndProcedure

Procedure ViewControls(x.f, y.f, w.f, h.f)
  Protected s.f=Neon_UIScale, lh.f, b.i, c0.f, c1.f, c2.f, c3.f, c4.f
  lh=GLFontLineHeight(*Neon_FontMono)
  Neon_Panel(x,y,w,h,"Controls",Neon_C_AccR,Neon_C_AccG,Neon_C_AccB)
  y+34*s : x+12*s
  c0=x : c1=x+64*s : c2=x+196*s : c3=x+320*s : c4=x+420*s
  Neon_Text(*Neon_FontSmall,c1,y,"PLAYER 1 KEYS",Neon_C_AmbR,Neon_C_AmbG,Neon_C_AmbB)
  Neon_Text(*Neon_FontSmall,c2,y,"GAMEPAD 1",Neon_C_AmbR,Neon_C_AmbG,Neon_C_AmbB)
  Neon_Text(*Neon_FontSmall,c3,y,"PLAYER 2 KEYS",Neon_C_AmbR,Neon_C_AmbG,Neon_C_AmbB)
  Neon_Text(*Neon_FontSmall,c4,y,"GAMEPAD 2",Neon_C_AmbR,Neon_C_AmbG,Neon_C_AmbB)
  y+lh+4*s
  For b=0 To 7
    Neon_Text(*Neon_FontMono,c0,y,CtlButtonName$(b),Neon_C_TextR,Neon_C_TextG,Neon_C_TextB)
    Neon_Text(*Neon_FontMono,c1,y,CtlKeyNames(1,1<<b),Neon_C_TextR,Neon_C_TextG,Neon_C_TextB)
    Neon_Text(*Neon_FontMono,c2,y,CtlPadNames(1,1<<b),Neon_C_DimR,Neon_C_DimG,Neon_C_DimB)
    Neon_Text(*Neon_FontMono,c3,y,CtlKeyNames(2,1<<b),Neon_C_TextR,Neon_C_TextG,Neon_C_TextB)
    Neon_Text(*Neon_FontMono,c4,y,CtlPadNames(2,1<<b),Neon_C_DimR,Neon_C_DimG,Neon_C_DimB)
    y+lh
  Next
  y+12*s
  Neon_Text(*Neon_FontSmall,c0,y,"THE WINDOW",Neon_C_AmbR,Neon_C_AmbG,Neon_C_AmbB) : y+lh+4*s
  ForEach CtlKeys()
    If CtlKeys()\player=0
      Neon_Text(*Neon_FontMono,c0,y,CtlKeys()\name$,Neon_C_TextR,Neon_C_TextG,Neon_C_TextB)
      Neon_Text(*Neon_FontMono,c1,y,CtlActionName$(CtlKeys()\bit),Neon_C_DimR,Neon_C_DimG,Neon_C_DimB)
      y+lh
    EndIf
  Next
EndProcedure

DataSection
  CtlButtonNames:
  Data.s "A", "B", "Select", "Start", "Up", "Down", "Left", "Right"
  ; player, NES button bit, key code, the key's name. Player 0: the window's shortcuts (bit = #CTL_ action).
  CtlKeyTable:
  Data.i 1, 1, #PB_Shortcut_X : Data.s "X"
  Data.i 1, 2, #PB_Shortcut_Z : Data.s "Z"
  Data.i 1, 4, #PB_Shortcut_Tab : Data.s "Tab"
  Data.i 1, 4, $10 : Data.s "Shift"            ; VK_SHIFT: the Shift key alone (#PB_Shortcut_Shift is a modifier flag)
  Data.i 1, 4, #PB_Shortcut_Space : Data.s "Space"
  Data.i 1, 8, #PB_Shortcut_Return : Data.s "Enter"
  Data.i 1, 16, #PB_Shortcut_Up : Data.s "Up"
  Data.i 1, 32, #PB_Shortcut_Down : Data.s "Down"
  Data.i 1, 64, #PB_Shortcut_Left : Data.s "Left"
  Data.i 1, 128, #PB_Shortcut_Right : Data.s "Right"
  Data.i 2, 1, #PB_Shortcut_H : Data.s "H"
  Data.i 2, 2, #PB_Shortcut_G : Data.s "G"
  Data.i 2, 4, #PB_Shortcut_T : Data.s "T"
  Data.i 2, 8, #PB_Shortcut_Y : Data.s "Y"
  Data.i 2, 16, #PB_Shortcut_I : Data.s "I"
  Data.i 2, 32, #PB_Shortcut_K : Data.s "K"
  Data.i 2, 64, #PB_Shortcut_J : Data.s "J"
  Data.i 2, 128, #PB_Shortcut_L : Data.s "L"
  Data.i 0, #CTL_RUNPAUSE, #PB_Shortcut_F5 : Data.s "F5"
  Data.i 0, #CTL_STEP, #PB_Shortcut_F6 : Data.s "F6"
  Data.i 0, #CTL_FRAME, #PB_Shortcut_F7 : Data.s "F7"
  Data.i 0, #CTL_RESET, #PB_Shortcut_F8 : Data.s "F8"
  Data.i 0, #CTL_FULLSCREEN, #PB_Shortcut_F11 : Data.s "F11"
  Data.i 0, #CTL_LEAVEFULL, #PB_Shortcut_Escape : Data.s "Esc"
  Data.i 0, #CTL_MUTE, #PB_Shortcut_M : Data.s "M"
  Data.i -1
  ; player, NES button bit, gamepad button (0 = the stick or d-pad)
  CtlPadTable:
  Data.i 1, 1, 1, 1, 2, 2, 1, 2, 3, 1, 4, 7, 1, 8, 8
  Data.i 1, 16, 0, 1, 32, 0, 1, 64, 0, 1, 128, 0
  Data.i 2, 1, 1, 2, 2, 2, 2, 2, 3, 2, 4, 7, 2, 8, 8
  Data.i 2, 16, 0, 2, 32, 0, 2, 64, 0, 2, 128, 0
  Data.i -1
  CtlActionNames:
  Data.i #CTL_RUNPAUSE : Data.s "run / pause"
  Data.i #CTL_STEP : Data.s "step one instruction"
  Data.i #CTL_FRAME : Data.s "run one frame"
  Data.i #CTL_RESET : Data.s "reset"
  Data.i #CTL_FULLSCREEN : Data.s "full screen on / off (also the Full screen button)"
  Data.i #CTL_LEAVEFULL : Data.s "leave full screen (the NES has no Esc of its own)"
  Data.i #CTL_MUTE : Data.s "sound off / on"
  Data.i -1
EndDataSection
