"""Generate the portable AArch64 core without changing either Pico target.

Run from anywhere: python tools/port_anvil.py (PMF_REPO: see the SBC vectors below).

Writes, under anvil/: cpu2a03.pi4 (rp2040/generate_cpu.py up to its Thumb-only
operand inlining pass, whose tail it does not execute), bridge, ppu, worker
(up to Core1Main), apu and cartridge.pi4 from the rp2350 sources, Tests/
sbc_vectors, zp_vectors and zp.pi4; then tools/anvil_bus_hooks.py adapts the
bridge, PPU, worker and APU for Anvil's cartridges, writes mapper9_video.pi4 and
generates guest_reset.pi4. The Pico sources' Thumb assembly is replaced by its
plain twin (rp2350/Diagnostics/asm_reference.pico2w) or by the PPU's reference
routines. No guest timing or opcode changes. Needs no third-party package.

tools/port_desktop.py and the N64 build (n64/build.py) take these files as their
input: regenerating them changes those builds too.
"""
from pathlib import Path
import os
import re

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'anvil'
OUT.mkdir(exist_ok=True)

# Pico-only compile switches, false on Anvil: the Pico's own mapper boards, the RP2350's extras
# (#PICO_ADVANCED, set by rp2350/mapper_state.pico2, 0 on the RP2040 - Anvil takes the RP2040's
# side) and the Pico display backends. Their CompilerIf blocks are resolved here, keeping a
# CompilerElse part, so the generated core names no Pico constant.
PICO_ONLY = re.compile(r'#(?:NES_PICO_MAPPERS=1|PICO_ADVANCED=1|NES_VIDEO_BACKEND=3(?: Or #NES_VIDEO_BACKEND=4)?(?: Or #NES_VIDEO_BACKEND=5)?)')

def drop_pico_only(s):
    out = []
    stack = []   # per open CompilerIf: None (kept as written) or [in_else] (a Pico-only one)
    for line in s.splitlines(keepends=True):
        word = line.strip().split(' ', 1)
        head, rest = word[0], (word[1].strip() if len(word) > 1 else '')
        if head == 'CompilerIf':
            stack.append([False] if PICO_ONLY.fullmatch(rest) else None)
            if stack[-1] is not None:
                continue
        elif head in ('CompilerElse', 'CompilerElseIf', 'CompilerEndIf'):
            assert stack, line
            top = stack[-1]
            if top is not None:
                assert head != 'CompilerElseIf', line
                if head == 'CompilerElse':
                    top[0] = True
                else:
                    stack.pop()
                continue
            if head == 'CompilerEndIf':
                stack.pop()
        if all(t is None or t[0] for t in stack):
            out.append(line)
    assert not stack
    return ''.join(out)

def portable(s):
    s = drop_pico_only(s)
    s = s.replace('ProcedureRAM', 'Procedure')
    s = s.replace('Micros()', 'NesHostUs()')
    return re.sub(r'^ReserveRegister .*\n', '', s, flags=re.M)

def replace_proc(s, name, body):
    pattern = rf'^Procedure(?:RAM|Naked)?(?:\.\w+)? {name}\([^\n]*\).*?^EndProcedure'
    s, n = re.subn(pattern, lambda m: body.strip(), s, flags=re.M | re.S)
    assert n == 1, (name, n)
    return s

def once(s, old, new):
    # A source edit that must apply exactly once: a changed source stops the port here.
    assert s.count(old) == 1, (old[:60], s.count(old))
    return s.replace(old, new)

# The Pico sources' hand-written Thumb assembly cannot be carried to A64 as text. Each such routine
# has a plain twin in rp2350/Diagnostics/asm_reference.pico2w (the routine as it was before it became
# assembly), and that image's Compare* checks hold the assembly to it on the board. The port takes
# the twin. The checks' inputs are NTSC (PpuSyncStatusReference keeps the NTSC line 261 and /3),
# which is all Anvil runs: nothing on Anvil sets CartPal, so PpuPreLine stays 261.
TWINS = (ROOT/'rp2350/Diagnostics/asm_reference.pico2w').read_text()

