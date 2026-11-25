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
from stage_audio import stage_audio, stage_oscillators
from stage_mapper import stage_mapper
from stage_fastppu import stage_fastppu
from stage_sync import stage_sync
from stage_input import stage_input
from stage_poll import poll_bank_size, poll_source, stage_poll
from stage_ramwait import ram_wait_source
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


def build(args, *, controller_trace=()):
    sdk = args.sdk.resolve()
    compiler = sdk / "PureMetalForge.exe"
    if not compiler.is_file():
        raise ValueError(f"missing compiler: {compiler}")
    cart, header = read_anvil_rom(args.rom, extra=EXPANSION_MAPPERS, pal_ok=True)
    chr_size = len(cart.chr) or {6: 32768, 13: 16384}.get(cart.mapper, 8192)
    program = prg_views(cart)
    polling, has_polls = poll_source(program, cart.mapper)
    audio_rate = getattr(args, "audio_rate", 48000)
    if audio_rate not in (20000, 48000):
        raise ValueError("supported audio rates are 20000 and 48000 Hz")
    # The NROM 20 kHz path can run through adjacent CPU windows while the
    # next device deadline is still ahead. The 48 kHz path retains its
    # original service cadence for the more frequent sample deadlines.
    chain_nrom = cart.mapper == 0 and audio_rate == 20000
    ram_wait, has_ram_waits = ram_wait_source(program, cart.mapper, chain_nrom)
    settings = {
        "NES_CHAIN_WINDOWS": int(cart.mapper == 1 or chain_nrom),
        "HOST_AUDIO_FRAMES": 256 if audio_rate == 20000 else 512,
        "NES_MMC1_ROWS": int(cart.mapper == 1 and not cart.chr and chr_size == 8192),
        "NES_BG_EXPANDED": int(cart.mapper in (0, 2) and chr_size == 8192),
        "NES_BANKED_WAITS": int(poll_bank_size(cart.mapper) == 8192),
        "NES_PREDICTABLE_IRQ": int(bool(poll_bank_size(cart.mapper))),
        "NES_HAS_POLLS": int(has_polls),
        "NES_HAS_RAM_WAITS": int(has_ram_waits),
        "VERIFY_INPUT": int(bool(controller_trace)),
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
            if name == "state" and audio_rate != 48000:
                if code.count("#NES_AUDIO_RATE=48000") != 1:
                    raise ValueError("shared NES audio rate declaration changed")
                code = code.replace("#NES_AUDIO_RATE=48000", f"#NES_AUDIO_RATE={audio_rate}")
            code = stage_expansion(name, code)
            if name == "lookup_tables":
                code = code.split("CartridgeData:", 1)[0] + "EndDataSection\n"
            elif name == "cpu2a03":
                code = stage_cpu(stage_poll(code), cart.mapper, program, has_ram_waits, chain_nrom)
            elif name.startswith("mapper"):
                code = stage_storage(name, stage_mapper(name, code, cart.mapper))
            elif name == "bridge":
                for old, new, count in CONTROLLER_PATCHES["bridge"]:
                    if code.count(old) != count:
                        raise ValueError("controller bus source changed")
                    code = code.replace(old, new)
                code = code.replace("PeekL(@QComplete)", "PeekI(@QComplete)")
                code = stage_input(stage_bus(code, cart.mapper))
            code = stage_audio(name, stage_fastppu(name, stage_region(name, code)), cart.mapper, audio_rate)
            code = stage_sync(name, code, cart.mapper, chain_nrom)
            # Board identity is fixed for the lifetime of this cartridge.
            code = code.replace("ExtraManaged(CartMapper)", "NesExtraBoard")
            code = code.replace("ExtraA12(CartMapper)", "NesA12Board")
            (guest / (name + ".pmi")).write_text(guest_names(code).replace('.pi4"', '.pmi"'), encoding="utf-8")
        (guest / "mapper_konami_namco.pmi").write_text(guest_names(expansion_source()), encoding="utf-8")
        app = stage / "n64"
        shutil.copytree(ROOT / "n64", app, ignore=shutil.ignore_patterns("build", "__pycache__","*.z64"))
        oscillator = app / "oscillators.n64"
        oscillator.write_text(stage_oscillators(oscillator.read_text(encoding="utf-8"), cart.mapper), encoding="utf-8")
        if controller_trace:
            if not args.check_frame:
                raise ValueError("controller replay requires a bounded verification run")
            lines = ["Procedure.i NesReplayPad(frame.i)"]
            for first, end, buttons in controller_trace:
                if not (0 <= first < end and 0 <= buttons <= 255):
                    raise ValueError("invalid controller replay interval")
                lines.append(f"  If frame>={first} And frame<{end} : ProcedureReturn {buttons} : EndIf")
            lines.extend(("  ProcedureReturn 0", "EndProcedure"))
            (app / "replay.pmi").write_text("\n".join(lines) + "\n")
        (app / "poll.pmi").write_text(polling)
        (app / "ramwait.pmi").write_text(ram_wait)
        (app / "region.pmi").write_text(render_region(audio_rate))
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
    parser.add_argument("--audio-rate", type=int, choices=(20000, 48000), default=48000)
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
