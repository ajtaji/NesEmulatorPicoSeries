"""Read explicitly named iNES files and check them against what the emulator runs."""
from dataclasses import dataclass
from pathlib import Path
import hashlib

SUPPORTED = {0, 2, 66}

@dataclass
class Cartridge:
    path: Path
    title: str
    mapper: int
    submapper: int
    mirror: int
    battery: bool
    conflicts: bool
    ram_size: int
    prg: bytes
    chr: bytes
    trainer: bytes
    sha256: str

def read_rom(path: Path, *, ram_limit=8192) -> Cartridge:
    data = path.read_bytes()
    if len(data) < 16 or data[:4] != b'NES\x1a':
        raise ValueError(f'{path.name}: invalid iNES header')
    h = data[:16]
    nes2 = h[7] & 12 == 8
    mapper = (h[6] >> 4) | (h[7] & 240)
    submapper = h[8] >> 4 if nes2 else 0
    if nes2:
        mapper |= (h[8] & 15) << 8
    def rom_size(low, high, unit):
        return (1 << (low >> 2)) * ((low & 3) * 2 + 1) if high == 15 else (low | (high << 8)) * unit
    prg_size = rom_size(h[4], h[9] & 15 if nes2 else 0, 16384)
    chr_size = rom_size(h[5], h[9] >> 4 if nes2 else 0, 8192)
    if not prg_size or prg_size % 8192 or chr_size % 1024:
        raise ValueError(f'{path.name}: unsupported ROM geometry')
    if h[6] & 8:
        raise ValueError(f'{path.name}: four-screen nametables need additional RAM')
    if (nes2 and (h[12] & 3) in (1, 3)) or (not nes2 and h[9] & 1):
        raise ValueError(f'{path.name}: PAL timing is not implemented')
    if nes2:
        ram = sum(64 << n for n in (h[10] & 15, h[10] >> 4) if n)
        chr_ram = sum(64 << n for n in (h[11] & 15, h[11] >> 4) if n)
        if ram > ram_limit or chr_ram > 8192:
            raise ValueError(f'{path.name}: cartridge RAM exceeds the current 8 KiB banks')
    else:
        ram = (h[8] or 1) * 8192 if mapper in (1, 5) else 0
    if ram > ram_limit:
        raise ValueError(f'{path.name}: PRG RAM exceeds 8 KiB')
    offset = 16
    trainer = data[offset:offset+512] if h[6] & 4 else b''
    offset += len(trainer)
    prg = data[offset:offset+prg_size]
    chr_data = data[offset+prg_size:offset+prg_size+chr_size]
    if len(prg) != prg_size or len(chr_data) != chr_size or (h[6] & 4 and len(trainer) != 512):
        raise ValueError(f'{path.name}: truncated cartridge')
    if mapper in (0, 3) and prg_size == 16384:
        prg *= 2
    if mapper == 0 and (len(prg) != 32768 or chr_size not in (0, 8192)):
        raise ValueError(f'{path.name}: unsupported NROM geometry')
    if mapper == 1 and len(prg) > 256 * 1024:
        raise ValueError(f'{path.name}: MMC1 outer-bank board variants are not implemented')
    if mapper == 5 and chr_size == 0:
        raise ValueError(f'{path.name}: MMC5 CHR RAM is not implemented')
    if mapper == 66 and (len(prg) % 32768 or chr_size == 0):
        raise ValueError(f'{path.name}: unsupported GxROM geometry')
    for size in (len(prg) // 8192, max(1, chr_size // 1024)):
        if size & (size-1):
            raise ValueError(f'{path.name}: non-power-of-two bank count')
    conflicts = mapper in (2, 3, 66) and submapper != 1
    return Cartridge(path, path.stem, mapper, submapper, h[6] & 1,
                     bool(h[6] & 2), conflicts, ram, prg, chr_data, trainer,
                     hashlib.sha256(data).hexdigest())

def prg_views(cart):
    """Immutable 32 KiB CPU windows; the existing flat-bias CPU is unchanged."""
    if cart.mapper != 2:
        return cart.prg
    last = cart.prg[-16384:]
    return b''.join(cart.prg[n:n+16384]+last for n in range(0,len(cart.prg),16384))

def validate(c: Cartridge):
    """Refuse, by name, anything this emulator build cannot run."""
    if c.mapper not in SUPPORTED:
        raise ValueError(f'{c.path.name}: mapper {c.mapper} is not supported (0, 2 and 66 are)')
    if c.ram_size or c.trainer:
        raise ValueError(f'{c.path.name}: cartridge work RAM and trainers are not supported')
    if c.mapper == 2 and c.chr:
        raise ValueError(f'{c.path.name}: the UxROM path needs 8 KiB CHR RAM, and this file has CHR ROM')
    if c.mapper == 2 and len(c.prg) % 16384:
        raise ValueError(f'{c.path.name}: UxROM PRG needs complete 16 KiB banks')
    if len(c.chr) > 16384:
        raise ValueError(f'{c.path.name}: at most 16 KiB of CHR ROM fits the PPU allocation')