def twin(name):
    """The plain twin of the routine name, renamed to name."""
    found = re.findall(rf'^Procedure(\.\w+)? {name}Reference(\([^\n]*\)\n.*?^EndProcedure)', TWINS, re.M | re.S)
    assert len(found) == 1, (name, len(found))
    kind, rest = found[0]
    return f'Procedure{kind} {name}{rest}'

def twin_body(name):
    """The twin's lines between its header and EndProcedure."""
    return twin(name).split('\n', 1)[1].rsplit('EndProcedure', 1)[0]

# The SBC test vectors live with the encoder in the compiler since 2026-10-18
# (Shared/Bluetooth/Diagnostics/sbc_vectors.pmi, made by its tools/make_sbc_vectors.py). PMF_REPO names
# the compiler's repository (or its OpenGl Work/ArduinoBasic tree); the default is a checkout of it
# named PureBasicCode beside this repository.
COMPILER = Path(os.environ.get('PMF_REPO') or (ROOT.parent / 'PureBasicCode'))
if (COMPILER / 'OpenGl Work' / 'ArduinoBasic').is_dir():
    COMPILER = COMPILER / 'OpenGl Work' / 'ArduinoBasic'
SBC_VECTORS = COMPILER / 'Shared' / 'Bluetooth' / 'Diagnostics' / 'sbc_vectors.pmi'
if not SBC_VECTORS.is_file():
    raise SystemExit(f'port_anvil: {SBC_VECTORS} not found - set PMF_REPO to the compiler repository')
generated = {}   # file name under anvil/ -> text, written only once every part has been derived

gen = ROOT / 'rp2040/generate_cpu.py'
prefix = gen.read_text().split('# Inline operand fetches.')[0]
ns = {'__file__': str(gen)}
exec(compile(prefix, str(gen), 'exec'), ns)
cpu = portable(ns['s'])
for macro in ('NZ','Fetch','Push','Pop','Charge','Tick','CrossPage','NextOp','DispatchNext'):
    cpu = re.sub(r'\b'+macro+r'\b', 'Cpu'+macro, cpu)
cpu = re.sub(r'  CompilerIf #CPU_ASM_TAIL = 1\n.*?  CompilerElse\n(.*?)  CompilerEndIf', r'\1', cpu, flags=re.S)
assert 'ASM' not in cpu
generated['cpu2a03.pi4']=cpu

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
generated['bridge.pi4']=portable(bridge)

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
ppu = once(ppu, 'ProcedureNaked PpuSprites()\n  ASM\n    b ppuspritesraw\n  EndASM', 'Procedure PpuSprites()\n  PpuSpritesRaw()')
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
ppu = once(ppu, 'ProcedureNaked PpuRgbLine()\n  ASM\n    b ppurgblineraw\n  EndASM', 'Procedure PpuRgbLine()\n  PpuRgbLineRaw()')
for name in ('PpuBuildSpriteCache', 'PpuIncY'):
    ppu = replace_proc(ppu, name, twin(name))
# The reference path composites indexed pixels then converts the entire row.
ppu = once(ppu, '        PpuSendLine()', '        PpuRgbLineRaw()\n        PpuSendLine()')
ppu += '\nProcedure PpuAdvance(cycles.i)\n  PpuAdvanceReference(cycles)\nEndProcedure\n'
# On A64 .i is 64-bit. Packed pixel words must retain 32-bit logical shifts.
for name in ('WLo','WHi','W0','W1','W2','W3'):
    ppu = ppu.replace(name+'.i', name+'.l')
    ppu = ppu.replace(name+'>>', '('+name+'&$FFFFFFFF)>>')
    ppu = ppu.replace(name+' >>', '('+name+'&$FFFFFFFF) >>')
