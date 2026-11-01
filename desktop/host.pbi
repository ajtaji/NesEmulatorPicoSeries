; The desktop host: what Anvil's monitor services (anvil/services.pi4) give the core on the Pi, here for
; Windows and Linux alike: the OS only through the engine's HOST SERVICES. Include this before core/core.pbi.
EnableExplicit
XIncludeFile "engine.pbi"

#CPU_TIMING=1          ; page-cross and branch cycles counted (as on every board)
#NES_SPLIT=0           ; one thread: a bus post runs the worker at once (bridge.pi4)
#PPU_PROFILE=0
#CART_CHR_BANKS=64     ; the CHR window the board builds size; desktop memory is not the limit

Global HostTimerStart.q
Global EmulateUs.i, EmulateCalls.i      ; Anvil's runtime counters, which GuestReset clears
; Anvil's mapper work areas sit at fixed addresses on the Pi ($03500000 up: the PRG, CHR and pattern
; windows, MMC5's sprite patterns, the extra boards' CHR RAM). tools/port_desktop.py turns each into
; an offset into this block.
Global AnvilWindow.i=AllocateMemory($30000)
; Anvil's test suites (core/tests/) build synthetic cartridges at fixed Pi addresses ($03200000 PRG,
; $03300000 CHR): here two blocks; and the audio session flag the mapper tests check survives a reset.
Global AnvilTestPrg.i=AllocateMemory($100000), AnvilTestChr.i=AllocateMemory($100000)
Global AudioSessionStarted.i

; Microseconds since the first call (the boards' Micros()).
Procedure.i NesHostUs()
  If HostTimerStart=0 : HostTimerStart=GL_Micros() : EndIf
  ProcedureReturn GL_Micros()-HostTimerStart
EndProcedure

Procedure SafetyPet()
EndProcedure
Procedure UsbSerialTask()
EndProcedure

; The cores share nothing here: one thread runs CPU, PPU and APU in turn.
Procedure FrameFence()
EndProcedure

; Nonnegative timing/count division (the boards use a divider or a library routine).
Procedure.i NesDiv(a.i,b.i)
  ProcedureReturn a/b
EndProcedure

; The boards' serial log, here the console when there is one, else nothing.
Global HostLog$
Procedure Say(t.s)
  HostLog$+t
EndProcedure
Procedure Num(v.i)
  HostLog$+Str(v)
EndProcedure
Procedure Eol()
  CompilerIf #PB_Compiler_ExecutableFormat=#PB_Compiler_Console
    PrintN(HostLog$)
  CompilerEndIf
  HostLog$=""
EndProcedure
