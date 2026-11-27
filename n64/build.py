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
from save_profile import SaveProfile, save_copy_source, save_profile, stage_save
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
    if code.count(proc) == 0:           # a reference core outside the unit: the bus's read is the shared NesReadSlow
        proc = "Procedure.i NesReadSlow(addr.i)\n"
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


def trace_compiled_writes(code):
    """Checking build of a reference core outside the unit (the compiled bus, NesWrite in the shared bridge): fold the
    same writes the unit folds at nes_mmc3_bus_write_timed / _workram (cputrace.n64, kind 2) - every managed write at
    $6000-$FFFF, the OAM DMA and every device register write at $2000-$4017 but $4016 - at the same point, before
    the bus moves the clock (CpuNow), so the two builds' guest digests compare instruction for instruction."""
    proc = "Procedure NesWrite(addr.i, value.i)\n"
    if code.count(proc) != 1:
        raise ValueError("compiled bus write procedure changed")
    code = code.replace(proc, "Declare NesCpuTraceWriteAt(addr.i,value.i)\n" + proc)
    for branch in ("    If MapManaged\n      CpuNow()\n", "  ElseIf addr=$4014\n    CpuNow()\n",
                   "  ElseIf addr<$4000 Or addr<=$4017\n    CpuNow()\n"):
        if code.count(branch) != 1:
            raise ValueError(f"compiled bus write branch changed: {branch.strip()!r}")
        head, tail = branch.split("\n", 1)
        indent = tail[:len(tail) - len(tail.lstrip())]
        code = code.replace(branch, f"{head}\n{indent}NesCpuTraceWriteAt(addr,value)\n{tail}")
    return code


def unit_reference_select(code):
    """The unit's reference core for a mapper other than MMC3: its threaded STA abs to $8000-$FFFF takes the full
    store (nes_absolute_store: the bus, the slot's write_fast, the module) instead of the native MMC3 bank-select
    shortcut (nes_native_mmc3_select), which is MMC3's register semantics."""
    branch = "beqz $t1, nes_native_mmc3_select"
    label = "nes_native_mmc3_select:\n"
    if code.count(branch) != 1 or code.count(label) != 1:
        raise ValueError("the threaded core's MMC3 select branch changed")
    # the full store takes the address in a0 (the select path's delay slot sets it): a two-word stop on the way
    return code.replace(branch, "beqz $t1, nes_unit_reference_store").replace(
        label, "nes_unit_reference_store:\nb nes_absolute_store\nor $a0, $t0, $zero\n" + label)


def trace_native_serial(code):
    """Checking build of the MMC1 reference core: an STA abs to $8000-$FFFF takes the threaded core's full store
    (nes_absolute_store, the bus's NesWrite) instead of its native serial-bit path, so that every mapper write is
    folded by trace_compiled_writes as the unit folds every one. Exact either way (the native path is the full
    store's shortcut for an intermediate bit); only where the CPU window ends differs, which the guest digest
    does not fold."""
    branch = "bne $t1, $zero, nes_native_mapper_serial\n"
    if code.count(branch) != 1:
        raise ValueError("MMC1 native serial branch changed")
    return code.replace(branch, "bne $t1, $zero, nes_absolute_store\n")


def trace_no_fill(code):
    """Checking build of a reference core outside the unit: without the threaded core's RAM-fill shortcut (stage_fill:
    a STA abs,X / INX / BNE loop done in one step), which the unit has not, so that both builds step - and fold -
    every instruction of such a loop. Exact either way; only which instructions are folded differs."""
    from stage_fill import FILL_LOOP
    if code.count(FILL_LOOP) > 1:
        raise ValueError("native RAM fill entry changed")
    return code.replace(FILL_LOOP, "nes_native_9d:\n")


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


IMAGE_BASE = 0x80000400       # the RDRAM image's load address (nes.bin is the image from there)

