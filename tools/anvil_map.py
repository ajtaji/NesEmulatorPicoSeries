"""The Anvil NES memory map: read anvil/memory_map.pi4, check it, derive the compiler's addresses.

anvil/memory_map.pi4 is the one place the port's fixed addresses come from. This module reads it the
way the compiler does (literal constants), and refuses - by region name - a map whose regions overlap,
whose no-cache lists disagree with its regions, whose shared mapper windows left their region, whose
Anvil addresses disagree with the Anvil checkout, or a built image that outgrew its room or left the
BSS window less than #NES_MAP_BSS_MARGIN free.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
MAP = ROOT / 'anvil' / 'memory_map.pi4'
GRAIN = 0x200000          # MmuAddNc rounds its range outwards to 2 MiB blocks
MIB = 1 << 20


class MapError(SystemExit):
    def __init__(self, text):
        super().__init__('memory map: ' + text)


def _consts(path, prefix=r'\w+'):
    out = {}
    for line in path.read_text(encoding='cp1252').splitlines():
        m = re.match(r'\s*#(' + prefix + r')\s*=\s*\$([0-9A-Fa-f]+)\b', line)
        if m:
            out.setdefault(m.group(1), int(m.group(2), 16))
    return out


def load(path=MAP):
    consts, regions = {}, []
    for line in path.read_text(encoding='cp1252').splitlines():
        m = re.match(r'#NES_MAP_(\w+)=\$([0-9A-Fa-f]+)\s*(?:;\s*(.*))?$', line.strip())
        if not m:
            continue
        name, value, note = m.group(1), int(m.group(2), 16), (m.group(3) or '')
        consts[name] = value
        r = re.match(r'region\s+(WB|NC|ANVIL|HIGH)\s+(.*)', note)
        if r:
            regions.append([name, value, None, r.group(1), r.group(2)])
    for r in regions:
        if r[0] + '_BYTES' not in consts:
            raise MapError(f'region {r[0]} has no #NES_MAP_{r[0]}_BYTES')
        r[2] = consts[r[0] + '_BYTES']
    return consts, [tuple(r) for r in regions]


def _hit(a_lo, a_hi, b_lo, b_hi):
    return a_lo < b_hi and b_lo < a_hi


def _span(r):
    return r[1], r[1] + r[2]


def _fmt(lo, hi):
    return f'${lo:08X}..${hi - 1:08X}'


def check(consts, regions, anvil=None):
    """Refuse a map that cannot be right before anything is compiled."""
    by = {r[0]: r for r in regions}
    for need in ('IMAGE', 'BSS', 'STACK', 'RECORD', 'CORE1_STACK', 'TESTS', 'WORK'):
        if need not in by:
            raise MapError(f'no region {need}')
    for i, a in enumerate(regions):
        for b in regions[i + 1:]:
            if _hit(*_span(a), *_span(b)):
                raise MapError(f'{a[0]} {_fmt(*_span(a))} overlaps {b[0]} {_fmt(*_span(b))}')
    for t in ('TEST_PRG', 'TEST_CHR'):
        lo, hi = _span(by['TESTS'])
        if not lo <= consts[t] < hi:
            raise MapError(f'{t} ${consts[t]:08X} is outside TESTS {_fmt(lo, hi)}')
    # The low payload window, and Anvil's stack corridor for the stack.
    pay0_hi = consts['ANVIL_PAY0_HI'] + 1
    for r in regions:
        lo, hi = _span(r)
        if r[3] in ('WB', 'NC') and r[0] != 'STACK' and not (by['IMAGE'][1] <= lo and hi <= pay0_hi):
            raise MapError(f'{r[0]} {_fmt(lo, hi)} is outside the low payload window ..${pay0_hi - 1:08X}')
    lo, hi = _span(by['STACK'])
    if not (consts['ANVIL_STACK_LO'] <= lo and hi - 16 >= consts['ANVIL_STACK_LO']
            and hi <= consts['ANVIL_STACK_HI'] + 1):
        raise MapError(f'STACK {_fmt(lo, hi)} (top ${hi:08X}) is not in Anvil\'s payload stack corridor')
    if _span(by['BSS'])[1] + MIB > _span(by['STACK'])[1]:
        raise MapError('the stack top is less than 1 MiB above the end of the BSS window')
    # The no-cache lists against the regions.
    mmu = [(consts['NC1_LO'], consts['NC1_HI']), (consts['NC2_LO'], consts['NC2_HI']),
           (consts['MMU_NC3_LO'], consts['MMU_NC3_HI'])]
    dma = mmu[:2] + [(consts['DMA_NC3_LO'], consts['DMA_NC3_HI'])]
    for lo, hi in mmu + dma:
        if lo % GRAIN or hi % GRAIN:
            raise MapError(f'no-cache range {_fmt(lo, hi)} is not on 2 MiB blocks')
    for r in regions:
        lo, hi = _span(r)
        if r[3] == 'NC' and not any(a <= lo and hi <= b for a, b in mmu[:2]):
            raise MapError(f'{r[0]} {_fmt(lo, hi)} is NC but in no NC range')
        if r[3] == 'WB':
            for a, b in mmu + dma:
                if _hit(lo, hi, a, b):
                    raise MapError(f'{r[0]} {_fmt(lo, hi)} is WB but touches no-cache range {_fmt(a, b)}')
        if r[3] == 'ANVIL' and not any(a <= lo and hi <= b for a, b in dma[2:]):
            raise MapError(f'{r[0]} {_fmt(lo, hi)} is not covered by the DMA list')
    # The shared mapper windows stay where their own files put them.
    work_lo, work_hi = _span(by['WORK'])
    for f in ('mapper_state.pi4', 'mapper_extra_state.pi4'):
        for name, v in _consts(ROOT / 'anvil' / f).items():
            if 0x01000000 <= v < 0x08000000 and not work_lo <= v < work_hi:
                raise MapError(f'{f}: #{name}=${v:08X} is outside WORK {_fmt(work_lo, work_hi)}')
    # Anvil's own addresses, as the Anvil checkout states them.
    if anvil is not None:
        mm = Path(anvil) / 'RaspberryPi4' / 'Board' / 'memmap.pi4'
        theirs = _consts(mm)
        for ours, name in (('ANVIL_FB', 'MON_FB_LO'), ('ANVIL_PAY0_HI', 'PAY0_HI'),
                           ('ANVIL_STACK_LO', 'PAY_STACK_LO'), ('ANVIL_STACK_HI', 'PAY_STACK_HI')):
            if theirs.get(name) != consts[ours]:
                got = theirs.get(name)
                raise MapError(f'#NES_MAP_{ours}=${consts[ours]:08X} but Anvil\'s #{name} is '
                               + (f'${got:08X}' if got is not None else 'missing'))
        lo, hi = _span(by['ANVIL'])
        if not lo <= consts['ANVIL_FB'] < hi:
            raise MapError('Anvil\'s framebuffer is outside the ANVIL region')


def compiler_args(consts):
    return ['--load-addr', f'0x{consts["IMAGE"]:08X}', '--bss-addr', f'0x{consts["BSS"]:08X}',
            '--stack-addr', f'0x{consts["STACK"] + consts["STACK_BYTES"]:08X}']


def check_built(consts, output):
    """Refuse a built image that outgrew its room or left the BSS window too little free space.
    Returns (image_bytes, bss_bytes, bss_free)."""
    m = re.search(r'image (\d+) bytes, occupying \$([0-9A-F]+)\.\.\$([0-9A-F]+)', output)
    b = re.search(r'\bbss \$([0-9A-F]+)\.\.\$([0-9A-F]+)', output)
    if not m or not b:
        raise MapError('the compiler did not report the image and BSS extents; nothing is checked')
    image, end = int(m.group(1)), int(m.group(3), 16) + 1
    room = consts['IMAGE'] + consts['IMAGE_BYTES']
    if end > room:
        raise MapError(f'the image ends at ${end - 1:08X}, past its room IMAGE ..${room - 1:08X} '
                       '(the next region is WINDOW)')
    lo, hi = int(b.group(1), 16), int(b.group(2), 16) + 1
    if lo != consts['BSS']:
        raise MapError(f'the BSS starts at ${lo:08X}, not at the BSS window ${consts["BSS"]:08X}')
    window = consts['BSS'] + consts['BSS_BYTES']
    free = window - hi
    if free < consts['BSS_MARGIN']:
        raise MapError(f'the BSS is {hi - lo:,} bytes (${lo:08X}..${hi - 1:08X}); the BSS window '
                       f'${consts["BSS"]:08X}..${window - 1:08X} keeps {free:,} bytes free, less than '
                       f'#NES_MAP_BSS_MARGIN ({consts["BSS_MARGIN"]:,}). Re-derive the map in '
                       'anvil/memory_map.pi4 before the BSS reaches the stack.')
    return image, hi - lo, free
