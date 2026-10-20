# Pimoroni Qw/ST Pad controllers

The [Pimoroni Qw/ST Pad](https://shop.pimoroni.com/products/qwst-pad) is a small
I2C game controller: eight large buttons (U, D, L, R, A, B, X, Y), two small
ones (+ and -) and four white LEDs, read through a TI TCA9555 16-bit I/O
expander ([datasheet](https://www.ti.com/lit/ds/symlink/tca9555.pdf),
[schematic](https://cdn.shopify.com/s/files/1/0174/1800/files/Pimoroni_QwSTPad_Schematic.pdf)).
Both Pico targets support up to two pads, built into every firmware.

## Wiring

Use a Qw/ST (Qwiic / STEMMA QT) cable to jumper wires:

| Qw/ST wire | Pico pin |
|---|---|
| SDA (blue) | GP8 (I2C0) |
| SCL (yellow) | GP9 (I2C0) |
| 3V3 (red) | 3V3 |
| GND (black) | GND |

GP8 and GP9 are free with every bundled display output. A second pad plugs into
the first pad's other Qw/ST connector. Each pad needs its own address: 0x21 is the
default, and cutting the address traces on the back gives 0x23, 0x25 or 0x27.

## Buttons

| Pad | NES |
|---|---|
| D-pad (U, D, L, R) | D-pad |
| A / B | A / B |
| + | Start |
| - | Select |
| X / Y | not used |

The first pad found (in address order) is player 1 and adds to the board's own
controls. The second is player 2 (`$4017`). At start-up each pad lights the LED
of its player number. A pad that is unplugged reads as no buttons and is looked
for again once a second, so it can be plugged in while a game runs.

## How it works

`rp2040/qwstpad.pico` (generated into `rp2350/qwstpad.pico2`) uses the
compiler's I2C library at 400 kHz. Core 0 sets each pad up before the second core
starts: inputs inverted (pressed reads 1), LED pins as outputs, the same register
values as Pimoroni's own library. From then on only core 1 uses the bus. Every
4 ms it reads each pad's input register and publishes one NES button byte per
player. A button change counts once two reads 4 ms apart agree, which rejects
contact bounce. Core 0 merges the bytes into the controller ports in its normal
input poll, so the CPU core spends no time on I2C.

On the Pico 2 W, build with PureMetal Forge 2026-10-19 or later. Earlier releases'
I2C library waited about 4 ms on every register read (forum 1357), and with a pad
attached the emulator fell to about one frame a second.

To use other pins or turn the pad support off, set these in your wrapper before
`Main()`:

```
QwstSda = 4 : QwstScl = 5 : QwstUnit = 0   ; another I2C pin pair
QwstEnabled = 0                            ; leave GP8/GP9 alone
```

USB diagnostic key `j` prints `pads=`, each player's button byte, and the read,
error and busy-time counters.

## Status

- Not yet run with a pad: none was on the bench when this was written.
- With no pad attached, the Pico 2 W passes the board test suite (1,928,288
  checks, 0 failures). It also ran a stored game at 60 FPS in every second, with
  core 0 headroom unchanged. Looking for a pad costs core 1 about 1 ms per second.
- With no pad attached, the Pico W passes the board test suite (1,926,732 checks,
  0 failures) and ran a stored game at 60 FPS in every second.
