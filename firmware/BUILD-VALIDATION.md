# Firmware downloads and hardware validation

Release v0.1.0 assets refreshed October 16, 2026. Eight UF2 files cover four
displays on both MCU families. Download the file matching your chip and wiring.

| UF2 file | Target | Display | Hardware validation | Display output |
|---|---|---|---|---|
| [nes-pico-w.uf2](https://github.com/ajtaji/NesEmulatorPicoSeries/releases/download/v0.1.0/nes-pico-w.uf2) | Pico W / RP2040 | LAFVIN ST7796 | **HARDWARE TESTED: Pico W + panel** | 60 FPS target |
| [nes-pico2-w.uf2](https://github.com/ajtaji/NesEmulatorPicoSeries/releases/download/v0.1.0/nes-pico2-w.uf2) | Pico 2 W / RP2350 | LAFVIN ST7796 | **HARDWARE TESTED: Pico 2 W + panel** | 60 FPS target |
| [nes-pico-w-display-pack2.uf2](https://github.com/ajtaji/NesEmulatorPicoSeries/releases/download/v0.1.0/nes-pico-w-display-pack2.uf2) | Pico W / RP2040 | ST7789 Display Pack 2.0 | **DISPLAY UNTESTED: no panel available** | 30 FPS target |
| [nes-pico2-w-display-pack2.uf2](https://github.com/ajtaji/NesEmulatorPicoSeries/releases/download/v0.1.0/nes-pico2-w-display-pack2.uf2) | Pico 2 W / RP2350 | ST7789 Display Pack 2.0 | **DISPLAY UNTESTED: no panel available** | 60 FPS target |
| [nes-pico-w-ili9341.uf2](https://github.com/ajtaji/NesEmulatorPicoSeries/releases/download/v0.1.0/nes-pico-w-ili9341.uf2) | Pico / Pico W / RP2040 | ILI9341 SPI1 | **HARDWARE TESTED: bare Pico + panel** | 30 FPS target |
| [nes-pico2-w-ili9341.uf2](https://github.com/ajtaji/NesEmulatorPicoSeries/releases/download/v0.1.0/nes-pico2-w-ili9341.uf2) | Pico 2 / Pico 2 W / RP2350 | ILI9341 SPI1 | **COMPILE ONLY: matching panel not tested** | 30 FPS target |
| [nes-pico-w-hx8357d.uf2](https://github.com/ajtaji/NesEmulatorPicoSeries/releases/download/v0.1.0/nes-pico-w-hx8357d.uf2) | Pico / Pico W / RP2040 | Adafruit HX8357D SPI1 | **HARDWARE TESTED: bare Pico + panel** | 30 FPS target |
| [nes-pico2-w-hx8357d.uf2](https://github.com/ajtaji/NesEmulatorPicoSeries/releases/download/v0.1.0/nes-pico2-w-hx8357d.uf2) | Pico 2 / Pico 2 W / RP2350 | Adafruit HX8357D SPI1 | **COMPILE ONLY: matching panel not tested** | 30 FPS target |

## What the labels mean

- **HARDWARE TESTED:** the listed board and a connected panel were exercised
  with games, and the physical picture was checked. LAFVIN was tested on Pico W
  and Pico 2 W. The RP2040 ILI9341/HX8357D builds were tested on a **bare Pico**;
  those display combinations were not separately tested on a Pico W.
- **DISPLAY UNTESTED:** both ST7789 builds compiled and passed physical-board
  SPI/DMA transport checks with **no ST7789 panel attached**. Those checks do
  not verify orientation, colors, stability or visible refresh.
- **COMPILE ONLY:** the RP2350 ILI9341/HX8357D builds compiled, but have not been
  tested with the matching physical display. Their RP2040 results do not
  establish RP2350 hardware validation.

Frame rates above are presentation targets, not guarantees for every game.
Guest NTSC timing remains about 60.1 emulated FPS when the board keeps up.
The RP2040 ILI9341/HX8357D game runs measured about 60.1 emulated / 30 displayed
FPS. Some heavier mapper/game scenes can run below real time.

ILI9341/HX8357D public profiles use silent output and USB controls by default;
the APU continues running. Their hardware validation does not certify Bluetooth
or DAC sound. LAFVIN/Display Pack retain their existing audio/input profiles.
No download contains commercial game ROMs or private speaker pairing details.

## Binary provenance

The v0.1.0 Git tag remains its original source snapshot; it has not been moved.
The four original LAFVIN/Display Pack binaries are retained byte-for-byte.
The added ILI9341 binaries come from source snapshot
[1cb3e85](https://github.com/ajtaji/NesEmulatorPicoSeries/tree/1cb3e85), and the
HX8357D binaries from
[ddc18ff](https://github.com/ajtaji/NesEmulatorPicoSeries/tree/ddc18ff).
`SHA256SUMS.txt` covers all eight UF2 files. Each image's family ID and end address
were checked; every image ends before the ROM-store boundary at 0x10050000.

Wiring and detailed results: [LAFVIN/performance](https://github.com/ajtaji/NesEmulatorPicoSeries/blob/main/PICO-MMC3-NMI-RESULTS.md),
[ST7789](https://github.com/ajtaji/NesEmulatorPicoSeries/blob/main/DISPLAY-PACK2.md), [ILI9341](https://github.com/ajtaji/NesEmulatorPicoSeries/blob/main/ILI9341.md),
[HX8357D](https://github.com/ajtaji/NesEmulatorPicoSeries/blob/main/HX8357D.md), [ROM loader/setup](https://github.com/ajtaji/NesEmulatorPicoSeries/blob/main/README.md).
