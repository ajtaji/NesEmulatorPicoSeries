# ILI9341 clock experiment, 2026-10-16

The retained firmware is the original 200 MHz host / 33.333 MHz SPI /
30 FPS presentation build. Its SHA-256 is in `clock-experiment.json`.
No experimental emulator, clock-switching code or fast profile was retained.

Native logs test DMA/ownership and ID, not physical pixel fidelity. Both
100 MHz trials passed those checks but visibly corrupted the image. Sending
commands more slowly did not fix it. Exploratory VRAM reads returned FF and
are not validation. The operator confirmed the 75 MHz picture was stable.

75 MHz SPI required a 150 MHz RP2040 host clock with these hardware SPI
dividers. The three completed 40-second game runs are included, with all
telemetry intervals. Contra and Castlevania accumulated guest-cycle debt;
Castlevania averaged 56.746 emulated / 56.621 displayed FPS. The user asked
to retain 30 FPS and return the host to 200 MHz, interrupting the remaining
higher-clock game run. No completed fourth-game result is claimed.

`restored-contra` is a 20-second run of the exact original firmware; its
summary excludes the first interval and covers 19.001 seconds. It records
60.103 emulated / 29.999 displayed FPS, 1,789,765 guest cycles/s, 47,999.8
APU samples/s and zero reported errors. The audio backend was silent.
`ili9341-restored-200mhz-stopped.txt` confirms the final four-ROM boot menu,
30.0 displayed FPS, with guest emulation stopped. No ROM bytes or framebuffer
images are included.
