r"""make_cpu_fix_test.py - a mapper-4 test cartridge for two fixes of the shared 6502 core: DEC absolute
($CE) takes 6 cycles, and the polling / countdown shortcuts read their own code through the PRG bank
mapped at PC rather than from the start of PRG.

    py make_cpu_fix_test.py <out.nes> [all|bne6|beq7|beq4|bne3]

What it runs (results in guest RAM, read from a dump of the emulator's guest RAM at the run's end):
  $0300-$0307  DEC abs against INC abs: the passes of a 38-cycle loop (four DEC $0400 or four INC $0400,
               INC / BNE on a 16-bit counter, LDA / BEQ on the NMI flag) that fit between two NMIs, two
               samples each, low byte first: DEC, INC, DEC, INC. Both opcodes are documented at 6 cycles,
               so the DEC and INC counts must agree (within one pass, the NMI's phase); with DEC charged
               3 cycles its loop is 26 cycles and runs about 45 % more passes.
  $0308-$0309  X, Y after a NEGATIVE BNE -6: the mapped bank holds LDA $2002 / INY / BNE (not a poll
               shape), the start of PRG at the same offset holds LDA $2002 / INX / BNE (the shape). X = 5
               and Y = 1 on entry; the loop only counts Y up, so X must still be 5. A shortcut that reads
               the start of PRG batches the loop as INX and changes X.
  $030A-$030B  X, Y after a NEGATIVE BNE -3: mapped INY / BNE, unmapped DEX / BNE; X = 200, Y = 1 on
               entry; X must still be 200.
  $030F        $A5 when everything ran.
The POSITIVE shapes (LDA $2002 / INX / BNE -6, LDA $2002 / AND #$40 / BEQ -7 on sprite 0's hit,
LDA zp / BEQ -4 on the NMI flag, DEX / BNE -3) sit in the mapped bank, with NOPs at the same offsets
at the start of PRG, so only a shortcut that reads the mapped bytes batches them: the emulator's
NesIdleBatched (instructions run by the shortcuts) is above zero only then. The second argument keeps
one positive shape (for attributing the count) or all four.
Hand-written 6502, assembled by the small two-pass assembler below; no third-party ROM or code."""
import sys
from pathlib import Path

ONLY = sys.argv[2] if len(sys.argv) > 2 else "all"
assert ONLY in ("all", "bne6", "beq7", "beq4", "bne3"), ONLY


class Asm:
    def __init__(self, org):
        self.org, self.code = org, []
    def op(self, *b): self.code.append(("b", list(b)))
    def lab(self, n): self.code.append(("l", n))
    def br(self, opc, n): self.code.append(("r", (opc, n)))
    def ab(self, opc, n): self.code.append(("a", (opc, n)))
    def build(self, labels):
        size = lambda k, v: {"b": len(v) if k == "b" else 0, "l": 0, "r": 2, "a": 3}[k]
        pc = self.org
        for k, v in self.code:
            if k == "l": labels[v] = pc
            pc += size(k, v)
        return size
    def emit(self, labels, size):
        out, pc = bytearray(), self.org
        for k, v in self.code:
            if k == "b": out += bytes(v)
            elif k == "r":
                d = labels[v[1]] - (pc + 2); assert -128 <= d < 128, v; out += bytes([v[0], d & 255])
            elif k == "a": out += bytes([v[0], labels[v[1]] & 255, labels[v[1]] >> 8])
            pc += size(k, v)
        return out


# --- bank 2, mapped at $8000 (R6 = 2): the shapes; bank 0 holds other bytes at the same offsets ---
sh = Asm(0x8000)
unmapped = {}          # offset in the bank -> the bytes the start of PRG holds there
def at(offset, n):     # place the next code at $8000 + offset
    while sum(len(v) if k == "b" else (2 if k == "r" else 3 if k == "a" else 0) for k, v in sh.code) < offset:
        sh.op(0xEA)
    sh.lab(n)
