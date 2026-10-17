# PureMetal NES for the Raspberry Pi Pico series

An NES (NTSC) emulator for the Raspberry Pi Pico family, written in PureMetal and
compiled with PureMetalForge to bare-metal machine code: no SDK and no RTOS.
Games are not part of the firmware. You load your own `.nes` files onto the
board's flash with a small Python tool, which has a window for everyday use and
a command line for scripts.

**No commercial game ROMs or private speaker configuration are included.** The
original synthetic demo cartridge is bundled for checks. Load games you are
entitled to use.

**[Download firmware from Releases](https://github.com/ajtaji/NesEmulatorPicoSeries/releases/latest).**
Choose the chip and display that match your hardware. All eight builds are
available as release assets; validation is specific to each board/display pair.

| Display | Pico W / RP2040 | Pico 2 W / RP2350 |
|---|---|---|
| LAFVIN ST7796 | [UF2 — hardware tested](https://github.com/ajtaji/NesEmulatorPicoSeries/releases/latest/download/nes-pico-w.uf2) | [UF2 — hardware tested](https://github.com/ajtaji/NesEmulatorPicoSeries/releases/latest/download/nes-pico2-w.uf2) |
| Pico Display Pack 2.0 ST7789 | [UF2 — display untested, 30 FPS target](https://github.com/ajtaji/NesEmulatorPicoSeries/releases/latest/download/nes-pico-w-display-pack2.uf2) | [UF2 — display untested, 60 FPS target](https://github.com/ajtaji/NesEmulatorPicoSeries/releases/latest/download/nes-pico2-w-display-pack2.uf2) |
| Standalone ILI9341 SPI1 | [UF2 — tested on bare Pico, 30 FPS](https://github.com/ajtaji/NesEmulatorPicoSeries/releases/latest/download/nes-pico-w-ili9341.uf2) | [UF2 — compile only, 30 FPS target](https://github.com/ajtaji/NesEmulatorPicoSeries/releases/latest/download/nes-pico2-w-ili9341.uf2) |
| Adafruit HX8357D SPI1 | [UF2 — tested on bare Pico, 30 FPS](https://github.com/ajtaji/NesEmulatorPicoSeries/releases/latest/download/nes-pico-w-hx8357d.uf2) | [UF2 — compile only, 30 FPS target](https://github.com/ajtaji/NesEmulatorPicoSeries/releases/latest/download/nes-pico2-w-hx8357d.uf2) |

ST7789 board-side transport tests ran without a connected panel. The Pico 2
ILI9341/HX8357D display combinations have not been tested on hardware. See the
[per-build validation and source versions](firmware/BUILD-VALIDATION.md) and
[download SHA-256 checksums](https://github.com/ajtaji/NesEmulatorPicoSeries/releases/latest/download/SHA256SUMS.txt).

[ILI9341 SPI1 display support](ILI9341.md) is selectable on both chips; the
bare Pico/module combination has been physically tested. Builds are in
`firmware/nes-pico-w-ili9341.uf2` and `firmware/nes-pico2-w-ili9341.uf2`.

[Adafruit HX8357D SPI1 output](HX8357D.md) is selectable on both chips, with
30 FPS presentation and a separate host FPS overlay. The bare Pico/module
combination has been physically tested; the Pico 2 build is compile-checked.

[Pimoroni Qw/ST Pad](QWSTPAD.md) I2C controllers are supported on both chips: one or two
pads on GP8/GP9 give players 1 and 2. Not yet run with a pad.

Display Pack physical-screen validation is pending. See [its driver notes](DISPLAY-PACK2.md)
and [current Pico compatibility/performance results](PICO-MMC3-NMI-RESULTS.md).

## Boards

| Board | Chip | Status |
|---|---|---|
| Raspberry Pi Pico W | RP2040 | Runs; measured on a board (below) |
| Raspberry Pi Pico | RP2040 | Board tested with ILI9341/HX8357D, USB controls and silent audio |
| Raspberry Pi Pico 2 W | RP2350 Arm | Runs; diagnostics and three-game board tests pass |
| Raspberry Pi Pico 2 | RP2350 Arm | Same port; not yet run on a board here (no Bluetooth audio) |
| Raspberry Pi 4 / Anvil | BCM2711 AArch64 | [Returning application, Neon/Vulkan, touch and Bluetooth](anvil/README.md) |
| Pimoroni Pico Plus 2 / Pico Plus 2 W | RP2350B + 8 MB PSRAM | Planned; not ported yet |
| Pimoroni Pico 2 W with a PSRAM kit | RP2350A + PSRAM | Planned; not ported yet |

Each chip family has its own folder (`rp2040/` and `rp2350/`). A port is added only after
it has run on a board.

The [Pi 4 / Anvil port](anvil/README.md) uses separate video, audio and input
modules, on-screen controls and host FPS counters. EXIT returns to Anvil.
Its touch ROM selector reads `.nes` files from `2:/NES` on the exFAT data
partition, so changing games needs no rebuild. The Pico flash ROM store remains
specific to the Pico firmware.

## Measured on a Pico W

At 200 MHz, with the display and Bluetooth audio running and 40 seconds per game,
three commercial cartridges (mapper 66 and two mapper-2 games) loaded from the ROM
store:

- 60.10 emulated frames per second; every one of the 40 seconds delivered 60;
- 1,789,766 CPU cycles per second, the NTSC rate;
- 47,998 audio samples per second, with zero Bluetooth underruns.

On the same board, the on-board test suite (`rp2040/Diagnostics/verify.picow`)
passes 1,926,732 checks with 0 failures.

## What you need

- A Pico W (or Pico) with the **LAFVIN ST7796 kit** wired as the firmware expects:

  | Signal | Pin |
  |---|---|
  | LCD SCK / MOSI | GP2 / GP3 (SPI0, 100 MHz) |
  | LCD CS / DC / RST | GP5 / GP6 / GP7 |
  | Button A / Button B | GP15 / GP14 (active low) |
  | Joystick X / Y | GP26 / GP27 (ADC) |

  Start is both buttons plus up; Select is both buttons plus down.
- Optional: one or two [Qw/ST Pad](QWSTPAD.md) controllers on GP8/GP9.
- Python 3 with `pyserial` (`py -3 -m pip install pyserial`) to load games.

## Pico 2 W

The RP2350 port uses both Cortex-M33 cores with the same computed-dispatch CPU,
PPU, APU, mapper events, and ROM-store format as the resolved RP2040 version.
The LAFVIN pinout and controls are the same. It runs at the Pico 2 W's nominal
150 MHz with 75 MHz LCD SPI.
Its screen is rotated 90 degrees left from the Pico W landscape orientation.
The unchanged 256x240 NES frame is centered at (32,120) on the 320x480 display;
the host FPS counter remains in the upper left, outside the emulated PPU.

Build the port with:

```
tools/build.ps1 -Compiler path\to\PureMetalForge.exe -Source rp2350/demo.pico2w -Output firmware/nes-pico2-w.uf2
tools/build.ps1 -Compiler path\to\PureMetalForge.exe -Source rp2350/Diagnostics/verify.pico2w -Output rp2350/Diagnostics/verify.uf2 -Port COM6 -Seconds 60 -VerifyNes
```

On the physical Pico 2 W (COM6), the full suite passes **1,926,732 checks with
zero failures**. It includes the mapper/DMC ordering, renderer comparisons, CPU
vectors, audio shutdown, byte-exact SBC vectors, and ROM-store flash operations.
CPU-only test loops execute 2,000,202 guest cycles in 319,760 microseconds and
2,000,030 guest cycles in 366,746 microseconds at 150 MHz. These are synthetic
CPU measurements, not game frame rates or guest instruction rates.
Raw output is in `rp2350/Diagnostics/verification-board.txt`; game measurements
and the test procedure are documented in `rp2350/README.md`.

Final 40-second samples with the LCD and Bluetooth stereo active:

| Game | Displayed FPS | Emulated FPS | PCM samples/second | New Bluetooth underruns |
|---|---:|---:|---:|---:|
| Mario / Duck Hunt cartridge, Mario gameplay | 60.047 | 60.097 | 47,996 | 0 |
| Contra | 60.022 | 60.097 | 47,997 | 0 |
| Castlevania | 60.021 | 60.096 | 47,994 | 0 |

All three had zero emulator errors, no stopped CPU, and at least 60 emulated
frames in each sampled interval. The startup underrun counter was 1 and remained
1 throughout each run. Contra's picture and sound were also confirmed by the
operator. These finite tests do not establish compatibility with every game.
The public boot menu measured 60.10 displayed FPS over ten steady intervals;
the first initialization interval is retained separately in its raw log.

`py -3 tools/port_rp2350.py` regenerates the port from the RP2040 sources. The
changes select RP2350 libraries, use the two-M33 launch library, replace the
absent SIO divider with M33 division, adapt SIO GPIO addresses and SPI/DMA request
layout, and spell one assembly register list explicitly. RP2040 files are not
modified by regeneration. Compiler and board libraries require no changes.

Use the same ROM loader with `--target rp2350 --port COM6`. The directory
stays at `$50000`; Pico 2 W game data can extend to `$1FEFFF`. The Pico 2 W radio firmware belongs at flash
offset **$200000** (the Pico W uses $100000). Install the RP2350-specific
`wb43439A0-7.95.49.00.combined.uf2` supplied with PureMetalForge before enabling
Bluetooth. Published firmware has no private speaker address.

## Getting started

1. Hold BOOTSEL while plugging in the Pico, then copy `firmware/nes-pico-w.uf2`
   to the drive that appears. For a Pico 2 W use `firmware/nes-pico2-w.uf2`.
2. Load games: double-click `tools/rom_loader_ui.pyw`, add your `.nes` files
   (their order is the boot menu's order), choose the board's port and target (`rp2040` or `rp2350`), and press
   **Load onto board**. Three games take about 7 seconds.
3. On the board, choose a game in the boot menu with the joystick and press A.

From a command line:

```
py -3 tools/rom_loader.py "My Game.nes" "Another Game.nes"
py -3 tools/rom_loader.py --target rp2350 --port COM6 "My Game.nes"
py -3 tools/rom_loader.py --dry-run "My Game.nes"
py -3 tools/rom_loader.py --clear
```

With more than one Pico attached, name the port with `--port`; the window asks
you to choose one. Loading reboots the chosen board into its boot menu.

## Supported games

- Pico W: **0, 2, 3, 7, 11, 34 (BNROM), 41, 66, 71, 79, 144, 148, 232**.
- Pico 2 W adds **1, 4, 13, 47, 118, 119, 206**, plus NINA-001 mapper 34.
- NTSC only. Mapper board sizes, submappers and RAM must fit the supported
  profile. Trainers, four-screen boards and battery-save persistence are excluded.
- Up to 63 games in **696 KiB** (Pico W) or **1720 KiB** (Pico 2 W).
  Prebuilt PRG views and predecoded CHR count toward this space.
- Update the firmware before using the new loader's version-2 packs. The loader
  checks the connected board's profile and flash boundary before erasing.

See [Pico cartridge support](PICO-MAPPERS.md) for hardware limits, board tests
and performance exceptions. Supported mapper IDs do not promise every game or
60 FPS in every workload.

## How the ROM store works

| Flash offset | Contents |
|---|---|
| `$00000` | Firmware (must end below `$50000`) |
| `$50000` | Directory: titles, mappers, sizes, CRC-32 of every game |
| `$51000`Ã¢â‚¬â€œ`$FEFFF` | Game data |
| `$FF000` | Sector reserved for the board tests |
| `$100000` (Pico W) / `$200000` (Pico 2 W) | Bluetooth radio firmware |

The loader runs inside the firmware's boot menu. The tool sends each 4 KiB with a
CRC; the board writes it, reads it back and checks it. The directory is erased
first and written last, so an interrupted load leaves an empty store, never a
half-written one. At every boot the board checks each game's CRC and leaves out,
with a printed reason, anything damaged. With no games stored it shows a built-in
demo cartridge.

## Audio

Video and audio are independently selectable compile-time plugins. The bundled
ST7796/DMA and Bluetooth backends are selected by the normal wrappers; headless,
silent, and custom outputs can be selected independently. See [OUTPUTS.md](OUTPUTS.md)
for the RGB565/PCM interfaces, ownership rules, custom wrappers, and examples.
Replacing a screen or audio device does not require editing CPU/PPU/APU code.
On Pico 2 W, the output-interface suite passes 80 checks in addition to the full
1,926,732 emulator checks. The modular build retains approximately 60 displayed
FPS and 48,000 PCM samples/second in the three 40-second game tests. Details are
in `rp2350/Diagnostics/MODULAR-OUTPUT-RESULTS.md`; fresh RP2040 physical runs with these interfaces are included in the
[Pico mapper results](PICO-MAPPERS-RESULTS.md).

The bundled hardware audio backend is **Bluetooth A2DP**
(SBC, 48 kHz stereo) on the Pico W's CYW43439 radio, which was built to verify
that the emulated audio is correct. The published firmware has no speaker
configured and is therefore silent. To use a speaker, build your own firmware
with its address (see *Building*).

## How it works

- **Core 0** runs the 2A03 CPU (computed-dispatch interpreter) and the PPU. The
  PPU is timestamped per instruction and renders runs of 8-pixel spans from a
  converted-row RGB565 cache. Sprites follow the NES priority rules, including
  sprite-zero hit.
- **Core 1** runs the APU (fed timestamped events through a lock-free queue), the
  LCD DMA (a whole frame is completed before it is sent), and the Bluetooth SBC
  encoder and transport.
- Immutable PRG-view switches remain queued events for DMC ordering. Pico 2 W
  MMC1/MMC3 windows fence the audio worker before changing shared bank data.

Accuracy limits: the PPU is not dot-exact (mid-scanline changes take effect at
8-pixel granularity), only documented CPU opcodes are implemented, and some
DMC/OAM/IRQ edge timing is approximate. Only NTSC is supported.

## Building

You need PureMetalForge (the PureMetal compiler). From PowerShell:

```
tools/build.ps1 -Compiler path\to\PureMetalForge.exe
```

This builds `rp2040/demo.picow` into `firmware/nes-pico-w.uf2`. Any image must end
below flash offset `$50000`; the build script and `tools/upload_pack.py` refuse
one that would overwrite the ROM store.
Validation happens before uploading. The uploader's `--target rp2040` or
`--target rp2350` checks the image's UF2 family before sending it to the selected
port. Never send a firmware image for one chip to the other chip's board.

To build with a Bluetooth speaker, make your own wrapper file next to
`rp2040/demo.picow` that includes `runtime.pico` and `cartridge.pico` and then
sets the speaker before `Main()`. On Pico 2 W, copy `rp2350/demo.pico2w` to a
private `.pico2w` wrapper and retain its `.pico2` includes:

```
DataSection
MySpeaker:
  Data.a $66,$55,$44,$33,$22,$11   ; 11:22:33:44:55:66, least significant byte first
EndDataSection
NesBluetoothSetPeer(?MySpeaker)
Main()
```

Keep that file out of version control if you don't want your speaker's address
published.

Generated sources are produced by scripts in `rp2040/` and reproduce
byte-for-byte: `generate_cpu.py` (the 2A03 core, from `nmos6502.pico`; needs
`py65`), `generate_ppu.py` (the renderer), `make_demo.py` (the built-in demo
cartridge), `make_sbc_vectors.py` and `Diagnostics/generate_zp_vectors.py`
(test vectors).

## Testing on a board

```
tools/build.ps1 -Compiler path\to\PureMetalForge.exe -Source rp2040/Diagnostics/verify.picow -Output rp2040/Diagnostics/verify.uf2 -Port COM7 -Seconds 60 -VerifyNes
```

The suite compares the optimized renderer, sprite evaluation and CPU against
independent reference implementations. It also covers controller logic, the APU,
the SBC encoder (byte-exact vectors), the ROM store's flash writes and CRC, and a
CPU throughput benchmark. It reports `NES board checks=N failures=0 PASS`.
`tools/capture.py` saves a framebuffer or the PCM ring from a running board.

## Repository layout

```
firmware/   ROM-free firmware images
rp2040/     firmware sources, generators and Diagnostics/ (board tests) for RP2040
rp2350/     reproducible Arm Pico 2 W port and the same board tests
tools/      ROM loader (window and command line), firmware upload, build, capture
licenses/   third-party licences
```

## Pico Display Pack 2.0

Select the ST7789 display plugin on either Pico with
`tools/build.ps1 -Target rp2040 -Display display-pack2` or `-Target rp2350`.
See [DISPLAY-PACK2.md](DISPLAY-PACK2.md) for wiring, the separate UF2 downloads,
FPS counter placement and hardware validation status. LAFVIN remains the default.

## Licence

MIT (see `LICENSE`). The CYW43439 Bluetooth firmware is included under its own
licences (`licenses/CYW43439-*.txt`). The SBC prototype filter coefficients are
cross-checked against BlueZ (`licenses/SBC-TABLES.md`, LGPL-2.1).

The [Pi 4 / Anvil port](anvil/README.md) supports 30 mapper IDs, including
MMC1/2/3/5, NINA, Codemasters, Namco 108, RAMBO, Sunsoft, TQROM and multicarts.
Its touch MENU button returns from a game to the exFAT ROM selector; EXIT
returns to Anvil. See the port documentation for board limits, measured
results and remaining compatibility/performance issues. Pico profiles are
documented separately in [PICO-MAPPERS.md](PICO-MAPPERS.md).

Current Pico interrupt and MMC3 work, native verification and performance limits:
[PICO-MMC3-NMI-RESULTS.md](PICO-MMC3-NMI-RESULTS.md).
