"""Set the ED64 save type on a copy of a big-endian N64 cartridge."""

import argparse
from pathlib import Path


SRAM_TYPES = {32: 3, 96: 4, 128: 6}


def patch_save_header(data: bytes, kib: int) -> bytes:
    """Return a cartridge identifying the configured SRAM capacity in KiB."""
    if kib not in SRAM_TYPES:
        raise ValueError("SRAM capacity must be 32, 96 or 128 KiB")
    if len(data) < 0x40 or data[:4] != b"\x80\x37\x12\x40":
        raise ValueError("expected a big-endian N64 .z64 cartridge")
    flags = data[0x3F] & 0x0F if data[0x3C:0x3E] == b"ED" else 0
    header = bytearray(data)
    header[0x3C:0x3E] = b"ED"
    header[0x3F] = (SRAM_TYPES[kib] << 4) | flags
    return bytes(header)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path, help="new .z64 path")
    parser.add_argument("--sram-kib", type=int, choices=tuple(SRAM_TYPES), required=True)
    args = parser.parse_args()
    try:
        data = patch_save_header(args.input.read_bytes(), args.sram_kib)
        with args.output.open("xb") as stream:
            stream.write(data)
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
