# Arm Pico 2 W port

Regenerate with `py -3 tools/port_rp2350.py` from the repository root. The
RP2040 tree is the semantic source; this folder contains the generated port.
Use the root README for wiring, builds, ROM loading, and supported mappers.
Video and audio backends are independently selected in the wrapper; see
[the output plugin guide](../OUTPUTS.md) for the interface and custom examples.
The standalone [ILI9341 SPI1 backend](../ILI9341.md) can also be selected with
`tools/build.ps1 -Target rp2350 -Display ili9341`. That panel has been tested on
the bare RP2040 Pico; the RP2350 ILI9341 build is compiled only. Its default
profile uses silent audio and USB controls, independently of the video driver.

The [Adafruit HX8357D SPI1 plugin](../HX8357D.md) is selected with
`tools/build.ps1 -Target rp2350 -Display hx8357d`. It presents a centered native
256x240 image in 480x320 landscape at 30 FPS, with the host HUD above it.
The RP2350 image compiles; physical HX8357D validation was performed only on
the bare RP2040 Pico. Audio and physical input remain independently selectable.

The LAFVIN LCD is rotated 90 degrees left from the RP2040 landscape layout, using the
ST7796 controller's rotation setting. The 256x240 NES frame is centered at
(32,120) in 320x480 portrait coordinates. DMA still sends the completed frame;
the emulated framebuffer and PPU rendering are unchanged. The host FPS overlay
stays at (4,4), outside the NES image.
The operator confirmed this orientation on the physical board on 2026-10-16.
Both public and speaker-enabled builds booted successfully; their DMA menu
measurements are in `Diagnostics/rotation-menu-board.txt` and
`Diagnostics/rotation-private-menu-board.txt`. Emulation remains stopped at the
boot menu after this display check. The 40-second game measurements below were
recorded for the original port before this display-only rotation.

The port retains the CPU's per-opcode computed dispatch, the renderer, APU,
queued bank changes, SBC stereo output, controls, and ROM-store protocol.
Hardware changes are limited to:

- RP2350 libraries and the two-M33 launch adapter (six-word handshake).
- Native M33 division for nonnegative timing/count values, replacing the
  RP2040-only SIO divider.
- RP2350 SIO GPIO set/clear/output-enable addresses in the radio hot path.
- SPI0's new address and the RP2350 DMA DREQ number/shift/busy bit.
- Explicit register-list syntax accepted by the M33 assembler.
- A consistent 150 MHz system clock and 75 MHz SPI, with peripheral dividers
  derived from `ClockSysConfigKhz()`.

The radio image lives at flash offset `$200000`. Firmware must end before
`$50000`. The directory remains at `$50000`; version-2 game data extends
from `$51000` to `$1FEFFF`, with `$1FF000` reserved for board checks.
Use `--target rp2350` in the ROM loader. See [Pico mapper support](../PICO-MAPPERS.md).
Firmware release images contain the original demo and no commercial games.
Speaker addresses belong in private wrappers outside Git.

Physical board: Pico 2 W on COM6, serial `3D00D889CF7F499A`. The full diagnostic
verdict is in `Diagnostics/verification-board.txt`. Its 1,926,732 checks include
CPU vectors and polling, independent renderer comparisons, mapper boundaries
and worker/DMC bank ordering, audio shutdown, SBC vectors, and real flash writes.
The public firmware's boot/menu output is in `Diagnostics/public-menu-board.txt`.

Game measurements use `tools/benchmark.py`: Start at 3 seconds, another Start
for Mario at 7 seconds, right for 300 guest frames at 12 seconds, and A at 25
seconds. Each final `*-board.json` summarizes all 40 sampled intervals; matching
text files retain the raw counters. These are finite workload samples, not a
guarantee for every scene or game. Bluetooth underruns are cumulative and include
startup; compare their first and last values to identify new playback underruns.

The current mapper/interrupt revision passes 1,928,288 full checks and 59,923
focused checks. See [current results](../PICO-MMC3-NMI-RESULTS.md); the
verification-board.txt file above is an earlier baseline.

## Pinbot speed (2026-10-24)

Measured on COM6 (Pico 2 W, LAFVIN panel), silent build. The silent build is `rp2350/demo.pico2w` with
`#NES_AUDIO_BACKEND=0`; the APU still runs. The figures are frames per second from the board's own
per-second line, over 62 s of Pinbot's attract mode with no input.

| Stretch | Before | After |
|---|---|---|
| s1-15 | 60 | 60 |
| s21-24 | 55-56 | 68-69 (catching up after the dip) |
| s27-35 and s44-52 | 57-58 | 63-64 (catching up) |
| Scene changes (s16-17, s23-24, s33, s40-41, s50, s57-58) | 31-52 | 32-52 |

The emulator paces to real time and catches up after a slow second. So 63-64 FPS means core 0 now has
time to spare where it had none.

**The lever.** Profiled with a 10 kHz SysTick sampler on core 0, plus the guest PC (r8) while core 0 was
in `CpuRunPaged`. Three quarters of the 6502's time in the slow stretch went to two timing loops: the
`DEX/BNE` delay at `$FD80` and the per-scanline `LDY #9 / DEY / BNE` wait at `$FDCC`. The CPU now runs
such a countdown in one step. In `rp2040/generate_cpu.py`, a ROM `DEX` or `DEY` followed by `BNE` back to
itself is taken as many passes at once as the cycle budget allows. Each pass is 5 cycles (6 across a
page) and 2 instructions; the batch stops one pass short of zero. Emulated timing is exact: checked in
`PollLoopTests` against the same loops run one instruction at a time, flat and paged (612,005 checks).
Two planted faults, a 4-cycle pass and the paged CPU reading its loop code through `PrgBias`, were
caught (20,728 and 17,555 failures).

**Also in this change.**
- The paged CPU's batches read their code from ROM through the 8 KiB slot's own bias. Through `PrgBias`,
  a status poll in a switched bank could have matched another bank's bytes.
- A CHR-RAM byte on TQROM forgets just its four cached tile rows (`PpuForgetChrRow`, exact) instead of
  moving the whole tile cache on a generation. That cut palette-pair rebuilds in a scene change from
  ~140 to 1 a second. `ChrRowForgetTests` (51,200 checks) caught a planted fault (4,207 failures).
- `$2006`/`$2007` writes run `PicoCpuPpuChanged` once, not twice.

Full verify on COM6: 2,640,801 checks, 0 failures.

**Unchanged.** The PureMetal demo, Mario / Duck Hunt, Contra and Mega Man 3 hold 60 FPS, second for second
the same as before. Castlevania III dips to 57-58 at s18-19 in both builds.

**Still slow: the scene changes.** Pinbot clears 4 KiB of CHR RAM through `$2007` with the background on.
That is ~50,000 writes a second, each a full PPU sync and register write: about 13 us of core 0 per byte.
Reaching 60 there needs roughly twice that path's speed.
