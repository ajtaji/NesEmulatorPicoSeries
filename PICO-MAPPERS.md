# Pico cartridge mapper profiles

Both targets keep the computed-dispatch CPU, native PPU pixel renderer, base APU,
SBC codec, Bluetooth transport and output plugin interfaces. Cartridge adapters
add memory windows, mirroring, RAM protection and mapper IRQs. No game-specific
CPU timing, renderer or audio settings are used.

## Supported profiles

| Mapper | Board family | Pico W | Pico 2 W |
|---:|---|---|---|
| 0 | NROM | Yes | Yes |
| 1 | MMC1, standard boards up to 256 KiB PRG | No | Yes |
| 2 | UxROM | Yes | Yes |
| 3 | CNROM | Yes | Yes |
| 4 | MMC3 | No | Yes |
| 5 | MMC5 (Castlevania III), scanline IRQ; MMC5 sound not emulated | No | Yes |
| 7 | AxROM, one-screen mirroring | Yes | Yes |
| 11 | Color Dreams | Yes | Yes |
| 13 | CPROM, 16 KiB CHR RAM | No | Yes |
| 19 | Namco 163, with its wavetable sound | No | Yes |
| 24, 26 | Konami VRC6, with its sound | No | Yes |
| 34 | BNROM / NINA-001 | BNROM | Both |
| 41 | Caltron | Yes | Yes |
| 47 | MMC3 multicart | No | Yes |
| 66 | GxROM | Yes | Yes |
| 69 | Sunsoft FME-7, with the 5B's sound | No | Yes |
| 71 | Codemasters, including BF9097 mirroring | Yes | Yes |
| 79 | NINA-03/06 | Yes | Yes |
| 118 | TxSROM | No | Yes |
| 119 | TQROM, mixed CHR ROM/RAM | No | Yes |
| 144 | Death Race bus-conflict variant | Yes | Yes |
| 148 | Sachen | Yes | Yes |
| 206 | Namco 108 | No | Yes |
| 232 | Camerica multicart, including submapper 1 | Yes | Yes |

These are bounded hardware profiles, not a guarantee that every ROM using an ID
works. The parser checks board sizes and submappers. NTSC and PAL (from the header or a PAL region tag in the file name); trainers,
four-screen boards, MMC1 outer-bank variants and persistent battery saves are
excluded. Cartridge RAM is volatile. The native PPU remains instruction-timestamped,
with its existing 8-pixel rendering granularity and approximate edge behavior.
The normal wrappers use NES_SPLIT=2 and two decoded CHR windows; retain these for
the added cartridge adapters.

The authorized USA folder has 857 files. The loader accepts 334 individually on
Pico W and 811 on Pico 2 W with these profiles and their flash limits. These are
header/geometry checks, not 334/811 completed gameplay tests.

## Memory and bus ordering

Pico W retains immutable 32 KiB PRG views in flash, including paired switchable
and fixed banks for mappers 71 and 232. The existing queued PRG event makes the
APU's DMC reads use the correct view. No PRG copying occurs during a switch.
CHR ROM has a raw copy and a predecoded copy in flash. The selected decoded bank
uses the existing 16 KiB allocation; CHR changes flush converted-row cache tags.
An additional 2 KiB CIRAM backing preserves physical nametable pages through
one-screen and mirroring changes. Native rendering reads the existing mirrored
nametable arrays and descriptors.

Pico 2 W uses four immutable 8 KiB PRG pointers, 8 KiB PRG RAM and 16 KiB
CHR RAM plus decoded backing. CPU and APU have separate pointer tables. A
timestamped mapping event lets earlier DMC reads finish against the old banks,
without copying PRG or fencing the audio worker on each switch. Flat and paged
computed-dispatch loops share generated opcode semantics; the loop is selected
once per CPU window. Operand reads crossing an 8 KiB boundary use the bus path.

MMC3's A12 observer batches constant regions and reuses native sprite evaluation.
A bounded, non-mutating IRQ preview replaces one-instruction windows when the
next IRQ is farther away. PPU bus changes invalidate that horizon. Masked IRQs
use normal windows; CLI/PLP/RTI boundaries now preserve their interrupt latency.
An NMI raised on the final PPUCTRL write cycle permits the following instruction
before interrupt entry. These are general interrupt/bus fixes, not ROM patches.
The pixel renderer, base APU, SBC codec and Bluetooth output remain unchanged.

Public builds retain 2,660 bytes free SRAM on RP2040 and 175,232 bytes on RP2350,
after compiler-reserved stacks/windows. System clocks remain 200 MHz / 150 MHz.
The same LAFVIN wiring, completed-frame DMA, host FPS overlay and Pico 2 W left
rotation remain in use. Video/audio plugins do not depend on the mapper profile.

## Loading ROMs

Update firmware before using version-2 packs. In the window, choose the USB port
and target: rp2040 for Pico W, rp2350 for Pico 2 W. The CLI equivalents are:

```
py -3 tools/rom_loader.py --target rp2040 --port COM7 "Game.nes"
py -3 tools/rom_loader.py --target rp2350 --port COM6 "Game.nes"
```

Firmware ends before $50000. The directory remains at $50000, data starts at
$51000. The W store ends before $FF000 (696 KiB); the 2 W store ends before
$1FF000 (1720 KiB). The following sector is reserved for diagnostics. Radio
firmware begins at $100000 / $200000 respectively and is preserved.
Version-2 entries record submapper, PRG RAM presence and predecoded CHR. Firmware
reads the original version-1 format too. The loader checks the connected board's
version/profile and advertised flash boundary before erasing. CRC/readback checks
and directory-last commit remain in use. PRG views and predecoded CHR take more
space than the original .nes file; the loader shows actual store use.

## Validation

The final native suites pass 1,926,732 checks on Pico W and 1,928,288 on
Pico 2 W, with zero failures. Focused mapper/interrupt suites pass 575 and
59,923 checks respectively. The latter includes randomized A12/reference
comparisons, non-mutating IRQ horizon predictions, CPU-register canaries,
bank-boundary operands, DMC ordering and CLI/PLP/RTI/NMI regression cases.
Independent renderer, APU shutdown and byte-exact stereo SBC tests remain in
the full suite. See [MMC3/NMI results](PICO-MMC3-NMI-RESULTS.md) for the current
measurements and limits; [the original port results](PICO-MAPPERS-RESULTS.md)
are retained as a historical baseline. Finite board samples are not full-game
validation. Some MMC3 workloads still fall below 60 FPS.

## Remaining mappers

MMC2, RAMBO-1, the other Sunsoft boards and the remaining Anvil-only boards are not exposed by
these Pico profiles. (MMC5, Namco 163, VRC6 and Sunsoft FME-7 run on the Pico 2 W.
Not drawn yet: MMC5's extended-attribute mode and vertical split, and Namco 163
nametables taken from CHR ROM.) Their extra pattern-fetch, extended nametable, IRQ or sound
requirements need a separate native-renderer adapter and validation. Pico W's
remaining SRAM also prevents the additional RAM and advanced mapper profile used on Pico 2 W.
They are refused rather than silently run as another mapper.
