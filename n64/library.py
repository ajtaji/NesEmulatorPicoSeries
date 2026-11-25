"""Build the common N64 NES library launcher and provision per-ROM SD saves."""
import argparse
from hashlib import sha256
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib

from build import build, ROOT, read_anvil_rom, EXPANSION_MAPPERS, save_profile
from library_profiles import PROFILES, board_table_source


CORE_BASE = 0x1000000
CORE_ALIGN = 0x10000
CORE_PROFILES = PROFILES


def word(image, offset):
    return struct.unpack_from(">I", image, offset)[0]


def replace_word(image, offset, expected, value):
    if word(image, offset) != expected:
        raise ValueError(f"unexpected core loader instruction at {offset:#x}")
    struct.pack_into(">I", image, offset, value)


def relocate_core(data, offset):
    """Point the existing stage-2 loader at its own header and executable."""
    image = bytearray(data)
    if offset % CORE_ALIGN:
        raise ValueError("runtime core needs a 64 KiB-aligned placement")
    stage = word(image, 0x1C)
    if not 0x1000 < stage <= len(image) - 0xC00:
        raise ValueError("invalid PureMetal stage 2")
    replace_word(image, stage + 0x6C, 0x3C15B000, 0x3C15B000 + (offset >> 16))
    replace_word(image, stage + 0x4E0, 0x3C0C1000, 0x3C0C1000 + (offset >> 16))
    return image[:stage + 0xC00]


def build_library(sdk, output, audio_rate):
    sdk = sdk.resolve()
    with tempfile.TemporaryDirectory(prefix="nes-n64-library-") as scratch:
        work = Path(scratch)
        cores = bytearray()
        cases = []
        def compile_core(profile):
            mapper, chr_ram = profile
            core = work / f"runtime-{mapper}-{int(chr_ram)}.z64"
            build(argparse.Namespace(sdk=sdk, out=core, runtime=True, runtime_mapper=mapper,
                                     runtime_chr_ram=chr_ram, audio_rate=audio_rate, check_frame=0))
            return core.read_bytes()

        with ThreadPoolExecutor(max_workers=4) as pool:
            built_cores = list(pool.map(compile_core, CORE_PROFILES))
        for (mapper, chr_ram), data in zip(CORE_PROFILES, built_cores):
            offset = CORE_BASE + len(cores)
            cores.extend(relocate_core(data, offset))
            cores.extend(bytes(-len(cores) % CORE_ALIGN))
            if mapper == 1:
                cases.append(f"  If mapper=1 And chrRam={int(chr_ram)} : ProcedureReturn ${0x10000000+offset:X} : EndIf")
            else:
                cases.append(f"  If mapper={mapper} : ProcedureReturn ${0x10000000+offset:X} : EndIf")
        shutil.copytree(ROOT / "n64" / "library", work / "menu")
        (work / "menu" / "boards.pmi").write_text(board_table_source(), encoding="ascii")
        (work / "menu" / "cores.pmi").write_text("\n".join([
            "Procedure.i NesLibCore(mapper.i, chrRam.i)", *cases, "  ProcedureReturn 0", "EndProcedure", "",
        ]), encoding="ascii")
        launch = work / "menu"
        subprocess.run([str(sdk / "PureMetalForge.exe"), "--compile", "menu.n64", "-o", "menu.bin"],
                       cwd=launch, env=dict(os.environ, PMF_ROOT=str(sdk)), stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, check=True)
        image = bytearray((launch / "menu.z64").read_bytes())
        if len(image) > 0x800000:
            raise ValueError("menu overlaps the library emulator")
        image[0x20:0x34] = b"NES LIBRARY         "
        image = image.ljust(CORE_BASE, b"\0") + cores
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(image)
    subprocess.run([sys.executable, "-I", str(sdk / "tools" / "n64_rom_check.py"), str(output)],
                   check=True)
    print(f"{sha256(image).hexdigest()}  {output}")


def prepare_saves(source, destination):
    """Provision erased 32 KiB save files without altering existing slots."""
    seen = {}
    for rom in sorted(source.iterdir()):
        if not rom.is_file() or rom.suffix.casefold() != ".nes":
            continue
        data = rom.read_bytes()
        try:
            cart, header = read_anvil_rom(rom, extra=EXPANSION_MAPPERS)
        except ValueError:
            continue
        profile = save_profile(cart, header)
        if not profile.size:
            continue
        size = 16 + data[4] * 16384 + data[5] * 8192
        fingerprint = zlib.crc32(data[:size])
        prior, _ = seen.setdefault(fingerprint, (rom, 131072 if cart.mapper == 5 else 32768))
        if prior != rom and prior.read_bytes()[:size] != data[:size]:
            raise ValueError(f"save fingerprint collision between {rom.name} and {prior.name}")
    destination.mkdir(parents=True, exist_ok=True)
    for fingerprint, (_, capacity) in seen.items():
        save = destination / f"{fingerprint:08X}.SAV"
        if save.exists():
            if save.stat().st_size != capacity:
                raise ValueError(f"existing save has the wrong size: {save}")
            continue
        with save.open("xb") as stream:
            stream.write(b"\xff" * capacity)
    print(f"{len(seen)} battery save slots in {destination}")


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
