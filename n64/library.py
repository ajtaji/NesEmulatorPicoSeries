"""Build the common N64 NES library launcher and provision per-ROM SD saves."""
import argparse
from hashlib import sha256
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib

from build import build, ROOT


CORE_OFFSET = 0x200000


def word(image, offset):
    return struct.unpack_from(">I", image, offset)[0]


def replace_word(image, offset, expected, value):
    if word(image, offset) != expected:
        raise ValueError(f"unexpected core loader instruction at {offset:#x}")
    struct.pack_into(">I", image, offset, value)


def relocate_core(data):
    """Point the existing stage-2 loader at its own header and executable."""
    image = bytearray(data)
    stage = word(image, 0x1C)
    if not 0x1000 < stage <= len(image) - 0xC00:
        raise ValueError("invalid PureMetal stage 2")
    replace_word(image, stage + 0x6C, 0x3C15B000, 0x3C15B020)
    replace_word(image, stage + 0x4E0, 0x3C0C1000, 0x3C0C1020)
    return image


def build_library(sdk, output, audio_rate):
    sdk = sdk.resolve()
    with tempfile.TemporaryDirectory(prefix="nes-n64-library-") as scratch:
        work = Path(scratch)
        core = work / "runtime.z64"
        build(argparse.Namespace(sdk=sdk, out=core, runtime=True, audio_rate=audio_rate, check_frame=0))
        shutil.copytree(ROOT / "n64" / "library", work / "menu")
        launch = work / "menu"
        subprocess.run([str(sdk / "PureMetalForge.exe"), "--compile", "menu.n64", "-o", "menu.bin"],
                       cwd=launch, env=dict(os.environ, PMF_ROOT=str(sdk)), stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, check=True)
        image = bytearray((launch / "menu.z64").read_bytes())
        if len(image) > CORE_OFFSET:
            raise ValueError("menu overlaps the library emulator")
        image[0x20:0x34] = b"NES LIBRARY         "
        image = image.ljust(CORE_OFFSET, b"\0") + relocate_core(core.read_bytes())
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(image)
    subprocess.run([sys.executable, "-I", str(sdk / "tools" / "n64_rom_check.py"), str(output)],
                   check=True)
    print(f"{sha256(image).hexdigest()}  {output}")


def battery_mmc1(header):
    if len(header) < 16 or header[:4] != b"NES\x1a":
        return False
    flags, high = header[6:8]
    prg, chr_ = header[4:6]
    return ((flags >> 4) | (high & 0xf0)) == 1 and flags & 2 and not (
        flags & 12 or high & 15 or header[8] > 1 or header[9] & 1 or
        prg < 1 or prg > 16 or prg & (prg - 1) or chr_ > 16 or chr_ & (chr_ - 1)
    )


def prepare_saves(source, destination):
    """Provision erased 32 KiB save files without altering existing slots."""
    seen = {}
    for rom in sorted(source.iterdir()):
        if not rom.is_file() or rom.suffix.casefold() != ".nes":
            continue
        data = rom.read_bytes()
        if not battery_mmc1(data):
            continue
        size = 16 + data[4] * 16384 + data[5] * 8192
        if len(data) < size:
            continue
        fingerprint = zlib.crc32(data[:size])
        prior = seen.setdefault(fingerprint, rom)
        if prior != rom and prior.read_bytes()[:size] != data[:size]:
            raise ValueError(f"save fingerprint collision between {rom.name} and {prior.name}")
    destination.mkdir(parents=True, exist_ok=True)
    for fingerprint in seen:
        save = destination / f"{fingerprint:08X}.SAV"
        if save.exists():
            if save.stat().st_size != 32768:
                raise ValueError(f"existing save has the wrong size: {save}")
            continue
        with save.open("xb") as stream:
            stream.write(b"\xff" * 32768)
    print(f"{len(seen)} MMC1 save slots in {destination}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    launcher = commands.add_parser("build")
    launcher.add_argument("--sdk", type=Path, required=True)
    launcher.add_argument("--out", type=Path, required=True)
    launcher.add_argument("--audio-rate", type=int, choices=(20000, 48000), default=20000)
    saves = commands.add_parser("saves")
    saves.add_argument("source", type=Path)
    saves.add_argument("destination", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "build":
            build_library(args.sdk, args.out, args.audio_rate)
        else:
            prepare_saves(args.source, args.destination)
    except subprocess.CalledProcessError as error:
        parser.exit(1, (error.output or b"command failed").decode(errors="replace") + "\n")
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")
