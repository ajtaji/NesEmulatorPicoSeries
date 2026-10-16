# Pico MMC3 and interrupt work

This revision fixes the Lolo 2 interrupt ordering failure and removes several
measured MMC3 bottlenecks. It does **not** establish 60 FPS for every MMC3 game.
The original port measurements remain in [the historical results](PICO-MAPPERS-RESULTS.md).

## General fixes

An NMI raised by the final bus write of STA $2000 was delivered before the next
instruction. Lolo 2 updates its cached PPU control in that next instruction; its
handler previously observed the old value and disabled further NMIs. The bridge
now accounts for that bus-phase boundary. Native tests verify the intervening
instruction and interrupt stack PC. No ROM patches or game-specific settings
were added. CLI/PLP poll the old interrupt mask; RTI polls its restored mask.
Those cases have independent native regression checks.

The CPU generator remains the source of both computed-dispatch implementations.
Pico 2 W selects either the original flat PRG view or four 8 KiB PRG pointers
once per CPU window. Bank switches update pointers rather than copying memory.
Separate timestamped APU mappings preserve DMC ordering without an audio fence
on every bank write. Cross-bank opcode operands and in-window bank changes are
tested. The base pixel renderer, APU, SBC and Bluetooth implementation are
unchanged. Video/audio plugin contracts and the left display rotation remain.

## Measured bottlenecks

- The original Goal! Two sample spent 4,494,489 microseconds on 9,254 PRG-slot
  copies, about 486 microseconds per copy. Pointer changes cost about 1–2
  microseconds and publish a small ordered mapping event.
- A pending but masked MMC3 IRQ forced one-instruction CPU windows. The multicart
  reached about 78,794 windows per second and roughly 584 ms/s of synchronization.
  Masked IRQs now use normal windows; validated unmask boundaries retain latency.
- The A12 observer revisited sprite/OAM data and constant pattern regions.
  It now reuses sprite evaluation and batches constant regions. The two 32-frame
  observer fixtures fell from 145,671/211,061 us to about 20,455/26,054 us.
  Their electrical history and IRQ fields match an independent fetch-edge model.
- IRQ-enabled windows use a bounded, non-mutating horizon prediction instead of
  stepping every instruction while the counter is far from assertion. CPU PPU
  writes end the window to recompute the horizon.
- Mirroring changes formerly copied CIRAM byte by byte and rebuilt every tile
  descriptor. Block copies and a canonical physical-CIRAM descriptor cache avoid
  that repetition. MMC3 latch-only and repeated-value writes also bypass remapping.

These figures identify separate experiments, not additive percentages from one
profile. Release builds disable detailed observer/predictor timers. Remaining
Goal! Two scenes still run below 60 FPS; connected Bluetooth does not prove clear
audio when emulation is slow. The PPU remains instruction-timestamped with its
existing eight-pixel granularity, rather than a fully cycle-exact implementation.
In the final Goal! Two title-screen sample, late intervals reached 57–58 FPS:
PPU synchronization accounted for about 550 ms/s and CPU execution about 380
ms/s. An earlier IRQ-enabled cup-menu sample spent about 225 ms/s waiting for
PPU RPCs. These counters overlap synchronization totals and must not be added
as independent frame costs. Further work remains in PPU/bus synchronization.

## Native validation

| Physical board | Full suite | Focused mapper/interrupt suite | Failures |
|---|---:|---:|---:|
| Pico W / COM7 | 1,926,732 | 575 | 0 |
| Pico 2 W / COM6 | 1,928,288 | 59,923 | 0 |

The focused Pico 2 W suite includes randomized A12 comparisons, IRQ prediction
and state-restoration checks, register canaries, nametable descriptor aliases,
bank-crossing operands, self-bank-switch continuation and DMC ordering. Full
suites retain independent CPU/renderer, APU shutdown and byte-exact SBC checks.
Native transcripts and public build summaries are under each target's
`Diagnostics/mmc3-nmi/`. Pico W does not expose MMC3: its board checks cover the
shared interrupt changes and its supported mapper profile.

Host validation passes six unit tests and 524,359 additional assertions, including
the real loader window's target/capacity changes. RP2350 generation reproduces
the committed sources; Anvil regeneration is byte-identical. Public firmware
ends below the $50000 ROM directory, with 2,660 bytes free SRAM on W and 175,232
on 2 W. Clocks remain 200 MHz and 150 MHz respectively.

## Reproducing finite board samples

`tools/board_smoke.py` accepts owned ROM paths, replaces the board's ROM menu,
applies timed USB controls, records telemetry and a complete framebuffer, and
resets to the stopped boot menu after every sample. It hashes the supplied
already-installed firmware; it does not claim firmware readback verification.
Requires pyserial and Pillow. For example:

```powershell
py -3 tools/board_smoke.py --port COM6 --target rp2350 --firmware my-private.uf2 --output results --seconds 40 "C:\ROMs\Contra.nes"
```

The native wrappers are `Diagnostics/verify` and `Diagnostics/mappers` for each
target. Build them with `tools/build.ps1`, selecting the matching source/port.
Only one board should play Bluetooth audio during comparative testing. USB
framebuffer capture pauses emulation, so capture-induced audio gaps must not be
reported as normal playback measurements. Public UF2s contain no commercial ROMs
or private speaker configuration. Detailed final game samples are recorded
separately from the native correctness verdicts.

USB controls: `s` Start, `a` A, `b` B, `u` up, `n` down, `l` left, `r` right,
`R` held right and `0` release. `j` retains input diagnostics. Physical joystick
and button/chord mappings are unchanged.
