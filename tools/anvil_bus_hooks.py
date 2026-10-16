"""Cartridge adapters applied after generating the unchanged portable core.

The hand-maintained PPU bus modules implement CIRAM and mapper observation;
the generated renderer and CPU opcode routines are not rewritten here.
"""
import re

def adapt_generated_core(out):
    p=out/'bridge.pi4';s=p.read_text()
    s=s.replace('    v=NesOpenBus\n  ElseIf addr=$4016',
      '    v=NesOpenBus\n    If (CartMapper=1 Or CartMapper=4) And MapRamEnable<>0 : v=MapRam(addr&8191) : EndIf\n  ElseIf addr=$4016',1)
    s=s.replace('    If addr>=$8000 And (CartMapper=66 Or CartMapper=2)',
      '    If CartMapper=1 Or CartMapper=4\n      CpuNow() : NesRpc(0,0,0,CpuCycles+AccessPhase)\n      MapperWrite(addr,value,CpuCycles+AccessPhase) : CpuEndWindow()\n    ElseIf addr>=$8000 And (CartMapper=66 Or CartMapper=2)',1)
    s=s.replace('    ProcedureReturn 0\n  EndIf\n  ProcedureReturn 0\nEndProcedure\n; The same',
      '    If (CartMapper=1 Or CartMapper=4) And MapRamEnable<>0 : ProcedureReturn MapRam(addr&8191) : EndIf\n    ProcedureReturn 0\n  EndIf\n  ProcedureReturn 0\nEndProcedure\n; The same',1)
    s=s.replace('Procedure.i NesDmaRead(addr.i)\n  addr=addr&$FFFF',
      'Procedure.i NesDmaRead(addr.i)\n  addr=addr&$FFFF\n  If addr>=$6000 And addr<$8000 And (CartMapper=1 Or CartMapper=4) And MapRamEnable<>0 : ProcedureReturn MapRam(addr&8191) : EndIf',1)
    p.write_text(s)
    p=out/'ppu.pi4';s=p.read_text()
    a=s.index('Procedure.i PpuNtAddr');b=s.index('Procedure PpuColours',a)
    s=s[:a]+'XIncludeFile "ppu_bus_read.pi4"\n'+s[b:]
    a=s.index('Procedure PpuWrite');b=s.index('; Packed tile fetch',a)
    s=s[:a]+'XIncludeFile "ppu_bus_write.pi4"\n'+s[b:]
    s=s.replace('  PpuAdvanceReference(cycles)\nEndProcedure',
      '  If CartMapper=4 : MapperPpuTicks(cycles) : EndIf\n  PpuAdvanceReference(cycles)\nEndProcedure')
    p.write_text(s)
    p=out/'worker.pi4';s=p.read_text()
    s=s.replace('    ProcedureReturn PpuRegRead(addr&7)',
      '    i=PpuRegRead(addr&7) : MapperRegNotice(addr&7) : ProcedureReturn i',1)
    s=s.replace('    PpuRegWrite(addr&7,value)','    PpuRegWrite(addr&7,value) : MapperRegNotice(addr&7)')
    s=s.replace('      QResult=PpuRegRead(addr&7)',
      '      QResult=PpuRegRead(addr&7) : MapperRegNotice(addr&7)')
    p.write_text(s)
    extend_mappers(out)

def generate_guest_reset(out):
    # BSS symbols are unordered. Reset named guest declarations, never a broad
    # address range that could include a live host device or service pointer.
    sizes={'a':1,'u':2,'w':2,'l':4,'i':8,'q':8,'Label':8}
    lines=[];seen=set()
    for name in ('cpu2a03','bridge','ppu','apu','worker'):
        source=(out/(name+'.pi4')).read_text()
        source=re.sub(r'CompilerIf #PPU_PROFILE=2.*?CompilerEndIf','',source,flags=re.S)
        for line in source.splitlines():
            if line.startswith('Global Dim '):
                m=re.fullmatch(r'Global Dim (\w+)\.(\w+)\(([^)]+)\)',line)
                if m:
                    var,ty,count=m.groups()
                    if var not in seen:lines.append(f'  GuestClear(@{var}(0),({count})*{sizes[ty]})');seen.add(var)
            elif line.startswith('Global '):
                for field in line[7:].split(','):
                    m=re.fullmatch(r'\s*(\w+)\.\w+(?:\s*=\s*(.+))?\s*',field)
                    if m:
                        var,val=m.groups()
                        if var not in seen:lines.append(f'  {var}={val or "0"}');seen.add(var)
    source='''; Generated from the guest state declarations. Host devices and selector
; state are deliberately outside this reset. Worker is joined before entry.
Procedure GuestClear(p.i,n.i)
  Protected i.i
  For i=0 To n-1 : PokeA(p+i,0) : Next
EndProcedure
Procedure GuestReset()
'''+ '\n'.join(lines)+'''
  GuestClear(@FrameBottomStore(0),61440)
  GuestClear(@AlternateTop(0),61440) : GuestClear(@AlternateBottom(0),61440)
  FramePending=0 : FrameConsumed=0 : PublishTop=0 : PublishBottom=0
  RenderTop=0 : MenuRequested=0 : InputSeen=0 : EmulateUs=0 : EmulateCalls=0
  VideoFrames=0 : VideoUs=0
  MapManaged=0
  MapIrq=0 : MapDots=0 : MapIrqClocks=0 : MapIrqAssertions=0
  AudioReadCursor=0
EndProcedure
'''
    (out/'guest_reset.pi4').write_text(source)


