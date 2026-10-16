# Initial Pico mapper port: historical baseline

**Historical measurements before the MMC3/NMI fixes.** Current implementation,
validation and remaining performance limits are in
[PICO-MMC3-NMI-RESULTS.md](PICO-MMC3-NMI-RESULTS.md). Statements below describe
the original port and are not the current firmware status.

Tested on the original LAFVIN carriers, Pico W on COM7 and Pico 2 W on COM6.
Firmware uses the existing 200 MHz / 150 MHz clocks respectively. Pico 2 W keeps
the confirmed left screen rotation. Completed-frame DMA, the host FPS overlay,
touch-independent carrier controls and Bluetooth output interfaces are retained.

## Scope and limits

Pico W exposes 13 mapper IDs: 0, 2, 3, 7, 11, 34 (BNROM), 41, 66, 71, 79,
144, 148 and 232. Pico 2 W exposes those plus 1, 4, 13, 47, 118, 119 and 206,
and supports the NINA-001 form of 34. See PICO-MAPPERS.md for board geometry limits.
The authorized folder contains 857 files; 334 pass the W profile and individual
store-capacity checks, and 811 pass the 2 W checks. These counts are header/size
eligibility, not gameplay validation. Battery RAM is volatile; no save persistence.

MMC3-derived support is experimental. Several games fall below real-time speed;
a connected Bluetooth stream does not prove clean audio at these lower rates.
No per-game CPU, video or audio timing knobs were added to hide these limits.

Adventures of Lolo 2 reaches a black screen. A private instruction trace found
NMI occurring between STA $2000 (enable NMI) and STA $00 (update cached control).
The handler reads the old cache and clears the NMI-enable bit, leaving the game
waiting forever. Register/flag canaries across every mapper write found zero
corruption. This is an unresolved native interrupt-timing compatibility issue;
the CPU/PPU were deliberately left unchanged rather than patched for this ROM.

The mapper 47 multicart has particularly poor speed when an IRQ remains pending.
The conservative cartridge CPU-window limiter falls to one instruction. Raising
that limit while CPU interrupts are masked would need validated CLI/RTI interrupt
latency support; this port does not make that accuracy tradeoff silently.

## Verification

Both boards passed the existing 1,926,732-check suite with zero failures, including
CPU vectors, renderer reference comparisons, APU shutdown, stereo SBC, controls,
flash-store tests and DMC bank ordering. New mapper diagnostics passed 544 checks
on W and 19,281 on 2 W. They check bank markers, CPU register/flag preservation,
mirroring, bus conflicts, PRG RAM protection, CPROM/TQROM aliases and DMC ordering.
The A12 observer matched an independent reference across 2,000 randomized inputs.
Its 32-frame timings were 254,923 vs 145,671 microseconds (pattern mode 0) and
1,111,224 vs 211,061 microseconds (mode 1), reference vs optimized on Pico 2 W.

The host suite passed six unit tests and 524,361 additional assertions, including
all CHR bitplane combinations, CRCs, immutable PRG views, loader target switching,
flash boundaries and pre-erase refusal of incompatible packs. Text comparisons
against Git HEAD confirm the CPU interpreter, native pixel renderer, base APU,
SBC, Bluetooth transport, input and output plugin implementation files unchanged.
Anvil regeneration reproduced the existing Anvil files byte-for-byte.

Bank changes live in cartridge/bus adapters. Only a changed mutable PRG slot
fences queued APU events at the write timestamp; CHR and IRQ writes do not.
MMC3 latch-only writes and unchanged bank values no longer remap all slots.

## Finite game runs

These are 18–40 second automated samples with controller commands, serial
telemetry and a completed framebuffer capture, not full-game playthroughs.
FPS is emulated frames / measured time. Display rates can be slightly lower.
BT=1 means the transport reported connected throughout the sampled rows.
The JSON includes the firmware hash where recorded; earlier samples predate the
last MMC3 register-update optimization and remain explicitly identified by hash.
There were no reported CPU/bridge errors or stopped-CPU flags in these runs.

