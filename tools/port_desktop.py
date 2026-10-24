"""Generate the desktop NES core (desktop/core/*.pbi, PureBasic, C back end) from Anvil's portable core.

Anvil (anvil/*.pi4) is the NES as plain PureMetal Basic: CPU, bus, PPU, APU and the mapper set, with its
platform, video and scheduling kept outside `core.pi4`. This script translates that portable core into
PureBasic so the desktop program and the boards run the same emulation source:

  * ProcedureRAM -> Procedure; a `.Label` array -> `.i`.
  * The CPU's computed dispatch (`Goto Dispatch(op)`, PureMetal) -> GCC labels-as-values through the C
    back end: `!goto *(void*)((integer*)a_dispatch.a)[g_tmp];` (PureBasic emits `?Label` as `&&label`).
  * The two AArch64 ASM blocks -> their plain forms (PpuRgbLineRaw's palette lookup, MapCopy).
  * services.pi4 (the Pi's monitor ABI) is not copied: desktop/host.pbi supplies NesHostUs, SafetyPet and
    the rest.

Run from the repository root:  py -3 tools/port_desktop.py
Do not edit desktop/core by hand; change anvil/ (or this script) and regenerate.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'anvil'
OUT = ROOT / 'desktop' / 'core'

# core.pi4's order, without services.pi4 (replaced by desktop/host.pbi) and selector.pi4 (desktop/rom.pbi).
FILES = ['state', 'cpu2a03', 'mapper_state', 'bridge', 'ppu', 'mappers', 'mapper_extra', 'mapper_extra_bus',
         'mapper5', 'mapper5_video', 'apu', 'mapper5_audio', 'mapper69_audio', 'mapper9_video',
         'mapper_adapters', 'audio_api', 'worker']
# included by the files above
NESTED = ['ppu_bus_read', 'ppu_bus_write', 'mapper_extra_state']
# included after the core by core.pbi: tables and the built-in demo, the guest reset, the mapper database
SUPPORT = ['cartridge', 'guest_reset', 'rom_metadata']
# from selector.pi4 (the Pi's exFAT picker): only the header checks and the CRC-based mapper correction
SELECTOR_PROCS = ['RomCrc', 'RomResolveMetadata', 'RomValidateHeader']


def rom_check():
    """selector.pi4's ROM checks, for a ROM read from a file: the raw PRG/CHR are at RomRawPrg/RomRawChr
    (desktop/machine.pbi allocates them) and RomStatus$ is a string."""
    sel = (SRC / 'selector.pi4').read_text(encoding='cp1252').replace('\r\n', '\n')
    procs = []
    for p in SELECTOR_PROCS:
        m = re.search(r'^Procedure(?:\.\w)? ' + p + r'\(.*?^EndProcedure', sel, flags=re.S | re.M)
        if not m:
            raise SystemExit(f'selector.pi4: {p} not found')
        procs.append(m.group(0))
    text = '\n'.join(procs)
    text = text.replace('#ROM_RAW_PRG', 'RomRawPrg').replace('#ROM_RAW_CHR', 'RomRawChr')
    # The desktop runs PAL (as the Pico does): the header's TV system is noted, not refused - NES 2.0's field
    # 1 is PAL (3, dual, stays NTSC); an iNES 1 header with bytes 12-15 clear says PAL in byte 9's bit 0.
    refusal = ('  If (nes2<>0 And (RomHeader(12)&3)<>0 And (RomHeader(12)&3)<>2) Or (nes2=0 And (RomHeader(9)&1)<>0)\n'
               '    RomStatus="PAL timing is unsupported" : ProcedureReturn 0\n  EndIf\n')
    if text.count(refusal) != 1:
        raise SystemExit('selector.pi4: the PAL refusal this script replaces has changed')
    text = text.replace(refusal,
        '  RomHeaderPal=0\n'
        '  If nes2 : RomHeaderPal=Bool((RomHeader(12)&3)=1) : EndIf\n'
        '  If nes2=0 And RomHeader(12)=0 And RomHeader(13)=0 And RomHeader(14)=0 And RomHeader(15)=0 : RomHeaderPal=RomHeader(9)&1 : EndIf\n')
    text = re.sub(r'\bRomStatus=0\b', 'RomStatus$=""', text)
    text = re.sub(r'\bRomStatus=(")', r'RomStatus$=\1', text)
    if re.search(r'\bRomStatus\b(?!\$)', text):
        raise SystemExit('selector.pi4: a RomStatus use this script does not translate')
    head = ('Global RomLoaded.i,RomChosen.i=-1\n'
            'Global Dim RomHeader.a(16)\n'
            'Global Dim RomCrcTable.i(256)\n'
            'Global RomMapper.i,RomPrgBytes.i,RomChrBytes.i,RomSubmapper.i,RomMetadataCorrections.i\n'
            'Global RomStatus$, RomRawPrg.i, RomRawChr.i, RomHeaderPal.i\n')
    return head + text

KEYWORD_RENAMES = {'step': 'stepN'}
WINDOWS = {}          # Anvil work-area constant -> offset into AnvilWindow

DISPATCH ='!goto *(void*)((integer*)a_dispatch.a)[g_tmp];'

ASM_REPLACEMENTS = {
    'PpuRgbLineRaw': '''Procedure PpuRgbLineRaw()
  Protected x.i
  For x=0 To 255
    PokeU(FrameRow+x*2,RgbPal(PeekA(@LinePixels(0)+x)))
  Next
EndProcedure''',
    'MapCopy': '''Procedure MapCopy(dst.i,src.i,bytes.i)
  If bytes>0 : CopyMemory(src,dst,bytes) : EndIf
EndProcedure''',
}


def replace_asm_procedures(text, name):
    for proc, plain in ASM_REPLACEMENTS.items():
        m = re.search(r'^Procedure(?:RAM)? ' + proc + r'\(.*?^EndProcedure', text, flags=re.S | re.M)
        if m and 'ASM' in m.group(0):
            text = text[:m.start()] + plain + text[m.end():]
    if re.search(r'^\s*ASM\s*$', text, flags=re.M):
        raise SystemExit(f'{name}: an ASM block is left that this script does not translate')
    return text


def translate(text, name):
    text = text.replace('\r\n', '\n')
    text = replace_asm_procedures(text, name)
    text = re.sub(r'\bProcedureRAM\b', 'Procedure', text)
    text = text.replace('Global Dim Dispatch.Label(256)', 'Global Dim Dispatch.i(256)')
    n = 0
    def goto(m):
        nonlocal n
        n += 1
        return m.group(1) + DISPATCH
    text = re.sub(r'^(\s*)Goto Dispatch\(Tmp\)\s*$', goto, text, flags=re.M)
    if name == 'cpu2a03' and n == 0:
        raise SystemExit('cpu2a03: no computed dispatch found to translate')
    if 'Goto Dispatch(' in text:
        raise SystemExit(f'{name}: a computed Goto this script does not translate')
    text = re.sub(r'XIncludeFile "(\w+)\.pi4"', r'XIncludeFile "\1.pbi"', text)
    # Anvil's fixed work areas in the Pi's memory map ($03500000-$0351FFFF): on the PC they are offsets
    # into AnvilWindow, a block desktop/host.pbi allocates.
    def window(m):
        value = int(m.group(2), 16)
        if not 0x03500000 <= value < 0x03530000:
            raise SystemExit(f'{name}: {m.group(1)}=${m.group(2)} is outside the work-area window')
        WINDOWS[m.group(1)] = value - 0x03500000
        return ''
    text = re.sub(r'^(#\w+)=\$(0[0-9A-Fa-f]{7})[ \t]*(?:;.*)?\n', window, text, flags=re.M)
    text = bool_wrap(text)
    # A data label shares its line with Data in PureMetal; PureBasic wants it on a line of its own.
    text = re.sub(r'^(\w+):\s*(Data\.)', r'\1:\n\2', text, flags=re.M)
    # PureBasic keywords (case-insensitive there) that the core uses as lowercase variable names.
    for word, new in KEYWORD_RENAMES.items():
        text = re.sub(r'\b' + word + r'\b', new, text)
    head = f'; Generated by tools/port_desktop.py from anvil/{name}.pi4 - do not edit; regenerate.\n'
    return head + text


CONDITION_KEYWORDS = ('If ', 'ElseIf ', 'While ', 'Until ', 'Case ', 'For ', 'Select ', 'CompilerIf ',
                      'CompilerElseIf ', 'Procedure', 'Declare', 'Global ', 'Protected ', 'Define ', 'Macro ',
                      'Structure', 'Data.', 'XIncludeFile', 'EnableExplicit', '!')


def split_statements(line):
    """The line's statements (split on ':' outside strings), and its trailing comment."""
    parts, cur, in_str, i = [], '', False, 0
    while i < len(line):
        c = line[i]
        if c == '"':
            in_str = not in_str
        elif not in_str and c == ';':
            parts.append(cur)
            return parts, line[i:]
        if not in_str and c == ':':
            parts.append(cur); cur = ''; i += 1; continue
        cur += c; i += 1
    parts.append(cur)
    return parts, ''