# positive BNE -6: X = 1, then LDA $2002 / INX / BNE until X wraps
at(0x100, "pos6"); sh.op(0xA2, 1); sh.lab("p6"); sh.op(0xAD, 2, 0x20); sh.op(0xE8); sh.br(0xD0, "p6"); sh.op(0x60)
# positive BEQ -7: wait for sprite 0's flag to clear (BIT / BVS, not a shape), then the poll
at(0x140, "pos7"); sh.lab("p7c"); sh.op(0x2C, 2, 0x20); sh.br(0x70, "p7c"); sh.op(0xA9, 0)
sh.lab("p7"); sh.op(0xAD, 2, 0x20); sh.op(0x29, 0x40); sh.br(0xF0, "p7"); sh.op(0x60)
# positive BEQ -4: clear the NMI flag, then LDA $40 / BEQ until the NMI sets it
at(0x180, "pos4"); sh.op(0xA9, 0); sh.op(0x85, 0x40); sh.lab("p4"); sh.op(0xA5, 0x40); sh.br(0xF0, "p4"); sh.op(0x60)
# positive BNE -3: X = 200, DEX / BNE
at(0x1C0, "pos3"); sh.op(0xA2, 200); sh.lab("p3"); sh.op(0xCA); sh.br(0xD0, "p3"); sh.op(0x60)
# negative BNE -6: mapped LDA $2002 / INY / BNE; the start of PRG: LDA $2002 / INX / BNE
at(0x200, "neg6"); sh.op(0xA2, 5); sh.op(0xA0, 1); sh.lab("n6"); sh.op(0xAD, 2, 0x20); sh.op(0xC8); sh.br(0xD0, "n6"); sh.op(0x60)
unmapped[0x204] = [0xAD, 2, 0x20, 0xE8, 0xD0, 0xFA]
# negative BNE -3: mapped INY / BNE; the start of PRG: DEX / BNE
at(0x240, "neg3"); sh.op(0xA2, 200); sh.op(0xA0, 1); sh.lab("n3"); sh.op(0xC8); sh.br(0xD0, "n3"); sh.op(0x60)
unmapped[0x244] = [0xCA, 0xD0, 0xFD]

# --- bank 7, fixed at $E000: reset, the measurements, NMI ---
m = Asm(0xE000)
op, lab, br, ab = m.op, m.lab, m.br, m.ab
op(0x78); op(0xD8); op(0xA2, 0xFF); op(0x9A)
op(0xA9, 0); op(0x8D, 0, 0x20); op(0x8D, 1, 0x20)
op(0xA2, 0); lab("mm"); op(0x8E, 0, 0x80); ab(0xBD, "banks"); op(0x8D, 1, 0x80); op(0xE8); op(0xE0, 8); br(0xD0, "mm")
op(0xA9, 0); op(0x8D, 0, 0xA0)                                  # vertical mirroring
lab("v1"); op(0x2C, 2, 0x20); br(0x10, "v1")
lab("v2"); op(0x2C, 2, 0x20); br(0x10, "v2")
op(0xA9, 0x3F); op(0x8D, 6, 0x20); op(0xA9, 0); op(0x8D, 6, 0x20)
op(0xA2, 0); lab("pl"); ab(0xBD, "pal"); op(0x8D, 7, 0x20); op(0xE8); op(0xE0, 32); br(0xD0, "pl")
op(0xA9, 0x20); op(0x8D, 6, 0x20); op(0xA9, 0); op(0x8D, 6, 0x20)
op(0xA0, 8); op(0xA2, 0); op(0xA9, 1)                            # both name tables: tile 1 (opaque)
lab("nt"); op(0x8D, 7, 0x20); op(0xE8); br(0xD0, "nt"); op(0x88); br(0xD0, "nt")
op(0xA9, 0xF0); op(0xA2, 0); lab("om"); op(0x9D, 0, 2); op(0xE8); br(0xD0, "om")
op(0xA9, 100); op(0x8D, 0, 2); op(0xA9, 1); op(0x8D, 1, 2); op(0xA9, 0); op(0x8D, 2, 2); op(0xA9, 100); op(0x8D, 3, 2)
op(0xA9, 0); op(0x8D, 3, 0x20); op(0xA9, 2); op(0x8D, 0x14, 0x40)  # OAM DMA once
op(0xA9, 0); op(0x8D, 5, 0x20); op(0x8D, 5, 0x20)
op(0xA9, 0); op(0x85, 0x40)
op(0xA9, 0x80); op(0x8D, 0, 0x20); op(0xA9, 0x1E); op(0x8D, 1, 0x20)
def wait_nmi():                                                 # LDA / NOP / BEQ: not a shape (-5)
    n = f"w{len(m.code)}"
    op(0xA9, 0); op(0x85, 0x40); lab(n); op(0xA5, 0x40); op(0xEA); br(0xF0, n)
