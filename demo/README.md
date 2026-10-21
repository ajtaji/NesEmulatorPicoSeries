# PureMetal NES demo

A demo for the NES - and for this emulator - written entirely in PureMetal, with no inline
assembly, and compiled for the 6502 by PureMetal Forge.

- "PUREMETAL" in big shaded letters, fading in from black and shimmering through a band of hues
- three layers of stars drifting at three speeds (sprites)
- "PUREMETAL NES" in rainbow sprite letters riding a sine wave
- a marquee along the bottom that scrolls while the picture above it stands still (a sprite-0
  split)
- an original four-channel tune on the 2A03: two pulses, triangle bass and noise drums

`PureMetalDemo.nes` is the built cartridge: NTSC, mapper 2 (UxROM) with CHR RAM, 32 KB of program.
Load it like any game: `py -3 tools/rom_loader.py --target rp2350 --port COM6 demo/PureMetalDemo.nes`
(or the loader window). It runs at 60 frames a second on the Pico W and the Pico 2 W, and plays on a
Bluetooth speaker with the speaker builds.

## Files

| File | What it is |
|---|---|
| `demo.nes6502` | the program |
| `demo_assets.nes6502` | the tiles, tables and song, generated - do not edit |
| `make_demo_assets.py` | makes `demo_assets.nes6502`: `py -3 demo/make_demo_assets.py` (needs Pillow); `--check` says whether the committed file is current |
| `PureMetalDemo.nes` | the cartridge built from `demo.nes6502` |

## Building

```
PureMetalForge.exe --compile demo/demo.nes6502 -o demo/PureMetalDemo.hex
```

The `.nes6502` extension selects PureMetal Forge's Nintendo Entertainment System board: code at
$8000, the compiler writes the vectors and calls the program's `NMI()` at every vertical blank, and a
`.nes` cartridge is written beside the `.hex`. That board, interrupt handlers and DataSection tables
on the 6502, and the 6502 code optimiser the demo needs to fit its frame, are in the PureMetal Forge
release after 2026-10-19; an earlier compiler refuses this source.

## Credits

The logo is rendered from Lato Regular (SIL Open Font License 1.1, `fonts/source/lato/OFL.txt`). The
8x8 font, the music and the program are original to this demo, under the repository's MIT licence.
