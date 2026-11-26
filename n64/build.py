"""Build a Nintendo 64 cartridge containing one NES game."""
import argparse
import os
import re
from pathlib import Path
from types import SimpleNamespace
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from anvil_cartridge import read_anvil_rom
from library_profiles import BOARD_LIMITS, board_table_source
from save_profile import save_copy_source, save_profile, stage_save
from save_header import patch_save_header
from rom_catalog import prg_views
from port_desktop import CONTROLLER_PATCHES
from stage_cpu import stage_cpu, stage_cpu_asm, trace_reference
from stage_bus import stage_bus, stage_runtime_mmc3_bus
from stage_simple_mapper import stage_simple_mapper
from stage_audio import stage_audio, stage_oscillators
from stage_mapper import stage_mapper
from stage_fastppu import stage_fastppu
from stage_sync import stage_sync
from stage_input import stage_input
from stage_poll import poll_bank_size, poll_source, stage_poll
from stage_ramwait import ram_wait_source, runtime_wait_source
from stage_expansion import EXPANSION_MAPPERS, expansion_source, stage_expansion
from stage_storage import check_storage_layout
from stage_region import header_is_pal, render_region, stage_region

# Forge uses target-specific file extensions. Stage the shared guest sources
# with a neutral extension; the checked-in originals remain authoritative.
SHARED = """state cpu2a03 mapper_state mapper_extra_state bridge ppu ppu_bus_read
ppu_bus_write mappers mapper_extra mapper_extra_bus mapper5 mapper5_video apu
mapper5_audio mapper69_audio mapper9_video mapper_adapters worker lookup_tables""".split()


def guest_names(code):
    # PureMetal N64 uses Chr() in its debug console. Keep the guest pattern pointer distinct.
    return re.sub(r'\bChr\b(?!\s*\()', 'NesChrWindow', code)


def replay_source(controller_trace):
    """Encode ordered controller intervals for the bounded verification cart."""
    for first, end, buttons in controller_trace:
        if not (0 <= first < end and 0 <= buttons <= 255):
            raise ValueError("invalid controller replay interval")
    last = max(end for _, end, _ in controller_trace)
    # Avoid expanding distant, sparse input events into a large ROM table.
    if last > max(4096, 64 * len(controller_trace)):
        lines = ["Procedure.i NesReplayPad(frame.i)"]
        for first, end, buttons in controller_trace:
            lines.append(f"  If frame>={first} And frame<{end} : ProcedureReturn {buttons} : EndIf")
        lines.extend(("  ProcedureReturn 0", "EndProcedure"))
    else:
        masks = bytearray(last)
        # The original ordered predicates give the first overlap priority.
        for first, end, buttons in reversed(controller_trace):
            masks[first:end] = bytes([buttons]) * (end - first)
        lines = [
            "Procedure.i NesReplayPad(frame.i)",
            f"  If frame<0 Or frame>={len(masks)} : ProcedureReturn 0 : EndIf",
            "  ProcedureReturn PeekA(?NesReplayMasks+frame)",
            "EndProcedure",
            "DataSection",
            "NesReplayMasks:",
        ]
        for i in range(0, len(masks), 32):
            lines.append("  Data.a " + ",".join(map(str, masks[i:i + 32])))
        lines.append("EndDataSection")
    return "\n".join(lines) + "\n"


def trace_bus_reads(code):
    """Checking build: fold every PPU / APU register read into the CPU trace."""
    old = "  ElseIf addr<$4000 Or addr=$4015\n    CpuNow()\n"
    proc = "Procedure.i NesReadPeripheral(addr.i)\n"
    if code.count(old) != 1 or code.count(proc) != 1:
        raise ValueError("peripheral read path changed")
    code = code.replace(old, old + "    NesCpuTraceRead(addr)\n")
    return code.replace(proc, "Declare NesCpuTraceRead(addr.i)\n" + proc)


