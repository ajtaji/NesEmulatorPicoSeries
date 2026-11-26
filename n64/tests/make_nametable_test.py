r"""make_nametable_test.py - a mapper-4 (MMC3) CHR-RAM test cartridge for the N64 port's shown picture (design note,
N.22, part C): the two physical name tables hold DIFFERENT tiles and attributes ($2000 gets tiles 1-8, $2C00 tiles
8-15 - under either mirroring those are the two tables), the mirroring flips every 128 frames, the scroll moves
3 pixels right and 1 down a frame, so fine X and fine Y pass every value and the scroll crosses both table
boundaries (the horizontal one every 512 / 3 frames, the vertical one every 240), and once a frame, from the MMC3
IRQ near line 100, the scroll changes mid-frame by the $2006 / $2005 / $2005 / $2006 sequence (v set at once) and
then, after a delay, PPUMASK's red emphasis is set in the middle of a line (a split line). 32 sprites move over both
tables: pairs of a behind-background sprite and a front sprite of the next index 4 pixels apart (the priority
quirk), ten on one row (the eight-sprite limit), flips; the sprite size flips every 256 frames, the left-column
clip every 64. One CHR-RAM row (tile 15's) is rewritten every vblank.
    py make_nametable_test.py <out.nes>
Hand-written 6502, assembled by the small two-pass assembler below (make_sprite0_test.py's); no third-party ROM
or code."""
import sys
from pathlib import Path

code = []          # (kind, bytes or label)
def op(*b): code.append(("b", list(b)))
def lab(n): code.append(("l", n))
def br(opc, n): code.append(("r", (opc, n)))
def ab(opc, n): code.append(("a", (opc, n)))

ORG = 0xE000
FR, FRH, SX, SXH, SY, SYT, MIR, MASK = 0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x18, 0x17
# reset
op(0x78); op(0xD8); op(0xA2, 0xFF); op(0x9A)
op(0xA9, 0); op(0x8D, 0, 0x20); op(0x8D, 1, 0x20)
op(0xA9, 0x40); op(0x8D, 0x17, 0x40); op(0xA9, 0); op(0x8D, 0x10, 0x40)            # no APU frame IRQ, no DMC IRQ: the IRQ is the MMC3's
op(0xA2, 0); lab("mm"); op(0x8E, 0, 0x80); ab(0xBD, "chrtab"); op(0x8D, 1, 0x80); op(0xE8); op(0xE0, 8); br(0xD0, "mm")
op(0xA9, 0); op(0x8D, 0, 0xA0); op(0x85, MIR)                       # vertical mirroring first
op(0xA9, 0x80); op(0x8D, 1, 0xA0)
lab("v1"); op(0x2C, 2, 0x20); br(0x10, "v1")
lab("v2"); op(0x2C, 2, 0x20); br(0x10, "v2")
# the tiles into CHR-RAM, both pattern tables ($0000 the background's, $1000 the sprites')
for hi in (0x00, 0x10):
    op(0xA9, hi); op(0x8D, 6, 0x20); op(0xA9, 0); op(0x8D, 6, 0x20)
    op(0xA2, 0); lab(f"ct{hi}"); ab(0xBD, "tiles"); op(0x8D, 7, 0x20); op(0xE8); br(0xD0, f"ct{hi}")
