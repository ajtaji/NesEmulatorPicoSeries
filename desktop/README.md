# PureMetal NES on the desktop

The boards' NES emulator as a Windows program, written in PureBasic and drawn with the Neon Arcade
Display Engine. It runs the same CPU, PPU and APU as the boards, with the same mappers. The game is
in the window at 60 Hz (50 Hz for PAL games), with sound, a keyboard or gamepad, a ROM picker, and
debug panes: CPU, PPU, OAM, APU, mapper and ROMs.

## Where the emulation comes from

`desktop/core/` is **generated** — do not edit it. `tools/port_desktop.py` translates Anvil's
portable core (`anvil/*.pi4`, itself generated from the Pico sources) into PureBasic. On the way it:

- turns the CPU's computed `Goto Dispatch(Tmp)` into a C computed goto (labels-as-values);
- wraps PureMetal's 0/1 comparisons in `Bool()`;
- maps Anvil's fixed Pi work areas onto `AnvilWindow`, an ordinary allocation;
- writes `declares.pbi`;
- patches in what the Pico has and Anvil does not yet:
  - **PAL timing** — the Pico's `NesTiming` globals, and its CPU-cycle ↔ PPU-dot conversions in the
    PPU, the worker, MMC3/MMC5 and the APU;
  - the hooks for **VRC6 (mappers 24, 26) and Namco 163 (19)**, both with their sound. Those two live
    in the hand-written `mapper_konami_namco.pbi`, taken from `rp2350/mapper_vrc6.pico2`,
    `mapper_n163.pico2` and the plain reference forms in `Diagnostics/asm_reference.pico2w`.

Every patch must apply exactly as often as listed, or the port stops. A changed Anvil is a reason to
look, not to guess.

| File | What it is |
|---|---|
| `host.pbi` | the services Anvil's monitor gives the core on the Pi: timer, log, stubs |
| `machine.pbi` | loading a `.nes` file through Anvil's own header checks and mapper database; PAL detection (`NesTiming`); the frame loop |
| `sound.pbi` | Windows waveOut, 48 kHz, fed from the APU's sample ring |
| `view.pbi` | the debug panes |
| `nes_desktop.pb` | the window |
| `nes_check.pb` | the console check: every test suite, then a game for N frames |
| `cpu_tests.pbi` | runs Anvil's core and mapper suites (`core/tests/`, ported from `anvil/Tests`) and the 1200 opcode vectors (`cpu_vectors.pbi`, from `tools/gen_desktop_cpu_vectors.py`, py65 as the oracle) |
| `dispatch_bench.pb` | computed goto against a procedure-pointer table (`core/cpu2a03_procs.pbi`, from `tools/gen_desktop_cpu_procs.py`) |
| `disasm.pbi` | the CPU pane's disassembler (`tools/gen_desktop_disasm.py`) |

To regenerate, from the repository root:

```bash
py tools/port_desktop.py
```

Then regenerate the procedure-table CPU, which is built from the generated CPU:

```bash
py tools/gen_desktop_cpu_procs.py
```

## Building the desktop version

