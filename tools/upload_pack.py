"""Validate that NES firmware ends below the ROM store, then send it with PureMetalForge."""
import argparse
from pathlib import Path
import struct
import subprocess

# Firmware ends below the ROM store (rp2040/rom_store.pico, flash offset $50000).
FIRMWARE_END = 0x10050000


def check_pack(path, expected_family=None):
    data = Path(path).read_bytes()
    if not data or len(data) % 512:
        raise ValueError('Not a complete UF2')
    end = 0
    seen = set()
    image_family = None
    for offset in range(0, len(data), 512):
        block = data[offset:offset+512]
        magic0, magic1, flags, target, size, number, count, family = struct.unpack_from('<8I', block)
        if (magic0, magic1, struct.unpack_from('<I',block,508)[0]) != (0x0A324655,0x9E5D5157,0x0AB16F30):
            raise ValueError('Invalid UF2 block')
        if flags != 0x2000 or family not in (0xE48BFF56, 0xE48BFF59) or size != 256:
            raise ValueError('Expected RP2040 or RP2350 Arm secure flash blocks')
        if image_family is None:
            image_family = family
        if family != image_family or (expected_family is not None and family != expected_family):
            raise ValueError('UF2 family does not match the selected target')
        if count != len(data)//512 or number in seen or number >= count:
            raise ValueError('Invalid UF2 block numbering')
        seen.add(number)
        if target < 0x10000000 or target+size > FIRMWARE_END:
            raise ValueError(f'UF2 block at {target:08X} reaches past {FIRMWARE_END:08X}: the firmware would overwrite the ROM store (games at flash offset $50000) or the radio firmware')
        end=max(end,target+size)
    return end


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('uf2',type=Path)
    p.add_argument('--compiler',required=True,type=Path)
    p.add_argument('--port',required=True,help='serial port of the board running PureMetal NES firmware')
    p.add_argument('--target',choices=['rp2040','rp2350'],required=True)
    a=p.parse_args()
    end=check_pack(a.uf2,0xE48BFF56 if a.target=='rp2040' else 0xE48BFF59)
    print(f'Validated {a.target} firmware ending at 0x{end:08X}; {FIRMWARE_END-end} bytes before the ROM store',flush=True)
    # This documented CLI route sends a ready UF2 unchanged; it builds nothing.
    result=subprocess.run([str(a.compiler),'--radio-firmware',str(a.uf2.resolve()),'--port',a.port],capture_output=True,text=True)
    print(result.stdout)
    print(result.stderr)
    if result.returncode == 0:
        from serial.tools import list_ports
        if not any(p.device.upper() == a.port and p.vid == 0x2E8A for p in list_ports.comports()):
            raise SystemExit('Image written, but NES USB serial did not return; boot is unverified.')
    raise SystemExit(result.returncode)
