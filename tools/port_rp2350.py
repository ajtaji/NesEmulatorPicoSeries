"""Reproduce the Arm Pico 2 W port from the tested RP2040 implementation.

Emulated CPU/PPU/APU behavior is shared. Substitutions below concern board
libraries, SIO register addresses, SPI/DMA layout, cartridge RAM profiles,
flash boundaries and target identification.
"""
from pathlib import Path
import re
from pico_prg_pages import paged_fetch,dual_cpu

ROOT = Path(__file__).resolve().parents[1]


def port(text, name):
    if name=='cpu2a03.pico':
        text=dual_cpu(text)
    elif name=='bridge.pico':
        text=paged_fetch(text,name)
    # Spell the same register list explicitly for the RP2350 assembler.
    text = text.replace('{r1-r4}', '{r1,r2,r3,r4}')
    text = re.sub(r'(XIncludeFile "[^"]*)\.picow"', r'\1.pico2w"', text)
    text = re.sub(r'(XIncludeFile "[^"]*)\.pico"', r'\1.pico2"', text)
    text = text.replace('RP2040/Lib/', 'RP2350/Lib/')
    text = text.replace('multicore_launch()', 'NesLaunchCore1()')
    if name == 'video_st7796.pico':
        # One quarter-turn left from landscape: center the unchanged NES frame
        # in the controller's 320x480 portrait coordinate space.
        text = text.replace('Tft796Window(112,40,367,279)', 'Tft796Window(32,120,287,359)')
        text = text.replace('$4003C008', '$40080008').replace('$4003C024', '$40080024').replace('$4003C00C', '$4008000C')
        text = text.replace('#SPI_DMA_TREQ_SPI0_TX<<15', '#SPI_DMA_TREQ_SPI0_TX<<#SPI_DMA_TREQ_SHIFT')
        text = text.replace('SpiPeriFromSys(200000)', 'SpiPeriFromSys(ClockSysConfigKhz())')
        text = text.replace('Tft796Rotate(1)', 'Tft796Rotate(0)')
    if name == 'video_st7789.pico':
        text = text.replace('$D0000014', '__ST7789_SET__').replace('$D0000018', '$D0000020').replace('__ST7789_SET__', '$D0000018')
        text = text.replace('$4003C008', '$40080008').replace('$4003C024', '$40080024').replace('$4003C00C', '$4008000C')
        text = text.replace('#SPI_DMA_TREQ_SPI0_TX<<15', '#SPI_DMA_TREQ_SPI0_TX<<#SPI_DMA_TREQ_SHIFT')
        text = text.replace('St7789SpiKhz.i=62500', 'St7789SpiKhz.i=75000')
        text = text.replace('St7789FrameDivider.i=2', 'St7789FrameDivider.i=1')
    if name == 'st7789.picow':
        text = text.replace('$4003C024', '$40080024').replace('$4003C000', '$40080000')
    if name == 'display_id.pico':
        text = text.replace('Standalone RP2040', 'Standalone RP2350').replace('DISPLAY_ID RP2040', 'DISPLAY_ID RP2350')
    if name in ('video_ili9341.pico', 'video_hx8357d.pico'):
        text = text.replace('$D0000014', '__ILI9341_SET__').replace('$D0000018', '$D0000020').replace('__ILI9341_SET__', '$D0000018')
        text = text.replace('$40040008', '$40088008').replace('$40040024', '$40088024').replace('$4004000C', '$4008800C')
        text = text.replace('#SPI_DMA_TREQ_SPI1_TX<<15', '#SPI_DMA_TREQ_SPI1_TX<<#SPI_DMA_TREQ_SHIFT')
    if name in ('ili9341.picow', 'hx8357d.picow', 'hx8357d_output.picow'):
        text = text.replace('$40040024', '$40088024').replace('$40040000', '$40088000')
    if name == 'math.pico':
        # All NES call sites divide nonnegative bounded timing/count values.
        # The RP2040 SIO divider does not exist on RP2350; M33 has native divide.
        text = '''; Nonnegative NES timing/count division using the M33 divider.
ProcedureRAM.i NesDiv(dividend.i, divisor.i)
  ProcedureReturn dividend/divisor
EndProcedure
'''
    if name == 'mappers.pico':
        # Hot bus adapters must share SRAM with the computed-dispatch CPU.
        for proc in ('PicoMapperWrite','PicoNtRead','PicoNtWrite','PicoMirrorSet','PicoInvalidateChr','PicoChrSwitch','PicoChrFour','PicoRamRead','PicoChrWrite','PicoRegisterNotice','PicoWorkerPrgSet'):
            text=re.sub(r'Procedure(\.i)? '+proc+r'\(',lambda m:'ProcedureRAM'+(m[1] or '')+' '+proc+'(',text)
    if name == 'ppu.pico':
        # The background tile cache at 2048 entries (40 KB with its tags), from 1024: SMB3 shows more
        # distinct tile rows than 1024 hold, and missed ~100k rows a second; at 2048 the capacity
        # misses are gone (4096 gives no more). The Pico W keeps 1024 for its SRAM. The tile loop's
        # hash mask is 11 bits in tools/m33/ppu_render_tile.s, the RP2350's only form of that loop.
        for old, new in (('Global Dim RgbCache.i(4096)', 'Global Dim RgbCache.i(8192)'),
                         ('Global Dim RgbTags.i(1024)', 'Global Dim RgbTags.i(2048)'),
                         ('  For i=0 To 1023'+chr(10), '  For i=0 To 2047'+chr(10)),
                         ('  For i=0 To 1023'+chr(13)+chr(10), '  For i=0 To 2047'+chr(13)+chr(10))):
            text = text.replace(old, new)
        if 'RgbTags.i(2048)' not in text or 'For i=0 To 2047' not in text:
            raise SystemExit('ppu.pico: the tile cache size lines were not found')
    if name == 'dmc_shadow.pico':
        # Core 0 runs it at every sync while a sample plays; the RP2040 keeps it in flash for SRAM.
        for proc in ('SdFetch','SdAdvance','SdWrite','SdBudget'):
            text=re.sub(r'Procedure(\.i)? '+proc+r'\(',lambda m:'ProcedureRAM'+(m[1] or '')+' '+proc+'(',text)
    if name == 'state.pico':
        # The Pico 2 W has 520 KB of SRAM: a 170 ms PCM ring and a 130 ms Bluetooth lead, so a
        # busy scene the emulator runs a few frames late never reaches the speaker as silence.
        text = text.replace('#NES_AUDIO_RING_SAMPLES=4096 ', '#NES_AUDIO_RING_SAMPLES=8192 ')
        text = text.replace('#NES_BT_LEAD_US=65000 ', '#NES_BT_LEAD_US=130000')
    if name == 'mapper_state.pico':
        text = text.replace('#PICO_ADVANCED=0', '#PICO_ADVANCED=1')
    if name == 'rom_store.pico':
        text = text.replace('$FF000', '$1FF000').replace('$FEFFF', '$1FEFFF')
        # The Pico 2 W's flash is 4 MB: the link key sits in its last sector.
        text = text.replace('#ROMSTORE_BTKEY = $1FF000', '#ROMSTORE_BTKEY = $3FF000')
        text = text.replace('; $100000 up is the Bluetooth radio firmware',
                            '; $200000 up is the Bluetooth radio firmware')
    if name == 'runtime.pico':
        text = text.replace('ClockInitKhz(200000)', 'ClockInitKhz(150000)')
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
    text = splice_m33(text, name)
    return '\n'.join(line.rstrip() for line in text.split('\n'))


def splice_m33(text, name):
    """Hand-written Thumb-1 that has a faster Cortex-M33 form: the RP2040 source marks the span with
    '; M33 tools/m33/<file>' ... '; END M33' inside its ASM block, and the RP2350 copy gets the file's
    Thumb-2 in its place. A marker without its end, or a file that is missing, stops the port."""
    out, lines, i = [], text.split('\n'), 0
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped.startswith('; M33 tools/m33/'):
            snippet = ROOT / stripped.split()[2]
            end = next((j for j in range(i + 1, len(lines)) if lines[j].strip() == '; END M33'), None)
            if end is None:
                raise SystemExit(f'{name}: "{stripped}" has no "; END M33" after it')
            if not snippet.is_file():
                raise SystemExit(f'{name}: {snippet} named by an M33 marker does not exist')
            out.append('    ; Cortex-M33 form from ' + stripped.split()[2] + ' (the RP2040 source holds the Thumb-1 form)')
            out += snippet.read_text(encoding='utf-8').rstrip('\n').split('\n')
            i = end + 1
            continue
        out.append(lines[i])
        i += 1
    return '\n'.join(out)


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