def top_level_comparison(expr):
    """A comparison (= <> < > <= >=) anywhere in expr, outside strings; << and >> are shifts, not one."""
    in_str, i = False, 0
    while i < len(expr):
        c = expr[i]
        if c == '"':
            in_str = not in_str
        elif not in_str:
            if expr[i:i + 2] in ('<<', '>>'):
                i += 2
                continue
            if c in '=<>':
                return True
        i += 1
    return False


def own_level_comparison(expr):
    """A comparison at expr's own level: not inside its parentheses, not in strings, not << or >>."""
    depth, in_str, i = 0, False, 0
    while i < len(expr):
        c = expr[i]
        if c == '"':
            in_str = not in_str
        elif not in_str:
            if c == '(':
                depth += 1
            elif c == ')':
                depth -= 1
            elif depth == 0:
                if expr[i:i + 2] in ('<<', '>>'):
                    i += 2
                    continue
                if c in '=<>':
                    return True
        i += 1
    return False


def split_args(text):
    args, depth, in_str, cur = [], 0, False, ''
    for c in text:
        if c == '"':
            in_str = not in_str
        if not in_str:
            if c == '(':
                depth += 1
            elif c == ')':
                depth -= 1
            elif c == ',' and depth == 0:
                args.append(cur); cur = ''; continue
        cur += c
    args.append(cur)
    return args


