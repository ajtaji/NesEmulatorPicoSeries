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

The port reads NTSC or PAL guest timing from the NES header. The VI uses the console's TV standard. The guest PPU renders 256 Ã— 240 in a centered 320 Ã— 240 framebuffer with three VI buffers. In the runtime MMC3 cartridge everything outside the picture is black on every shown frame, and the outer 8 columns on each side, which a CRT's overscan hid, are drawn black as well (`#NES_CROP_X` and `#NES_CROP_Y` in `show.n64`). An emulator stop shows a red screen. The AI receives 16-bit stereo at a nominal 48 kHz, with the mono NES mix on both channels.

The VR4300 executes the Anvil 2A03 core. Its MIPS interpreter uses computed jumps and keeps the NES registers, flags and cycle budget in host registers across ordinary instructions. Memory-mapped operations use the shared bus handlers. The builder recognizes short read-only loops in the selected PRG banks. On MMC1 and CNROM, it verifies the entire loop fits within the active physical 8 KiB slot. The CPU can batch a RAM wait within an execution window, or a PPU status wait up to the first event that could change the returned value or signal an interrupt. Timed writes, sprite-zero hits, sprite overflow, frame IRQs and DMC reads bound those intervals.

The runtime MMC3 cartridge does not use that interpreter: it runs its own 2A03 core in documented VR4300 assembly, `cpu6502.n64`. One handler per opcode, one shared block per addressing mode, the guest registers and flags held in host registers for the whole window, internal RAM, the stack, PRG ROM and work RAM inline, and every other address a call to the same bus procedures. It reproduces the interpreter's behaviour exactly, including its access phases, open-bus values and polling shapes. A checking build (`build.py` with the CPU trace on, `cputrace.n64`) folds the state after every instruction into a per-frame digest, so the two cores can be compared frame by frame over the same fixed-input route. The other cartridge configurations still use the interpreter.

The playable runtime MMC3 cartridge can keep a record of a console run. `build.py --console-record` adds `console_record.n64`: once a guest frame it counts the pictures shown and not shown, the sound underruns, the frame period and the emulator's own work in it (Count ticks), the RSP band program's clocks and the RDP's busy counters, and once a second it writes them into the SummerCart64's memory (its ROM space, made writable at start), where a reader dumps them over USB after the run. Without the option the cartridge is byte for byte the same. The record also splits each frame's work into its parts (band closes, fallback lines, the hand-over, the APU timing and its calls, the sound synthesis, the DMC bytes and PPU writes, and what is left for the guest CPU) and hashes the pictures shown before the first button. `--record-every-picture` hashes every shown picture instead, in a record area of its own, for a test cartridge that runs by itself: `tests/make_nametable_test.py out.nes --scroll` writes one, a side-scrolling picture under both mirrorings that rewrites the column entering at the right edge, for about a minute, and then a plain screen.

The PPU produces a 256 × 240 indexed image. NROM and UxROM cartridges with 8 KiB of CHR use expanded pattern rows updated on CHR writes and tile descriptors updated on nametable writes. Scroll and sprite composition still run at guest timestamps. Banks with PPU fetch side effects retain the original callbacks. The VR4300 synthesizes audio in native blocks and supplies nominal 48 kHz stereo to the AI. The VI runs independently. A completed NES picture can be superseded if the VI still owns all three buffers and waiting would drain the audio reserve. The guest PPU renders each frame and processes its status edges.

## Cartridge support

The builder uses the project's Anvil mapper and header validation plus the VRC6 and Namco 163 support from the desktop port. It carries over the existing board restrictions, including unsupported trainers, Dendy timing, VRC6 nametable modes and Namco 163 CHR-RAM pattern banking. The game is embedded at build time, so the port needs no flash-cart filesystem driver.

Small games use base RDRAM. Larger games can use the Expansion Pak. On MMC5 and mapper 228, the loader can fetch 8 KiB PRG banks from the N64 cartridge on demand when the complete image would exceed the memory budget. The build checks the end of program statics against the VI buffer allocation.

## SummerCart64 NES library

The library launcher opens original `.nes` files on a FAT32 SummerCart64 SD card. It reads the header, selects the existing mapper backend and maps the original ROM banks. Backend selection uses board and memory geometry. The library contains no NES ROMs or per-title emulator images. It accepts NTSC iNES and linear-size NES 2.0 images for the project's mapper IDs, subject to board geometry and RDRAM limits. Legacy headers that require database corrections and PAL timing are still handled by the standalone build. [Runtime checks](validation/sd-library.txt)

