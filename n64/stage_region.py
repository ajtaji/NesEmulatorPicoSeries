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
    mmc3_clock = name == "mappers" and 'mmc3_ticks.n64' in source
    if name == "mappers" and "mapper_budget.n64" in source:
        patches = []
    elif mmc3_clock:
        patches = [patch for patch in patches if patch[0] not in (
            "left=cycles*3 : line=PpuLine", "If line=261 And odd<>0", "(line<240 Or line=261)",
            "If line=262 : line=0 : odd=odd!1 : EndIf", "If line=261 : nextLine=0 : EndIf",
        )]
    for old, new, expected in patches:
        if source.count(old) != expected:
            raise ValueError(f"{name}: PAL timing patch expected {expected} occurrences of {old!r}")
        source = source.replace(old, new)
    if mmc3_clock:
        start = source.index("Procedure.i MapperCpuBudget()")
        end = source.index("EndProcedure", start) + len("EndProcedure")
        source = source[:start] + 'XIncludeFile "../n64/mmc3_budget.n64"' + source[end:]
    return source


def render_region(audio_rate: int = 48000) -> str:
    """Extract the desktop's timing procedure and the Pico-derived APU tables."""
    desktop = (ROOT / "desktop" / "machine.pbi").read_text(encoding="utf-8")
    timing = re.search(r"^Procedure NesTiming\(pal\.i\)\n.*?^EndDataSection\b", desktop, re.M | re.S)
    desktop_state = "  MachinePal=pal\n"
    if not timing or timing[0].count(desktop_state) != 1:
        raise ValueError("desktop timing procedure or PAL APU tables changed")
    # Preserve the original regional CPU clock as a rational sample cadence.
    region = timing[0].replace(desktop_state, "")
    if audio_rate == 20000:
        for original, native in (
            ("ApuSampleBase=34 : ApuFracStep=30607 : ApuFracDen=48000",
             "ApuSampleBase=83 : ApuFracStep=2607 : ApuFracDen=20000"),
            ("ApuSampleBase=37 : ApuFracStep=101 : ApuFracDen=352",
             "ApuSampleBase=89 : ApuFracStep=43 : ApuFracDen=88"),
        ):
            if region.count(original) != 1:
                raise ValueError("regional APU sample cadence changed")
            region = region.replace(original, native)
    return "; NES timing and PAL APU tables from desktop/machine.pbi.\n" + region + "\n"