# THE MAPPER MODULES (mapper-modules design note, sections 2-3): mapper -> the module's source name, modules/<name>.n64
# (its hot part, the mapper slot's bytes) and modules/<name>_cold.n64 (its cold part, the cold slot's bytes). The
# first is the default module: the one assembled in the slots of the shipped compile, so the checking builds see it.
MODULES = {4: "mmc3", 1: "mmc1"}
# THE UNIT BUILD: the runtime cartridge whose CPU runs the hot unit is built once for every mapper. Nothing of it is
# staged for the cartridge's mapper: #GAME_MAPPER is UNIT_MAPPER ("chosen at load") and the sources' unit branches
# test #NES_UNIT; the mapper's own code is its module, installed into the two slots at load (modules/install.n64).
UNIT_MAPPER = -1
# ... but for two sources still read #GAME_MAPPER=4 as "the unit build" (status.n64's status-read rule and
# library/wait.n64's RAM-wait index, both in another worker's conversion at the time of writing): until they test
# #NES_UNIT, game.pmi carries this constant for the unit build. No other source of the unit build reads it as 4.
UNIT_GAME_MAPPER = 4


def module_store(modules, slot_bytes, cold_bytes):
    """The cartridge file modules.bin (modules/install.n64): a 32-byte header (the mark, the count, the slot's and the
    cold slot's sizes, zeros), one 16-byte row a module (mapper, offset of its hot bytes, their count, offset of its
    cold bytes), then each module's bytes as they run in the two slots, each part 16-aligned. modules maps a mapper
    to (hot bytes, cold bytes)."""
    import struct
    head = b"NESMODST" + struct.pack(">III", len(modules), slot_bytes, cold_bytes) + bytes(12)
    rows, body = b"", b""
    offset = 32 + 16 * len(modules)
    for mapper, (code, cold) in sorted(modules.items()):
        if len(code) != slot_bytes or len(cold) != cold_bytes:
            raise RuntimeError(f"mapper {mapper}'s module is {len(code)} + {len(cold)} bytes, not the slots' "
                               f"{slot_bytes} + {cold_bytes}")
        hot_at = offset + len(body)
        body += code + bytes(-len(code) % 16)
        rows += struct.pack(">IIII", mapper, hot_at, len(code), offset + len(body))
        body += cold + bytes(-len(cold) % 16)
    data = head + rows + body
    return data + bytes(max(0, 544 - len(data)))   # the installer reads the header and table as 544 bytes


def check_mapper_slot(symbols, image, slot_bytes, cold_bytes):
    """The mapper slots' rules (unit/slot.n64, unit/cold_slot.n64), read from the build's own symbols and image: each
    slot is exactly its size from a 16-byte boundary, the module's part fits it, the entry labels the common code calls
    lie at their fixed offsets, and no relative branch in either part leaves the two slots (a branch's target moves
    with the bytes; only j / jal may leave). Returns (hot bytes, cold bytes): the module of this compile as it runs."""
    import struct
    sym = {}
    for line in symbols.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split()
        if len(parts) >= 2:
            sym[parts[1]] = int(parts[0], 16)
    slot, fill, end = sym["nes_mapper_slot"], sym["nes_mapper_slot_fill"], sym["nes_mapper_slot_end"]
    if slot % 16 or end - slot != slot_bytes or not slot <= fill <= end:
        raise RuntimeError(f"mapper slot ${slot:08X}..${end:08X} (module to ${fill:08X}) is not {slot_bytes} bytes "
                           "from a 16-byte boundary with the module inside it")
    cold, cold_fill, cold_end = sym["nes_mapper_cold"], sym["nes_mapper_cold_fill"], sym["nes_mapper_cold_end"]
    if cold % 16 or cold_end - cold != cold_bytes or not cold <= cold_fill <= cold_end:
        raise RuntimeError(f"cold slot ${cold:08X}..${cold_end:08X} (module to ${cold_fill:08X}) is not {cold_bytes} "
                           "bytes from a 16-byte boundary with the module's cold part inside it")
    for offset, label in enumerate(SLOT_ENTRIES):
        if sym.get(label) != slot + 8 * offset:
            raise RuntimeError(f"the slot's entry {label} is not at slot + {8 * offset}")
    for offset, label in enumerate(COLD_ENTRIES):
        if sym.get(label) != cold + 8 * offset:
            raise RuntimeError(f"the cold slot's entry {label} is not at cold slot + {8 * offset}")
    if sym.get("nes_cold_moddata") != cold + 48:
        raise RuntimeError("the cold slot's module data (nes_cold_moddata) is not at cold slot + 48")
    # a module's data in its parts (tables) is not decoded: the span from a label <name>_data to <name>_data_end, and
    # the cold slot's register table (nes_cold_maptable, 8 words)
    data = [(sym[k], sym[k + "_end"]) for k in sym if k.endswith("_data") and k + "_end" in sym
            and (slot <= sym[k] < end or cold <= sym[k] < cold_end)]
    data.append((sym["nes_cold_maptable"], sym["nes_cold_maptable"] + 32 + 256))   # the table and the module data
    for pc in [*range(slot, fill, 4), *range(cold, cold_fill, 4)]:
        if any(lo <= pc < hi for lo, hi in data):
            continue
        w = struct.unpack_from(">I", image, pc - IMAGE_BASE)[0]
        op, rt = w >> 26, (w >> 16) & 31
        if op in (4, 5, 6, 7, 20, 21, 22, 23) or (op == 1 and rt in (0, 1, 2, 3, 16, 17, 18, 19)):
            off = w & 0xFFFF
            target = pc + 4 + ((off - 0x10000 if off & 0x8000 else off) << 2)
            if not (slot <= target < end or cold <= target < cold_end):
                raise RuntimeError(f"the mapper module's branch at ${pc:08X} leaves the slots (to ${target:08X})")
    print(f"NES mapper slot: {slot_bytes} bytes at ${slot:08X}, module {fill - slot} bytes, {end - fill} free; "
          f"cold slot: {cold_bytes} bytes at ${cold:08X}, module {cold_fill - cold} bytes, {cold_end - cold_fill} free")
    return image[slot - IMAGE_BASE:end - IMAGE_BASE], image[cold - IMAGE_BASE:cold_end - IMAGE_BASE]


