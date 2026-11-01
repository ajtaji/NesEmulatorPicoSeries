; Sound on the PC: the APU's 48 kHz mono PCM (Anvil's AudioRead takes it from the ring) to the sound card,
; through the engine (GL_AudioOpen / Next / Play: waveOut on Windows, ALSA on Linux), four 1024-sample
; buffers (~85 ms queued at most). The engine plays 16-bit stereo: each sample goes to both sides.
EnableExplicit

#SOUND_BUFFERS=4
#SOUND_SAMPLES=1024
#SOUND_RATE=48000

Global SoundOn.i, SoundMuted.i, SoundUnderruns.i, SoundQueued.i, SoundLast.w
Global Dim SoundMono.w(#SOUND_SAMPLES)

Procedure.i SoundBegin()
  If GL_AudioOpen(#SOUND_RATE,#SOUND_SAMPLES,#SOUND_BUFFERS)=0 : ProcedureReturn 0 : EndIf
  SoundOn=1 : AudioReset()
  ProcedureReturn 1
EndProcedure

; Hand the card every buffer it has room for while the APU's ring holds one. Returns the samples it still has queued.
Procedure.i SoundPump()
  Protected *dst, n.i, k.i, v.w
  If SoundOn=0 : AudioReset() : ProcedureReturn 0 : EndIf
  While ApuSamples-AudioReadCursor>=#SOUND_SAMPLES
    *dst=GL_AudioNext()
    If *dst=0 : Break : EndIf
    n=AudioRead(@SoundMono(0),#SOUND_SAMPLES)
    If n<#SOUND_SAMPLES
      SoundUnderruns+1
      For k=n To #SOUND_SAMPLES-1 : SoundMono(k)=SoundLast : Next
    EndIf
    SoundLast=SoundMono(#SOUND_SAMPLES-1)
    For k=0 To #SOUND_SAMPLES-1
      v=SoundMono(k) : If SoundMuted : v=0 : EndIf
      PokeW(*dst+k*4,v) : PokeW(*dst+k*4+2,v)
    Next
    GL_AudioPlay(*dst)
  Wend
  SoundQueued=GL_AudioQueued()                     ; (one sample a pair)
  ProcedureReturn SoundQueued
EndProcedure

Procedure SoundEnd()
  GL_AudioClose()
  SoundOn=0
EndProcedure