def convert_expr(expr):
    """PureMetal gives a comparison the value 0/1 wherever it stands; PureBasic only inside Bool(). Every
    parenthesised group (and every call argument) whose own level compares becomes Bool(...)."""
    out, i, in_str = '', 0, False
    while i < len(expr):
        c = expr[i]
        if c == '"':
            in_str = not in_str
            out += c; i += 1; continue
        if in_str or c != '(':
            out += c; i += 1; continue
        depth, j = 1, i + 1
        while depth:
            if expr[j] == '"':
                j = expr.index('"', j + 1)
            elif expr[j] == '(':
                depth += 1
            elif expr[j] == ')':
                depth -= 1
            j += 1
        inner = expr[i + 1:j - 1]
        call = bool(re.search(r'[\w$]$', out))
        if call:
            args = [convert_expr(a) for a in split_args(inner)]
            args = [f'Bool({a.strip()})' if own_level_comparison(a) and not out.endswith('Bool') else a for a in args]
            out += '(' + ','.join(args) + ')'
        else:
            inner = convert_expr(inner)
            out += ('Bool(' if own_level_comparison(inner) else '(') + inner + ')'
        i = j
    return out


def first_assignment(stmt):
    """Index of the statement's assignment '=' (depth 0, not part of <= >= <>), or -1."""
    depth, in_str = 0, False
    for i, c in enumerate(stmt):
        if c == '"':
            in_str = not in_str
        elif not in_str:
            if c == '(':
                depth += 1
            elif c == ')':
                depth -= 1
            elif c == '=' and depth == 0:
                prev = stmt[i - 1] if i else ''
                nxt = stmt[i + 1] if i + 1 < len(stmt) else ''
                if prev in '<>' or nxt in '<>':
                    return -1
                return i
    return -1


