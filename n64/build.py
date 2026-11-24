"""Build a Nintendo 64 cartridge containing one NES game."""
import argparse
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from anvil_cartridge import read_anvil_rom
from rom_catalog import prg_views
from port_desktop import CONTROLLER_PATCHES
from stage_cpu import stage_cpu
from stage_bus import stage_bus
from stage_audio import stage_audio
from stage_mapper import stage_mapper
from stage_fastppu import stage_fastppu
from stage_sync import stage_sync
from stage_expansion import EXPANSION_MAPPERS, expansion_source, stage_expansion
from stage_storage import check_storage_layout, stage_storage
from stage_region import header_is_pal, render_region, stage_region

# Forge uses target-specific file extensions. Stage the shared guest sources
# with a neutral extension; the checked-in originals remain authoritative.
SHARED = """state cpu2a03 mapper_state mapper_extra_state bridge ppu ppu_bus_read
ppu_bus_write mappers mapper_extra mapper_extra_bus mapper5 mapper5_video apu
mapper5_audio mapper69_audio mapper9_video mapper_adapters worker lookup_tables""".split()


def guest_names(code):
    # PureMetal N64 uses Chr() in its debug console. Keep the guest pattern pointer distinct.
    return re.sub(r'\bChr\b(?!\s*\()', 'NesChrWindow', code)


def build(args):
    sdk = args.sdk.resolve()
    compiler = sdk / "PureMetalForge.exe"
    if not compiler.is_file():
        raise ValueError(f"missing compiler: {compiler}")
    cart, header = read_anvil_rom(args.rom, extra=EXPANSION_MAPPERS, pal_ok=True)
    chr_size = len(cart.chr) or {6: 32768, 13: 16384}.get(cart.mapper, 8192)
    program = prg_views(cart)
    settings = {
        "VERIFY_FRAME": args.check_frame, "GAME_PAL": int(header_is_pal(header)), "GAME_MAPPER": cart.mapper, "GAME_SUB": cart.submapper,
        "GAME_MIRROR": cart.mirror, "GAME_RAM": cart.ram_size,
        "GAME_CONFLICT": int(cart.conflicts), "GAME_BATTERY": int(cart.battery),
        "GAME_FOUR_SCREEN": int(bool(header[6] & 8)),
        "GAME_PRG": header[4] * 16384, "GAME_VIEWS": len(program),
        "GAME_CHR": chr_size, "GAME_CHR_RAM": int(not cart.chr),
        "CART_CHR_BANKS": max(2, chr_size // 8192),
    }
    with tempfile.TemporaryDirectory(prefix="nes-n64-") as tmp:
        stage = Path(tmp)
        guest = stage / "anvil"
        guest.mkdir()
        for name in SHARED:
            source = ROOT / "anvil" / (("cartridge" if name == "lookup_tables" else name) + ".pi4")
            code = source.read_text(encoding="utf-8")
            code = stage_expansion(name, code)
            if name == "lookup_tables":
                code = code.split("CartridgeData:", 1)[0] + "EndDataSection\n"
            elif name == "cpu2a03":
                code = stage_cpu(code, cart.mapper)
            elif name.startswith("mapper"):
                code = stage_storage(name, stage_mapper(name, code))
            elif name == "bridge":
                for old, new, count in CONTROLLER_PATCHES["bridge"]:
                    if code.count(old) != count:
                        raise ValueError("controller bus source changed")
                    code = code.replace(old, new)
                code = code.replace("PeekL(@QComplete)", "PeekI(@QComplete)")
                code = stage_bus(code, cart.mapper)
            code = stage_audio(name, stage_fastppu(name, stage_region(name, code)))
            code = stage_sync(name, code)
            # Board identity is fixed for the lifetime of this cartridge.
            code = code.replace("ExtraManaged(CartMapper)", "NesExtraBoard")
            code = code.replace("ExtraA12(CartMapper)", "NesA12Board")
            (guest / (name + ".pmi")).write_text(guest_names(code).replace('.pi4"', '.pmi"'), encoding="utf-8")
        (guest / "mapper_konami_namco.pmi").write_text(guest_names(expansion_source()), encoding="utf-8")
        app = stage / "n64"
        shutil.copytree(ROOT / "n64", app, ignore=shutil.ignore_patterns("build", "__pycache__","*.z64"))
        (app / "region.pmi").write_text(render_region())
        (app / "game.pmi").write_text("".join(f"#{k} = {v}\n" for k, v in settings.items()))
        (app / "game.bin").write_bytes(program + cart.chr)
        result = subprocess.run([str(compiler), "--compile", "nes.n64", "-o", "nes.bin"],
                                cwd=app, env=dict(os.environ, PMF_ROOT=str(sdk)),
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        log = result.stdout.decode(errors="replace")
        if result.returncode or not (app / "nes.z64").is_file():
            raise RuntimeError(log)
        check_storage_layout(log)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(app / "nes.z64", args.out)
        print(log.split("VR4300: image")[-1].strip())
        print(args.out.resolve())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", type=Path, default=os.environ.get("PMF_ROOT"), required=not os.environ.get("PMF_ROOT"))
    parser.add_argument("--rom", type=Path, default=ROOT / "demo/PureMetalDemo.nes")
    parser.add_argument("--out", type=Path, default=ROOT / "n64/build/nes.z64")
    parser.add_argument("--check-frame", type=int, default=0, help="stop on a guest frame for capture (0 keeps playing)")
    try:
        args = parser.parse_args()
        if args.check_frame < 0:
            parser.error("--check-frame must be nonnegative")
        build(args)
    except (OSError, ValueError, RuntimeError) as error:
        sys.exit(str(error))
