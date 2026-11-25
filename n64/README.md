# NES on Nintendo 64

Build a Nintendo 64 cartridge that boots directly into one NES game. The included PureMetal NES demo ran on a physical N64 with SummerCart64. The initial hardware build ran its animated scene at **4.60 NES frames per second** between guest frames 60 and 120. At that speed the AI runs out of samples between submissions and music plays intermittently. Real-time NTSC gameplay requires roughly 60 guest frames per second.

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

The port reads NTSC or PAL guest timing from the NES header. The VI uses the console's TV standard. The guest PPU renders 256 Ã— 240 in a centered 320 Ã— 240 framebuffer with three VI buffers. The AI receives 16-bit stereo at a nominal 48 kHz, with the mono NES mix on both channels.

The VR4300 executes the Anvil 2A03 core. Its MIPS interpreter uses computed jumps and keeps the NES registers, flags and cycle budget in host registers across ordinary instructions. Memory-mapped operations use the shared bus handlers. The builder recognizes short read-only loops in the selected PRG banks. On MMC1 and CNROM, it verifies the entire loop fits within the active physical 8 KiB slot. The CPU can batch a RAM wait within an execution window, or a PPU status wait up to the first event that could change the returned value or signal an interrupt. Timed writes, sprite-zero hits, sprite overflow, frame IRQs and DMC reads bound those intervals.

The PPU produces a 256 × 240 indexed image. NROM and UxROM cartridges with 8 KiB of CHR use expanded pattern rows updated on CHR writes and tile descriptors updated on nametable writes. Scroll and sprite composition still run at guest timestamps. Banks with PPU fetch side effects retain the original callbacks. The VR4300 synthesizes audio in native blocks and supplies nominal 48 kHz stereo to the AI. The VI runs independently. A completed NES picture can be superseded if the VI still owns all three buffers and waiting would drain the audio reserve. The guest PPU renders each frame and processes its status edges.

## Cartridge support

The builder uses the project's Anvil mapper and header validation plus the VRC6 and Namco 163 support from the desktop port. It carries over the existing board restrictions, including unsupported trainers, Dendy timing, VRC6 nametable modes and Namco 163 CHR-RAM pattern banking. Mapper work RAM is volatile across resets and power cycles. The game is embedded at build time, so the port needs no flash-cart filesystem driver.

Small games use base RDRAM. Larger games can use the Expansion Pak. On MMC5 and mapper 228, the loader can fetch 8 KiB PRG banks from the N64 cartridge on demand when the complete image would exceed the memory budget. The build checks the end of program statics against the VI buffer allocation.

## Display engine integration

The emulator uses LibPureMetalN64 directly. It acquires a VI buffer with `LpmDisplayGet`, uploads indexed strips and scanline palettes through the RDP, and presents after the RDP interrupt with `LpmRdpDetachShow`. Joybus supplies controller input. The in-progress Neon Arcade Display Engine requires no changes for this port.

## Verification

The physical-console log records the build hash, reset vector, CPU cycles, sample counts and program counter. At guest frame 120 the console reported 3,573,714 NES CPU cycles and 95,843 produced audio samples. The same image gave identical guest checkpoints in the N64 emulator. That console measurement predates the VR4300 interpreter, PPU and APU optimizations. [Hardware capture](validation/demo-console.txt)

For a reproducible end-to-end check, install Pillow and run:

```powershell
python n64/verify.py --sdk "$env:PMF_ROOT" --emulator "C:\path\to\VR4300RSPStudio.exe"
```

The check builds the bundled demo, boots it with 4 MiB RDRAM, and stops the guest after frame 60. It compares all 61,440 pixels against the desktop emulator's frame at N64 color precision, checks both borders, verifies the guest CPU and APU counters, and checks captured stereo PCM. Normal builds keep running. The same frame comparison also passed for a PAL-header copy of the demo. Synthetic tests in the N64 emulator exercised MMC1 and MMC3 PRG and CHR switching, MMC5 PCM read side effects, mapper 234 read-triggered banking, VRC6 and Namco 163 expansion audio, and large MMC5 and mapper 228 ROMs. Two controller masks verified all eight serial bits, strobe behavior and an idle second port. Across 1,500 guest frames, the optimized APU produced byte-identical audio and the same final picture as the earlier implementation. On the physical N64, Thwaite v0.04 also completed the scripted tutorial, handed off to the controller, and reached guest frame 1,800. The first hardware run exposed an address error on a row-end cache writeback. Aligning the writeback to a 16-byte cache line fixed startup. The corrected hardware baseline measured 56.10 guest fps and five queue-empty events between frames 180 and 240. [Thwaite console trace](validation/thwaite-console.txt)