assert 'ASM' not in ppu
# Packed decoded CHR: four 2-bit pixels expand through one 32-bit lookup.
# Keep the reference routine separately for board differential checks.
ppu = once(ppu, 'Procedure PpuFetchTile()', 'Procedure PpuFetchTileReference()')
ppu = once(ppu, 'FrameRow=@FrameTop(0)+PpuLine*512','FrameRow=RenderTop+PpuLine*512')
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
generated['ppu.pi4']=portable(ppu)

worker = portable((ROOT/'rp2350/worker.pico2').read_text().split('ProcedureRAM Core1Main()')[0])
# Core1Main's own declaration (the Pico's Qw/ST Pad poll) goes with the Core1Main it serves.
worker = once(worker, 'Declare.i QwstPoll()\n', '')
worker = replace_proc(worker, 'PpuSyncStatus', twin('PpuSyncStatus'))
# OAM DMA from a RAM page: the assembly copy's twin is the NesDmaRead loop it replaced
# (asm_reference's CompareOamDma), which is the source's own path for every other page.
worker, n = re.subn(r'^    If value<\$20\n.*?^      EndASM\n    Else\n(      For i=0 To 255\n'
                    r'        Oam\(\(PpuOamAddr\+i\)&255\)=NesDmaRead\(value\*256\+i\)\n      Next\n)    EndIf\n',
                    lambda m: re.sub(r'^  ', '', m[1], flags=re.M), worker, flags=re.M | re.S)
assert n == 1, ('OAM DMA', n)
assert 'ASM' not in worker
generated['worker.pi4']=worker
for name in ('apu','cartridge'):
    content=portable((ROOT/('rp2350/'+name+'.pico2')).read_text())
    if name=='apu':
        # ApuTick's assembly is its pulse, triangle and noise; its twin ends where the plain DMC starts.
        tick=twin_body('ApuTick')
        assert tick.endswith('  DmcTimer=DmcTimer-dt\n'), tick[-60:]
        content, n = re.subn(r'^  ApuTickDt=dt\n  ASM\n.*?^  EndASM\n  DmcTimer=DmcTimer-dt\n',
                             lambda m: tick, content, flags=re.M | re.S)
        assert n == 1, ('ApuTick', n)
        content=replace_proc(content, 'ApuMixSample', twin('ApuMixSample'))
        # The Pico mixer adds a cartridge chip's ExpSample (declared in its own mapper_state); Anvil
        # mixes MMC5 and 5B after the base mixer (mapper_adapters.pi4), so here it is always 0.
        content=once(content, 'Global ApuTickDt.i', 'Global ExpSample.i                               ; 0 on Anvil (see port_anvil.py)\nGlobal ApuTickDt.i')
        content=content.replace('ApuSamples','ApuProduced')
        content=content.replace('Global ApuProduced.i,','Global ApuSamples.i\nGlobal ApuProduced.i,',1)
        start=content.index('Procedure ApuAdvance(')
        end=content.index('EndProcedure',start)
        content=content[:end]+'  FrameFence() : ApuSamples=ApuProduced\n'+content[end:]
        content='Declare FrameFence()\n'+content
    assert 'ASM' not in content, name
    generated[name+'.pi4']=content
zp=re.search(r'Procedure ZpVectorTests\(\).*?EndProcedure',(ROOT/'rp2350/Diagnostics/verify.pico2w').read_text(),re.S)[0]
generated['Tests/sbc_vectors.pi4']=SBC_VECTORS.read_text()
generated['Tests/zp_vectors.pi4']=(ROOT/'rp2350/Diagnostics/zp_vectors.pico2').read_text()
generated['Tests/zp.pi4']='XIncludeFile "zp_vectors.pi4"\n'+zp+'\n'
# Everything is derived before anything is written: a source the port no longer fits stops it
# above with the anvil folder untouched.
(OUT/'Tests').mkdir(exist_ok=True)
for name, text in generated.items():
    (OUT/name).write_text(text)
from anvil_bus_hooks import adapt_generated_core, generate_guest_reset
adapt_generated_core(OUT)
generate_guest_reset(OUT)
print('Generated Anvil AArch64 core; Pico sources unchanged')
