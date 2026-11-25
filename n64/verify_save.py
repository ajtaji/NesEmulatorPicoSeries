"""Verify battery-backed MMC1 RAM across independent Nintendo 64 boots."""

import argparse
from pathlib import Path
import re
import shutil
import tempfile
from unittest.mock import patch

import build as cartridge
from verify import run_headless


CHECK_FRAME = 120
STATUS = 0x40
INITIAL = 0x41
PAYLOAD = bytes((index & 255) ^ (0x60 + (index >> 8)) ^ 0xC5 for index in range(8192))


def fixture(battery):
    """An original 6502 program fills erased RAM or verifies a previous fill."""
    base = 0xC000
    code = bytearray()
    labels = {}
    fixups = []

    def emit(*values):
        code.extend(values)

    def label(name):
        labels[name] = len(code)

    def branch(op, target):
        emit(op, 0)
        fixups.append((len(code) - 1, target, 1))

    def jump(op, target):
        emit(op, 0, 0)
        fixups.append((len(code) - 2, target, 2))

    # Disable IRQ and rendering, then inspect the first byte before writing.
    emit(0x78, 0xD8, 0xA2, 0xFF, 0x9A, 0xA9, 0, 0x8D, 0, 0x20, 0x8D, 1, 0x20)
    emit(0xAD, 0, 0x60, 0x85, INITIAL, 0xC9, PAYLOAD[0])
    branch(0xF0, "loaded")
    emit(0xC9, 0)
    branch(0xF0, "blank")
    emit(0xC9, 255)
    branch(0xD0, "failed")
    label("blank")
    jump(0x20, "check_blank")
    jump(0x20, "fill")
    jump(0x20, "check_pattern")
    emit(0xA9, 1)
    branch(0xD0, "stop")
    label("loaded")
    jump(0x20, "check_pattern")
    emit(0xA9, 2)
    branch(0xD0, "stop")
    label("failed")
    emit(0xA9, 255)
    label("stop")
    emit(0x85, STATUS)
    label("idle")
    jump(0x4C, "idle")

    label("reset_pointer")
    emit(0xA9, 0, 0x85, 0x20, 0xA8, 0xA9, 0x60, 0x85, 0x21, 0x60)

    for name, operation in (
        ("check_blank", (0xB1, 0x20, 0xC5, INITIAL)),
        ("fill", (0x98, 0x45, 0x21, 0x49, 0xC5, 0x91, 0x20)),
        ("check_pattern", (0x98, 0x45, 0x21, 0x49, 0xC5, 0xD1, 0x20)),
    ):
        label(name)
        jump(0x20, "reset_pointer")
        label(name + "_byte")
        emit(*operation)
        if name != "fill":
            branch(0xD0, "failed")
        emit(0xC8)
        branch(0xD0, name + "_byte")
        emit(0xE6, 0x21, 0xA5, 0x21, 0xC9, 0x80)
        branch(0xD0, name + "_byte")
        emit(0x60)

    for offset, target, width in fixups:
        if width == 1:
            delta = labels[target] - offset - 1
            if not -128 <= delta <= 127:
                raise ValueError(f"fixture branch out of range: {target}")
            code[offset] = delta & 255
        else:
            code[offset:offset + 2] = (base + labels[target]).to_bytes(2, "little")

    prg = bytearray(32768)
    prg[16384:16384 + len(code)] = code
    prg[-6:] = (base + labels["idle"]).to_bytes(2, "little") + base.to_bytes(2, "little") * 2
    header = b"NES\x1a" + bytes((2, 0, 0x10 | (2 if battery else 0), 0, 1)) + bytes(7)
    return header + prg


