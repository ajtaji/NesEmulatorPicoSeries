r"""make_sprite0_test.py - a mapper-4 test cartridge that raises the sprite-0 hit at a different place every
frame, for the PPU checking build (design note, N3): sprite 0's X sweeps 3 pixels a frame, fine X
scroll cycles 0-15, its flips cycle every 8 frames, the left-column clip toggles every 16 and the
sprite size every 32. The main loop polls $2002 bit 6 (clear, then set), so the PPU is caught up
dot by dot around the hit. The N64 port's PPU checking build (build.py --ppu-check) runs it
and compares the state machine's sprite-0 flag with the renderer's at every draw.
    py make_sprite0_test.py <out.nes>
Hand-written 6502, assembled by the small two-pass assembler below; no third-party ROM or code."""
import sys
from pathlib import Path

OPS = {"sei": [0x78], "cld": [0xD8], "txs": [0x9A], "inx": [0xE8], "iny": [0xC8], "dey": [0x88], "txa": [0x8A],
       "pha": [0x48], "pla": [0x68], "rti": [0x40], "tax": [0xAA]}
code = []          # (kind, bytes or label)
def op(*b): code.append(("b", list(b)))
def lab(n): code.append(("l", n))
def br(opc, n): code.append(("r", (opc, n)))
def ab(opc, n): code.append(("a", (opc, n)))

ORG = 0xE000
# reset
op(0x78); op(0xD8); op(0xA2, 0xFF); op(0x9A)
op(0xA9, 0); op(0x8D, 0, 0x20); op(0x8D, 1, 0x20)
op(0xA2, 0); lab("mm"); op(0x8E, 0, 0x80); ab(0xBD, "chrtab"); op(0x8D, 1, 0x80); op(0xE8); op(0xE0, 6); br(0xD0, "mm")
op(0xA9, 0); op(0x8D, 0, 0xA0)                        # vertical mirroring
lab("v1"); op(0x2C, 2, 0x20); br(0x10, "v1")
lab("v2"); op(0x2C, 2, 0x20); br(0x10, "v2")
op(0xA9, 0x3F); op(0x8D, 6, 0x20); op(0xA9, 0); op(0x8D, 6, 0x20)
op(0xA2, 0); lab("pl"); ab(0xBD, "pal"); op(0x8D, 7, 0x20); op(0xE8); op(0xE0, 32); br(0xD0, "pl")
op(0xA9, 0x20); op(0x8D, 6, 0x20); op(0xA9, 0); op(0x8D, 6, 0x20)
op(0xA0, 8); op(0xA2, 0)                               # 8 pages: both name tables
lab("nt"); op(0x8A); op(0x29, 3); op(0x8D, 7, 0x20); op(0xE8); br(0xD0, "nt"); op(0x88); br(0xD0, "nt")
op(0xA9, 0xF0); op(0xA2, 0); lab("om"); op(0x9D, 0, 2); op(0xE8); br(0xD0, "om")
op(0xA9, 100); op(0x8D, 0, 2); op(0xA9, 1); op(0x8D, 1, 2); op(0xA9, 0); op(0x8D, 2, 2); op(0x8D, 3, 2)
op(0xA9, 0); op(0x85, 0x10); op(0x85, 0x11)
op(0xA9, 0x80); op(0x8D, 0, 0x20); op(0xA9, 0x1E); op(0x8D, 1, 0x20)
lab("main")
lab("w0"); op(0x2C, 2, 0x20); br(0x70, "w0")          # wait while the flag is up (BVS)
lab("w1"); op(0x2C, 2, 0x20); br(0x50, "w1")          # wait for the hit (BVC)
op(0xE6, 0x11)                                         # hits seen
ab(0x4C, "main")
# NMI: OAM DMA, then sprite 0 and the scroll for the next frame
lab("nmi")
op(0x48); op(0xA9, 2); op(0x8D, 0x14, 0x40)
op(0xE6, 0x10); op(0xA5, 0x10)
op(0x0A); op(0x18); op(0x65, 0x10); op(0x8D, 3, 2)     # X = 3 * frame
op(0xA5, 0x10); op(0x0A); op(0x0A); op(0x0A); op(0x29, 0xC0); op(0x8D, 2, 2)   # flips: frame bits 3-4
op(0xA5, 0x10); op(0x29, 0x10); br(0xF0, "noclip"); op(0xA9, 0x18); br(0xD0, "mask")
lab("noclip"); op(0xA9, 0x1E)
lab("mask"); op(0x8D, 1, 0x20)
op(0xA5, 0x10); op(0x29, 0x20); op(0x09, 0x80); op(0x8D, 0, 0x20)  # sprite size: frame bit 5
op(0xA5, 0x10); op(0x29, 0x0F); op(0x8D, 5, 0x20); op(0xA9, 0); op(0x8D, 5, 0x20)
op(0x68); op(0x40)
lab("chrtab"); op(0, 2, 4, 5, 6, 7)
lab("pal"); op(*[0x0F, 0x16, 0x27, 0x30, 0x0F, 0x1A, 0x2A, 0x3A, 0x0F, 0x11, 0x21, 0x31, 0x0F, 0x14, 0x24, 0x34] * 2)

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
prg = bytearray(b"\xEA" * 32768)
prg[0x6000:0x6000 + len(out)] = out
prg[0x7FFA:0x8000] = bytes([labels["nmi"] & 255, labels["nmi"] >> 8, 0, 0xE0, 0, 0xE0])
tiles = bytearray(8192)
pats = {1: ([0xF0, 0x0F, 0xCC, 0x33, 0xAA, 0x55, 0xFF, 0x18], [0] * 8),
        2: ([0] * 8, [0x80 >> r for r in range(8)]),
        3: ([0xFF] * 8, [0x3C] * 8)}
for half in (0, 0x1000):
    for t, (p0, p1) in pats.items():
        for r in range(8):
            tiles[half + t * 16 + r] = p0[r]; tiles[half + t * 16 + 8 + r] = p1[r]
head = b"NES\x1a" + bytes([2, 1, 0x40, 0]) + bytes(8)
Path(sys.argv[1]).write_bytes(head + prg + tiles)
print(sys.argv[1], len(head + prg + tiles), "bytes; code", len(out), "bytes")
