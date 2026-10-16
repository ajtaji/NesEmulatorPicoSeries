# Modular output validation — 2026-10-16

Output API version 1 separates device callbacks from frame ownership and PCM
production. CPU, PPU, APU, and SBC codec source files match commit `df6baf0`.
The refactor moves ST7796/SPI/DMA operations into a video backend and exposes
generic audio callbacks/status while preserving the Bluetooth transport/codec
algorithms and its existing queue allowance.

The physical Pico 2 W on COM6 passed the full 1,926,732 emulator checks and
80 separate custom-output contract checks, each with zero failures. See
`modular-verification-board.txt` and `output-contract-board.txt`. The contract
suite covers pending frame ownership, completion/abort/timeout behavior, host
HUD isolation, sample order and signed values, partial reads, ring and counter
wraparound, clipping overruns, invalid requests, and the example PCM consumer.

The compile matrix (`output-build-matrix.json`) covers headless, custom, and
mixed video/audio choices on RP2350 and RP2040, checking UF2 family/bounds and
that unselected ST7796/CYW43439 driver globals are absent from the image. Both
normal public firmware images also compile. RP2040 was not attached for a new
hardware run; only the RP2350 has been tested on hardware after this refactor.

At 150 MHz with 75 MHz LCD SPI, the bundled ST7796 video and Bluetooth stereo
backend retained real-time behavior in all 40 sampled intervals of each game:

| Game | LCD FPS | Emulated FPS | PCM samples/s | New Bluetooth underruns |
|---|---:|---:|---:|---:|
| Mario | 60.047 | 60.097 | 47,996 | 0 |
| Contra | 60.022 | 60.097 | 47,997 | 0 |
| Castlevania | 60.021 | 60.096 | 47,994 | 0 |

All runs had zero emulator errors, no stopped CPU, `audio_live=1`, and no new
Bluetooth underruns beyond the one recorded during startup. See the matching
`modular-*-board.txt/json` files. These are bounded tests, not a compatibility
guarantee for all scenes or unimplemented devices. No physical DAC is installed;
the PCM example is a tested buffer consumer, not a validated DAC driver.

Public and private speaker-enabled builds both booted to the rotated menu.
After testing, the board is at its boot menu with game emulation/audio streaming
stopped. The existing ROM store and radio firmware were preserved. Firmware
hashes/bounds are in `modular-build-manifest.json`.