def build_test(sdk, directory, *, battery, persist):
    directory.mkdir()
    rom = directory / "fixture.nes"
    out = directory / "fixture.z64"
    rom.write_bytes(fixture(battery))
    copytree = shutil.copytree

    def staging(source, destination, *args, **kwargs):
        result = copytree(source, destination, *args, **kwargs)
        if Path(source) == cartridge.ROOT / "n64":
            entry = Path(destination) / "nes.n64"
            source_code = entry.read_text(encoding="utf-8")
            hook = "\nRunGame()\n"
            if source_code.count(hook) != 1:
                raise ValueError("fixture cannot locate the cartridge entry")
            source_code = source_code.replace(hook, hook +
                f'LpmDebugPrint("NES SAVE FIXTURE " + Str(M({STATUS})) + " INITIAL " + Str(M({INITIAL})))\n')
            entry.write_text(source_code, encoding="utf-8")
        return result

    with patch.object(cartridge.shutil, "copytree", staging):
        cartridge.build(argparse.Namespace(sdk=sdk, rom=rom, out=out, audio_rate=20000,
                                          check_frame=CHECK_FRAME, persist_save=persist))
    return out


def cold_boot(sdk, emulator, rom, save_dir, name, expected, initial, *, force_sram=False):
    save_dir.mkdir(exist_ok=True)
    report = rom.parent / f"{name}.txt"
    save_mode = ("--save", "sram") if force_sram else ()
    run_headless(sdk, emulator, rom, "--boot", "lle", "--ram", "4", "--frames", "180",
                 "--test", report, "--save-dir", save_dir, *save_mode)
    text = report.read_text(encoding="utf-8")
    match = re.search(r"^NES SAVE FIXTURE (\d+) INITIAL (\d+)$", text, re.M)
    if (not match or int(match[1]) != expected or int(match[2]) not in initial or
            f"NES CHECKPOINT {CHECK_FRAME}" not in text or "FIRST code " in text or "NES STOP" in text):
        raise ValueError(f"unexpected guest result for {name}: {report}")
    if not force_sram and not re.search(r'^SAVE domain2=sram .*decided_by="the ED64 header"$', text, re.M):
        raise ValueError(f"SRAM type was not selected from the cartridge header: {report}")


def verify(sdk, emulator, work):
    out = build_test(sdk, work / "battery", battery=True, persist=True)
    saved = out.parent / "saves"
    cold_boot(sdk, emulator, out, saved, "erased-boot", 1, (0, 255))
    image = saved / "fixture.sra"
    original = image.read_bytes()
    if original != PAYLOAD.ljust(32768, b"\xff"):
        raise ValueError(f"wrong MMC1 payload in {image}")
    cold_boot(sdk, emulator, out, saved, "persisted-boot", 2, (PAYLOAD[0],))
    if image.read_bytes() != original:
        raise ValueError("loading an unchanged save modified the SRAM file")

    for name, battery, persist, seeded in (("no-battery", False, True, False),
                                           ("verifier-default", True, None, True)):
        out = build_test(sdk, work / name, battery=battery, persist=persist)
        saves = out.parent / "saves"
        image = saves / "fixture.sra"
        expected_save = bytes(byte ^ 255 for byte in original) if seeded else None
        if expected_save is not None:
            saves.mkdir()
            image.write_bytes(expected_save)
        cold_boot(sdk, emulator, out, saves, "control", 1, (0, 255), force_sram=True)
        actual_save = image.read_bytes() if image.exists() else None
        if actual_save != expected_save:
            raise ValueError(f"unexpected SRAM file change for {name}")
    print("PASS: all 8,192 MMC1 bytes survived a cold boot; both controls left SRAM untouched")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", type=Path, required=True)
    parser.add_argument("--emulator", type=Path, required=True)
    parser.add_argument("--results", type=Path, help="keep cartridges, logs, and SRAM images in a new directory")
    args = parser.parse_args()
    if args.results:
        args.results.mkdir(parents=True)
        verify(args.sdk.resolve(), args.emulator.resolve(), args.results.resolve())
    else:
        with tempfile.TemporaryDirectory(prefix="nes-n64-save-") as work:
            verify(args.sdk.resolve(), args.emulator.resolve(), Path(work))
