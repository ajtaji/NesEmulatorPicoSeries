"""Reproduce the Arm Pico 2 W port from the tested RP2040 implementation.

Emulated CPU/PPU/APU behavior is shared. Substitutions below concern board
libraries, SIO register addresses, SPI/DMA layout and the target identification.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def port(text, name):
    # Spell the same register list explicitly for the RP2350 assembler.
    text = text.replace('{r1-r4}', '{r1,r2,r3,r4}')
    text = re.sub(r'(XIncludeFile "[^"]*)\.picow"', r'\1.pico2w"', text)
    text = re.sub(r'(XIncludeFile "[^"]*)\.pico"', r'\1.pico2"', text)
    text = text.replace('RP2040/Lib/', 'RP2350/Lib/')
    text = text.replace('multicore_launch()', 'NesLaunchCore1()')
    if name == 'bt_radio.pico':
        # RP2350 SIO has interleaved high-GPIO registers: SET/CLR/OE moved.
        addresses = {'$D0000014': '$D0000018', '$D0000018': '$D0000020',
                     '$D0000024': '$D0000038', '$D0000028': '$D0000040'}
        text = re.sub(r'\$D00000(?:14|18|24|28)', lambda m: addresses[m[0]], text)
        text = text.replace('; RP2040 CYW43439', '; RP2350 CYW43439')
    if name == 'display.pico':
        # One quarter-turn left from landscape: center the unchanged NES frame
        # in the controller's 320x480 portrait coordinate space.
        text = text.replace('Tft796Window(112,40,367,279)', 'Tft796Window(32,120,287,359)')
        text = text.replace('$4003C008', '$40080008').replace('$4003C024', '$40080024').replace('$4003C00C', '$4008000C')
        text = text.replace('#SPI_DMA_TREQ_SPI0_TX<<15', '#SPI_DMA_TREQ_SPI0_TX<<#SPI_DMA_TREQ_SHIFT')
    if name == 'math.pico':
        # All NES call sites divide nonnegative bounded timing/count values.
        # The RP2040 SIO divider does not exist on RP2350; M33 has native divide.
        text = '''; Nonnegative NES timing/count division using the M33 divider.
ProcedureRAM.i NesDiv(dividend.i, divisor.i)
  ProcedureReturn dividend/divisor
EndProcedure
'''
    if name == 'rom_store.pico':
        text = text.replace('; $100000 up is the Bluetooth radio firmware',
                            '; $200000 up is the Bluetooth radio firmware')
    if name == 'runtime.pico':
        text = text.replace('Tft796Rotate(1)', 'Tft796Rotate(0)')
        text = text.replace('ClockInitKhz(200000)', 'ClockInitKhz(150000)')
        text = text.replace('SpiPeriFromSys(200000)', 'SpiPeriFromSys(ClockSysConfigKhz())')
        text = 'XIncludeFile "RP2350/Lib/multicore_smp.pico2"\n' + text
        text += '''\nProcedure.i NesLaunchCore1()
  McCore1ReleaseHold()
  If McLaunchCore1()=6 : ProcedureReturn 1 : EndIf
  ProcedureReturn 0
EndProcedure
'''
        text = text.replace('NES PureMetal RP2040', 'NES PureMetal RP2350')
    if name == 'hud.pico':
        text = text.replace('(112,40,256,240)', '(32,120,256,240)')
    if name.endswith('.picow'):
        text = '#CLOCK_KHZ=150000\n' + text
        text = text.replace('ClockInitKhz(200000)', 'ClockInitKhz(150000)')
        text = text.replace('NesDiv(t*200,', 'NesDiv(t*150,')
    return '\n'.join(line.rstrip() for line in text.split('\n'))


def main():
    count = 0
    for source in (ROOT / 'rp2040').rglob('*'):
        if source.suffix not in ('.pico', '.picow'):
            continue
        target = ROOT / 'rp2350' / source.relative_to(ROOT / 'rp2040')
        target = target.with_suffix('.pico2w' if source.suffix == '.picow' else '.pico2')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(port(source.read_text(encoding='utf-8'), source.name), encoding='utf-8', newline='\n')
        count += 1
    print(f'Regenerated {count} RP2350 files from rp2040 (150 MHz, 75 MHz LCD SPI)')


if __name__ == '__main__':
    main()
