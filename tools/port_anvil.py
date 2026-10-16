"""Generate the portable AArch64 core without changing either Pico target.

Uses the same CPU generator before its Thumb-only operand inlining pass and
the PPU's existing reference routines. No guest timing or opcode changes.
Requires py65, as does generate_cpu.py. Does not execute or write its tail.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'anvil'
OUT.mkdir(exist_ok=True)

def portable(s):
    s = re.sub(r'^[ \t]*CompilerIf #(?:NES_PICO_MAPPERS=1|NES_VIDEO_BACKEND=3(?: Or #NES_VIDEO_BACKEND=4)?(?: Or #NES_VIDEO_BACKEND=5)?)\n.*?^[ \t]*CompilerEndIf\n', '', s, flags=re.M | re.S)
    s = s.replace('ProcedureRAM', 'Procedure')
    s = s.replace('Micros()', 'NesHostUs()')
    return re.sub(r'^ReserveRegister .*\n', '', s, flags=re.M)

def replace_proc(s, name, body):
    pattern = rf'^Procedure(?:RAM|Naked)?(?:\.\w+)? {name}\([^\n]*\).*?^EndProcedure'
    s, n = re.subn(pattern, body.strip(), s, flags=re.M | re.S)
    assert n == 1, (name, n)
    return s

gen = ROOT / 'rp2040/generate_cpu.py'
prefix = gen.read_text().split('# Inline operand fetches.')[0]
ns = {'__file__': str(gen)}
exec(compile(prefix, str(gen), 'exec'), ns)
cpu = portable(ns['s'])
for macro in ('NZ','Fetch','Push','Pop','Charge','Tick','CrossPage','NextOp','DispatchNext'):
    cpu = re.sub(r'\b'+macro+r'\b', 'Cpu'+macro, cpu)
cpu = re.sub(r'  CompilerIf #CPU_ASM_TAIL = 1\n.*?  CompilerElse\n(.*?)  CompilerEndIf', r'\1', cpu, flags=re.S)
assert 'ASM' not in cpu
(OUT/'cpu2a03.pi4').write_text(cpu)

bridge = portable((ROOT/'rp2350/bridge.pico2').read_text())
bridge = replace_proc(bridge, 'NesFence', 'Procedure NesFence()\nEndProcedure')
bridge = replace_proc(bridge, 'NesRead', '''Procedure.i NesRead(addr.i)
  ProcedureReturn NesReadSlow(addr)
EndProcedure''')
bridge = replace_proc(bridge, 'CpuFetchByte', '''Procedure.i CpuFetchByte()
  Protected v.i
  v=NesRead(PC) : PC=(PC+1)&$FFFF
  ProcedureReturn v
EndProcedure''')
bridge = replace_proc(bridge, 'CpuFetchAddress', '''Procedure CpuFetchAddress()
  Ea=NesRead(PC)|(NesRead((PC+1)&$FFFF)<<8)
  PC=(PC+2)&$FFFF
EndProcedure''')
assert 'ASM' not in bridge
(OUT/'bridge.pi4').write_text(portable(bridge))

ppu = portable((ROOT/'rp2350/ppu.pico2').read_text())
# The optimized Thumb path is replaced by the already tested portable path.
ppu = ppu[:ppu.index('Global PpuRemaining.i')]
ppu = replace_proc(ppu, 'PpuClearSprites', '''Procedure PpuClearSprites()
  Protected i.i
  For i=0 To 255 : SpriteLine(i)=0 : Next
  For i=0 To 31 : SpriteSpan(i)=0 : Next
EndProcedure''')
ppu = replace_proc(ppu, 'PpuSpritesRaw', '''Procedure PpuSpritesRaw()
  PpuSpritesReference()
EndProcedure''')
ppu = ppu.replace('ProcedureNaked PpuSprites()\n  ASM\n    b ppuspritesraw\n  EndASM', 'Procedure PpuSprites()\n  PpuSpritesRaw()')
ppu = replace_proc(ppu, 'PpuOverlay8', '''Procedure PpuOverlay8()
  Protected i.i, sp.i, bg.i
  For i=0 To 7
    sp=SpriteLine(PpuDot+i) : bg=LinePixels(WOff+i)&3
    If sp<>0
      If (sp&$80)<>0 And bg<>0 And PpuDot+i<>255 : PpuStatus=PpuStatus|$40 : EndIf
      If (sp&$40)=0 Or bg=0 : LinePixels(WOff+i)=sp&31 : EndIf
    EndIf
  Next
EndProcedure''')
ppu = replace_proc(ppu, 'PpuRgbLineRaw', '''Procedure PpuRgbLineRaw()
  Protected i.i
  For i=0 To 255 : PokeU(FrameRow+i*2,RgbPal(LinePixels(i))) : Next
EndProcedure''')
ppu = ppu.replace('ProcedureNaked PpuRgbLine()\n  ASM\n    b ppurgblineraw\n  EndASM', 'Procedure PpuRgbLine()\n  PpuRgbLineRaw()')
# The reference path composites indexed pixels then converts the entire row.
ppu = ppu.replace('        PpuSendLine()', '        PpuRgbLineRaw()\n        PpuSendLine()')
ppu += '\nProcedure PpuAdvance(cycles.i)\n  PpuAdvanceReference(cycles)\nEndProcedure\n'
# On A64 .i is 64-bit. Packed pixel words must retain 32-bit logical shifts.
for name in ('WLo','WHi','W0','W1','W2','W3'):
    ppu = ppu.replace(name+'.i', name+'.l')
    ppu = ppu.replace(name+'>>', '('+name+'&$FFFFFFFF)>>')
    ppu = ppu.replace(name+' >>', '('+name+'&$FFFFFFFF) >>')
assert 'ASM' not in ppu
# Packed decoded CHR: four 2-bit pixels expand through one 32-bit lookup.
# Keep the reference routine separately for board differential checks.
ppu = ppu.replace('Procedure PpuFetchTile()', 'Procedure PpuFetchTileReference()',1)
ppu = ppu.replace('FrameRow=@FrameTop(0)+PpuLine*512','FrameRow=RenderTop+PpuLine*512')
at=ppu.index('Procedure PpuFetchTileReference()')
ppu=ppu[:at]+'''Global Dim PixelSpread.l(256)
Procedure PpuFetchTile()
  Protected tile.i,attr.i,palette.i,row.i,bits.i,packed.i
  tile=Nt(WAddr&$FFF)
  attr=Nt($3C0|(WAddr&$C00)|((WAddr>>4)&$38)|((WAddr>>2)&7))
  palette=((attr>>(((WAddr>>4)&4)|(WAddr&2)))&3)*4
  row=((PpuCtrl&16)<<8)+tile*16+((WAddr>>12)&7)*2
  bits=PeekU(Pattern+row)
  packed=palette*$01010101
  WLo=PixelSpread(bits&255)|packed : WHi=PixelSpread(bits>>8)|packed
EndProcedure
'''+ppu[at:]
ppu = replace_proc(ppu,'PpuRgbLineRaw','''Procedure PpuRgbLineRaw()
  ASM
    adrp x9, global_linepixels
    add x9, x9, #:lo12:global_linepixels
    adrp x10, global_rgbpal
    add x10, x10, #:lo12:global_rgbpal
    adrp x11, global_framerow
    ldr x11, [x11, #:lo12:global_framerow]
    mov x12, #256
__nes_a64_rgb:
    ldrb w13, [x9], #1
    lsl x13, x13, #1
    ldrh w13, [x10, x13]
    strh w13, [x11], #2
    subs x12, x12, #1
    b.ne __nes_a64_rgb
  EndASM
EndProcedure''')
(OUT/'ppu.pi4').write_text(portable(ppu))

worker = (ROOT/'rp2350/worker.pico2').read_text().split('ProcedureRAM Core1Main()')[0]
(OUT/'worker.pi4').write_text(portable(worker))
for name in ('apu','cartridge'):
    content=portable((ROOT/('rp2350/'+name+'.pico2')).read_text())
    if name=='apu':
        content=content.replace('ApuSamples','ApuProduced')
        content=content.replace('Global ApuProduced.i,','Global ApuSamples.i\nGlobal ApuProduced.i,',1)
        start=content.index('Procedure ApuAdvance(')
        end=content.index('EndProcedure',start)
        content=content[:end]+'  FrameFence() : ApuSamples=ApuProduced\n'+content[end:]
        content='Declare FrameFence()\n'+content
    (OUT/(name+'.pi4')).write_text(content)
print('Generated Anvil AArch64 core; Pico sources unchanged')
(OUT/'Tests').mkdir(exist_ok=True)
(OUT/'Tests/sbc_vectors.pi4').write_text((ROOT/'rp2350/Diagnostics/sbc_vectors.pico2').read_text())
(OUT/'Tests/zp_vectors.pi4').write_text((ROOT/'rp2350/Diagnostics/zp_vectors.pico2').read_text())
verify=(ROOT/'rp2350/Diagnostics/verify.pico2w').read_text()
zp=re.search(r'Procedure ZpVectorTests\(\).*?EndProcedure',verify,re.S)[0]
(OUT/'Tests/zp.pi4').write_text('XIncludeFile "zp_vectors.pi4"\n'+zp+'\n')
from anvil_bus_hooks import adapt_generated_core, generate_guest_reset
adapt_generated_core(OUT)
generate_guest_reset(OUT)