```powershell
python n64/library.py build --sdk "$env:PMF_ROOT" --out "NES Library.z64"
python n64/library.py saves "path-to-roms" "path-to-sd\NES\SAVES"
```

Put the input `.nes` files under `/NES/USA/` and put `NES Library.z64` on the card beside the existing flashcart menu. Launch it from the flashcart menu. D-pad up/down moves through the list, left/right or C-left/C-right jumps by initial letter, Z opens the letter picker, L/R moves a page, A opens a game, and Start opens the display settings. In a running game, hold L+R for half a second to return to the library. A game with an unsupported board or format shows an error in the browser.

Battery-backed games use individual 32 KiB files under `/NES/SAVES/`. MMC5 uses 128 KiB files. The hex filename is the CRC32 of the iNES header and declared PRG and CHR bytes. The host tool provisions erased files and preserves existing saves. The launcher configures SummerCart64 SD writeback for the selected file, then the emulator updates its SRAM as the guest saves. USB ROM deployment of the launcher still reads games and saves from SD.

## Battery saves on flashcarts

Playable builds persist battery RAM on supported boards and declare the required SRAM size in their N64 cartridge header. Ordinary work RAM remains volatile. `--no-persist-save` builds a playable cartridge with volatile RAM. Bounded verification leaves persistence off by default, so the same ROM and input schedule always start with fresh guest RAM.

Zelda retains the first 8,192 bytes of a 32 KiB N64 SRAM save. Use the game's normal file and save commands. The port restores those bytes after mapper initialization and writes changed 256-byte pages at the end of each guest frame. This stores the NES battery memory, so a cold boot returns to the game's own save selection screen. On an SRAM write error the port keeps the pending pages for retry.

The build selects the board's existing save memory, including banked MMC5 and Sunsoft RAM. Namco 163 packs its 128 internal bytes after any external save RAM. NES 2.0 headers select the nonvolatile region independently of volatile memory. A battery header with no supported backing produces a build diagnostic. To exercise battery saves in a bounded test, pass `--persist-save` and use a private emulator save directory.