For a timing run, add `--benchmark` to the verification command. It builds a continuously running cartridge and measures the difference in modeled CP0 Count between guest frames 60 and 120 at 46,875,000 ticks per second. Checkpoint builds additionally report AI buffer submissions and observed queue-empty transitions after playback starts. Comparing recorded PCM checks sample values. The queue counter measures interruptions in playback.

The initial cartridge measured 4.35 guest fps on the N64 model. The updated port reaches the VI rate in the bundled demo and in the active Thwaite input replay. The hardware timing above applies to the original cartridge.

The controller replay uses the upstream Thwaite v0.04 cartridge. Supply the NES file locally and run the following command. It checks the game state after starting the game, advancing the tutorial, moving and firing. The report times each 60-frame interval, counts AI underruns and compares the final picture and every complete PCM block to a reference. [Thwaite v0.04 release](https://github.com/pinobatch/thwaite-nes/releases/tag/v0.04)

```powershell
python n64/verify_game.py --sdk "$env:PMF_ROOT" --emulator "C:\path\to\VR4300RSPStudio.exe" --rom "C:\Games\thwaite.nes"
```

Thwaite sustained about 60 guest fps during movement and firing with zero observed AI underruns. The optimized tutorial interval from guest frames 180 to 240 averaged 60.76 fps. The entire 450-frame replay recorded zero underruns, and all 61 tutorial pictures matched the earlier renderer's frame fingerprints. During the busiest frame the guest uploads 3,199 nametable bytes. The CPU batches identical PPUDATA stores in counted loops only while rendering is disabled and the next device event is beyond the batch. The PPU updates the mirrored tile bytes and their cached rendering data together. In the optimized demo's 1,800-frame run, the last queue-empty event occurred at guest frame 41 during silent initialization. Playback stayed fed from the first audible sample onward. Nova the Squirrel v1.0.3 also reached its MMC1 title screen with identical guest state and pixels before and after banked wait batching. The current v1.0.6a cartridge requests 32 KiB of nonvolatile PRG RAM, beyond the port’s existing 8 KiB MMC1 work RAM. [Emulator results](validation/playability.txt)

## Commercial gameplay replays

Use a local NTSC ROM to replay World 1-1 in Super Mario Bros., the overworld in The Legend of Zelda, or Wood Man's stage in Mega Man 2. The verifier checks the ROM revision, applies controller input on guest frames, and compares guest CPU cycles, PC, sample counts, the final 320 by 240 framebuffer and the complete captured stereo stream with the pre-optimization build. It reports guest fps using the modeled N64 Count register and counts AI queue-empty transitions during the gameplay interval.

```powershell
python n64/verify_library.py MegaMan2 --sdk "$env:PMF_ROOT" --emulator "C:\path\to\VR4300RSPStudio.exe" --rom "path-to-roms\Mega Man 2 (U).nes" --results n64/build/gameplay/verified/MegaMan2
```

Add `--extended` to the Mega Man 2 command to continue moving, jumping and firing through frame 1860 at 20 kHz. Its `metrics.txt` includes the later 600 frames and each 60-frame interval so short slowdowns and audio gaps are visible.

Use `--endurance` for the 20 kHz World 1-1 route through frame 1140, the Zelda sword pickup and return outdoors through frame 1440, or Wood Man through frame 3060. The per-interval results include coalesced video presentations.

Select `Mario` or `Zelda` and supply the corresponding ROM to run the other replays. Each results directory contains the debugger log, framebuffer, stereo WAV and bounded replay cartridge. Use `n64/build.py` without `--check-frame` to build a cartridge for unrestricted controller play.

The N64 build defaults to 48 kHz audio. Pass `--audio-rate 20000` to `n64/build.py` or `n64/verify_library.py` to mix the mono NES signal at 20 kHz and send it to both AI channels. Both rates use the same regional NES CPU and device clocks. The 20 kHz mode uses 256 sample frames per AI buffer (12.8 ms) and adjusts the DC filter for the lower rate.
