# Video and audio plugins

Video and audio are independent build-time plugins. Select them in the entry
wrapper, without editing the CPU, PPU, APU, scheduler, or ROM loader. Calls are
direct and statically linked; there is no runtime plugin loader or per-pixel
virtual dispatch. Output API version 1 is declared in `outputs/state.pico`.

| Wrapper setting | 0 | 1 | 2 |
|---|---|---|---|
| `#NES_VIDEO_BACKEND` | Headless | LAFVIN ST7796/SPI DMA | Your video plugin |
| `#NES_AUDIO_BACKEND` | Silent | Bluetooth A2DP/SBC | Your audio plugin |

Both constants must be set before including `runtime`. The normal `demo` and
verification wrappers select 1/1. Selecting 0 or 2 excludes that output's
bundled hardware libraries and implementation, not merely its initialization.
The emulated PPU and APU continue running with headless/silent outputs.
In headless mode the legacy `lcd`/display count measures completed backend frame
consumption; it does not represent a physical display refresh.

The folders and extensions are `rp2040/*.pico` with `.picow` wrappers, or
`rp2350/*.pico2` with `.pico2w` wrappers. Use the board-specific libraries in a
hardware plugin. The RP2350 tree is regenerated from RP2040 sources by
`tools/port_rp2350.py`; add bundled plugins to RP2040 first and extend that
generator for any MCU-specific register differences.

## Make a wrapper

Copy the target's `demo` wrapper so its CPU, timing, CHR, and split settings are
retained. Change the two backend constants, then include your plugins after
`runtime` and before `Main()`. For example, a Pico 2 W wrapper can retain the
ST7796 display and replace Bluetooth with your DAC:

```text
#NES_VIDEO_BACKEND=1
#NES_AUDIO_BACKEND=2
; Retain the other configuration lines from rp2350/demo.pico2w here.
EnableExplicit
XIncludeFile "runtime.pico2"
XIncludeFile "cartridge.pico2"
XIncludeFile "my_dac.pico2"
Main()
```

These paths assume the wrapper is beside `rp2350/demo.pico2w`. A plugin can
include its own device libraries. Keep personal configuration, speaker addresses,
and device-specific wiring in your wrapper. `my-*.picow` and `my-*.pico2w` wrappers
are ignored by Git.

Runnable examples for each chip:

- `examples/headless`: no display or audio hardware backend (0/0).
- `examples/custom_output`: wrapper-supplied video and audio (2/2). It includes
  a headless video implementation and a PCM staging-buffer audio example.
- `examples/pcm_st7796`: bundled display with custom PCM consumption (1/2).
- `examples/headless_bluetooth`: headless video with bundled Bluetooth (0/1);
  add a private peer configuration to enable its Bluetooth connection.
- `examples/pcm_capture`: an audio plugin implementing the sample-copy contract.
  It drives no physical audio device. It is a starting point for a DAC/I2S/PWM
  implementation, not a claimed working DAC driver.

For example:

```powershell
tools/build.ps1 -Compiler path\to\PureMetalForge.exe -Source rp2350/examples/custom_output.pico2w -Output rp2350/Diagnostics/custom-output.uf2
```

## Video contract

The PPU produces a completed **256x240 RGB565** frame. Pixels are native-endian
16-bit words, 256 pixels per row, 512 bytes per row. Memory has two separate
buffers: `top` contains rows 0..119 and `bottom` rows 120..239; each is 61,440
bytes. Do not assume those buffers are adjacent. Convert color format, scale,
letterbox, rotate, and set the panel window inside the video plugin.

| Procedure | Caller | Contract |
|---|---|---|
| `VideoBegin()` | Core 0, before worker launch | Initialize device and clear the physical display. |
| `VideoClockHz()` | Core 0, startup reporting | Return actual bus clock, or 0 if not applicable. |
| `VideoStart(top,bottom)` | Core 1 | Accept one completed frame; return 1, or 0 on failure. Start DMA or a bounded copy. |
| `VideoPoll()` | Core 1 | Return 0 while busy, 1 once the frame is fully consumed, or -1 on failure. Service transfer stages without blocking. |
| `VideoCanWriteLine(line)` | Core 0 | Return 1 only if the backend will never read that row again for the current transfer. Returning 0 is always valid. |
| `VideoHudRect(x,y,width,height,pixels)` | Core 1, between frames | Draw a host RGB565 rectangle; consume/copy its pixels before returning. Clip or ignore unsupported HUD regions. |
| `VideoAbort()` | Core 1 | Cancel transfers and release hardware safely. Never acknowledge still-running DMA as complete. |

`display.pico[2]` owns frame tickets, fences, timeouts, completion counts, and
the wait before overwriting a buffer. A plugin must not change those globals or
publish `DisplayDone` itself. It must not modify emulated pixels or retain
framebuffer pointers after completing the frame. Only one frame is submitted at
a time. Initialization does not submit partial frames.

Implement `VideoCanWriteLine` as `ProcedureReturn 0` first: the scheduler will
wait for full completion before reusing any row. The bundled DMA backend reports
safe row progress to overlap next-frame rendering with the current transfer.
This hook runs on a different core: inspect only atomically published state and
hardware progress, use memory barriers when publishing progress, and never call
the device's mutable SPI/command routines from it. Conservative progress is safe;
optimistic progress can corrupt a frame.

The framebuffer always represents the NES image. The FPS overlay goes through
`VideoHudRect` and remains outside PPU rendering. The bundled backend centers the
frame at (112,40) on Pico W landscape, or (32,120) on Pico 2 W's rotated portrait
display. Custom backends choose their own presentation and HUD placement.

## Audio contract

