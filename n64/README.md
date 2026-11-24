# NES on Nintendo 64

Build a Nintendo 64 cartridge that boots directly into one NES game. The included PureMetal NES demo ran on a physical N64 with SummerCart64. Its animated scene ran at **4.60 NES frames per second** between guest frames 60 and 120. This is a working hardware port with a substantial performance gap. At that speed the AI runs out of samples between submissions and music plays intermittently.

## Build and run

Use Python 3 and a Windows PureMetal Forge SDK with the Nintendo 64 target and LibPureMetalN64. Set `PMF_ROOT` to the directory containing `PureMetalForge.exe` and the `Mips` directory. Run from the repository root.

```powershell
python n64/build.py
python n64/build.py --rom "C:\Games\game.nes" --out "C:\Games\game.z64"
```

The first command writes **n64/build/nes.z64** with the original demo. Boot the resulting big-endian `.z64` in an N64 emulator or copy it to a flash cartridge. The build also accepts `--sdk PATH` in place of the environment variable. A cartridge contains the game you selected. To change games, build another cartridge.

| NES control | N64 controller |
|---|---|
| D-pad | D-pad or analog stick |
| A / B | A / B |
| Start / Select | Start / Z |
| Player 1 / Player 2 | Controller port 1 / 2 |

The port reads NTSC or PAL guest timing from the NES header. The VI uses the console's TV standard. The guest PPU renders 256 × 240 in a centered 320 × 240 double buffer. The AI receives 16-bit stereo at a nominal 48 kHz, with the mono NES mix on both channels.

## Cartridge support

The builder uses the project's Anvil mapper and header validation plus the VRC6 and Namco 163 support from the desktop port. It carries over the existing board restrictions, including unsupported trainers, Dendy timing, VRC6 nametable modes and Namco 163 CHR-RAM pattern banking. Mapper work RAM is volatile across resets and power cycles. The game is embedded at build time, so the port needs no flash-cart filesystem driver.

Small games use base RDRAM. Larger games can use the Expansion Pak. On MMC5 and mapper 228, the loader can fetch 8 KiB PRG banks from the N64 cartridge on demand when the complete image would exceed the memory budget. The build checks the end of program statics against the VI buffer allocation.

## Display engine integration

**No change is required to the in-progress Neon Arcade Display Engine.** Its N64 port already presents through LibPureMetalN64. This emulator acquires the framebuffer with `LpmDisplayGet`, writes native RGBA5551 pixels, writes back the CPU cache, and presents with `LpmDisplayShow`. Keeping the original PPU in control of rasterization preserves mid-scanline register writes, sprite-zero hits, and mapper fetch effects. N64 controller and audio output use the existing Joybus and AI APIs. If a future cross-platform frontend needs an engine-only interface, the missing convenience would be a way to acquire a writable CPU framebuffer with its format and stride, then present it. The current cart already has that functionality through the underlying library.

## Verification

The physical-console log records the build hash, reset vector, CPU cycles, sample counts and program counter. At guest frame 120 the console reported 3,573,714 NES CPU cycles and 95,843 produced audio samples. The same image gave identical guest checkpoints in the N64 emulator. The console run preceded the final large-ROM storage and PAL frame-limit changes. [Hardware capture](validation/demo-console.txt)

For a reproducible end-to-end check, install Pillow and run:

```powershell
python n64/verify.py --sdk "$env:PMF_ROOT" --emulator "C:\path\to\VR4300RSPStudio.exe"
```

The check builds the bundled demo, boots it with 4 MiB RDRAM, and stops the guest after frame 60. It compares all 61,440 pixels against the desktop emulator's frame at N64 color precision, checks both borders, verifies the guest CPU and APU counters, and checks captured stereo PCM. Normal builds keep running. The same frame comparison also passed for a PAL-header copy of the demo. Synthetic tests in the N64 emulator exercised MMC1 and MMC3 PRG and CHR switching, MMC5 PCM read side effects, mapper 234 read-triggered banking, VRC6 and Namco 163 expansion audio, and large MMC5 and mapper 228 ROMs. Two controller masks verified all eight serial bits, strobe behavior and an idle second port. Across 1,500 guest frames, the optimized APU produced byte-identical audio and the same final picture as the earlier implementation. Physical-console coverage so far is the bundled UxROM demo.
