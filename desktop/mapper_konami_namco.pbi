; Konami VRC6 (mappers 24 and 26) and Namco 163 (mapper 19), with their sound, for the desktop core: the
; two cartridges the Pico profile runs (rp2350/mapper_vrc6.pico2, rp2350/mapper_n163.pico2) that Anvil
; does not have. The same registers, IRQ counters, budgets and sound as the Pico's - the sound from the
; plain forms the boards check their assembly against (rp2350/Diagnostics/asm_reference.pico2w:
; V6TickReference, V6MixReference, N1TickReference, N1ChannelReference) - on Anvil's mapper framework:
; MapperPrg / MapperChr / MapperMirror for the banks, MapIrq for the IRQ line, ExtraManaged's hooks
; (tools/port_desktop.py patches them in) for the bus, the CPU-cycle ticks and the window budget.
; ExpChip and ExpSample are declared with the core (the APU's mix adds ExpSample, as on the Pico).
;   ExpChip 1 = VRC6: two pulses and a sawtooth. ExpChip 2 = N163: up to eight wavetable channels.
EnableExplicit

Global VrcPrg16.i, VrcPrg8.i, VrcIrqLatch.i, VrcIrqCounter.i, VrcIrqEnable.i, VrcIrqAfterAck.i
Global VrcIrqMode.i, VrcPrescaler.i, VrcWarned.i
Global Dim V6Period.i(3) : Global Dim V6Enable.i(3) : Global Dim V6Timer.i(3) : Global Dim V6Step.i(3)
Global Dim V6Duty.i(2) : Global Dim V6Volume.i(2) : Global Dim V6Mode.i(2)
Global V6Rate.i, V6Acc.i, V6Halt.i
Global Dim N1Prg.i(3) : Global Dim N1Ram.a(128) : Global Dim N1Sound.a(128) : Global Dim N1Output.i(8) : Global Dim N1NtBank.i(4)
Global N1Address.i, N1ChrRamOff.i, N1IrqCounter.i, N1IrqEnable.i, N1WarnedChr.i
Global N1Timer.i, N1Current.i, N1Mute.i
Global ExpPeak.i, ExpSounding.i     ; the largest |ExpSample| and the samples it was not 0 (nes_check, the APU pane)

Procedure.i KonamiNamcoMapper(mapper.i)
  ProcedureReturn Bool(mapper=19 Or mapper=24 Or mapper=26)
EndProcedure

; ---------------------------------------------------------------- VRC6
Procedure VrcIrqTicks(cycles.i)
  Protected clocks.i, room.i
  If VrcIrqEnable=0 : ProcedureReturn : EndIf
  If VrcIrqMode
    clocks=cycles
  Else
    ; scanline mode: the 341/3 prescaler, in thirds of a CPU cycle
    VrcPrescaler=VrcPrescaler-cycles*3 : clocks=0
    While VrcPrescaler<=0 : VrcPrescaler=VrcPrescaler+341 : clocks=clocks+1 : Wend
  EndIf
  While clocks>0
    room=255-VrcIrqCounter
    If clocks<=room
      VrcIrqCounter=VrcIrqCounter+clocks : clocks=0
    Else
      clocks=clocks-room-1 : VrcIrqCounter=VrcIrqLatch : MapIrq=1 : MapIrqAssertions=MapIrqAssertions+1
    EndIf
  Wend
EndProcedure

Procedure.i VrcIrqBudget()
  Protected clocks.i, cycles.i
  If VrcIrqEnable=0 : ProcedureReturn 128 : EndIf
  If MapIrq : ProcedureReturn 1 : EndIf
  clocks=256-VrcIrqCounter
  If VrcIrqMode
    cycles=clocks
  Else
    cycles=NesDiv(VrcPrescaler+(clocks-1)*341+2,3)
  EndIf
  If cycles>128 : cycles=128 : EndIf
  If cycles<1 : cycles=1 : EndIf
  ProcedureReturn cycles
EndProcedure

Procedure VrcSoundWrite(reg.i, value.i)
  Protected ch.i
  ch=(reg>>12)-9
  Select reg&3
    Case 0
      If ch<2
        V6Mode(ch)=value>>7 : V6Duty(ch)=(value>>4)&7 : V6Volume(ch)=value&15
      Else
        V6Rate=value&63
      EndIf
    Case 1
      V6Period(ch)=(V6Period(ch)&$F00)|value
    Case 2
      V6Period(ch)=(V6Period(ch)&$FF)|((value&15)<<8)
      V6Enable(ch)=value>>7
      If V6Enable(ch)=0
        V6Step(ch)=0
        If ch=2 : V6Acc=0 : EndIf
      EndIf
    Case 3
      If ch=0 : V6Halt=value&1 : EndIf
  EndSelect
EndProcedure

Procedure VrcWrite(addr.i, value.i)
  Protected reg.i
  If addr<$8000
    If addr>=$6000 And MapRamEnable : MapRam(addr&8191)=value : EndIf
    ProcedureReturn
  EndIf
  If CartMapper=26 : addr=(addr&$FFFC)|((addr&1)<<1)|((addr>>1)&1) : EndIf
  reg=addr&$F003
  If reg>=$9000 And reg<=$B002 : VrcSoundWrite(reg,value) : ProcedureReturn : EndIf
  Select reg&$F000
    Case $8000 : VrcPrg16=value&15 : MapperUpdate()
    Case $C000 : VrcPrg8=value&31 : MapperUpdate()
    Case $B000
      If reg=$B003
        Select (value>>2)&3
          Case 0 : MapperMirror(1)
          Case 1 : MapperMirror(0)
          Case 2 : MapperMirror(2)
          Case 3 : MapperMirror(3)
        EndSelect
        MapRamEnable=Bool((value&128)<>0)
        If (value&$13)<>0 And VrcWarned=0
          VrcWarned=1 : Say("VRC6: this game uses a nametable mode that is not supported ($B003=") : Num(value) : Say(")") : Eol()
        EndIf
      EndIf
    Case $D000 : MapRegs(reg&3)=value : MapperUpdate()
    Case $E000 : MapRegs(4+(reg&3))=value : MapperUpdate()
    Case $F000
      Select reg
        Case $F000 : VrcIrqLatch=value
        Case $F001
          VrcIrqAfterAck=value&1 : VrcIrqEnable=Bool((value&2)<>0) : VrcIrqMode=Bool((value&4)<>0)
          If VrcIrqEnable : VrcIrqCounter=VrcIrqLatch : VrcPrescaler=341 : EndIf
          MapIrq=0
        Case $F002
          MapIrq=0 : VrcIrqEnable=VrcIrqAfterAck
      EndSelect
  EndSelect
EndProcedure

; The three channels over dt CPU cycles (V6TickReference).
Procedure VrcSoundTick(dt.i)
  Protected ch.i, t.i, s.i
  If V6Halt : ProcedureReturn : EndIf
  For ch=0 To 1
    If V6Enable(ch)
      t=V6Timer(ch)-dt
      If t<=0
        s=V6Step(ch)
        While t<=0 : t=t+V6Period(ch)+1 : s=(s+1)&15 : Wend
        V6Step(ch)=s
      EndIf
      V6Timer(ch)=t
    EndIf
  Next
  If V6Enable(2)
    t=V6Timer(2)-dt
    While t<=0
      t=t+V6Period(2)+1
      V6Step(2)=V6Step(2)+1
      If V6Step(2)=14
        V6Step(2)=0 : V6Acc=0
      ElseIf V6Step(2)&1
        V6Acc=(V6Acc+V6Rate)&255
      EndIf
    Wend
    V6Timer(2)=t
  EndIf
EndProcedure

; Each step of a VRC6 channel is 256 in the 2A03 mix's units (V6MixReference).
Procedure VrcSoundMix()
  Protected ch.i, sum.i
  For ch=0 To 1
    If V6Enable(ch)
      If V6Mode(ch) Or 15-V6Step(ch)<=V6Duty(ch) : sum=sum+V6Volume(ch) : EndIf
    EndIf
  Next
  If V6Enable(2) : sum=sum+(V6Acc>>3) : EndIf
  ExpSample=sum<<8
EndProcedure

; ---------------------------------------------------------------- Namco 163
Procedure N1Ticks(cycles.i)
  If N1IrqEnable=0 Or N1IrqCounter>=$7FFF : ProcedureReturn : EndIf
  N1IrqCounter=N1IrqCounter+cycles
  If N1IrqCounter>=$7FFF
    N1IrqCounter=$7FFF : MapIrq=1 : MapIrqAssertions=MapIrqAssertions+1
  EndIf
EndProcedure

Procedure.i N1Budget()
  Protected cycles.i
  If N1IrqEnable=0 Or N1IrqCounter>=$7FFF : ProcedureReturn 128 : EndIf
  If MapIrq : ProcedureReturn 1 : EndIf
  cycles=$7FFF-N1IrqCounter
  If cycles>128 : cycles=128 : EndIf
  If cycles<1 : cycles=1 : EndIf
  ProcedureReturn cycles
EndProcedure

; A table from CIRAM ($E0 and up: page value&1) or a read-only 1 KiB CHR-ROM bank. PpuWrite writes a
; table whose MapNtSlots names its CIRAM page; a ROM table's slot (2+table) matches no page.
Procedure N1Nametable(table.i, value.i)
  Protected i.i, physical.i
  If value>=$E0
    physical=value&1 : N1NtBank(table)=-1
    MapNtSlots(table)=physical
    For i=0 To 1023 : Nt(table*1024+i)=MapCiram(physical*1024+i) : Next
  Else
    N1NtBank(table)=value : MapNtSlots(table)=2+table
    CopyMemory(CartChr+((value*1024)&(MapChrBytes-1)),@Nt(table*1024),1024)
  EndIf
  MapMirrorMode=-1 : BgCacheAddr=-1 : RgbLastKey=-1
EndProcedure

Procedure N1SoundRamWrite(value.i)
  Protected address.i
  address=N1Address&127
  N1Ram(address)=value : N1Sound(address)=value
  If N1Address&128 : N1Address=128|((address+1)&127) : EndIf
EndProcedure

Procedure.i N1Read(addr.i)
  Protected value.i, address.i
  Select addr&$F800
    Case $4800
      address=N1Address&127 : value=N1Ram(address)
      If N1Address&128 : N1Address=128|((address+1)&127) : EndIf
      ProcedureReturn value
    Case $5000 : ProcedureReturn N1IrqCounter&255
    Case $5800 : ProcedureReturn ((N1IrqCounter>>8)&127)|(N1IrqEnable<<7)
  EndSelect
  ProcedureReturn NesOpenBus
EndProcedure

Procedure N1Write(addr.i, value.i)
  If addr<$8000
    If addr>=$6000
      MapRam(addr&8191)=value
    ElseIf (addr&$F800)=$4800
      N1SoundRamWrite(value)
    ElseIf (addr&$F800)=$5000
      N1IrqCounter=(N1IrqCounter&$7F00)|value : MapIrq=0
    ElseIf (addr&$F800)=$5800
      N1IrqCounter=(N1IrqCounter&255)|((value&127)<<8) : N1IrqEnable=value>>7 : MapIrq=0
    EndIf
    ProcedureReturn
  EndIf
  If addr<$C000
    If value>=$E0 And N1WarnedChr=0 And (N1ChrRamOff>>(((addr>>14)&1)+6)&1)=0
      N1WarnedChr=1 : Say("N163: this game maps CHR-RAM patterns, which are not drawn yet") : Eol()
    EndIf
    MapRegs((addr>>11)&7)=value : MapperUpdate()
  ElseIf addr<$E000
    N1Nametable((addr>>11)&3,value)
  Else
    Select addr&$F800
      Case $E000 : N1Prg(0)=value&63 : N1Mute=(value>>6)&1 : MapperUpdate()
      Case $E800 : N1Prg(1)=value&63 : N1ChrRamOff=value&$C0 : MapperUpdate()
      Case $F000 : N1Prg(2)=value&63 : MapperUpdate()
      Case $F800 : N1Address=value
    EndSelect
  EndIf
EndProcedure

; One channel (N1ChannelReference): phase on by its frequency, its sample out as (nibble - 8) * volume.
Procedure N1Channel(base.i)
  Protected freq.i, phase.i, length.i, sample.i, position.i
  freq=N1Sound(base)|(N1Sound(base+2)<<8)|((N1Sound(base+4)&3)<<16)
  phase=N1Sound(base+1)|(N1Sound(base+3)<<8)|(N1Sound(base+5)<<16)
  length=(256-(N1Sound(base+4)&$FC))<<16
  phase=(phase+freq)%length
  N1Sound(base+1)=phase&255 : N1Sound(base+3)=(phase>>8)&255 : N1Sound(base+5)=(phase>>16)&255
  position=((phase>>16)+N1Sound(base+6))&255
  sample=(N1Sound(position>>1)>>((position&1)*4))&15
  N1Output(((base-$40)>>3)&7)=(sample-8)*(N1Sound(base+7)&15)
EndProcedure

; Every 15 CPU cycles the next enabled channel, round-robin (N1TickReference).
Procedure N1SoundTick(dt.i)
  Protected count.i
  If N1Mute : ProcedureReturn : EndIf
  N1Timer=N1Timer-dt
  While N1Timer<=0
    N1Timer=N1Timer+15
    count=((N1Sound($7F)>>4)&7)+1
    N1Current=N1Current+1 : If N1Current>=count : N1Current=0 : EndIf
    N1Channel($78-N1Current*8)
  Wend
EndProcedure

; The enabled channels averaged; one at full swing (+-120) is about a full 2A03 pulse.
Procedure N1SoundMix()
  Protected count.i, sum.i, i.i
  If N1Mute : ExpSample=0 : ProcedureReturn : EndIf
  count=((N1Sound($7F)>>4)&7)+1
  For i=0 To count-1 : sum=sum+N1Output(7-i) : Next
  ExpSample=(sum*20)/count
EndProcedure

; ---------------------------------------------------------------- the hooks (tools/port_desktop.py)
Procedure KonamiNamcoInit()
  Protected i.i
  ExpChip=0 : ExpSample=0 : ExpPeak=0 : ExpSounding=0
  For i=0 To 7 : MapRegs(i)=i : Next
  If CartMapper=19
    N1Prg(0)=0 : N1Prg(1)=1 : N1Prg(2)=2 : N1Address=0 : N1ChrRamOff=0
    N1IrqCounter=0 : N1IrqEnable=0 : N1WarnedChr=0
    For i=0 To 3 : N1NtBank(i)=-1 : Next
    For i=0 To 127 : N1Ram(i)=0 : N1Sound(i)=0 : Next
    For i=0 To 7 : N1Output(i)=0 : Next
    N1Timer=15 : N1Current=0 : N1Mute=0
    MapRamEnable=1
    ExpChip=2
  Else
    VrcPrg16=0 : VrcPrg8=0 : VrcWarned=0
    VrcIrqLatch=0 : VrcIrqCounter=0 : VrcIrqEnable=0 : VrcIrqAfterAck=0 : VrcIrqMode=0 : VrcPrescaler=341
    For i=0 To 2 : V6Period(i)=0 : V6Enable(i)=0 : V6Timer(i)=1 : V6Step(i)=0 : Next
    For i=0 To 1 : V6Duty(i)=0 : V6Volume(i)=0 : V6Mode(i)=0 : Next
    V6Rate=0 : V6Acc=0 : V6Halt=0
    MapRamEnable=0
    ExpChip=1
  EndIf
  MapIrq=0
EndProcedure

Procedure KonamiNamcoUpdate()
  Protected i.i
  If CartMapper=19
    MapperPrg(0,N1Prg(0)) : MapperPrg(1,N1Prg(1)) : MapperPrg(2,N1Prg(2))
  Else
    MapperPrg(0,VrcPrg16*2) : MapperPrg(1,VrcPrg16*2+1) : MapperPrg(2,VrcPrg8)
  EndIf
  MapperPrg(3,MapPrgBytes/8192-1)
  For i=0 To 7 : MapperChr(i,MapRegs(i)) : Next
EndProcedure

Procedure KonamiNamcoWrite(addr.i, value.i)
  If CartMapper=19 : N1Write(addr,value) : Else : VrcWrite(addr,value) : EndIf
EndProcedure

Procedure.i KonamiNamcoLowRead(addr.i, openbus.i)
  If CartMapper=19 And addr>=$4800 And addr<$6000 : ProcedureReturn N1Read(addr) : EndIf
  If addr>=$6000 And addr<$8000 And MapRamEnable : ProcedureReturn MapRam(addr&8191) : EndIf
  ProcedureReturn openbus
EndProcedure

Procedure KonamiNamcoCpuTicks(cycles.i)
  If CartMapper=19 : N1Ticks(cycles) : Else : VrcIrqTicks(cycles) : EndIf
EndProcedure

Procedure.i KonamiNamcoBudget()
  If CartMapper=19 : ProcedureReturn N1Budget() : EndIf
  ProcedureReturn VrcIrqBudget()
EndProcedure

Procedure ExpTick(dt.i)
  If ExpChip=1 : VrcSoundTick(dt) : ElseIf ExpChip=2 : N1SoundTick(dt) : EndIf
EndProcedure

Procedure ExpMix()
  If ExpChip=1 : VrcSoundMix() : ElseIf ExpChip=2 : N1SoundMix() : EndIf
  If ExpSample<>0
    ExpSounding=ExpSounding+1
    If ExpSample>ExpPeak : ExpPeak=ExpSample : ElseIf -ExpSample>ExpPeak : ExpPeak=-ExpSample : EndIf
  EndIf
EndProcedure