The unchanged APU produces **48,000 signed 16-bit mono PCM samples per emulated
second** in a 4096-sample ring. A plugin owns the device clock, sample-format
conversion, buffering, channel duplication, encoding, resampling, and underrun
behavior. A stereo/I2S device can duplicate samples; a different device sample
rate needs resampling inside the plugin.

| Procedure | Caller | Contract |
|---|---|---|
| `AudioBegin()` | Core 0, after selection and before CPU reset | Initialize output, reset consumer state, then enable it. Worker polling can already be running: keep `AudioRunning=0` until initialization is complete. |
| `AudioPoll()` | Core 1 | Cooperatively consume/refill output; set `AudioWorked=0` on an idle pass. Return promptly so APU events and display DMA stay serviced. |
| `AudioReset()` | Audio backend | Set the generic consumer cursor to the current producer position. Call only while its consumer is stopped or on its owning core. |
| `AudioRead(destination,capacity)` | Core 1, one consumer | Copy up to `capacity` available samples to plugin-owned memory and return the count. Capacity is in samples; destination must hold that many 16-bit words. |

`AudioRead` preserves signed samples and ring order, handles wraparound, and caps
reads at 4096 samples. A null destination or nonpositive capacity is refused;
the plugin must supply valid, 16-bit-aligned writable memory. If the consumer fell
behind by more than a ring, it records one `AudioOverruns` event and retains the
newest ring. It does not generate silence or count an underrun for a short read:
the device plugin knows when a hardware deadline was missed and applies its own
policy. Never read stale samples as though they were new.

Copy PCM into your own DMA buffers. Do not point a DAC DMA channel at the APU
ring: the APU will reuse it. Do not call `AudioRead` concurrently or from an ISR
while `AudioPoll` uses its cursor. An ISR can flag which plugin-owned buffer needs
refilling; `AudioPoll` fills it. The bundled Bluetooth backend retains its tested
private SBC packet cursor and codec logic; custom plugins can use `AudioRead`.

Shared fields in `outputs/state` are the backend's status/telemetry interface:

| Field | Meaning |
|---|---|
| `AudioRunning` | Consumer is initialized and allowed to run. |
| `AudioLive` | Output is active (not a claim about sound quality). |
| `AudioWorked` | Last poll did work; reset on idle polls. |
| `AudioBusyUs` | Cumulative time spent doing output work. |
| `AudioPackets` | Completed packets or device-buffer submissions. |
| `AudioUnderruns`, `AudioOverruns`, `AudioWireErrors` | Cumulative backend error counters. |
| `AudioQueueSlack` | Additional permitted APU queue lag in guest CPU cycles, 0..1536; normally 0 for a DAC. Bluetooth retains its existing 1536-cycle allowance. Actual DMC reads still force synchronization. |

Telemetry includes generic `audio_*` fields. Bluetooth builds also retain the
old `bt_*` labels for existing measurement tools. USB `q` and `k` remain
Bluetooth-specific diagnostics, compiled only with backend 1.

## Timing, ownership, and resources

The output contracts target the normal `#NES_SPLIT=2` configuration: CPU/PPU on
core 0; APU, audio output, and video transfer on core 1. Keep worker callbacks
bounded and cooperative. A blocking multi-millisecond transfer can starve the
other output. Put hot poll/progress routines in `ProcedureRAM` where appropriate.
Core 0 alone owns USB and watchdog service. The ROM loader parks core 1 in SRAM
while writing flash; plugins must not create an independent flash-reading core
or flash-resident interrupt handler that bypasses that arrangement.

Default video owns SPI0, DMA channel 0, and GP2/3/5/6/7. Bluetooth owns the radio
and its fixed GP23/24/25/29 bus. Inputs own GP14/15 and ADC GP26/27. Allocate
other DMA channels/peripherals/pins for a DAC, or replace the conflicting backend.
Respect the compiler ABI and the emulator's reserved registers in custom assembly.

## Checks

`Diagnostics/outputs` is a standalone on-board contract suite with custom mock
video and PCM plugins. It tests deferred frame consumption, completion counts,
abort/timeouts, disabled video, HUD isolation, signed PCM order, partial reads,
ring/counter wraparound, overruns, and the example consumer. It does not emulate
the MCU on the host and contains no commercial ROMs.

```powershell
tools/build.ps1 -Compiler path\to\PureMetalForge.exe -Source rp2350/Diagnostics/outputs.pico2w -Output rp2350/Diagnostics/outputs.uf2 -Port COM6 -Seconds 8
```

The existing full emulator suite and board gameplay measurements validate the
bundled devices. A third-party plugin also needs its own device-level validation;
the PCM example makes no untested DAC hardware claims.

## Pi 4 / Anvil

The [Anvil port](anvil/README.md) selects video, input and audio modules with
`tools/build_anvil.py --video-plugin`, `--input-plugin` and `--audio-plugin`.
Its scheduler runs guest computation on core 1 and all device/service calls on
core 0. This differs from the Pico ownership described above. Plugins must
release their resources before Main returns to Anvil. The default video module
uses Neon Arcade/Vulkan and complete-frame DMA; Bluetooth consumes the same
48 kHz signed PCM ring. The initial port has build-time plugin selection.
The Anvil touch selector adds `VideoMenuDraw()` and `InputMenuPoll()` to
selector-enabled plugins; their contracts and exFAT ROM folder are documented
in the Anvil README. `--no-selector` retains the smaller embedded-demo mode.

On Anvil, gameplay input plugins may set `MenuRequested` to stop the joined
guest session and return to the ROM selector. `ExitRequested` still returns
to Anvil. The lifecycle adapter suspends Bluetooth while the selector is
active, resets guest PCM/state, and resumes the same connection for a new game.
Other audio plugins use their existing `AudioStop()` / `AudioBegin()` contract.
