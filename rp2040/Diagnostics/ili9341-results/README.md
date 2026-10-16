# ILI9341 bare Pico board results

COM14, RP2040 at 200 MHz, SPI1 33.333 MHz, 30 FPS presentation, silent audio.
`build.txt` identifies the exact emulator firmware; `games.json` contains four
40-second tests. Individual telemetry logs preserve startup and all intervals.
The extra Mario/Contra gameplay runs send Start after reaching the title screen;
Castlevania already reached gameplay in its 40-second run. Framebuffer images
were reviewed locally and are not bundled with these results.

`ili9341-full-w.txt`: full emulator checks after the CRC-table allocation fix.
`ili9341-native-w.txt`: 97 ID/input/DMA/cadence/ownership checks. Exploratory
VRAM reads in that log returned FF and are not included in the successful check
count. The operator confirmed the physical game picture, colors and orientation.
No physical audio device was tested; APU samples and codec vectors are separate
from speaker validation. The Pico 2 build is compiled only.

`ili9341-stopped-menu.txt` confirms the final four-ROM menu at 30 FPS, with no
guest emulation running. Games were loaded from the operator's own files; no
commercial ROM bytes or private Bluetooth configuration are included.