def bool_wrap(text):
    """PureMetal assigns comparisons (`a=(b&16)=0`); PureBasic needs them inside Bool()."""
    out = []
    for line in text.split('\n'):
        stmts, comment = split_statements(line)
        if len(stmts) == 1 and not comment and ':' not in line:
            stmts = [line]
        new = []
        for st in stmts:
            s = st.strip()
            lead = st[:len(st) - len(st.lstrip())]
            tail = ' ' if st.endswith(' ') else ''
            if s.startswith('ProcedureReturn '):
                val = s[len('ProcedureReturn '):].rstrip()
                if top_level_comparison(val):
                    val = convert_expr(val)
                    if own_level_comparison(val):
                        val = f'Bool({val})'
                    st = f'{lead}ProcedureReturn {val}' + tail
                new.append(st); continue
            if not s or s.startswith(CONDITION_KEYWORDS):
                new.append(st); continue
            k = first_assignment(s)
            if k > 0:
                lhs, rhs = s[:k], s[k + 1:].strip()
                if re.match(r'^[\w*\\@().$+\-&|!<>]*$', lhs.replace(' ', '')) and top_level_comparison(rhs):
                    rhs = convert_expr(rhs)
                    if own_level_comparison(rhs):
                        rhs = f'Bool({rhs})'
                    st = f'{lead}{lhs}={rhs}' + tail
            elif k < 0 and re.match(r'^\w+\s*\(', s) and re.search(r'[<>=]', s):
                # a call with a comparison for an argument (`MapCheck(WorkerClock<=CpuCycles,1)`)
                st = lead + convert_expr(s.rstrip()) + tail
            new.append(st)
        out.append(':'.join(new) + comment)
    return '\n'.join(out)


PROC = re.compile(r'^Procedure(\.\w)?\s+(\w+)\s*\((.*)\)\s*$', flags=re.M)


