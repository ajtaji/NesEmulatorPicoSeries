# Raspberry Pi 4 / Anvil port

PureMetal AArch64 application for the resident Anvil monitor. It uses the
6502 computed-goto dispatch and guest-cycle scheduler, with separate video,
audio and input modules. It is **a returning PMF payload**, not a replacement
`kernel8.img`. No boot files or autoboot settings are changed.

Board-tested on a Pi 4 running Anvil build 281, service ABI 1.7. Mario ran
for 60 seconds at 59.97 emulated and 60.00 displayed FPS with Bluetooth audio.
The user confirmed the touch controls and audible output. See
[Diagnostics/board-results.json](Diagnostics/board-results.json) for measured
results, error counters and the distinction between timed and touch exits.

## Build

An explicit checkout of [Anvil](https://github.com/ajtaji/Anvil) supplies the
Neon Arcade, Vulkan, MMU and BCM2711 device libraries. The dependency used
for this port is commit `b79122db24f361eded4f076a6da48e4dd429d63d`.
Use `PureMetalForge.exe --compile`; the build helper invokes that compiler.

```powershell
python tools/build_anvil.py --compiler <PureMetalForge.exe> --anvil <Anvil-checkout> --out <work-folder>/nes.img --rom <game.nes>
```

Omit `--rom` to build the original demonstration cartridge. `--seconds 10`
enables a bounded test run; the default, `--seconds 0`, runs until Exit.
The `.img.pmf` sidecar is the loadable application. ROM data and local
dependency paths are confined to the output directory's generated wrapper.
Do not commit those generated wrappers or commercial ROM payloads.

Upload/run with Anvil's `tools/board_run.py`, supplying the board's address
with `--console-ip`. It asks the running monitor for its staging window,
checks the transfer digest on the board and captures the returned frame.
For production storage use a separate application filename, never
`KERNEL8.IMG`. This initial port selects a ROM at build time; the Pico flash
directory and USB ROM loader are not used by the Pi.

## Modules and ownership

* `core.pi4`, `cpu2a03.pi4`, `bridge.pi4`, `ppu.pi4`, `apu.pi4` and
  `worker.pi4` own guest state. `port_anvil.py` derives the portable CPU from
  the same generator before its Thumb assembly pass. Pico files are not
  modified. Packed CHR lookup and the RGB conversion loop are native A64.
* `scheduler.pi4` owns two complete RGB565 frames and their publication
  fences. Core 1 computes CPU/PPU/APU work. Core 0 owns all hardware and
  every Anvil service call. Anvil parallel jobs are bounded to two-second
  slices and joined before exit. Guest execution is paced from elapsed
  time at 1,789,773 cycles/second, not one timer interrupt per instruction.
* `video_neon.pi4` owns its own Neon Arcade/Vulkan context, GPU allocations
  and DMA publication. The monitor suspends its renderer before entry and
  reconstructs it after return. Whole frames are rendered before DMA starts;
  persistent controls and the FPS strip have independent damage rectangles.
  The current backend supports the tested 1280x800 logical, rotated 800x1280
  DSI surface. Another screen belongs in another video plugin.
* `input_touch.pi4` translates Anvil's screen-space contacts to NES button
  bits. The host UI has D-pad, A, B, Start, Select and Exit. Multiple contact
  IDs are tracked independently. Exit signals the guest worker to stop,
  joins it and returns to Anvil.
* `hud.pi4` and `ui.pi4` draw host controls and separate VIDEO/EMU FPS
  counters. Neither changes the emulated PPU image.
* `audio_null.pi4` and `audio_bluetooth.pi4` are alternative audio plugins.
  Both consume the existing APU's signed 16-bit, mono, 48 kHz PCM.
  The Bluetooth plugin layers the existing L2CAP/AVDTP/A2DP behavior and
  duplicated-stereo SBC format over `bt_h4.pi4`, the Pi's UART transport.
  The Pico's gSPI radio driver is not used on the Pi.
* `platform.pi4` owns CPU cache setup and teardown. Resident shared state
  retains Anvil's normal WB attributes; DMA and GPU arenas are NC. The
  secondary's application stack is separate from Anvil's guarded stack.

`--video-plugin`, `--input-plugin` and `--audio-plugin` select replacement
modules at build time. No indirect call or plugin lookup is added to a guest
opcode, PPU pixel or APU sample. The video and PCM contracts are the same as
[OUTPUTS.md](../OUTPUTS.md). Anvil lifecycle additions are:

* Input: `InputPoll()` updates `NesController` and `ExitRequested`.
* Audio: `AudioStop()` releases the device; `AudioDiagnostics(address)`
  stores plugin-specific diagnostics (the Bluetooth plugin reserves 192 bytes).
* Video: `VideoDiagnostics(address)` stores four u64 timing totals. The
  scheduler retains the frame buffers until `VideoPoll()` reports completion
  and aborts a failed or timed-out transfer.

The bundled Neon UI is a host presentation layer; a replacement screen may
also replace that layer. The initial build helper includes the Anvil graphics
libraries even when a replacement video module is selected.

## Bluetooth configuration

Bluetooth borrows the Pi 4's PL011, which Anvil also uses for its serial
console. The plugin saves its UART registers, pin muxes and pulls. It powers
down Bluetooth, flushes both FIFOs and restores those settings before return.
No firmware console routing or boot configuration is changed. The firmware
patch is read from the explicit Anvil dependency's `Firmware/CYW43455` folder.

For the existing private Pico speaker wrapper:

```powershell
python tools/build_anvil.py --compiler <PureMetalForge.exe> --anvil <Anvil-checkout> --out <private-work>/nes.img --rom <game.nes> --bluetooth-peer-wrapper <private-wrapper.pico2w>
```

The wrapper must contain one six-byte peer `Data.a` record. The speaker
address stays in the private build wrapper. The TaoTronics speaker was tested
on the board and the user confirmed clear sound. The diagnostic counters
include startup and connection time; see the recorded underrun/overrun counts
rather than assuming every audio packet was delivered without interruption.

## Validation

`--verify-core` runs the original CPU zero-page vectors and differential
checks of every packed CHR tile-fetch address against the portable reference.
`--verify-audio` in a Bluetooth build runs the existing mono/stereo SBC oracle
vectors and returns without opening the radio or starting emulation.

`return_test.pi4` is the small, standalone one-second return proof. The
compiler must be given `--entry-returns --wants-services`, with separate image,
BSS and stack addresses as in `build_anvil.py`.

The current emulator's supported mapper set remains **0, 2 and 66**. This
port does not add mapper compatibility or pretend that all iNES games work.
Game parsing and PRG views use the same `rom_catalog.py` checks as the Pico.
