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
The exFAT selector was tested with 857 ROM files; all copied files were read
back and compared byte for byte. Its 48 loader checks passed. The user selected
and played Rygar, which measured 60.02 displayed FPS and returned via EXIT.
The final menu presents at a steady 60 FPS; its completed image is retained
instead of rebuilding the text list every frame. See
[Diagnostics/selector-results.json](Diagnostics/selector-results.json).

## Build

An explicit checkout of [Anvil](https://github.com/ajtaji/Anvil) supplies the
Neon Arcade, Vulkan, MMU and BCM2711 device libraries. The dependency used
for this port is commit `b79122db24f361eded4f076a6da48e4dd429d63d`.
Use `PureMetalForge.exe --compile`; the build helper invokes that compiler.

```powershell
python tools/build_anvil.py --compiler <PureMetalForge.exe> --anvil <Anvil-checkout> --out <work-folder>/nes.img
```

The default opens the touch ROM selector on **exFAT partition 2, `2:/NES`**.
Copy `.nes` files into that folder; no rebuild is needed when games change.
Tap a title to play, use the letters to jump through the sorted list, or
PREVIOUS/NEXT to page. REFRESH rereads the folder. EXIT returns to Anvil from
both the selector and the game. During play, MENU returns to the selector
so another game can be loaded without restarting the application. The D-pad, A/B, Start and Select controls are preserved during gameplay.
The selector remains silent; Bluetooth starts after a game is chosen, suspends
on MENU and resumes for the next game. Guest state is reset only after both
workers have joined.

`--no-selector` builds the original demonstration cartridge. `--rom <game.nes>`
retains the embedded single-game diagnostic mode. `--seconds 10` enables a
bounded test (separate menu and game limits); the default, `--seconds 0`, runs
until Exit.
The `.img.pmf` sidecar is the loadable application. ROM data and local
dependency paths are confined to the output directory's generated wrapper.
Do not commit those generated wrappers or commercial ROM payloads.

Upload/run with Anvil's `tools/board_run.py`, supplying the board's address
with `--console-ip`. It asks the running monitor for its staging window,
checks the transfer digest on the board and captures the returned frame.
For production storage use a separate application filename, never
`KERNEL8.IMG`. For example, save the application as `2:/payloads/NES.PMF`
and launch it with `boot 2:/payloads/NES.PMF`. The Pico flash directory and
USB ROM loader are not used by the Pi.

To copy an explicitly named local ROM folder over Anvil's network console:

```powershell
python tools/copy_anvil_roms.py --directory "G:\Nes Roms\USA" --ip <Pi-IP> --compiler <PureMetalForge.exe> --anvil <Anvil-checkout> --out <private-work-folder>
```

This copies only that folder's `.nes` files (not subfolders), verifies the RAM
transfer digest, then compares every stored file byte for byte. Identical files
are skipped; different files with the same name in `2:/NES` are replaced. It
does not delete extra games or change boot files/settings. Its private bundle
must not be committed. The copy tool is bounded to 4096 files and 256 MiB per
batch; the selector displays up to 4096 games. Filenames must fit 255 UTF-8 bytes.
ROM loading supports up to 1 MiB PRG and 1 MiB CHR for MMC5,
512 KiB PRG and 256 KiB CHR for MMC3,
256 KiB PRG and 128 KiB CHR for standard MMC1, and the original sizes for
mappers 0/2/66. CNROM supports 32 KiB PRG/32 KiB CHR, AxROM 256 KiB PRG
and 8 KiB CHR RAM, and Color Dreams 128 KiB PRG/128 KiB CHR. Invalid/truncated files and unsupported mappers stay
in the selector with an error message. Cartridge RAM is volatile: battery-backed saves are not written to disk.

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
  bits. The host UI has D-pad, A, B, Start, Select, MENU and EXIT. Multiple contact
  IDs are tracked independently. Exit signals the guest worker to stop,
  joins it and returns to Anvil.
* `selector.pi4` scans and loads files through Anvil ABI 1.7. The immutable
  UxROM views match `rom_catalog.prg_views`; no opcode, guest rendering or APU
  behavior is changed. Raw PRG uses `0x03200000` (up to 1 MiB), CHR uses
  `0x03300000` (up to 1 MiB), and PRG views use `0x03400000` (1 MiB). These are
  separate from stacks, framebuffer storage and the GPU/DMA arenas.
  Managed mappers copy changed banks into a 32 KiB CPU window at `0x03500000`,
  an 8 KiB CHR window at `0x03508000`, and its decoded shadow at `0x0350A000`.
  `mappers.pi4` owns register state, PRG RAM, CHR aliases and CIRAM mirroring.
  MMC3 observes filtered PPU A12 rises and contributes a separate IRQ source;
  the APU IRQ cannot clear it. The CPU interpreter and output transport are
  unchanged. MMC5 has separate cartridge video/audio modules; small entry
  adapters retain the original tile/sprite/mixer algorithms for other games.
  `mapper5_video.pi4` supplies independent sprite/BG CHR, extended attributes,
  fill and vertical split data, plus the repeated-NT-read scanline detector.
  The optimized observer skips interior fetches that cannot trigger detection;
  native checks compare its complete state with the unbatched implementation.
  `mapper5_audio.pi4` owns two pulses, independent envelope/length clocks, PCM
  and cartridge IRQ state. Timer segments are integrated at the existing PCM
  sample cadence; ultrasonic periods retain their DAC mean without alias buzz.
  Cartridge output is mixed before the APU publishes its PCM write index.
  Base APU channels/filter, stereo SBC and Bluetooth device code are preserved.
  The default video plugin retains its complete menu image at `0x07400000`
  (4,096,000 bytes). List changes trigger a full GPU redraw; FPS changes draw
  only the HUD strip. Each presentation still publishes a complete frame by
  DMA at vertical sync. The normal game render path is unchanged.
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

* Input: `InputPoll()` updates `NesController`, `MenuRequested` and `ExitRequested`.
  MENU requests a joined guest stop and selector return; EXIT ends the app.
  With the selector enabled, `InputMenuPoll()` returns 1..8 for visible rows,
  -1/-2 for previous/next, -3 for refresh, or 100..125 for A..Z. EXIT updates
  `ExitRequested`. While `RomMenuActive` is set, normal input polling must not
  consume menu contacts.
* Audio: `AudioStop()` releases the device; `AudioDiagnostics(address)`
  stores plugin-specific diagnostics (the Bluetooth plugin reserves 192 bytes).
* Video: `VideoDiagnostics(address)` stores four u64 timing totals. The
  scheduler retains the frame buffers until `VideoPoll()` reports completion
  and aborts a failed or timed-out transfer.
  Selector builds also require a synchronous `VideoMenuDraw()` that reads the
  published menu state and reports success/failure. `video_menu_neon.pi4` is
  the default presentation module; a replacement display supplies its own.

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
`--verify-mappers` runs synthetic bank, RAM protection, CHR alias, mirroring,
IRQ and session-reset checks, all 65,536 multiplier pairs, fixed expansion
sound waveform checks, and 140,000 optimized/unbatched MMC5 bus-state comparisons.
`--verify-rom` exercises malformed headers and short reads, scans exFAT, and
compares the loaded Mario/Duck Hunt, Contra and Castlevania PRG/CHR images to
host-generated FNV-1a expectations. Those three files must be in `2:/NES`.

`return_test.pi4` is the small, standalone one-second return proof. The
compiler must be given `--entry-returns --wants-services`, with separate image,
BSS and stack addresses as in `build_anvil.py`.

The Anvil mapper set is **0, 1, 2, 3, 4, 5, 7, 11 and 66**. Mapper 1 implements standard
MMC1 serial registers, PRG/CHR modes, one-screen/H/V mirroring and 8 KiB RAM.
Outer-bank and extra-RAM boards (SUROM/SXROM etc.) are unsupported. Mapper 4
implements MMC3 B/C banks, RAM protection, mirroring/four-screen RAM and the
filtered A12 IRQ counter. MMC6 and nonzero MMC1/MMC3 submappers are unsupported.
The bounded iNES/NES 2.0 parser rejects trainers, extended size encodings,
unsupported RAM and PAL-only images. Mapper support does not imply every ROM
works: existing PPU 8-pixel rendering granularity, documented-opcode coverage
and DMC/OAM/interrupt timing limits still apply. Pico mapper support is unchanged.

On-board mapper results and the six-game menu/resume sequence are recorded in
[Diagnostics/mapper-results.json](Diagnostics/mapper-results.json). Independent
[Blargg MMC3 tests](https://github.com/christopherpow/nes-test-roms/tree/master/mmc3_irq_tests)
cover clocking, details, A12, scanline timing and revision B. Test binaries and
commercial ROMs are not included. Hardware register references:
[MMC1](https://www.nesdev.org/wiki/MMC1), [MMC3](https://www.nesdev.org/wiki/MMC3).

## Additional cartridge hardware: 3, 7, 11 and 5

CNROM (3) selects an 8 KiB CHR bank; AxROM (7) selects 32 KiB PRG and one-screen
CIRAM; Color Dreams (11) independently selects 32 KiB PRG and 8 KiB CHR banks.
NES 2.0 submapper 1 disables bus conflicts and submapper 2 enables AND conflicts.
Legacy CNROM defaults to conflicts; AxROM and Color Dreams default to none, as
recommended by [NESdev's submapper convention](https://www.nesdev.org/wiki/NES_2.0_submappers).
Unusual CNROM RAM/oversize/security-diode boards are outside this implementation.

MMC5 (5) implements four PRG/CHR modes, protected banked RAM, ExRAM access modes,
fill/arbitrary nametable sources, 8x16 sprite/BG separation, extended attributes,
CL-style vertical split, multiplier, scanline IRQ/status and cartridge sound.
The MMC5A timer is implemented; peripheral pins/debug devices are not. IRQs and
PPUDATA interactions remain bounded by the existing instruction/8-pixel PPU
timing; this is not a new cycle-exact PPU. Expansion sound gain/reconstruction
is approximate. Battery RAM remains volatile.

NES 2.0 gives an explicit PRG RAM size (0/8/16/32/64/128 KiB supported). Legacy
iNES size zero uses a 64 KiB superset without per-game CRC tables. This avoids
pretending that incomplete old headers identify an exact MMC5 board. MMC5 CHR
RAM boards and nonzero MMC5 submappers are rejected. Raw ROM windows fit before
the existing PRG views; the decoded pool is 1 MiB. Stack, GPU, DMA and Anvil
ownership are unchanged.

See [Diagnostics/more-mappers-results.json](Diagnostics/more-mappers-results.json)
for current native checks, independent CHR/ExRAM demonstrations and measured
mixed-mapper game sessions. Independent sources/binaries are kept outside the
repository: [CHR bank test](https://github.com/christopherpow/nes-test-roms/tree/master/mmc5test_v2),
[executable ExRAM test](https://github.com/christopherpow/nes-test-roms/tree/master/exram).
Hardware references: [MMC5](https://www.nesdev.org/wiki/MMC5),
[CNROM](https://www.nesdev.org/wiki/CNROM), [Color Dreams](https://www.nesdev.org/wiki/INES_Mapper_011).