The header uses the ED64 homebrew save type. The flashcart maps that SRAM into N64 PI domain 2 and handles transferring it to a save file. The sizes below are the N64 SRAM chip capacities. They can exceed the number of bytes the NES board retains. [Flashcart menu header parser](https://github.com/n64brew/N64FlashcartMenu/blob/1903b4bcfe388a4048bc14551115ff5525085a51/src/menu/rom_info.c#L726-L744) [SummerCart64 deployer header parser](https://github.com/Polprzewodnikowy/SummerCart64/blob/a1e7996d2cbece686820a5c785029c68514f17b0/sw/deployer/src/n64.rs#L18-L40)

| N64 capacity | ED64 save nibble | `sc64deployer --save-type` |
|---:|---:|---|
| 32 KiB | 3 | `sram` |
| 96 KiB | 4 | `sram-banked` |
| 128 KiB | 6 | `sram1m` |

SummerCart64 maps its 96 KiB mode as three 32 KiB banks and its 128 KiB mode as contiguous SRAM. The 128 KiB build uses the contiguous layout by default. Use `--banked-sram-128` only for the project's emulator or hardware that implements four banks at 256 KiB strides. Use the layout your flashcart implements when moving the cartridge between devices. [SummerCart64 PI address decoder](https://github.com/Polprzewodnikowy/SummerCart64/blob/a1e7996d2cbece686820a5c785029c68514f17b0/fw/rtl/n64/n64_pi.sv#L211-L228)

For normal SD boot with N64FlashcartMenu, copy the playable `.z64` to the SD card and select it in the menu. The menu recognizes the header and stores each game's file under a `saves` directory next to its ROM, using the same base name with a `.sav` extension. Give each game and save profile a distinct filename. Back up the existing save before changing the save type or moving it to another flashcart. [N64FlashcartMenu SD save files](https://github.com/n64brew/N64FlashcartMenu/blob/1903b4bcfe388a4048bc14551115ff5525085a51/docs/10_getting_started_sd.md#save-files)

For SummerCart64 USB boot, stop any other listener using that port and upload with the console off. Supply an existing save or a new dedicated file of exactly the selected N64 capacity. This 32 KiB direct-boot example uses the tag for Zelda's 8 KiB guest battery RAM.

```powershell
sc64deployer -p serial://<port> upload --direct --save-type sram --save "Zelda.sav" "Zelda.z64"
sc64deployer -p serial://<port> debug --save "Zelda-writeback.sav"
```

The second command receives USB writeback into a separate file. After saving in-game, wait for the writeback confirmation before stopping the listener or powering down. With USB power maintained, `sc64deployer download save <new-file>` reads the active save into a backup before an upload or reset replaces it. Keep ROM shadowing at its default. The default IS-Viewer address `0x03FF0000` overlaps 96 and 128 KiB saves, so omit `--isv` when using those modes. The benchmark listener uses `--no-writeback` and is intended for verification carts. [SummerCart64 shared save memory](https://github.com/Polprzewodnikowy/SummerCart64/blob/a1e7996d2cbece686820a5c785029c68514f17b0/docs/01_memory_map.md#pi-memory-map) [Deployer save and debug commands](https://github.com/Polprzewodnikowy/SummerCart64/blob/a1e7996d2cbece686820a5c785029c68514f17b0/sw/deployer/src/main.rs)

Use the postbuild helper if an already SRAM-enabled cartridge needs a corrected header. The helper creates a new file and leaves the original intact. It changes no guest code or cartridge checksums. Select the capacity the runtime expects, and apply this before any optional cartridge signing.

```powershell
python n64/save_header.py input.z64 output.z64 --sram-kib 32
```

## Display engine integration

The emulator uses LibPureMetalN64 directly. It acquires a VI buffer with `LpmDisplayGet`, uploads indexed strips and scanline palettes through the RDP, and presents after the RDP interrupt with `LpmRdpDetachShow`. Joybus supplies controller input. The in-progress Neon Arcade Display Engine requires no changes for this port.

## Verification

Run `python n64/verify_save.py --sdk <sdk> --emulator <emulator>` to test all 8 KiB of MMC1 save RAM across two independent boots and check the volatile controls.

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

Use a local NTSC ROM to replay World 1-1 in Super Mario Bros., the overworld in The Legend of Zelda, or Wood Man's stage in Mega Man 2. The verifier checks the ROM revision, applies controller input on guest frames, and compares the guest CPU cycles, PC, sample counts and final 320 by 240 framebuffer against the pre-optimization build. It checks the complete captured stereo stream against its verified audio reference. It reports guest fps using the modeled N64 Count register and counts AI queue-empty transitions during the gameplay interval.

```powershell
python n64/verify_library.py MegaMan2 --sdk "$env:PMF_ROOT" --emulator "C:\path\to\VR4300RSPStudio.exe" --rom "path-to-roms\Mega Man 2 (U).nes" --results n64/build/gameplay/verified/MegaMan2
```

Add `--extended` to the Mega Man 2 command to continue moving, jumping and firing through frame 1860 at 20 kHz. Its `metrics.txt` includes the later 600 frames and each 60-frame interval so short slowdowns and audio gaps are visible.

Use `--endurance` for the 20 kHz World 1-1 route through frame 1140, the Zelda sword pickup and return outdoors through frame 1440, or Wood Man through frame 3060. Add `--combat` on the Zelda command in place of `--endurance` to keep moving and attacking in the enemy room through guest frame 1980. Use `--combat 2940` to extend the same route with another 960 frames of movement and sword attacks. The per-interval results include coalesced video presentations.

Select `Mario` or `Zelda` and supply the corresponding ROM to run the other replays. Each results directory contains the debugger log, framebuffer, stereo WAV and bounded replay cartridge. Use `n64/build.py` without `--check-frame` to build a cartridge for unrestricted controller play.

The N64 build defaults to 48 kHz audio. Pass `--audio-rate 20000` to `n64/build.py` or `n64/verify_library.py` to mix the mono NES signal at 20 kHz and send it to both AI channels. Both rates use the same regional NES CPU and device clocks. The 20 kHz mode uses 512 sample frames per AI buffer (25.6 ms) and adjusts the DC filter for the lower rate.

At both output rates, the N64 mixer averages the nonlinear triangle/noise/DMC output over a triangle cycle when the active triangle timer is 0 or 1. The triangle sequencer continues advancing. When either counter stops it, the mixer uses the held DAC value. This removes the audible tone that appeared when Mega Man 2 parked the channel at an ultrasonic frequency. [Title and Wood Man measurements](validation/triangle-audio.txt)