# PAL timing, which the Pico cores have (rp2040/runtime.pico NesTiming, bridge/ppu/apu/mapper*.pico) and
# Anvil does not yet: the same globals and the same CPU-cycle <-> PPU-dot conversions, patched into
# Anvil's text before translation. Every patch must apply exactly as many times as listed, or the port
# stops (a changed Anvil is a reason to look, not to guess).
PAL_GLOBALS = """; The TV system (machine.pbi's NesTiming sets them from CartPal, as rp2040/runtime.pico does). NTSC: 262
; lines, 3 dots a CPU cycle, an odd frame's pre-render line one dot short, 1.789773 MHz. PAL: 312 lines,
; 3.2 dots a cycle (16 per 5: PpuDotFrac carries the fifths), no short line, 1.662607 MHz.
Global CartPal.i, PpuPreLine.i=261, PpuLineCount.i=262, PpuFrameDots.i=89342, PpuOddToggle.i=1, PpuDotFrac.i
Global ApuSampleBase.i=37, ApuFracStep.i=101, ApuFracDen.i=352
Global ApuStep1.i=7457, ApuStep2.i=14913, ApuStep3.i=22371, ApuStep4.i=29829, ApuStep5.i=37281
"""
PAL_PROCS = """; CPU cycles to PPU dots (rp2040/ppu.pico): 3 each (NTSC), or 16 per 5 (PAL) with the remainder carried
; in PpuDotFrac. PpuTakeDots spends the cycles; PpuDotsFor only looks ahead (the mapper observers, run
; before PpuAdvance on the same cycles, see the same dots). PpuCyclesWithin(d) is the most cycles that
; keep the PPU no more than d dots ahead (NTSC d/3) - the budgets and the status deadline.
Procedure.i PpuTakeDots(cycles.i)
  Protected total.i,dots.i
  If CartPal=0 : ProcedureReturn cycles*3 : EndIf
  total=cycles*16+PpuDotFrac : dots=NesDiv(total,5) : PpuDotFrac=total-dots*5
  ProcedureReturn dots
EndProcedure
Procedure.i PpuDotsFor(cycles.i)
  If CartPal=0 : ProcedureReturn cycles*3 : EndIf
  ProcedureReturn NesDiv(cycles*16+PpuDotFrac,5)
EndProcedure
Procedure.i PpuCyclesWithin(dots.i)
  If dots<0 : ProcedureReturn 0 : EndIf
  If CartPal=0 : ProcedureReturn NesDiv(dots,3) : EndIf
  ProcedureReturn (dots*5+4-PpuDotFrac)>>4
EndProcedure
"""
PAL_PATCHES = {
    'bridge': [('Global NesLatch2.i\n', 'Global NesLatch2.i\n' + PAL_GLOBALS, 1)],
    'ppu': [('Procedure PpuAdvanceReference(cycles.i)', PAL_PROCS + 'Procedure PpuAdvanceReference(cycles.i)', 1),
            ('  dots=cycles*3\n', '  dots=PpuTakeDots(cycles)\n', 1),
            ('PpuLine=241 Or PpuLine=261', 'PpuLine=241 Or PpuLine=PpuPreLine', 1),
            ('ElseIf PpuLine=261\n', 'ElseIf PpuLine=PpuPreLine\n', 1),
            ('If PpuLine=261 And PpuOdd<>0', 'If PpuLine=PpuPreLine And PpuOdd<>0', 1),
            ('ElseIf PpuLine=261 And edge=1', 'ElseIf PpuLine=PpuPreLine And edge=1', 1),
            ('ElseIf PpuLine=261 And edge=280', 'ElseIf PpuLine=PpuPreLine And edge=280', 1),
            ('If PpuLine=262\n          PpuLine=0 : PpuOdd=PpuOdd!1',
             'If PpuLine=PpuLineCount\n          PpuLine=0 : PpuOdd=PpuOdd!PpuOddToggle', 1)],
    'worker': [('(PpuLine=241 Or PpuLine=261)', '(PpuLine=241 Or PpuLine=PpuPreLine)', 1),
               ('NesDiv(edge-PpuDot-1,3)', 'PpuCyclesWithin(edge-PpuDot-1)', 1)],
    'mappers': [('If line=261 : nextLine=0 : EndIf', 'If line=PpuPreLine : nextLine=0 : EndIf', 1),
                ('left=cycles*3 : line=PpuLine', 'left=PpuDotsFor(cycles) : line=PpuLine', 1),
                ('If line=261 And odd<>0', 'If line=PpuPreLine And odd<>0', 1),
                ('(line<240 Or line=261)', '(line<240 Or line=PpuPreLine)', 1),
                ('If line=262 : line=0 : odd=odd!1 : EndIf', 'If line=PpuLineCount : line=0 : odd=odd!PpuOddToggle : EndIf', 1),
                ('(PpuLine<240 Or PpuLine=261)', '(PpuLine<240 Or PpuLine=PpuPreLine)', 1),
                ('budget=(341-PpuDot)/3', 'budget=PpuCyclesWithin(341-PpuDot)', 1),
                ('budget=(257-PpuDot)/3', 'budget=PpuCyclesWithin(257-PpuDot)', 1),
                ('If PpuLine>=240 And PpuLine<261\n    distance=(261-PpuLine)*341-PpuDot',
                 'If PpuLine>=240 And PpuLine<PpuPreLine\n    distance=(PpuPreLine-PpuLine)*341-PpuDot', 1),
                ('budget=distance/3', 'budget=PpuCyclesWithin(distance)', 1)],
    'mapper5_video': [('left=cycles*3 : line=PpuLine', 'left=PpuDotsFor(cycles) : line=PpuLine', 1),
                      ('If line=261 And odd<>0', 'If line=PpuPreLine And odd<>0', 1),
                      ('(line<240 Or line=261)', '(line<240 Or line=PpuPreLine)', 1),
                      ('If line=262 : line=0 : odd=odd!1 : EndIf', 'If line=PpuLineCount : line=0 : odd=odd!PpuOddToggle : EndIf', 1)],
    'apu': [('event=7457', 'event=ApuStep1', 1), ('event=14913', 'event=ApuStep2', 1),
            ('event=22371', 'event=ApuStep3', 1), ('event=29829', 'event=ApuStep4', 1),
            ('event=37281', 'event=ApuStep5', 1),
            ('ApuSampleFrac=ApuSampleFrac+101', 'ApuSampleFrac=ApuSampleFrac+ApuFracStep', 1),
            ('      ApuSampleLeft=37\n', '      ApuSampleLeft=ApuSampleBase\n', 1),
            ('If ApuSampleFrac>=352', 'If ApuSampleFrac>=ApuFracDen', 1),
            ('ApuSampleFrac=ApuSampleFrac-352 : ApuSampleLeft=38', 'ApuSampleFrac=ApuSampleFrac-ApuFracDen : ApuSampleLeft=ApuSampleBase+1', 1)],
    'mapper5_audio': [('M5AudioClock=7457', 'M5AudioClock=ApuStep1', 2)],
}

