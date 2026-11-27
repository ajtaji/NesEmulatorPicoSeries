"""Generate cartridge hardware metadata shared by the N64 library components."""
from anvil_cartridge import BOARD_LIMITS, BOARD_SUBMAPPERS, LEGACY_RAM_BOARDS, SUPPORTED
from stage_expansion import EXPANSION_MAPPERS


RUNTIME_MAPPERS = SUPPORTED | EXPANSION_MAPPERS
PROFILES = [(mapper, False) for mapper in sorted(RUNTIME_MAPPERS)] + [(1, True)]


def board_table_source():
    lines = ["DataSection", "NesRomBoards:"]
    for mapper in range(256):
        if mapper not in RUNTIME_MAPPERS:
            lines.append("  Data.l 0,0,0,0")
            continue
        prg, chr_ = BOARD_LIMITS.get(mapper, (524288, 262144))
        if mapper == 1:
            prg = 524288    # SUROM / SXROM: the N64 module's outer PRG bank (modules/mmc1.n64); the shared table says 256 KB
        ram = {5: 8, 69: 1}.get(mapper, int(mapper in LEGACY_RAM_BOARDS))
        submask = sum(1 << sub for sub in BOARD_SUBMAPPERS.get(mapper, {0}))
        lines.append(f"  Data.l {prg // 16384},{min(64, chr_ // 8192)},{ram},{submask}")
    return "\n".join([*lines, "EndDataSection", ""])
