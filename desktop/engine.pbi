; The Neon Arcade Display Engine (https://github.com/ajtaji/Neon-Arcade-Dispay-Engine), which gives every
; program here everything the OS provides: the window, drawing, input, the clock, sound, full screen and the
; gamepads (its HOST SERVICES). Nothing in desktop/ calls the OS itself, so the same source builds on Windows
; and Linux. Found cloned beside this repository unless /CONSTANT GL_ENGINE_DIR$=<path>/ (Windows) or
; --constant GL_ENGINE_DIR$=<path>/ (Linux) says otherwise; the trailing slash matters.
CompilerIf Not Defined(GL_ENGINE_DIR$, #PB_Constant)
  #GL_ENGINE_DIR$ = #PB_Compiler_FilePath + "../../Neon-Arcade-Dispay-Engine/"
CompilerEndIf
XIncludeFile #GL_ENGINE_DIR$ + "GlTypes.pbi"
XIncludeFile #GL_ENGINE_DIR$ + "GlUtilities.pbi"
XIncludeFile #GL_ENGINE_DIR$ + "GlMath.pbi"
XIncludeFile #GL_ENGINE_DIR$ + "GlSpriteFunctions.pbi"
XIncludeFile #GL_ENGINE_DIR$ + "GlUI.pbi"
XIncludeFile #GL_ENGINE_DIR$ + "GlUIChrome.pbi"
