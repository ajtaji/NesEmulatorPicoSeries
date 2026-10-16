# PureMetal NES for the Raspberry Pi Pico series

An NES (NTSC) emulator for the Raspberry Pi Pico family, written in PureMetal and
compiled with PureMetalForge to bare-metal machine code: no SDK and no RTOS.
Games are not part of the firmware. You load your own `.nes` files onto the
board's flash with a small Python tool, which has a window for everyday use and
a command line for scripts.

**This repository contains no ROMs and no firmware with ROMs in it.** Use games
you are entitled to use.

## Boards

| Board | Chip | Status |
|---|---|---|
| Raspberry Pi Pico W | RP2040 | Runs; measured on a board (below) |
| Raspberry Pi Pico | RP2040 | Same firmware; not yet run on a board here (no Bluetooth audio) |
| Raspberry Pi Pico 2 / Pico 2 W | RP2350 | Planned; not ported yet |
| Pimoroni Pico Plus 2 / Pico Plus 2 W | RP2350B + 8 MB PSRAM | Planned; not ported yet |
| Pimoroni Pico 2 W with a PSRAM kit | RP2350A + PSRAM | Planned; not ported yet |

Each chip family has its own folder (`rp2040/` today). A port is added only after
it has run on a board.

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
- Python 3 with `pyserial` (`py -3 -m pip install pyserial`) to load games.

## Getting started

1. Hold BOOTSEL while plugging in the Pico, then copy `firmware/nes-pico-w.uf2`
   to the drive that appears.
2. Load games: double-click `tools/rom_loader_ui.pyw`, add your `.nes` files
   (their order is the boot menu's order), choose the board's port, and press
   **Load onto board**. Three games take about 7 seconds.
3. On the board, choose a game in the boot menu with the joystick and press A.

From a command line:

```
py -3 tools/rom_loader.py "My Game.nes" "Another Game.nes"
py -3 tools/rom_loader.py --dry-run "My Game.nes"
py -3 tools/rom_loader.py --clear
```

With more than one Pico attached, name the port with `--port`; the window asks
you to choose one. Loading reboots the chosen board into its boot menu.

## Supported games

- Mappers 0 (NROM), 2 (UxROM with 8 KiB CHR RAM) and 66 (GxROM), NTSC.
- CHR ROM up to 16 KiB; no cartridge work RAM, trainers or battery saves.
- Anything else is refused by name when you add it, before the board is touched.
- The ROM store holds 712 KiB and up to 63 games.

## How the ROM store works

| Flash offset | Contents |
|---|---|
| `$00000` | Firmware (must end below `$50000`) |
| `$50000` | Directory: titles, mappers, sizes, CRC-32 of every game |
| `$51000`–`$FEFFF` | Game data |
| `$FF000` | Sector reserved for the board tests |
| `$100000` | Bluetooth radio firmware |

The loader runs inside the firmware's boot menu. The tool sends each 4 KiB with a
CRC; the board writes it, reads it back and checks it. The directory is erased
first and written last, so an interrupted load leaves an empty store, never a
half-written one. At every boot the board checks each game's CRC and leaves out,
with a printed reason, anything damaged. With no games stored it shows a built-in
demo cartridge.

## Audio

Audio output is meant to be modular. Today the one output is **Bluetooth A2DP**
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
- Bank switches are queued events, so the DMC channel on core 1 reads the right
  bank without stopping core 0.

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

To build with a Bluetooth speaker, make your own wrapper file next to
`rp2040/demo.picow` that includes `runtime.pico` and `cartridge.pico` and then
sets the speaker before `Main()`:

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
tools/      ROM loader (window and command line), firmware upload, build, capture
licenses/   third-party licences
```

## Licence

MIT (see `LICENSE`). The CYW43439 Bluetooth firmware is included under its own
licences (`licenses/CYW43439-*.txt`). The SBC prototype filter coefficients are
cross-checked against BlueZ (`licenses/SBC-TABLES.md`, LGPL-2.1).