# the slots' entry labels, in order, 8 bytes each (unit/slot.n64, unit/cold_slot.n64): every module defines them
SLOT_ENTRIES = ("u_mappercpubudget", "u_nesmmc3fetchdeadline", "u_mapperpputicks", "u_mappera12", "u_mapperwrite",
                "nes_slot_write_sync", "nes_slot_write_fast", "u_mapperclockirq", "nes_slot_cpu_ticks", "nes_slot_read")
COLD_ENTRIES = ("nes_cold_init", "nes_cold_reserved", "nes_cold_maptable")


def outside_slots(image, symbols, slot_bytes, cold_bytes):
    """The RDRAM image with both slots cut out: what every module's compile must give byte for byte."""
    sym = {}
    for line in symbols.decode(errors="replace").splitlines():
        parts = line.split()
        if len(parts) >= 2:
            sym[parts[1]] = int(parts[0], 16)
    slot, cold = sym["nes_mapper_slot"] - IMAGE_BASE, sym["nes_mapper_cold"] - IMAGE_BASE
    first, second = sorted(((slot, slot_bytes), (cold, cold_bytes)))
    return (image[:first[0]] + image[first[0] + first[1]:second[0]] + image[second[0] + second[1]:],
            (slot, cold))


def first_difference(a, b, symbols, places, slot_bytes, cold_bytes):
    """Where two compiles' images first differ outside the slots, by the default compile's nearest symbol."""
    sym = sorted((int(x.split()[0], 16), x.split()[1]) for x in symbols.decode(errors="replace").splitlines()
                 if len(x.split()) >= 2)
    slot, cold = places
    for i in range(min(len(a), len(b))):
        if a[i] != b[i] and not (slot <= i < slot + slot_bytes or cold <= i < cold + cold_bytes):
            pc = IMAGE_BASE + i
            near = [s for s in sym if s[0] <= pc]
            return f"first at ${pc:08X} ({near[-1][1]} + {pc - near[-1][0]})" if near else f"first at ${pc:08X}"
    return f"sizes {len(a)} and {len(b)}"


