The SBC prototype coefficient values in rp2040/sbc_encoder.pico were cross-checked
against BlueZ sbc_tables.h, licensed LGPL-2.1-or-later:
https://android.googlesource.com/platform/external/bluetooth/bluez/+/14be985aba4674bcf565a25355479d0391b73043/sbc/sbc_tables.h

The referenced source credits Marcel Holtmann, Henryk Ploetz and Brad Midgley.
The cosine coefficients are mathematically generated. The PureMetal analysis,
bit allocation, quantization and packet-writing implementation is supplied in
full source, along with deterministic board vectors and their Python generator.

The Bluetooth firmware data is Infineon firmware redistributed for Raspberry Pi
silicon; the two CYW43439 licenses in this directory accompany that data.