# the palettes
op(0xA9, 0x3F); op(0x8D, 6, 0x20); op(0xA9, 0); op(0x8D, 6, 0x20)
op(0xA2, 0); lab("pl"); ab(0xBD, "pal"); op(0x8D, 7, 0x20); op(0xE8); op(0xE0, 32); br(0xD0, "pl")
# table A at $2000: ((lo + hi) & 7) + 1; table B at $2C00: ((lo >> 2) & 7) + 8 (tiles and attributes alike)
op(0xA9, 0x20); op(0x8D, 6, 0x20); op(0xA9, 0); op(0x8D, 6, 0x20)
op(0xA0, 0); lab("ta_h"); op(0xA2, 0); lab("ta_l")
op(0x84, 0x20); op(0x8A); op(0x18); op(0x65, 0x20); op(0x29, 7); op(0x69, 1); op(0x8D, 7, 0x20)
op(0xE8); br(0xD0, "ta_l"); op(0xC8); op(0xC0, 4); br(0xD0, "ta_h")
op(0xA9, 0x2C); op(0x8D, 6, 0x20); op(0xA9, 0); op(0x8D, 6, 0x20)
op(0xA0, 0); lab("tb_h"); op(0xA2, 0); lab("tb_l")
op(0x8A); op(0x4A); op(0x4A); op(0x29, 7); op(0x18); op(0x69, 8); op(0x8D, 7, 0x20)
op(0xE8); br(0xD0, "tb_l"); op(0xC8); op(0xC0, 4); br(0xD0, "tb_h")
# OAM page: hidden until the first NMI moves the sprites in
op(0xA9, 0xF0); op(0xA2, 0); lab("om"); op(0x9D, 0, 2); op(0xE8); br(0xD0, "om")
op(0xA9, 0); op(0x85, FR); op(0x85, FRH); op(0x85, SX); op(0x85, SXH); op(0x85, SY); op(0x85, SYT)
op(0xA9, 0x1E); op(0x85, MASK)
# the MMC3 IRQ near line 100, then NMI and rendering on
op(0xA9, 100); op(0x8D, 0, 0xC0); op(0x8D, 1, 0xC0); op(0x8D, 1, 0xE0); op(0x58)
op(0xA9, 0x88); op(0x8D, 0, 0x20); op(0xA9, 0x1E); op(0x8D, 1, 0x20)
lab("main"); ab(0x4C, "main")

# NMI: OAM DMA, a CHR-RAM row, the next frame's scroll, mirroring, mask, size, sprites, the IRQ again
lab("nmi")
op(0x48); op(0x8A); op(0x48); op(0x98); op(0x48)
op(0xA9, 2); op(0x8D, 0x14, 0x40)
op(0xA9, 0x00); op(0x8D, 6, 0x20); op(0xA5, FR); op(0x29, 7); op(0x09, 0xF0); op(0x8D, 6, 0x20)
op(0xA5, FR); op(0x8D, 7, 0x20)                                      # tile 15, row frame & 7, plane 0
op(0xE6, FR); br(0xD0, "nohi"); op(0xE6, FRH); lab("nohi")
op(0x18); op(0xA5, SX); op(0x69, 3); op(0x85, SX); op(0xA5, SXH); op(0x69, 0); op(0x29, 1); op(0x85, SXH)
op(0xE6, SY); op(0xA5, SY); op(0xC9, 240); br(0x90, "yok"); op(0xA9, 0); op(0x85, SY)
op(0xA5, SYT); op(0x49, 2); op(0x85, SYT); lab("yok")
op(0xA5, FR); op(0x29, 0x7F); br(0xD0, "nomir"); op(0xA5, MIR); op(0x49, 1); op(0x85, MIR); op(0x8D, 0, 0xA0)
lab("nomir")
op(0xA5, FR); op(0x29, 0x40); br(0xF0, "clip"); op(0xA9, 0x18); br(0xD0, "mask"); lab("clip"); op(0xA9, 0x1E)
lab("mask"); op(0x85, MASK); op(0x8D, 1, 0x20)
op(0xA5, FRH); op(0x29, 1); op(0x0A); op(0x0A); op(0x0A); op(0x0A); op(0x0A)          # 8 x 16 on odd 256 frames
op(0x09, 0x88); op(0x05, SXH); op(0x05, SYT); op(0x8D, 0, 0x20)
op(0x2C, 2, 0x20); op(0xA5, SX); op(0x8D, 5, 0x20); op(0xA5, SY); op(0x8D, 5, 0x20)
op(0xA2, 0); op(0xA0, 0)
lab("sl")
ab(0xB9, "spy"); op(0x18); op(0x65, FR); op(0x9D, 0, 2)
ab(0xB9, "spt"); op(0x9D, 1, 2)
ab(0xB9, "spa"); op(0x9D, 2, 2)
ab(0xB9, "spx"); op(0x38); op(0xE5, FR); op(0x9D, 3, 2)
op(0xE8); op(0xE8); op(0xE8); op(0xE8); op(0xC8); op(0xC0, 32); br(0xD0, "sl")
op(0xA9, 100); op(0x8D, 0, 0xC0); op(0x8D, 1, 0xC0); op(0x8D, 0, 0xE0); op(0x8D, 1, 0xE0)
op(0x68); op(0xA8); op(0x68); op(0xAA); op(0x68); op(0x40)