def outside_symbols(symbols, places, slot_bytes, cold_bytes):
    """The build's symbols that lie outside both slots (the common code's and the variables'), as a set of lines."""
    slot, cold = (IMAGE_BASE + p for p in places)
    keep = set()
    for line in symbols.decode(errors="replace").splitlines():
        parts = line.split()
        if len(parts) >= 2:
            a = int(parts[0], 16)
            if not (slot <= a < slot + slot_bytes or cold <= a < cold + cold_bytes):
                keep.add(line.strip())
    return keep


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
    # The 6502 core: "asm" (cpu6502.n64, the hot unit) for a runtime cartridge whose mapper has a module, else the
    # compiled reference interpreter. A unit build with the reference core is MMC3's checking build (mmc3_run.n64).
    # "unit-reference": the compiled interpreter inside the unit (mmc3_run.n64's holder), with the unit's bus, PPU,
    # scheduler and the mapper's module - the checking build that compares the cores alone, for any module's mapper.
    cpu_core = getattr(args, "cpu_core", None) or ("asm" if runtime and cart.mapper in MODULES else "reference")
    unit_reference = cpu_core == "unit-reference"
    if unit_reference:
        cpu_core = "reference"
    if (cpu_core == "asm" or unit_reference) and not runtime:
        raise ValueError("the assembly 6502 core and the unit's reference core are built for the runtime cartridge only")
    unit = runtime and (cpu_core == "asm" or cart.mapper == 4 or unit_reference)
    stage_as = UNIT_MAPPER if unit else cart.mapper   # what the shared sources are staged for
    if runtime and unit:
        # the battery RAM of every module: MapRam's 8 KB, marked dirty by the modules' own work-RAM writes
        save = SaveProfile(8192, "@MapRam(0)", "")
    elif runtime:
        ram_size = {5: 131072, 69: 32768}.get(cart.mapper, 8192)
        save = save_profile(SimpleNamespace(mapper=cart.mapper, battery=True, ram_size=ram_size, chr=b"\0"), header)
        if save.reason:
            save = None
    if save and save.reason:
        print(f"NES save: {save.reason}", file=sys.stderr)
    save_bytes = save.size if save else 0
    save_banks = 1 if save_bytes <= 32768 else 3 if save_bytes <= 98304 else 4
    chr_size = len(cart.chr) or {6: 32768, 13: 16384}.get(stage_as, 8192)
    program = prg_views(cart)
    polling, has_polls = poll_source(program, stage_as)
    audio_rate = getattr(args, "audio_rate", 48000)
    if audio_rate not in (20000, 48000):
        raise ValueError("supported audio rates are 20000 and 48000 Hz")
    # The NROM 20 kHz path can run through adjacent CPU windows while the
    # next device deadline is still ahead. The 48 kHz path retains its
    # original service cadence for the more frequent sample deadlines.
    chain_nrom = stage_as == 0 and audio_rate == 20000
    mmc1_20k = stage_as == 1 and audio_rate == 20000
    raster_deadline = mmc1_20k
    ram_wait, has_ram_waits = ram_wait_source(program, stage_as, chain_nrom)
    runtime_waits = unit or (runtime and cart.mapper in (0, 1))
    mmc1_rows = stage_as == 1 and (getattr(args, "runtime_chr_ram", False) if runtime
                                   else not cart.chr and chr_size == 8192)
    if unit and cpu_core == "reference" and cart.mapper not in MODULES:
        raise ValueError(f"the unit's reference core runs a module's mapper; mapper {cart.mapper} has no module")
    cpu_trace = getattr(args, "cpu_trace", False)
    # the checking builds that compare two cores' digests over different shortcut rules (the unit's against a reference
    # core outside it): every idle-loop and RAM-wait shortcut off (NesIdleEnabled = 0 from load), so that both step,
    # and fold, every instruction. The shortcuts are exact; the oracles (sound, checkpoints) run with them on.
    idle_off = getattr(args, "idle_off", False)
    if idle_off and not (runtime and args.check_frame):
        raise ValueError("--idle-off is a runtime verification build")
    a12_check = getattr(args, "a12_check", False)
    ppu_check = getattr(args, "ppu_check", False)
    twin_check = getattr(args, "twin_check", False)
    wb_measure = getattr(args, "wb_measure", False)
    rsp_check = getattr(args, "rsp_check", False)
    if (wb_measure or rsp_check) and not (unit and args.check_frame):
        raise ValueError("the band write-back measure and the RSP check are runtime-MMC3 verification builds")
    if twin_check and not (unit and args.check_frame):
        raise ValueError("the emitter twin's check is a runtime-MMC3 verification build")
    if ppu_check and not (unit and args.check_frame):
        raise ValueError("the PPU check is a runtime-MMC3 verification build")
    if a12_check and not (unit and args.check_frame):
        raise ValueError("the A12 check is a runtime-MMC3 verification build")
    if cpu_trace and not (runtime and args.check_frame):
        raise ValueError("the CPU trace is a runtime verification build")
    # N5 (design note, N.22): the runtime-MMC3 cartridge shows the RSP band emitter's picture. The old per-pixel
    # renderer and its CI8 blit stay for the builds that compare against them, and as --old-show (the reference).
    old_show = getattr(args, "old_show", False)
    show_check = getattr(args, "show_check", False)
    rdp_show = (unit and not old_show
                and not (twin_check or rsp_check or ppu_check or wb_measure))
    if show_check and not (unit and args.check_frame) or old_show and not unit:
        raise ValueError("the show check and the old show are runtime-MMC3 builds (the check a verification build)")
    # N9: the console record (console_record.n64), only in the playable cart that shows the RSP's picture
    console_record = getattr(args, "console_record", False)
    if console_record and not (rdp_show and not args.check_frame):
        raise ValueError("the console record is built into the playable runtime-MMC3 cart only (no verify frame)")
    # the console record hashing every shown picture (a test cart that runs by itself; its own record area)
    record_pictures = getattr(args, "record_every_picture", False)
    if record_pictures and not console_record:
        raise ValueError("--record-every-picture is a form of the console record (--console-record)")
    # N10 (design note, N.52): the synthesis on the RSP, in every build that runs the RSP program (the RSP show);
    # --syn-check adds the CPU twin and compares every sample of every block before it is queued
    syn_check = getattr(args, "syn_check", False)
    if syn_check and not (rdp_show and args.check_frame):
        raise ValueError("the synthesis check is a runtime-MMC3 verification build with the RSP show")
    settings = {
        "NES_RSP_SYN": int(rdp_show and audio_rate == 20000),
        "NES_SYN_CHECK": int(syn_check),
        "NES_CONSOLE_RECORD": int(console_record),
        "NES_REC_PICTURES_ALL": int(record_pictures),
        "NES_CPU_TRACE": int(cpu_trace),
        "NES_IDLE_OFF": int(idle_off),
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
        "NES_APU_SPLIT": int(unit),
        "NES_HW_TELEMETRY": int(telemetry),
        "NES_RUNTIME_ROM": int(runtime),
        "NES_DMC_RASTER_DEADLINE": int(raster_deadline),
        "NES_CHAIN_WINDOWS": int(cart.mapper == 1 or chain_nrom),
        "HOST_AUDIO_FRAMES": 512,
        # the mapper slot (unit/slot.n64; the mapper-modules design note, section 3): the hot span's last bytes
        "NES_SLOT_BYTES": 2896,
        # the cold slot (unit/cold_slot.n64): the cold part's last bytes, the module's cold part (init, its rare paths)
        "NES_COLD_SLOT_BYTES": 1536,
        # the unit build (any mapper, its module installed at load) and the module assembled in place in this compile
        "NES_UNIT": int(unit),
        "NES_SLOT_MODULE": 4,
        "NES_MMC1_ROWS": int(mmc1_rows),
        "NES_RETAINED_ROWS": int(mmc1_rows or unit),
        "NES_BG_EXPANDED": int(stage_as in (0, 2) and chr_size == 8192),
        "NES_BANKED_WAITS": int(poll_bank_size(stage_as) == 8192),
        "NES_PREDICTABLE_IRQ": int(bool(poll_bank_size(stage_as))),
        "NES_HAS_POLLS": int(runtime_waits or has_polls),
        "NES_HAS_RAM_WAITS": int(runtime_waits or has_ram_waits),
        "VERIFY_INPUT": int(bool(controller_trace)),
        "VERIFY_FRAME": args.check_frame, "GAME_PAL": int(header_is_pal(header)), "GAME_MAPPER": UNIT_GAME_MAPPER if unit else cart.mapper, "GAME_SUB": cart.submapper,
        "GAME_SAVE_BYTES": save_bytes, "GAME_SAVE_BANKS": save_banks,
        "GAME_SAVE_LINEAR": int(save_banks == 4 and not getattr(args, "banked_sram_128", False)),
        "GAME_MIRROR": cart.mirror, "GAME_RAM": cart.ram_size,
        "GAME_CONFLICT": int(cart.conflicts), "GAME_BATTERY": int(cart.battery),
        "GAME_FOUR_SCREEN": int(bool(header[6] & 8)),
        "GAME_PRG": header[4] * 16384, "GAME_VIEWS": len(program),
        "GAME_CHR": chr_size, "GAME_CHR_RAM": int(not cart.chr),
        "CART_CHR_BANKS": (max(4, min(64, max(BOARD_LIMITS.get(m, (524288, 262144))[1] for m in
                                              (MODULES if unit else (cart.mapper,))) // 8192))
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
                # the unit's reference core is staged in MMC3's threaded shape (the 8 KB biases, the unit's bus)
                code = stage_cpu(stage_poll(code), 4 if unit else cart.mapper, program, has_ram_waits, chain_nrom,
                                 mmc1_20k, runtime)
                if unit and cart.mapper != 4:
                    code = unit_reference_select(code)
                if cpu_trace:
                    code = trace_reference(code)
                    if not unit:
                        code = trace_no_fill(code)
                    if not unit and cart.mapper == 1:
                        code = trace_native_serial(code)
                if runtime and not unit and cart.mapper == 1:
                    serial = "nes_native_mapper_serial:\n"
                    if code.count(serial) != 1:
                        raise ValueError("native MMC1 serial write entry changed")
                    code = code.replace(serial, serial + """    la $t0, global_cartmapper
    ld $t1, 0($t0)
    beq $t1, $zero, nes_absolute_store
    nop
""")
            elif name.startswith("mapper"):
                code = stage_mapper(name, code, stage_as, runtime, unit)
            elif name == "bridge":
                for old, new, count in CONTROLLER_PATCHES["bridge"]:
                    if code.count(old) != count:
                        raise ValueError("controller bus source changed")
                    code = code.replace(old, new)
                code = code.replace("PeekL(@QComplete)", "PeekI(@QComplete)")
                code = stage_input(stage_bus(code, stage_as, unit))
            code = stage_audio(name, stage_fastppu(name, stage_region(name, code), unit),
                               stage_as, audio_rate, split=unit)
            code = stage_sync(name, code, stage_as, chain_nrom, raster_deadline, runtime, unit)
            code = stage_simple_mapper(name, code, stage_as)
            if name == "bridge" and unit:
                code = stage_runtime_mmc3_bus(code)
            # Board identity is fixed for the lifetime of this cartridge.
            code = code.replace("ExtraManaged(CartMapper)", "NesExtraBoard")
            code = code.replace("ExtraA12(CartMapper)", "NesA12Board")
            if save_bytes and not (unit and name == "mappers"):
                code = stage_save(name, code, save)
            if cpu_trace and name == "bridge":
                code = trace_bus_reads(code)
                if not unit:
                    code = trace_compiled_writes(code)
            (guest / (name + ".pmi")).write_text(guest_names(code).replace('.pi4"', '.pmi"'), encoding="utf-8")
        expansion = expansion_source(stage_as)
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
        if cpu_trace and unit:
            write = app / "unit" / "write.n64"
            write.write_text(trace_bus_writes(write.read_text(encoding="utf-8")), encoding="utf-8")
        oscillator = app / "oscillators.n64"
        oscillator.write_text(stage_oscillators(oscillator.read_text(encoding="utf-8"), stage_as), encoding="utf-8")
        if controller_trace:
            if not args.check_frame:
                raise ValueError("controller replay requires a bounded verification run")
            replay = replay_source(controller_trace)
            (app / "replay.pmi").write_text(replay)
        (app / "poll.pmi").write_text(polling)
        (app / "ramwait.pmi").write_text(runtime_wait_source(stage_as, unit) if runtime_waits else ram_wait)
        (app / "region.pmi").write_text(render_region(audio_rate))
        def write_settings(module):
            (app / "game.pmi").write_text("".join(f"#{k} = {v}\n" for k, v in {**settings, "NES_SLOT_MODULE": module}.items()))

        # the modules this cart carries: all of them, but in the A12 checking build (MMC3's own check, whose exact walk
        # outside the unit reads the MMC3 module's labels) and the unit's reference core (a checking build of the
        # cores, laid out by the compiler around the holder procedure, not pinned: it carries the ROM's module only)
        carried = ([4] if a12_check else [cart.mapper] if unit and cpu_core == "reference" and cart.mapper in MODULES
                   else list(MODULES))
        write_settings(carried[0])
        (app / "game.bin").write_bytes(program + cart.chr)
        slot_bytes, cold_bytes = settings["NES_SLOT_BYTES"], settings["NES_COLD_SLOT_BYTES"]
        blank = (bytes(slot_bytes), bytes(cold_bytes))
        (app / "modules.bin").write_bytes(module_store({m: blank for m in carried}, slot_bytes, cold_bytes))

        def compile_cart():
            result = subprocess.run([str(compiler), "--compile", "nes.n64", "-o", "nes.bin"],
                                    cwd=app, env=dict(os.environ, PMF_ROOT=str(sdk)),
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            log = result.stdout.decode(errors="replace")
            if result.returncode or not (app / "nes.z64").is_file():
                raise RuntimeError(log)
            return log

        log = compile_cart()
        check_storage_layout(log)
        if cpu_core == "asm":
            check_hot_unit(app / "nes.bin.sym")
        if unit:
            # The mapper slots (mapper-modules design note, section 3): each module is assembled in place, at the
            # slots' addresses, by a compile of its own (#NES_SLOT_MODULE); its store bytes are that compile's slot
            # bytes. The common code is the same for every module, so every compile's RDRAM image OUTSIDE the two
            # slots, and its symbols there, must be the first compile's (MMC3's, the default module) byte for byte.
            first = (app / "nes.bin").read_bytes(), (app / "nes.bin.sym").read_bytes()
            built = {carried[0]: check_mapper_slot(app / "nes.bin.sym", first[0], slot_bytes, cold_bytes)}
            common, places = outside_slots(first[0], first[1], slot_bytes, cold_bytes)
            common_symbols = outside_symbols(first[1], places, slot_bytes, cold_bytes)
            for module in carried[1:]:
                write_settings(module)
                compile_cart()
                image, symbols = (app / "nes.bin").read_bytes(), (app / "nes.bin.sym").read_bytes()
                if cpu_core == "asm":
                    check_hot_unit(app / "nes.bin.sym")
                built[module] = check_mapper_slot(app / "nes.bin.sym", image, slot_bytes, cold_bytes)
                there, at = outside_slots(image, symbols, slot_bytes, cold_bytes)
                if at != places or there != common:
                    raise RuntimeError(f"mapper {module}'s compile changed the image outside the mapper slots: "
                                       + first_difference(first[0], image, first[1], places, slot_bytes, cold_bytes))
                if outside_symbols(symbols, at, slot_bytes, cold_bytes) != common_symbols:
                    raise RuntimeError(f"mapper {module}'s compile changed the symbols outside the mapper slots")
                print(f"NES mapper module {module} ({MODULES[module]}): the image outside the slots byte for byte "
                      "the default module's")
            # The store is a cartridge file, outside the RDRAM image: the last compile, with the real store and the
            # default module in place, must give the first compile's RDRAM image and symbols, byte for byte.
            write_settings(carried[0])
            store = module_store(built, slot_bytes, cold_bytes)
            (app / "modules.bin").write_bytes(store)
            log = compile_cart()
            if ((app / "nes.bin").read_bytes(), (app / "nes.bin.sym").read_bytes()) != first:
                raise RuntimeError("the mapper store's second compile changed the RDRAM image")
            if (app / "nes.z64").read_bytes().count(store) != 1:
                raise RuntimeError("the mapper store is not in the cartridge exactly once")
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
    parser.add_argument("--cpu-core", choices=("asm", "reference", "unit-reference"), default=None,
                        help="the 6502 core: asm (cpu6502.n64, the runtime MMC3 default) or the reference interpreter")
    parser.add_argument("--cpu-trace", action="store_true",
                        help="checking build: a per-frame digest of the state after every instruction (needs --check-frame)")
    parser.add_argument("--idle-off", action="store_true",
                        help="checking build: every idle-loop and RAM-wait shortcut off from load (needs --check-frame)")
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
    parser.add_argument("--syn-check", action="store_true",
                        help="checking build: the APU synthesis on the RSP (rspsyn.n64rsp) and its CPU twin "
                             "(apusynth.n64), every sample of every AI block compared (needs --check-frame)")
    parser.add_argument("--console-record", action="store_true",
                        help="the playable cart keeps a record of its run in the flash cart's memory (console_record.n64)")
    parser.add_argument("--record-every-picture", action="store_true",
                        help="with --console-record: every shown picture hashed into the record, buttons or not, in "
                             "its own record area (a test cart that runs by itself)")
    try:
        args = parser.parse_args()
        if args.check_frame < 0:
            parser.error("--check-frame must be nonnegative")
        build(args)
    except (OSError, ValueError, RuntimeError) as error:
        sys.exit(str(error))