You need PureBasic 6.41 (x64, the C back end: `pbcompilerc.exe`) and two public repositories, cloned side
by side: this one and the [Neon Arcade Display Engine](https://github.com/ajtaji/Neon-Arcade-Dispay-Engine).
The engine's name really is spelled "Dispay".

```powershell
git clone https://github.com/ajtaji/NesEmulatorPicoSeries.git
git clone https://github.com/ajtaji/Neon-Arcade-Dispay-Engine.git
cd NesEmulatorPicoSeries
& "C:\Program Files\PureBasic\Compilers\pbcompilerc.exe" desktop\nes_desktop.pb /EXE desktop\PureMetalNES.exe /THREAD /DPIAWARE /OPTIMIZER
& "C:\Program Files\PureBasic\Compilers\pbcompilerc.exe" desktop\nes_check.pb /CONSOLE /OPTIMIZER /OUTPUT desktop\nes_check.exe
```

Then run `desktop\PureMetalNES.exe`. It opens on the built-in demo, and **Open ROM...** picks a game.
Or name the game: `desktop\PureMetalNES.exe demo\PureMetalDemo.nes`. `nes_check.exe` does not use the
engine.

`nes_desktop.pb` looks for the engine at `../../Neon-Arcade-Dispay-Engine/`, relative to itself: the clone
beside this repository. For an engine elsewhere, add `/CONSTANT GL_ENGINE_DIR$=<path>/` (the trailing slash
matters).

`PureMetalNES.exe [game.nes] [--mute] [--pal|--ntsc] [--cpu-tests] [--tab N] [--shot window.png --seconds S]`

- **Keys, player 1:** arrows are the D-pad; X is A, Z is B; Enter is Start; Shift, Tab or Space is Select.
- **Keys, player 2:** I/J/K/L are the D-pad; H is A, G is B; Y is Start; T is Select. The second
  gamepad is player 2's; the first, player 1's.
- **Debugging:** F5 runs or pauses, F6 steps one instruction, F7 steps one frame, F8 resets.
- **Display and sound:** F11 is full screen, M is mute.
- **TV system:** the toolbar's TV button cycles auto / NTSC / PAL. Auto follows the Pico's rule: the
  header's TV system, else a PAL-only region tag in the file name — "(E)", "(Europe)", "(PAL)" — and
  never one that also names an NTSC region.
- **Tests:** the CPU pane's "Run tests" runs every suite, as `nes_check` does.

`nes_check.exe [game.nes [frames [last-frame.png]]] [--pal|--ntsc]`

## Results (2026-10-23, Windows 11, x64, /OPTIMIZER)

**Tests:** 390,993 checks, 0 failures.

| Suite | Checks |
|---|---|
| Anvil core | 132,612 — the Pi's own count |
| Anvil mappers | 206,477 |
| Opcode vectors | 51,600 |
| Both controllers through $4016/$4017 | 304 |

**Games:** 1800 frames each, unthrottled; none stopped.

| Game | Mapper | TV | fps | M instructions/s |
|---|---|---|---|---|
| PureMetalDemo.nes | 2 | NTSC | 1378 | 13.3 |
| rp2040/demo.nes | 0 | NTSC | 2936 | 28.4 |
| Super Mario Bros / Duck Hunt | 66 | NTSC | 1459 | 13.8 |
| Contra | 2 | NTSC | 2419 | 22.8 |
| Castlevania | 2 | NTSC | 2128 | 21.2 |
| Castlevania III | 5 | NTSC | 1841 | 16.9 |
| Super Mario Bros 3 | 4 | NTSC | 1483 | 14.2 |
| Mega Man 3 | 4 | NTSC | 2813 | 34.2 |
| Mega Man 4 | 4 | NTSC | 1635 | 19.5 |
| Pinbot | 119 | NTSC | 1772 | 18.6 |
| Nobunaga's Ambition 2 | 5 | NTSC | 2259 | 20.0 |
| Bandit Kings of Ancient China | 5 | NTSC | 2314 | 22.1 |
| Mr. Gimmick (E) | 69 | PAL (file name) | 2281 | 24.6 |
| Battletoads (E) | 7 | PAL (file name) | 2287 | 24.1 |
| Blaster Master (E) | 1 | PAL (file name) | 2406 | 26.0 |
| Akumajou Densetsu (VRC6 sound in 86% of samples) | 24 | NTSC | 1921 | 17.6 |
| Megami Tensei II (N163 sound) | 19 | NTSC | 2387 | 18.2 |
| Erika to Satoru no Yume Bouken (N163 sound) | 19 | NTSC | 2190 | 20.9 |
| Wagan Land 3 | 19 | NTSC | 1967 | 18.9 |
| Splatter House: Wanpaku Graffiti | 19 | NTSC | 3072 | 29.8 |

In the window every game is paced to real time: 60.0988 Hz, or 50.0070 Hz for PAL. That takes
about 1.8 million CPU cycles a second, a 25th to a 50th of what the core runs here unthrottled.

### Dispatch: computed goto against a procedure-pointer table

Both run the same opcode bodies and give the same last frame. Best of three, 1200 frames.

| | goto table | proc table |
|---|---|---|
| CPU alone (a RAM loop), /OPTIMIZER | **264 M instr/s** | 233 M instr/s (−12%) |
| CPU alone, no optimizer | **76 M instr/s** | 65 M instr/s (−15%) |
| Whole machine, five games, /OPTIMIZER | 15–28 M instr/s | within ±6% of goto |

The computed goto stays. The whole machine hardly notices, because the PPU and APU take most of
the time. `/OPTIMIZER` roughly doubles everything.

## Known limits

- **Undocumented opcodes stop the CPU**, as on the boards. Aladdin (E) stops at $07 (SLO).
- Kaiketsu Yanchamaru 3 [hM19], a hack re-pointed to mapper 19, stops on opcode $02 after 25
  instructions. It calls $C75C before it ever writes $F000, so it relies on $C000 powering on as the
  second-to-last bank, as on the original Irem board. Real N163 hardware leaves that register
  undefined; this core and the Pico start it at bank 2. With it started at the second-to-last bank,
  the hack runs, and the other four N163 games give the same frames.
- **Not drawn yet:** N163 CHR-RAM patterns, and VRC6's CHR-ROM nametable modes. As on the Pico, the
  log says so.
- **Not in Anvil yet**, so not here: the Pico's core-0 DMC/APU shadow. (The second controller is
  patched in, as the Pico has it.)
- Sound is Windows only for now. The gamepad code is in, but has not been tried with a real pad.
