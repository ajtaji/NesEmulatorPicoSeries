"""Boot the bundled demo under the N64 emulator and check guest frame 60."""
import argparse
import array
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import wave

from PIL import Image

HERE = Path(__file__).resolve().parent
# Desktop nes_check, PureMetalDemo.nes, 60 frames; R/G/B reduced to five bits.
DEMO_FRAME = "796fb273d3b85dbb7e7096c6e9aa87ebfdeea4c90bd872afb8bfb2b173ce71c7"


def verify(sdk, emulator):
    with tempfile.TemporaryDirectory(prefix="nes-n64-check-") as temp:
        work = Path(temp)
        cart = work / "demo.z64"
        subprocess.run([sys.executable, HERE / "build.py", "--sdk", sdk, "--check-frame", "60",
                        "--out", cart], check=True)
        subprocess.run([emulator, cart, "--ram", "4", "--test", work / "report.txt", "--frames", "1200",
                        "--png", work / "frame.png", "--wav", work / "sound.wav"], check=True)
        report = (work / "report.txt").read_text()
        if ("NES CHECKPOINT 60" not in report or "NES FRAME 60 CPU 1786882 PCM 47922 PC 40156 " not in report
                or "NES STOP" in report or "FIRST code " in report):
            raise ValueError("unexpected guest or VR4300 state:\n" + report)
        with Image.open(work / "frame.png") as picture:
            picture = picture.convert("RGB")
            if picture.size != (320, 240):
                raise ValueError(f"unexpected VI dimensions: {picture.size}")
            for border in [(0, 0, 32, 240), (288, 0, 320, 240)]:
                if picture.crop(border).getbbox():
                    raise ValueError("non-black VI border")
            pixels = picture.crop((32, 0, 288, 240)).tobytes()
        if hashlib.sha256(bytes(value >> 3 for value in pixels)).hexdigest() != DEMO_FRAME:
            raise ValueError("NES frame differs from the desktop reference")
        with wave.open(str(work / "sound.wav")) as pcm:
            if pcm.getnchannels() != 2 or pcm.getsampwidth() != 2 or abs(pcm.getframerate() - 48000) > 50:
                raise ValueError("unexpected AI sample format")
            samples = array.array("h", pcm.readframes(pcm.getnframes()))
        if len(samples) < 90000 or samples[::2] != samples[1::2] or len(set(samples)) < 32:
            raise ValueError("AI output is short, silent or mismatched between channels")
        print("PASS: guest cycles and PC, all 61,440 pixels, borders and stereo PCM at frame 60")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", type=Path, required=True)
    parser.add_argument("--emulator", type=Path, required=True)
    args = parser.parse_args()
    verify(args.sdk.resolve(), args.emulator.resolve())