def trace_bus_writes(code):
    """Checking build: fold every timed device write and work-RAM write into the CPU trace."""
    call = ("    daddiu sp, sp, -16\n    sd ra, 0(sp)\n    jal nescputracewrite\n    nop\n"
            "    ld ra, 0(sp)\n    daddiu sp, sp, 16\n")
    for label in ("nes_mmc3_bus_write_timed:\n", "nes_mmc3_bus_write_workram:\n"):
        if code.count(label) != 1:
            raise ValueError(f"bus write label {label.strip()} changed")
        code = code.replace(label, label + call)
    return code


def check_hot_unit(symbols):
    """The hot unit's guarantee (design note, section N): the core, the window code, the time
    advance and the bus write lie in ONE procedure, and its hot span - from the procedure's
    start to c65_fetch_slow, where its cold part begins - is under the VR4300's 16 KB
    direct-mapped I-cache, so no two of its hot lines can share a set. Read from the build's own
    symbol file; nothing is asked of the compiler."""
    sym = {}
    for line in symbols.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split()
        if len(parts) >= 2:
            sym[parts[1]] = int(parts[0], 16)
    start, cold = sym["cpurun"], sym["c65_fetch_slow"]
    span = cold - start
    if not 0 < span <= 16384:
        raise RuntimeError(f"hot unit span {span} bytes is not inside the 16384-byte I-cache")
    print(f"NES hot unit: {span} bytes hot span from ${start:08X}, {16384 - span} bytes to spare")