# VRC6 (24, 26) and Namco 163 (19), which the Pico profile runs and Anvil does not: desktop/
# mapper_konami_namco.pbi (hand-written, from the Pico's mapper_vrc6 / mapper_n163 and their plain
# reference forms) on Anvil's "extra" mapper hooks. These patches route those hooks to it.
KN = 'CartMapper=19 Or CartMapper=24 Or CartMapper=26'
MAPPER_PATCHES = {
    'bridge': [('Global NesLatch2.i\n', 'Global NesLatch2.i\n'
                'Global ExpChip.i, ExpSample.i   ; a cartridge sound chip (desktop/mapper_konami_namco.pbi) and its part of the next sample\n', 1),
               # N163's IRQ counter reads ($5000/$5800) are current only once the machine is brought up to now
               ('  ElseIf addr>=$4020 And ExtraManaged(CartMapper)\n    v=ExtraLowRead(addr,NesOpenBus)\n',
                '  ElseIf addr>=$5000 And CartMapper=19\n'
                '    CpuNow() : NesRpc(0,0,0,CpuCycles+AccessPhase)\n'
                '    v=ExtraLowRead(addr,NesOpenBus) : CpuEndWindow()\n'
                '  ElseIf addr>=$4020 And ExtraManaged(CartMapper)\n    v=ExtraLowRead(addr,NesOpenBus)\n', 1)],
    'mapper_extra': [('Procedure.i ExtraManaged(mapper.i)\n',
                      'Procedure.i ExtraManaged(mapper.i)\n  If KonamiNamcoMapper(mapper) : ProcedureReturn 1 : EndIf\n', 1),
                     ('  If CartMapper=41 Or CartMapper=228 Or CartMapper=234 : MapperMirror(1) : EndIf\nEndProcedure',
                      '  If CartMapper=41 Or CartMapper=228 Or CartMapper=234 : MapperMirror(1) : EndIf\n'
                      '  ExpChip=0 : ExpSample=0\n'
                      '  If ' + KN + ' : KonamiNamcoInit() : EndIf\nEndProcedure', 1),
                     ('  Select CartMapper\n    Case 79\n', '  Select CartMapper\n    Case 19, 24, 26\n      KonamiNamcoUpdate()\n    Case 79\n', 1),
                     ('  Protected reg.i,old.i,commit.i\n  Select CartMapper\n',
                      '  Protected reg.i,old.i,commit.i\n  Select CartMapper\n    Case 19, 24, 26\n      KonamiNamcoWrite(addr,value)\n', 1)],
    'mapper_extra_bus': [('Procedure.i ExtraLowRead(addr.i,openbus.i)\n',
                          'Procedure.i ExtraLowRead(addr.i,openbus.i)\n  If ' + KN + ' : ProcedureReturn KonamiNamcoLowRead(addr,openbus) : EndIf\n', 1),
                         ('Procedure ExtraCpuTicks(cycles.i)\n  Protected i.i,distance.i\n',
                          'Procedure ExtraCpuTicks(cycles.i)\n  Protected i.i,distance.i\n  If ' + KN + ' : KonamiNamcoCpuTicks(cycles) : ProcedureReturn : EndIf\n', 1)],
    'mappers': [('  If CartMapper=6 Or CartMapper=69 Or CartMapper=105 : ProcedureReturn ExtraBudget() : EndIf\n',
                 '  If ' + KN + ' : ProcedureReturn KonamiNamcoBudget() : EndIf\n'
                 '  If CartMapper=6 Or CartMapper=69 Or CartMapper=105 : ProcedureReturn ExtraBudget() : EndIf\n', 1)],
    'apu': [('    If CartMapper=69 : ExtraSoundAdvance(step) : EndIf\n',
             '    If CartMapper=69 : ExtraSoundAdvance(step) : EndIf\n    If ExpChip : ExpTick(step) : EndIf\n', 1),
            ('  x=PulseMix(pulse)+TndMix(TriDac*3+noise*2+DmcLevel)\n',
             '  x=PulseMix(pulse)+TndMix(TriDac*3+noise*2+DmcLevel)+ExpSample\n', 1)],
    'mapper_adapters': [('Procedure ApuMixSample()\n  ApuMixSampleBase()\n',
                         'Procedure ApuMixSample()\n  If ExpChip : ExpMix() : EndIf\n  ApuMixSampleBase()\n', 1)],
}
# The second controller, as rp2350/bridge.pico2 has it (Anvil reads $4017 with no pad behind it):
# NesController2 is the pad's state, latched by the $4016 strobe and read through $4017.
CONTROLLER_PATCHES = {
    'bridge': [('Global NesLatch2.i\n', 'Global NesLatch2.i, NesController2.i\n', 1),
               ('    If NesStrobe=0\n      v=v|(NesLatch2&1) : NesLatch2=(NesLatch2>>1)|$80\n',
                '    If NesStrobe\n      v=v|(NesController2&1)\n    Else\n'
                '      v=v|(NesLatch2&1) : NesLatch2=(NesLatch2>>1)|$80\n', 1),
               ('NesLatch=NesController : NesLatch2=0', 'NesLatch=NesController : NesLatch2=NesController2', 1)],
}
HAND = ['mapper_konami_namco']     # desktop/*.pbi files the core includes and declares like its own