def extend_mappers(out):
    p=out/'bridge.pi4';s=p.read_text()
    s=s.replace('    v=PeekA(PrgBase+addr-$8000)',      '    v=PeekA(PrgBase+addr-$8000)\n    If CartMapper=5\n      v=M5PrgRead(addr)\n      If addr=$FFFA Or addr=$FFFB : M5ScanReset() : EndIf\n      If addr<$C000 And M5PcmMode<>0\n        CpuNow() : NesRpc(0,0,0,CpuCycles) : M5PcmRead(v) : CpuEndWindow()\n      EndIf\n    EndIf',1)
    s=s.replace('  ElseIf addr=$4016\n',      '    If CartMapper=5 : v=M5PrgRead(addr) : EndIf\n  ElseIf addr>=$5000 And CartMapper=5\n    CpuNow() : NesRpc(0,0,0,CpuCycles+AccessPhase)\n    v=M5Read(addr) : CpuEndWindow()\n  ElseIf addr=$4016\n',1)
    s=s.replace('    If CartMapper=1 Or CartMapper=4\n      CpuNow()', '    If MapManaged\n      CpuNow()',1)
    s=s.replace('  ElseIf addr=$4016\n    NesStrobe=',      '  ElseIf addr>=$5000 And CartMapper=5\n    CpuNow() : NesRpc(0,0,0,CpuCycles+AccessPhase)\n    M5Write(addr,value) : CpuEndWindow()\n  ElseIf addr=$4016\n    NesStrobe=',1)
    s=s.replace('      ProcedureReturn PeekA(WorkerPrgBase+addr-$8000)',      '      If CartMapper=5\n        v=M5PrgRead(addr)\n        If addr<$C000 And M5PcmMode<>0 : M5PcmRead(v) : EndIf\n        ProcedureReturn v\n      EndIf\n      ProcedureReturn PeekA(WorkerPrgBase+addr-$8000)',1)
    s=s.replace('Procedure.i WorkerRead(addr.i)\n', 'Procedure.i WorkerRead(addr.i)\n  Protected v.i\n',1)
    s=s.replace('    If (CartMapper=1 Or CartMapper=4) And MapRamEnable<>0 : ProcedureReturn MapRam(addr&8191) : EndIf',      '    If CartMapper=5 : ProcedureReturn M5PrgRead(addr) : EndIf\n    If (CartMapper=1 Or CartMapper=4) And MapRamEnable<>0 : ProcedureReturn MapRam(addr&8191) : EndIf',1)
    s=s.replace('Procedure.i NesDmaRead(addr.i)\n  addr=addr&$FFFF',      'Procedure.i NesDmaRead(addr.i)\n  addr=addr&$FFFF\n  If CartMapper=5 And addr>=$6000 : ProcedureReturn M5PrgRead(addr) : EndIf',1)
    p.write_text(s)
    p=out/'bridge.pi4';s=p.read_text().replace('  ElseIf addr>=$5000 And CartMapper=5\n    CpuNow()', '  ElseIf addr>=$5C00 And addr<$6000 And CartMapper=5\n    v=M5Read(addr)\n  ElseIf addr>=$5000 And CartMapper=5\n    CpuNow()',1);p.write_text(s)
    p=out/'ppu.pi4';s=p.read_text().replace('Procedure PpuFetchTile()','Procedure PpuFetchTileBase()',1).replace('Procedure PpuSpritesRaw()','Procedure PpuSpritesBase()',1)
    s=s.replace('  If CartMapper=4 : MapperPpuTicks(cycles) : EndIf',      '  If CartMapper=4 : MapperPpuTicks(cycles) : EndIf\n  If CartMapper=5 : M5PpuTicks(cycles) : EndIf',1)
    p.write_text(s)
    p=out/'apu.pi4';s=p.read_text().replace('Procedure ApuMixSample()','Procedure ApuMixSampleBase()',1)
    s=s.replace('    ApuTick(step)', '    If CartMapper=5 : M5AudioAdvance(step) : EndIf\n    ApuTick(step)',1)
    p.write_text(s)
    p=out/'worker.pi4';s=p.read_text().replace('PpuRegWrite(addr&7,value) : MapperRegNotice(addr&7)',      'PpuRegWrite(addr&7,value) : MapperRegNotice(addr&7)\n    If CartMapper=5 : M5PpuNotice(addr,value) : EndIf')
    s=s.replace('  ElseIf command=3\n    OamCacheDirty=1',      '  ElseIf command=3\n    If CartMapper=5 : M5ScanReset() : EndIf\n    OamCacheDirty=1')
    p.write_text(s)
