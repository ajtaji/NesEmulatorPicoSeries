# Arm Pico 2 W port

Regenerate with `py -3 tools/port_rp2350.py` from the repository root. The
RP2040 tree is the semantic source; this folder contains the generated port.
Use the root README for wiring, builds, ROM loading, and supported mappers.
Video and audio backends are independently selected in the wrapper; see
[the output plugin guide](../OUTPUTS.md) for the interface and custom examples.
The LCD is rotated 90 degrees left from the RP2040 landscape layout, using the
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
`$50000`; the existing ROM store and directory layout remain unchanged.
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