# Anvil's own test suites (anvil/Tests), which the Pi runs from its menu: the core tests (the boards'
# zero-page vectors, then the PPU's packed tile fetch against its reference form) and the mapper tests
# (synthetic PRG/CHR fixtures through every mapper). Ported to desktop/core/tests/ as they are, except
# their fixed Pi buffers ($03200000 PRG, $03300000 CHR: host.pbi's AnvilTestPrg / AnvilTestChr) and the
# result block they leave at $02F00000 for the Pi's monitor (the desktop reads the globals instead).
TESTS = ['zp_vectors', 'zp', 'core', 'mapper5_bus_reference', 'mapper_extra', 'mappers']
TEST_BUFFERS = {'$03200000': 'AnvilTestPrg', '$03300000': 'AnvilTestChr'}


def port_tests():
    out = OUT / 'tests'
    out.mkdir(exist_ok=True)
    for name in TESTS:
        text = (SRC / 'Tests' / f'{name}.pi4').read_text(encoding='cp1252').replace('\r\n', '\n')
        text = re.sub(r'^[ \t]*PokeI\(\$02F00[0-9A-F]{3},.*\n', '', text, flags=re.M)
        for addr, buf in TEST_BUFFERS.items():
            text = text.replace(addr, buf)
        if re.search(r'\$0[23][0-9A-Fa-f]{6}\b', text):
            raise SystemExit(f'Tests/{name}.pi4: a Pi address is left')
        text = translate(text, name).replace(f'from anvil/{name}.pi4', f'from anvil/Tests/{name}.pi4')
        for const, off in WINDOWS.items():
            text = re.sub(re.escape(const) + r'\b', f'(AnvilWindow+${off:05X})', text)
        (out / f'{name}.pbi').write_text(text, encoding='cp1252', newline='\n')