def timing(rmw, dst):                                           # passes of the 38-cycle loop in one frame
    wait_nmi(); op(0xA9, 0); op(0x85, 0x40); op(0x85, 0x30); op(0x85, 0x31)
    n = f"t{len(m.code)}"
    lab(n)
    for _ in range(4): op(rmw, 0x00, 0x04)
    op(0xE6, 0x30); br(0xD0, n + "s"); op(0xE6, 0x31); lab(n + "s")
    op(0xA5, 0x40); br(0xF0, n)
    op(0xA5, 0x30); op(0x8D, dst, 3); op(0xA5, 0x31); op(0x8D, dst + 1, 3)
timing(0xCE, 0); timing(0xEE, 2); timing(0xCE, 4); timing(0xEE, 6)
op(0xA9, 30); op(0x85, 0x41)                                    # 30 rounds of the positive shapes
lab("round")
for name in ("bne6", "beq7", "beq4", "bne3"):
    if ONLY in ("all", name):
        ab(0x20, {"bne6": "pos6", "beq7": "pos7", "beq4": "pos4", "bne3": "pos3"}[name])
wait_nmi()
op(0xC6, 0x41); br(0xD0, "round")
ab(0x20, "neg6"); op(0x8E, 8, 3); op(0x8C, 9, 3)
ab(0x20, "neg3"); op(0x8E, 0x0A, 3); op(0x8C, 0x0B, 3)
op(0xA9, 0xA5); op(0x8D, 0x0F, 3)
lab("end"); op(0xE6, 0x50); ab(0x4C, "end")                     # a JMP that is not to itself
lab("nmi"); op(0xE6, 0x40); op(0x40)
lab("banks"); op(0, 2, 4, 5, 6, 7, 2, 1)                        # R0-R5 CHR, R6 = 2 ($8000), R7 = 1 ($A000)
lab("pal"); op(*[0x0F, 0x16, 0x27, 0x30] * 8)

labels = {}
sizes = [a.build(labels) for a in (sh, m)]
shapes, main = sh.emit(labels, sizes[0]), m.emit(labels, sizes[1])
prg = bytearray(b"\xEA" * 65536)                                # eight 8 KB banks, NOP-filled
prg[2 * 8192:2 * 8192 + len(shapes)] = shapes
for offset, data in unmapped.items():                           # bank 0: the start of PRG
    prg[offset:offset + len(data)] = bytes(data)
prg[7 * 8192:7 * 8192 + len(main)] = main
prg[0xFFFA:0x10000] = bytes([labels["nmi"] & 255, labels["nmi"] >> 8, 0, 0xE0, 0, 0xE0])
tiles = bytearray(8192)
for half in (0, 0x1000):
    for r in range(8):
        tiles[half + 16 + r] = 0xFF                             # tile 1: every pixel opaque (colour 1)
head = b"NES\x1a" + bytes([4, 1, 0x40, 0]) + bytes(8)
Path(sys.argv[1]).write_bytes(head + prg + tiles)
print(sys.argv[1], len(head + prg + tiles), "bytes; shapes", len(shapes), "main", len(main), "bytes;", ONLY)
