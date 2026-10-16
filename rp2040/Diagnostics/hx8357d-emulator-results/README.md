# HX8357D emulator board tests

Bare Pico COM14, USB serial E6609103C3949B22, 200 MHz host, 33.333 MHz pixel
SPI, 1 MHz commands, 30 FPS completed-frame presentation, silent audio output.
`build.json` identifies the installed image. `board.json` records controls and
physical confirmation. Every game ran for 40 seconds with telemetry continuously
read; summaries include startup rather than choosing only fast intervals.

The harness uses `tools/board_smoke.py` with the extra host-input timings in
`board.json` for Mario/Contra. The extra Start at 12 seconds leaves their long
introductions; right/A input follows. These are test controls, not game-specific
emulator changes. Locally reviewed captures reached gameplay in Mario, Contra
and Castlevania. ROM bytes and screenshots are not bundled.

The panel fixture passed 99 register, input isolation, DMA ownership, frame
cadence, completion and abort checks. The operator confirmed physical geometry,
colors and the FPS overlay. `core-preservation.txt` distinguishes unchanged
regression binaries from the new checks actually executed on this task.

APU sample counts validate emulated sample generation; the bare-board profile
has no physical audio device, so this test does not certify Bluetooth or DAC
sound. The Pico 2 version is compiled only. The final log confirms the four-game
menu at 30.0 FPS with guest emulation stopped.
