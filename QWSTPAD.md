# Pimoroni Qw/ST Pad controllers

The [Pimoroni Qw/ST Pad](https://shop.pimoroni.com/products/qwst-pad) is a small
I2C game controller: eight large buttons (U, D, L, R, A, B, X, Y), two small
ones (+ and -) and four white LEDs, read through a TI TCA9555 16-bit I/O
expander ([datasheet](https://www.ti.com/lit/ds/symlink/tca9555.pdf),
[schematic](https://cdn.shopify.com/s/files/1/0174/1800/files/Pimoroni_QwSTPad_Schematic.pdf)).
Both Pico targets support up to four pads, built into every firmware: players 1 and 2, and
players 3 and 4 through an emulated NES Four Score.

## Wiring

Use a Qw/ST (Qwiic / STEMMA QT) cable to jumper wires:

| Qw/ST wire | Pico pin |
|---|---|
| SDA (blue) | GP8 (I2C0) |
| SCL (yellow) | GP9 (I2C0) |
| 3V3 (red) | 3V3 |
| GND (black) | GND |

GP8 and GP9 are free with every bundled display output. A board with its own Qw/ST socket
needs no jumper wires: on the Pimoroni Pico Plus 2 W it is I2C0 on GP4/GP5, which
`rp2350/display_pack2.picoplus2w` sets. A second pad plugs into
the first pad's other Qw/ST connector. Each pad needs its own address: 0x21 is the
default, and cutting the address traces on the back gives 0x23, 0x25 or 0x27.

## Buttons

| Pad | NES |
|---|---|
| D-pad (U, D, L, R) | D-pad |
| A / B | A / B |
| + | Start |
| - | Select |
| X | turbo A |
| Y | turbo B |

The pads become players 1-4 in address order; player 1 adds to the board's own
controls. Players 1 and 2 are the two controller ports (`$4016`, `$4017`). While a third pad
answers, the emulator plugs in a **Four Score**: each port's strobe latches 24 bits - player 1
(or 2), then player 3 (or 4), then the adapter's signature (`$4016` 0,0,0,1,0,0,0,0; `$4017`
0,0,1,0,0,0,0,0) - so Four Score games see four players. With two pads or fewer each port is an
ordinary 8-bit controller. Each pad lights the LED of its player number. A pad that is
unplugged reads as no buttons; the bus is searched again once a second while fewer than four
pads answer, so pads can be plugged in or out, at any of the four addresses, while a game runs.
A held button stays held across that search.

X and Y repeat A and B at `QwstTurboHz` presses a second (15 by default; `QwstTurboHz = 0` in a
wrapper makes them plain A and B).

What the pad can and cannot be set up as (Pimoroni's schematic, TI's TCA9555 datasheet SCPS200):
- **Address:** A0 is tied high; A1 and A2 have cuttable traces, so 0x21 (as shipped), 0x23,
  0x25 or 0x27. All four are looked for.
- **INT** (TCA9555 pin 22) is tied to 3V3 on the pad and not on the connector, so pads are
  polled (every 4 ms), never interrupt-driven.
- **Bus:** 400 kHz is the TCA9555's fastest; the pad carries its own 10K pull-ups.
- **Pins:** TCA9555 pins 0 and 8 are not connected; 6, 7, 9 and 10 are the LEDs (active low).
- **A and B:** Pimoroni's library reads A on pin 14 and B on pin 12; the schematic's net names
  are the other way round. This firmware follows the library.

## How it works

The pad itself is driven by PureMetal Forge's shared Qw/ST Pad library,
`Shared/Qwst/qwstpad.pmi` (the same file on the Picos, the Uno R4, the Black Pill and
the Due), over the compiler's I2C library at 400 kHz; building this firmware needs a
PureMetal Forge with that library (compiler commit 1873c939c or later).
`rp2040/qwstpad.pico` (generated into `rp2350/qwstpad.pico2`) is only the NES part:
players, the NES byte, turbo, debounce and the core-1 polling. Core 0 sets each pad up before the second core
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

- **Run with a pad (2026-10-28):** Pimoroni Pico Plus 2 W (COM16), the pad on the board's own
  Qw/ST socket (I2C0, SDA GP4, SCL GP5; `rp2350/display_pack2.picoplus2w`). The pad answered at
  0x21 and its registers read TCA9555 power-on values before setup (FF FF FF FF 00 00 FF FF).
  Every button was pressed and read as the table says, turbo included; 0 read errors in 2
  minutes, the game at 60 FPS.
- The Four Score and the button map are checked by the board test suite (`InputTests`), which
  passes on the Pico 2 W (2,589,677 checks, 0 failures). The Four Score has not been run with
  three real pads: one pad is on the bench.
- Before the four-pad support, with no pad attached, the Pico 2 W passes the board test suite (1,928,288
  checks, 0 failures). It also ran a stored game at 60 FPS in every second, with
  core 0 headroom unchanged. Looking for a pad costs core 1 about 1 ms per second.
- With no pad attached, the Pico W passes the board test suite (1,926,732 checks,
  0 failures) and ran a stored game at 60 FPS in every second.
