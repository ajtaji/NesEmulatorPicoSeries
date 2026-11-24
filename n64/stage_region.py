"""Stage the existing Pico/desktop NES region timing for the N64 guest."""

from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from port_desktop import PAL_GLOBALS, PAL_PATCHES


def header_is_pal(header: bytes) -> bool:
    """Use the validated NES 2.0 timing field or the clean iNES TV flag."""
    if header[7] & 12 == 8:
        return header[12] & 3 == 1
    return not any(header[12:16]) and bool(header[9] & 1)


def stage_region(name: str, source: str) -> str:
    if name == "bridge":
        # The same declarations as the desktop. In N64 staging the pad patch
        # may already have extended the declaration of NesLatch2.
        return PAL_GLOBALS + source
    patches = PAL_PATCHES.get(name, [])
    if name == "guest_reset":
        patches = [
            ("  PpuWarmup=29658\n", "", 1),
            ("  ApuSampleLeft=37\n  ApuSampleFrac=101\n", "", 1),
            ("  DmcTimer=428\n", "", 1),
            ("  AudioReadCursor=0\nEndProcedure", "  AudioReadCursor=0\n  NesTiming(#GAME_PAL)\nEndProcedure", 1),
        ]
    for old, new, expected in patches:
        if source.count(old) != expected:
            raise ValueError(f"{name}: PAL timing patch expected {expected} occurrences of {old!r}")
        source = source.replace(old, new)
    return source


def render_region() -> str:
    """Extract the desktop's timing procedure and the Pico-derived APU tables."""
    desktop = (ROOT / "desktop" / "machine.pbi").read_text(encoding="utf-8")
    timing = re.search(r"^Procedure NesTiming\(pal\.i\)\n.*?^EndDataSection\b", desktop, re.M | re.S)
    desktop_state = "  MachinePal=pal\n"
    if not timing or timing[0].count(desktop_state) != 1:
        raise ValueError("desktop timing procedure or PAL APU tables changed")
    return "; NES timing and PAL APU tables from desktop/machine.pbi.\n" + timing[0].replace(desktop_state, "") + "\n"