def build(args, *, controller_trace=()):
    controller_trace = tuple(controller_trace)
    telemetry = getattr(args, "telemetry", False)
    if telemetry and args.check_frame:
        raise ValueError("live telemetry requires the production audio queue")
    sdk = args.sdk.resolve()
    compiler = sdk / "PureMetalForge.exe"
    if not compiler.is_file():
        raise ValueError(f"missing compiler: {compiler}")
    runtime = getattr(args, "runtime", False)
    if runtime:
        mapper = getattr(args, "runtime_mapper", 1)
        cart = SimpleNamespace(mapper=mapper, submapper=0, mirror=0, ram_size=0,
                               conflicts=False, battery=False, prg=b"", chr=b"")
        header = bytes(16)
    else:
        cart, header = read_anvil_rom(args.rom, extra=EXPANSION_MAPPERS, pal_ok=True)
    persist = getattr(args, "persist_save", None)
    save = save_profile(cart, header) if not runtime and (persist if persist is not None else not args.check_frame) else None
    if runtime:
        ram_size = {5: 131072, 69: 32768}.get(cart.mapper, 8192)
        save = save_profile(SimpleNamespace(mapper=cart.mapper, battery=True, ram_size=ram_size, chr=b"\0"), header)
        if save.reason:
            save = None
    if save and save.reason:
        print(f"NES save: {save.reason}", file=sys.stderr)
    save_bytes = save.size if save else 0
    save_banks = 1 if save_bytes <= 32768 else 3 if save_bytes <= 98304 else 4
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
    mmc1_20k = cart.mapper == 1 and audio_rate == 20000
    raster_deadline = mmc1_20k
    ram_wait, has_ram_waits = ram_wait_source(program, cart.mapper, chain_nrom)
    runtime_waits = runtime and cart.mapper in (0, 1, 4)
    mmc1_rows = cart.mapper == 1 and (getattr(args, "runtime_chr_ram", False) if runtime
                                     else not cart.chr and chr_size == 8192)
    # The runtime-MMC3 cartridge runs the assembly 6502 core (cpu6502.n64).
    # "reference" builds the compiled interpreter instead, for the checking
    # build that compares the two; the other configurations still use it.
    cpu_core = getattr(args, "cpu_core", None) or ("asm" if runtime and cart.mapper == 4 else "reference")
    if cpu_core == "asm" and not (runtime and cart.mapper == 4):
        raise ValueError("the assembly 6502 core is built for the runtime MMC3 cartridge only")
    cpu_trace = getattr(args, "cpu_trace", False)
    a12_check = getattr(args, "a12_check", False)
    ppu_check = getattr(args, "ppu_check", False)
    twin_check = getattr(args, "twin_check", False)
    wb_measure = getattr(args, "wb_measure", False)
    rsp_check = getattr(args, "rsp_check", False)
    if (wb_measure or rsp_check) and not (runtime and cart.mapper == 4 and args.check_frame):
        raise ValueError("the band write-back measure and the RSP check are runtime-MMC3 verification builds")
    if twin_check and not (runtime and cart.mapper == 4 and args.check_frame):
        raise ValueError("the emitter twin's check is a runtime-MMC3 verification build")
    if ppu_check and not (runtime and cart.mapper == 4 and args.check_frame):
        raise ValueError("the PPU check is a runtime-MMC3 verification build")
    if a12_check and not (runtime and cart.mapper == 4 and args.check_frame):
        raise ValueError("the A12 check is a runtime-MMC3 verification build")
    if cpu_trace and not (runtime and cart.mapper == 4 and args.check_frame):
        raise ValueError("the CPU trace is a runtime-MMC3 verification build")
    # N5 (design note, N.22): the runtime-MMC3 cartridge shows the RSP band emitter's picture. The old per-pixel
    # renderer and its CI8 blit stay for the builds that compare against them, and as --old-show (the reference).
    old_show = getattr(args, "old_show", False)
    show_check = getattr(args, "show_check", False)
    rdp_show = (runtime and cart.mapper == 4 and not old_show
                and not (twin_check or rsp_check or ppu_check or wb_measure))
    if show_check and not (runtime and cart.mapper == 4 and args.check_frame) or old_show and not (runtime and cart.mapper == 4):
        raise ValueError("the show check and the old show are runtime-MMC3 builds (the check a verification build)")
    # N9: the console record (console_record.n64), only in the playable cart that shows the RSP's picture
    console_record = getattr(args, "console_record", False)
    if console_record and not (rdp_show and not args.check_frame):
        raise ValueError("the console record is built into the playable runtime-MMC3 cart only (no verify frame)")
    settings = {
        "NES_CONSOLE_RECORD": int(console_record),
        "NES_CPU_TRACE": int(cpu_trace),
        "NES_A12_CHECK": int(a12_check),
        "NES_PPU_CHECK": int(ppu_check),
        "NES_TWIN_CHECK": int(twin_check or rsp_check),
        "NES_WB_MEASURE": int(wb_measure),
        "NES_RSP_CHECK": int(rsp_check),
        "NES_RDP_SHOW": int(rdp_show),
        "NES_SHOW_CHECK": int(show_check),
        # the CI8 rows: a whole frame (240 x 256) for the old renderer, the fallback lines' ring (240 rows) for N5
        "NES_LINE_BYTES": 240 * 256 + 255 if rdp_show else 61455,
        "NES_CPU_ASM": int(cpu_core == "asm"),
        # N6 (design note, N.25): the runtime-MMC3 cartridge's APU timing in the hot unit, its synthesis by block
        "NES_APU_SPLIT": int(runtime and cart.mapper == 4),
        "NES_HW_TELEMETRY": int(telemetry),
        "NES_RUNTIME_ROM": int(runtime),
        "NES_DMC_RASTER_DEADLINE": int(raster_deadline),
        "NES_CHAIN_WINDOWS": int(cart.mapper == 1 or chain_nrom),
        "HOST_AUDIO_FRAMES": 512,
        "NES_MMC1_ROWS": int(mmc1_rows),
        "NES_RETAINED_ROWS": int(mmc1_rows or (runtime and cart.mapper == 4)),
        "NES_BG_EXPANDED": int(cart.mapper in (0, 2) and chr_size == 8192),
        "NES_BANKED_WAITS": int(poll_bank_size(cart.mapper) == 8192),
        "NES_PREDICTABLE_IRQ": int(bool(poll_bank_size(cart.mapper))),
        "NES_HAS_POLLS": int(runtime_waits or has_polls),
        "NES_HAS_RAM_WAITS": int(runtime_waits or has_ram_waits),
        "VERIFY_INPUT": int(bool(controller_trace)),
        "VERIFY_FRAME": args.check_frame, "GAME_PAL": int(header_is_pal(header)), "GAME_MAPPER": cart.mapper, "GAME_SUB": cart.submapper,
        "GAME_SAVE_BYTES": save_bytes, "GAME_SAVE_BANKS": save_banks,
        "GAME_SAVE_LINEAR": int(save_banks == 4 and not getattr(args, "banked_sram_128", False)),
        "GAME_MIRROR": cart.mirror, "GAME_RAM": cart.ram_size,
        "GAME_CONFLICT": int(cart.conflicts), "GAME_BATTERY": int(cart.battery),
        "GAME_FOUR_SCREEN": int(bool(header[6] & 8)),
        "GAME_PRG": header[4] * 16384, "GAME_VIEWS": len(program),
        "GAME_CHR": chr_size, "GAME_CHR_RAM": int(not cart.chr),
        "CART_CHR_BANKS": (max(4, min(64, BOARD_LIMITS.get(cart.mapper, (524288, 262144))[1] // 8192))
                           if runtime else max(2, chr_size // 8192)),
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
            elif name == "cpu2a03" and cpu_core == "asm":
                code = stage_cpu_asm(code)
            elif name == "cpu2a03":
                code = stage_cpu(stage_poll(code), cart.mapper, program, has_ram_waits, chain_nrom, mmc1_20k, runtime)
                if cpu_trace:
                    code = trace_reference(code)
                if runtime and cart.mapper == 1:
                    serial = "nes_native_mapper_serial:\n"
                    if code.count(serial) != 1:
                        raise ValueError("native MMC1 serial write entry changed")
                    code = code.replace(serial, serial + """    la $t0, global_cartmapper
    ld $t1, 0($t0)
    beq $t1, $zero, nes_absolute_store
    nop
""")
            elif name.startswith("mapper"):
                code = stage_mapper(name, code, cart.mapper, runtime)
            elif name == "bridge":
                for old, new, count in CONTROLLER_PATCHES["bridge"]:
                    if code.count(old) != count:
                        raise ValueError("controller bus source changed")
                    code = code.replace(old, new)
                code = code.replace("PeekL(@QComplete)", "PeekI(@QComplete)")
                code = stage_input(stage_bus(code, cart.mapper))
            code = stage_audio(name, stage_fastppu(name, stage_region(name, code), runtime and cart.mapper == 4),
                               cart.mapper, audio_rate, split=runtime and cart.mapper == 4)
            code = stage_sync(name, code, cart.mapper, chain_nrom, raster_deadline, runtime)
            code = stage_simple_mapper(name, code, cart.mapper)
            if name == "bridge" and runtime and cart.mapper == 4:
                code = stage_runtime_mmc3_bus(code)
            # Board identity is fixed for the lifetime of this cartridge.
            code = code.replace("ExtraManaged(CartMapper)", "NesExtraBoard")
            code = code.replace("ExtraA12(CartMapper)", "NesA12Board")
            if save_bytes and not (runtime and cart.mapper == 4 and name == "mappers"):
                code = stage_save(name, code, save)
            if cpu_trace and name == "bridge":
                code = trace_bus_reads(code)
            (guest / (name + ".pmi")).write_text(guest_names(code).replace('.pi4"', '.pmi"'), encoding="utf-8")
        expansion = expansion_source(cart.mapper)
        if save_bytes:
            expansion = stage_save("mapper_konami_namco", expansion, save)
        (guest / "mapper_konami_namco.pmi").write_text(guest_names(expansion), encoding="utf-8")
        app = stage / "n64"
        shutil.copytree(ROOT / "n64", app, ignore=shutil.ignore_patterns("build", "__pycache__","*.z64"))
        if runtime:
            (app / "library" / "boards.pmi").write_text(board_table_source(), encoding="ascii")
        if save_bytes:
            mmc1 = app / "mmc1.n64"
            mmc1.write_text(stage_save("mmc1", mmc1.read_text(), save), encoding="utf-8")
            (app / "save_backing.pmi").write_text(save_copy_source(save), encoding="utf-8")
            (app / "save_restore.pmi").write_text(save.restore + "\n", encoding="utf-8")
        if cpu_trace:
            write = app / "unit" / "write.n64"
            write.write_text(trace_bus_writes(write.read_text(encoding="utf-8")), encoding="utf-8")
        oscillator = app / "oscillators.n64"
        oscillator.write_text(stage_oscillators(oscillator.read_text(encoding="utf-8"), cart.mapper), encoding="utf-8")
        if controller_trace:
            if not args.check_frame:
                raise ValueError("controller replay requires a bounded verification run")
            replay = replay_source(controller_trace)
            (app / "replay.pmi").write_text(replay)
        (app / "poll.pmi").write_text(polling)
        (app / "ramwait.pmi").write_text(runtime_wait_source(cart.mapper) if runtime_waits else ram_wait)
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
        if cpu_core == "asm":
            check_hot_unit(app / "nes.bin.sym")
        args.out.parent.mkdir(parents=True, exist_ok=True)
        image = (app / "nes.z64").read_bytes()
        if save_bytes:
            image = patch_save_header(image, save_banks * 32)
        args.out.write_bytes(image)
        print(log.split("VR4300: image")[-1].strip())
        print(args.out.resolve())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", type=Path, default=os.environ.get("PMF_ROOT"), required=not os.environ.get("PMF_ROOT"))
    parser.add_argument("--audio-rate", type=int, choices=(20000, 48000), default=48000)
    parser.add_argument("--runtime", action="store_true", help="build with a runtime ROM loader at cartridge offset 8 MiB")
    parser.add_argument("--rom", type=Path, default=ROOT / "demo/PureMetalDemo.nes")
    parser.add_argument("--out", type=Path, default=ROOT / "n64/build/nes.z64")
    parser.add_argument("--banked-sram-128", action="store_true",
                        help="use four bank windows for 128 KiB SRAM (default: SummerCart64 linear mapping)")
    parser.add_argument("--persist-save", action=argparse.BooleanOptionalAction, default=None,
                        help="persist NES battery RAM in cartridge SRAM (default on for playable builds, off for verification)")
    parser.add_argument("--telemetry", action="store_true", help="report live gameplay timing and AI starvation")
    parser.add_argument("--check-frame", type=int, default=0, help="stop on a guest frame for capture (0 keeps playing)")
    parser.add_argument("--cpu-core", choices=("asm", "reference"), default=None,
                        help="the 6502 core: asm (cpu6502.n64, the runtime MMC3 default) or the reference interpreter")
    parser.add_argument("--cpu-trace", action="store_true",
                        help="checking build: a per-frame digest of the state after every instruction (needs --check-frame)")
    parser.add_argument("--a12-check", action="store_true",
                        help="checking build: the exact and the analytic A12 walks compared at every call (needs --check-frame)")
    parser.add_argument("--ppu-check", action="store_true",
                        help="checking build: the PPU state machine against the renderer and the band rule (needs --check-frame)")
    parser.add_argument("--twin-check", action="store_true",
                        help="checking build: the RDP emitter's CPU twin draws every band into a second picture, compared "
                             "with the renderer's (needs --check-frame)")
    parser.add_argument("--rsp-check", action="store_true",
                        help="checking build: the RSP band emitter (rspband.n64rsp) and the twin on the same bands, every "
                             "command word compared, the twin's picture drawn from the RSP's words (needs --check-frame)")
    parser.add_argument("--wb-measure", action="store_true",
                        help="measuring build: the Count register around the band cut's write-back of the name tables, "
                             "the record and its OAM snapshot (needs --check-frame)")
    parser.add_argument("--old-show", action="store_true",
                        help="the runtime-MMC3 cartridge with the old per-pixel renderer and its CI8 blit shown (the "
                             "reference of the show check) instead of the RSP band emitter's picture")
    parser.add_argument("--show-check", action="store_true",
                        help="checking build: every frame finished at its end and its shown picture hashed (with "
                             "--old-show: the old renderer's picture of the frame, the reference) (needs --check-frame)")
    parser.add_argument("--console-record", action="store_true",
                        help="the playable cart keeps a record of its run in the flash cart's memory (console_record.n64)")
    try:
        args = parser.parse_args()
        if args.check_frame < 0:
            parser.error("--check-frame must be nonnegative")
        build(args)
    except (OSError, ValueError, RuntimeError) as error:
        sys.exit(str(error))