def pal_patch(text, name):
    text = text.replace('\r\n', '\n')
    for old, new, count in PAL_PATCHES.get(name, []) + MAPPER_PATCHES.get(name, []) + CONTROLLER_PATCHES.get(name, []):
        if text.count(old) != count:
            raise SystemExit(f'PAL patch: {name}: {old!r} found {text.count(old)} times, expected {count}')
        text = text.replace(old, new)
    return text


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    texts = {name: translate(pal_patch((SRC / f'{name}.pi4').read_text(encoding='cp1252'), name), name)
             for name in FILES + NESTED + SUPPORT}
    texts['rom_check'] = translate(rom_check(), 'rom_check').replace(
        'from anvil/rom_check.pi4', 'from anvil/selector.pi4 (its ROM checks)')
    ALL = FILES + NESTED + SUPPORT + ['rom_check']
    # PureMetal resolves a call anywhere in the program; PureBasic wants a procedure declared before its
    # first use. declares.pbi declares every core procedure up front; the core's own Declare lines for
    # those names go (a second Declare is an error).
    decls, names = [], set()
    hand = {h: (ROOT / 'desktop' / f'{h}.pbi').read_text(encoding='cp1252') for h in HAND}
    for name in ALL + HAND:
        for kind, proc, args in PROC.findall(texts[name] if name in texts else hand[name]):
            if proc in names:
                continue      # the CompilerIf alternatives of one procedure (PpuSprites with profiling)
            names.add(proc)
            decls.append(f'Declare{kind} {proc}({args})')
    # Every use of a work-area constant becomes AnvilWindow plus its offset.
    for name in ALL:
        for const, off in WINDOWS.items():
            texts[name] = re.sub(re.escape(const) + r'\b', f'(AnvilWindow+${off:05X})', texts[name])
        if re.search(r'\$03[45][0-9A-Fa-f]{5}', texts[name]):
            raise SystemExit(f'{name}: a Pi work-area address is left')
    host = (ROOT / 'desktop' / 'host.pbi').read_text(encoding='cp1252')
    hosted = {p for _, p, _ in PROC.findall(host)}
    for name in ALL:
        texts[name] = re.sub(r'^Declare(\.\w)?\s+(\w+)\s*\(.*\)\s*\n',
                             lambda m: '' if m.group(2) in hosted else m.group(0), texts[name], flags=re.M)
        texts[name] = re.sub(r'^Declare(\.\w)?\s+(\w+)\s*\(.*\)\s*\n',
                             lambda m: '' if m.group(2) in names else m.group(0), texts[name], flags=re.M)
        (OUT / f'{name}.pbi').write_text(texts[name], encoding='cp1252', newline='\n')
    (OUT / 'declares.pbi').write_text(
        '; Generated by tools/port_desktop.py: every core procedure, declared before any is used.\n'
        + '\n'.join(decls) + '\n', encoding='cp1252', newline='\n')
    # core.pbi is core.pi4 itself (its includes and the globals between them), less the Pi's services and
    # selector, with the declarations first.
    core = (SRC / 'core.pi4').read_text(encoding='cp1252').replace('\r\n', '\n')
    lines = []
    for line in core.split('\n'):
        m = re.match(r'XIncludeFile "(\w+)\.pi4"', line)
        if m and m.group(1) not in FILES:
            if m.group(1) not in ('services', 'selector'):
                raise SystemExit(f'core.pi4 includes {m.group(1)}.pi4, which this script does not port')
            continue
        if m and m.group(1) == 'state':
            lines.append(line.replace('.pi4', '.pbi'))
            lines.append('XIncludeFile "declares.pbi"')
            continue
        lines.append(re.sub(r'XIncludeFile "(\w+)\.pi4"', r'XIncludeFile "\1.pbi"', line))
    port_tests()
    (OUT / 'core.pbi').write_text(
        '; Generated by tools/port_desktop.py from anvil/core.pi4: the portable NES core. desktop/host.pbi\n'
        '; must be included first (the services this core calls); the program supplies what core.pi4 leaves\n'
        '; to its platform (CartSelect, the video and audio plugins...).\n' + '\n'.join(lines).rstrip()
        + "\n; Anvil's tables and built-in demo, the guest reset, the mapper database and the ROM checks.\n"
        + ''.join(f'XIncludeFile "{n}.pbi"\n' for n in SUPPORT + ['rom_check'])
        + "; The desktop's own cartridge hardware (hand-written, in desktop/).\n"
        + ''.join(f'XIncludeFile "../{h}.pbi"\n' for h in HAND),
        encoding='cp1252', newline='\n')
    print(f'Generated {len(ALL)} desktop core files from anvil/')


if __name__ == '__main__':
    main()
