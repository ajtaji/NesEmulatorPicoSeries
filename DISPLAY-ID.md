# Standalone SPI display identification

`rp2040/Diagnostics/display_id.pico` probes an unidentified SPI TFT on a bare
Pico through SPI1 at 100 kHz. It includes no emulator or wireless code and uses
a 125 MHz system clock. A blank Pico is suitable. It does not write panel gamma,
pixel-format, orientation, flash or EEPROM settings.

Disconnect USB before wiring. Use a bare board: GP10/11 overlap the LAFVIN
carrier's touch controller. The separate SD-card header stays disconnected.

| Display | Pico GPIO / supply | Physical pin |
|---|---|---:|
| VCC | 3V3 OUT | 36 |
| GND | GND | 18 |
| SCK | GP10 / SPI1 SCK | 14 |
| SDI / MOSI | GP11 / SPI1 TX | 15 |
| SDO / MISO | GP12 / SPI1 RX | 16 |
| CS | GP13 | 17 |
| D/C | GP16 | 21 |
| RESET | GP17 | 22 |
| LED | Disconnected for the register test | — |

Build with PureMetalForge:

```powershell
tools/build.ps1 -Compiler path\to\PureMetalForge.exe -Source rp2040/Diagnostics/display_id.pico -Output firmware/display-id-test.uf2
```

Hold BOOTSEL while connecting this test Pico and copy the resulting UF2 onto its
RPI-RP2 drive. The program exposes a USB serial port. It waits for a host command:

- `i`: read registers without resetting the panel.
- `r`: hardware-reset the panel, wait 150 ms, then read registers.

The probe prints raw replies, including controller-specific dummy bytes, for
registers D3, 04, 09, DA, DB and DC. Three consistent `xx 00 93 41` D3 replies
produce an ILI9341 candidate indication. Zeroes, FFs, unsupported registers or
shifted data are not proof of a controller type. Preserve raw replies for
diagnosis; a disconnected panel cannot produce a meaningful identification.
The presence of SDO/MISO does not guarantee every register is readable on a clone.
The backlight can remain off throughout identification.

The register layout is documented in the
[ILI9341 datasheet](https://www.lcdwiki.com/res/MAR2406/ILI9341_Datasheet.pdf).
The generated RP2350 counterpart is `rp2350/Diagnostics/display_id.pico2`; use
that source only for a Pico 2. These probe images have no game ROM store or audio
session and do not modify the two emulator boards unless explicitly uploaded there.
