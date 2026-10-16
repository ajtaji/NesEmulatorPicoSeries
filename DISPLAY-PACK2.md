# Pico Display Pack 2.0 / ST7789

The ST7789 plugin supports Pimoroni's 320×240 Pico Display Pack 2.0 on Pico W
and Pico 2 W. Choose it at build time or download the matching Display Pack UF2
from Releases. LAFVIN remains the default display. These are separate controller
drivers; selecting one changes neither the emulated CPU/PPU/APU nor audio plugin.

## Select and build

```powershell
tools/build.ps1 -Compiler path\to\PureMetalForge.exe -Target rp2040 -Display display-pack2
tools/build.ps1 -Compiler path\to\PureMetalForge.exe -Target rp2350 -Display display-pack2
```

Outputs are `firmware/nes-pico-w-display-pack2.uf2` and
`firmware/nes-pico2-w-display-pack2.uf2`. Select `-Display lafvin` for the original
carrier. `-Port COM7` / `-Port COM6` optionally uploads to the appropriate board.
`-Source` selects a custom wrapper instead of `-Display`. The loader and ROM
store work the same way for either display.

For a private speaker/DAC wrapper, copy `rp2040/display_pack2.picow` or
`rp2350/display_pack2.pico2w` and keep `#NES_VIDEO_BACKEND=3`. Audio settings stay
independent: 0=silent, 1=Bluetooth, 2=your audio plugin. Private speaker configuration
and commercial ROMs are excluded from the downloadable images.

## Wiring and behavior

| Signal | Pico GPIO |
|---|---:|
| SPI0 SCK | 18 |
| SPI0 MOSI | 19 |
| Chip select | 17 |
| Data/command | 16 |
| Backlight, on after clear | 20 |

The panel uses a software reset. The full 256×240 NES frame is centered at x=32,
y=0, without scaling or cropping. The FPS and emulation-rate counters occupy the
left 32-pixel margin and never modify the emulated framebuffer. The ROM menu uses
the same completed-frame path. DMA channel 0 sends the two existing 120-row
buffers as one panel window; submission happens only after a frame is complete.
Completion waits for both DMA and the SPI shifter before releasing chip select.
No additional full-screen buffer is allocated.

Pico W presents every second frame, about **30 FPS**, while keeping emulation,
PPU timing, interrupts, controller sampling and audio at the normal 60 Hz guest
rate. The discarded presentation frame writes RGB pixels into a single 512-byte
scratch row, so it cannot overwrite the completed frame while DMA is reading it.
Pico 2 W presents every frame, about **60 FPS**. The menu uses the same selected
output cadence. `St7789FrameDivider=1` or `2`, set before `Main()` in a custom
wrapper, selects every frame or every second frame. The FPS overlay reports the
actual display rate separately from the emulation rate.

With the ST7789 bus unconnected, the physical Pico W running Contra measured
60.09 emulated FPS, 30.00 completed display transfers per second, 1,789,774 guest
CPU cycles/s and 47,999 audio samples/s, with Bluetooth connected and no reported
CPU/bridge errors. This validates separate guest/presentation pacing; it does not
validate the absent panel's picture or refresh behavior.

Controller input is independent of this video plugin. The existing carrier uses
GP14/15 buttons and a GP26/27 joystick; Display Pack's four buttons alone do not
provide an NES D-pad. USB diagnostic controls also remain available. The RGB LED
is not required by the display driver. Keep display pins separate from any DAC
or other SPI peripheral.

## SPI rate and validation limits

Pico W requests 62.5 MHz, matching Pimoroni's RP2040 setting. With this emulator's
200 MHz clock and integer SPI divider, the actual bus is 50 MHz. Sending 122,880
frame bytes therefore takes at least 19.66 ms: full-frame display throughput is
below 60 FPS on that path. Pico 2 W uses Pimoroni's 75 MHz RP2350 setting; its
minimum transfer time is 13.11 ms. `VideoClockHz()` reports the actual rate.
These are transfer limits, not measured panel FPS. `St7789SpiKhz` may be set before
`Main()` in a custom wrapper; higher requests require hardware validation.

This display plugin is **experimental: the user has no Display Pack available**.
Both target builds are compiled and checked against the ROM-store boundary.
The physical Picos each pass 90 transport/presentation checks using an
**unconnected ST7789 SPI bus**. They exercise both DMA halves, shifter completion,
chip-select release, abort recovery, scratch-row isolation and the 30/60 cadence.
The ten-frame DMA test took 215,358 us at 50 MHz on W and 143,756 us at 75 MHz on
2 W, including test-loop overhead. These are bus-path measurements with no panel.
Sources and transcripts are `Diagnostics/st7789` and `Diagnostics/st7789-results/`
in each target. Rebuilt LAFVIN UF2s are byte-for-byte identical to the tested
release images, and Anvil regeneration is byte-identical.
Physical image orientation, colors, panel stability and FPS still require a
connected Display Pack; the test boards currently carry LAFVIN displays. The
existing LAFVIN firmware and board regression results remain separately available.

The pinout, 320×240 initialization values and landscape MADCTL setting follow
[Pimoroni's display driver](https://github.com/pimoroni/pimoroni-pico/blob/main/drivers/st7789/st7789.cpp),
its [SPI rate settings](https://github.com/pimoroni/pimoroni-pico/blob/main/drivers/st7789/st7789.hpp),
and [pin definitions](https://github.com/pimoroni/pimoroni-pico/blob/main/common/pimoroni_common.hpp).
The [Adafruit Display Pack example](https://github.com/adafruit/Adafruit_CircuitPython_ST7789/blob/main/examples/st7789_320x240_simpletest_Pimoroni_Pico_Display_2_0.py)
independently documents the same GPIO wiring. This plugin implements the
repository's existing output API in PureMetal.
