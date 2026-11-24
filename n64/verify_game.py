"""Replay Thwaite v0.04 at guest-frame boundaries and verify picture and PCM."""
import argparse
import hashlib
from pathlib import Path
import re
import tempfile
import wave

from PIL import Image

from build import build
from verify import run_headless


# Start the game, advance the tutorial, move right and fire.
INPUT = ((130, 134, 8), (190, 194, 1), (300, 304, 9),
         (420, 432, 128), (435, 441, 1))
ROM = "a2df24d9c9f72e56c2fdc4c703becc47a5700ad0158da8208247635ebeb3779c"
RGB = "214ca9713c1c5158aaa7f34e5793a5c1680622ce6f4901a9960cb8c63dbeeb5f"
PCM = "5263d5759399e609ef870af39d8c7ad69f57215de221a2413b6679a0442385db"


def verify_game(args, work):
    if hashlib.sha256(args.rom.read_bytes()).hexdigest() != ROM:
        raise ValueError("expected the Thwaite v0.04 release cartridge")
    args.check_frame = 450
    args.out = work / "replay.z64"
    build(args, controller_trace=INPUT)
    report, picture, sound = (work / name for name in ("report.txt", "frame.png", "sound.wav"))
    run_headless(args.sdk, args.emulator, args.out, "--ram", "4", "--test", report,
                 "--frames", "1250", "--png", picture, "--wav", sound)
    log = report.read_text()
    if ("NES CHECKPOINT 450" not in log or "NES FRAME 450 CPU 13401250 PCM 359408 PC 52804 " not in log
            or "NES STOP" in log or "FIRST code " in log):
        raise ValueError("replay diverged or failed to reach the gameplay checkpoint")
    with Image.open(picture) as im:
        if hashlib.sha256(im.convert("RGB").tobytes()).hexdigest() != RGB:
            raise ValueError("gameplay framebuffer differs from the reference")
    with wave.open(str(sound)) as wav:
        if (wav.getnframes() != 358912 or wav.getnchannels() != 2 or wav.getsampwidth() != 2
                or hashlib.sha256(wav.readframes(wav.getnframes())).hexdigest() != PCM):
            raise ValueError("gameplay PCM differs from the reference")
    clock = {int(frame): int(tick) for frame, tick in re.findall(
        r"^NES FRAME (\d+) CPU \d+ PCM \d+ PC \d+ COUNT (\d+)", log, re.M)}
    gaps = {int(frame): int(count) for count, frame in re.findall(
        r"^NES AI QUEUED \d+ UNDERRUNS (\d+) FRAME (\d+)", log, re.M)}
    checkpoints = sorted(gaps)
    print(f"Startup through frame {checkpoints[0]}: {gaps[checkpoints[0]]} observed AI underruns")
    for first, end in zip(checkpoints, checkpoints[1:]):
        ticks = (clock[end] - clock[first]) & 0xffffffff
        print(f"Guest {first} to {end}: {(end-first)*46_875_000/ticks:.2f} fps, "
              f"{gaps[end]-gaps[first]} observed AI underruns")
    print("PASS: gameplay checkpoint, framebuffer and 358,912 stereo sample pairs")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("sdk", "emulator", "rom"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--results", type=Path, help="keep the replay ROM and captures in this directory")
    args = parser.parse_args()
    if args.results:
        work = args.results.resolve()
        work.mkdir(parents=True, exist_ok=True)
        verify_game(args, work)
    else:
        with tempfile.TemporaryDirectory(prefix="nes-gameplay-") as name:
            verify_game(args, Path(name))