| Board | Game | Mapper | FPS | BT | Frame colours |
|---|---|---:|---:|---:|---:|
| Pico W | Castlevania (U) (PRG 0).nes | 2 | 60.10 | 1 | 15 |
| Pico W | Contra (U).nes | 2 | 60.10 | 1 | 13 |
| Pico W | Arkanoid (U).nes | 3 | 60.05 | 1 | 3 |
| Pico W | Gradius (U).nes | 3 | 60.10 | 1 | 7 |
| Pico W | Beetlejuice (U) [!].nes | 7 | 60.05 | 1 | 9 |
| Pico W | Mission Cobra (U).nes | 11 | 60.05 | 1 | 4 |
| Pico W | Deadly Towers (U).nes | 34 | 60.05 | 1 | 6 |
| Pico W | Caltron 6-in-1 (U).nes | 41 | 43.72 | 1 | 4 |
| Pico W | Super Mario Bros - Duck Hunt (U).nes | 66 | 60.10 | 1 | 10 |
| Pico W | Bee 52 (U).nes | 71 | 50.60 | 1 | 11 |
| Pico W | Double Strike (U) (V1.0).nes | 79 | 60.05 | 1 | 13 |
| Pico W | Death Race (U).nes | 144 | 60.05 | 1 | 8 |
| Pico W | Pyramid (U) (Sachen-Hacker).nes | 148 | 53.94 | 1 | 14 |
| Pico W | Quattro Adventure (U).nes | 232 | 60.05 | 1 | 9 |
| Pico 2 W | Metroid (U).nes | 1 | 60.05 | 1 | 11 |
| Pico 2 W | Tetris (U) [!].nes | 1 | 60.05 | 1 | 8 |
| Pico 2 W | Castlevania (U) (PRG 0).nes | 2 | 60.10 | 1 | 15 |
| Pico 2 W | Contra (U).nes | 2 | 60.10 | 1 | 13 |
| Pico 2 W | Gradius (U).nes | 3 | 60.07 | 1 | 13 |
| Pico 2 W | Adventures of Lolo 2 (U).nes | 4 | 60.05 | 1 | 1 |
| Pico 2 W | Mega Man 3 (U) [!].nes | 4 | 33.50 | 1 | 10 |
| Pico 2 W | Videomation (U).nes | 13 | 50.66 | 1 | 8 |
| Pico 2 W | Impossible Mission 2 (U).nes | 34 | 60.05 | 1 | 9 |
| Pico 2 W | Super Spike V'Ball - Nintendo World Cup (U) [!].nes | 47 | 10.94 | 1 | 7 |
| Pico 2 W | Super Mario Bros - Duck Hunt (U).nes | 66 | 60.10 | 1 | 11 |
| Pico 2 W | Bee 52 (U).nes | 71 | 45.83 | 1 | 12 |
| Pico 2 W | Double Strike (U) (V1.0).nes | 79 | 60.05 | 1 | 12 |
| Pico 2 W | Goal! Two (U).nes | 118 | 25.93 | 1 | 7 |
| Pico 2 W | Pinbot (U).nes | 119 | 36.04 | 1 | 8 |
| Pico 2 W | RBI Baseball (U).nes | 206 | 60.05 | 1 | 2 |

## Installed state

Both boards are left stopped in their ROM boot menus, with no game emulation or
Bluetooth audio stream running. W has Mario/Duck Hunt, Contra, Castlevania and
Gradius. 2 W has those plus Metroid, Mega Man 3, Videomation, Double Strike,
Bee 52 and RBI Baseball. The loader can replace these without rebuilding.

Public UF2s in firmware/ contain no commercial ROMs or private speaker pairing.
The physical boards retain the user-specific Bluetooth configuration. Detailed
numeric logs and JSON are under each target's Diagnostics/pico-mappers directory.
This historical snapshot predates the consolidation of the Anvil and Pico work on main.