# IRQ (near line 100): the scroll set at once by $2006 / $2005 / $2005 / $2006, then the red emphasis mid-line
lab("irq")
op(0x48); op(0x8A); op(0x48)
op(0x8D, 0, 0xE0)                                                    # acknowledge, disable
op(0x2C, 2, 0x20)
op(0xA9, 0x28); op(0x8D, 6, 0x20)                                    # table 2, fine Y 2
op(0xA9, 0x2E); op(0x8D, 5, 0x20)
op(0xA5, FR); op(0x0A); op(0x8D, 5, 0x20)                            # X = 2 x frame
op(0xA9, 0xA4); op(0x8D, 6, 0x20)                                    # v = t now
op(0xA2, 14); lab("dly"); op(0xCA); br(0xD0, "dly")
op(0xA5, MASK); op(0x09, 0x20); op(0x8D, 1, 0x20)                    # red emphasis, mid-line
op(0x68); op(0xAA); op(0x68); op(0x40)

lab("chrtab"); op(0, 2, 4, 5, 6, 7, 0, 1)
lab("pal"); op(*[0x0F, 0x16, 0x27, 0x30, 0x0F, 0x1A, 0x2A, 0x3A, 0x0F, 0x11, 0x21, 0x31, 0x0F, 0x14, 0x24, 0x34,
                 0x0F, 0x06, 0x17, 0x28, 0x0F, 0x09, 0x19, 0x29, 0x0F, 0x02, 0x12, 0x22, 0x0F, 0x05, 0x15, 0x25])
tiles = bytearray(256)
for t in range(1, 16):
    for r in range(8):
        if t & 1 and r < 2:
            continue                                                 # odd tiles: two empty rows (the empty test)
        tiles[t * 16 + r] = (t * 37 + r * 29) & 255
        tiles[t * 16 + 8 + r] = (t * 91 + r * 53) & 255 if t & 2 else 0
lab("tiles"); op(*tiles)
spy, spt, spa, spx = [], [], [], []
for k in range(8):                                                   # behind i, front i + 1, 4 pixels apart
    spy += [20 + k * 24, 20 + k * 24]; spt += [1 + k, 9 + k]; spa += [0x20 | (k & 3), (k & 3) | (0x40 if k & 1 else 0)]
    spx += [30 + k * 25, 34 + k * 25]
for k in range(10):                                                  # ten on one row: the eight-sprite limit
    spy += [150]; spt += [3 + k]; spa += [(k & 3) | (0x80 if k & 2 else 0)]; spx += [k * 22]
for k in range(6):
    spy += [60 + k * 30]; spt += [5 + k]; spa += [0x20 if k & 1 else 0]; spx += [200 - k * 33]
lab("spy"); op(*spy); lab("spt"); op(*spt); lab("spa"); op(*spa); lab("spx"); op(*spx)

def size(k, v):
    return {"b": len(v) if k == "b" else 0, "l": 0, "r": 2, "a": 3}[k]
labels, pc = {}, ORG
for k, v in code:
    if k == "l": labels[v] = pc
    pc += size(k, v)
out, pc = bytearray(), ORG
for k, v in code:
    if k == "b": out += bytes(v)
    elif k == "r":
        d = labels[v[1]] - (pc + 2); assert -128 <= d < 128, v; out += bytes([v[0], d & 255])
    elif k == "a": out += bytes([v[0], labels[v[1]] & 255, labels[v[1]] >> 8])
    pc += size(k, v)
assert len(out) <= 0x1FFA, len(out)
prg = bytearray(b"\xEA" * 32768)
prg[0x6000:0x6000 + len(out)] = out
prg[0x7FFA:0x8000] = bytes([labels["nmi"] & 255, labels["nmi"] >> 8, 0, 0xE0, labels["irq"] & 255, labels["irq"] >> 8])
head = b"NES\x1a" + bytes([2, 0, 0x40, 0]) + bytes(8)                # 32 KB PRG, CHR-RAM, mapper 4
Path(sys.argv[1]).write_bytes(head + prg)
print(sys.argv[1], len(head + prg), "bytes; code", len(out), "bytes")
