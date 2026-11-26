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
    py make_nametable_test.py <out.nes> [--scroll]
--scroll builds THE SCROLLING TEST instead (scroll_program below): a side-scrolling picture that rewrites the column
entering at the right edge, under both mirrorings, for about a minute with no input, then a steady plain end screen.
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
def nametable_program():
    """The name-table test (part C), as it was first written: 1,200 frames of the proof."""
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



def scroll_program():
    """THE SCROLLING TEST (--scroll): the right edge of a side-scrolling game, with no input, for about a minute.
    The picture scrolls right without stop and, as a side-scrolling game does, writes each new 8-pixel column of
    tiles (and its 32-pixel attribute column) into the name table just before it enters at the right edge. Four
    stretches: frames 0-1199 horizontal mirroring, 1 pixel a frame (SMB3's case: the column being rewritten is
    the same table's column at the left, under the left 8-pixel clip, and its new tiles show at the right edge);
    1200-2399 vertical mirroring, 2 a frame, and 2400-3299 the same at 3 a frame (the column entering at the right
    is in the horizontal neighbour table, $2400, across the table boundary every 256 pixels); 3300-3599
    horizontal mirroring again, 2 a frame. At each change of stretch rendering is off for four frames while the
    whole visible window is rewritten for the new mirroring, 11 columns a frame (as a game redraws a screen). Fine X passes every value. The MMC3 IRQ near line 200
    sets the horizontal scroll to 0 mid-frame (a fixed strip at the bottom, as a status bar; split lines). Eight
    sprites cross the right edge at 1 pixel a frame and three stand at x 248, 252 and 255. From frame 3600 the
    end screen: rendering off, a plain light-blue backdrop, steady from then on. No button is read."""
    FR, FRH, WX, WXH, NCL, NCH, SPD, MODE, PH = 0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17, 0x18
    THI, H, G, BB, P, TMP, TMP2, ENDF, OFFF, CNT, EL, EH, CB = (0x1A, 0x1B, 0x1C, 0x1D, 0x1E, 0x1F, 0x20, 0x21,
                                                                 0x22, 0x23, 0x24, 0x25, 0x26)
    ACL, ACH, APEND, IMM, WR, REW, Q = 0x27, 0x28, 0x29, 0x2A, 0x2B, 0x2C, 0x2D
    # reset: as the name-table test's, then horizontal mirroring, both tables cleared, the first window written
    op(0x78); op(0xD8); op(0xA2, 0xFF); op(0x9A)
    op(0xA9, 0); op(0x8D, 0, 0x20); op(0x8D, 1, 0x20)
    op(0xA9, 0x40); op(0x8D, 0x17, 0x40); op(0xA9, 0); op(0x8D, 0x10, 0x40)
    op(0xA2, 0); lab("smm"); op(0x8E, 0, 0x80); ab(0xBD, "chrtab"); op(0x8D, 1, 0x80); op(0xE8); op(0xE0, 8); br(0xD0, "smm")
    op(0xA9, 1); op(0x8D, 0, 0xA0)                                       # horizontal mirroring first
    op(0xA9, 0x80); op(0x8D, 1, 0xA0)
    lab("sv1"); op(0x2C, 2, 0x20); br(0x10, "sv1")
    lab("sv2"); op(0x2C, 2, 0x20); br(0x10, "sv2")
    for hi in (0x00, 0x10):
        op(0xA9, hi); op(0x8D, 6, 0x20); op(0xA9, 0); op(0x8D, 6, 0x20)
        op(0xA2, 0); lab(f"sct{hi}"); ab(0xBD, "tiles"); op(0x8D, 7, 0x20); op(0xE8); br(0xD0, f"sct{hi}")
    op(0xA9, 0x3F); op(0x8D, 6, 0x20); op(0xA9, 0); op(0x8D, 6, 0x20)
    op(0xA2, 0); lab("spl"); ab(0xBD, "pal"); op(0x8D, 7, 0x20); op(0xE8); op(0xE0, 32); br(0xD0, "spl")
    op(0xA9, 0x20); op(0x8D, 6, 0x20); op(0xA9, 0); op(0x8D, 6, 0x20)    # $2000-$2FFF cleared: both tables
    op(0xA0, 16); op(0xA9, 0); op(0xA2, 0); lab("scl"); op(0x8D, 7, 0x20); op(0xE8); br(0xD0, "scl"); op(0x88); br(0xD0, "scl")
    op(0xA9, 0xF0); op(0xA2, 0); lab("som"); op(0x9D, 0, 2); op(0xE8); br(0xD0, "som")
    for k, (y, t, a, x) in enumerate(((100, 5, 0, 248), (130, 6, 1, 252), (160, 7, 2, 255))):
        for j, v in enumerate((y, t, a, x)):
            op(0xA9, v); op(0x8D, 32 + 4 * k + j, 2)
    op(0xA9, 0); op(0xA2, 0x10); lab("szp"); op(0x95, 0); op(0xE8); op(0xE0, 0x30); br(0xD0, "szp")
    op(0xA9, 1); op(0x85, SPD)
    op(0xA9, 0x08); op(0x85, CB)                                         # PPUCTRL's base, NMI off in the reset
    op(0xA9, 1); op(0x85, IMM)                                           # attributes at once (rendering off)
    ab(0x20, "wwin")                                                      # columns 0-32, NC = 33
    op(0xA9, 0x88); op(0x85, CB)
    op(0xA9, 0); op(0x85, IMM)                                           # from now on attribute columns wait a frame
    op(0xA9, 199); op(0x8D, 0, 0xC0); op(0x8D, 1, 0xC0); op(0x8D, 1, 0xE0); op(0x58)
    op(0xA9, 0x88); op(0x8D, 0, 0x20); op(0xA9, 0x18); op(0x8D, 1, 0x20)
    lab("smain"); ab(0x4C, "smain")

    # wcol: column NC (16 bits) of the world into its table ($2000 + (NC >> 5 & 1) x $400, column NC & 31), NC + 1.
    # With q = NC >> 5 (the 32-column table's lap): rows 0 .. 1 + ((NC + q) & 7) sky (tile 0), rows 26-29 ground
    # (tiles 9 + ((NC + q) & 3)), every 16th column a post (tile 2), the rest ((NC + 3q + row) >> 1 & 7) + 1 - so a
    # column never holds what the column 32 before it held in the same slot (under horizontal mirroring the new
    # column replaces that one: the rewrite must change what is shown at the right edge). When NC & 3 = 0 its 32-pixel attribute column is due: written at
    # once while the window is rewritten with rendering off (IMM), otherwise in the next NMI that writes no tiles, so
    # that no NMI's PPU writes run past the vertical blank.
    lab("wcol")
    op(0xA5, NCL); op(0x4A); op(0x4A); op(0x4A); op(0x4A); op(0x4A); op(0x29, 1); op(0x0A); op(0x0A); op(0x09, 0x20); op(0x85, THI)
    op(0xA5, CB); op(0x09, 4); op(0x8D, 0, 0x20)                         # increment 32
    op(0x2C, 2, 0x20); op(0xA5, THI); op(0x8D, 6, 0x20); op(0xA5, NCL); op(0x29, 31); op(0x8D, 6, 0x20)
    op(0xA5, NCH); op(0x0A); op(0x0A); op(0x0A); op(0x85, TMP)
    op(0xA5, NCL); op(0x4A); op(0x4A); op(0x4A); op(0x4A); op(0x4A); op(0x05, TMP); op(0x85, Q)   # q = NC >> 5
    op(0xA5, NCL); op(0x18); op(0x65, Q); op(0x29, 7); op(0x18); op(0x69, 2); op(0x85, H)
    op(0xA5, NCL); op(0x18); op(0x65, Q); op(0x29, 3); op(0x18); op(0x69, 9); op(0x85, G)
    op(0xA5, Q); op(0x0A); op(0x18); op(0x65, Q); op(0x18); op(0x65, NCL); op(0x85, BB)
    op(0xA5, NCL); op(0x29, 15); op(0x85, P)
    op(0xA2, 0)
    lab("wrow")
    op(0xE4, H); br(0x90, "wsky")
    op(0xE0, 26); br(0xB0, "wgnd")
    op(0xA5, P); br(0xF0, "wpost")
    op(0x8A); op(0x18); op(0x65, BB); op(0x4A); op(0x29, 7); op(0x18); op(0x69, 1); br(0xD0, "wput")
    lab("wsky"); op(0xA9, 0); br(0xF0, "wput")
    lab("wgnd"); op(0xA5, G); br(0xD0, "wput")
    lab("wpost"); op(0xA9, 2)
    lab("wput"); op(0x8D, 7, 0x20); op(0xE8); op(0xE0, 30); br(0xD0, "wrow")
    op(0xA5, NCL); op(0x29, 3); br(0xD0, "wdone")
    op(0xA5, NCL); op(0x85, ACL); op(0xA5, NCH); op(0x85, ACH); op(0xA9, 1); op(0x85, APEND)
    op(0xA5, IMM); br(0xF0, "wdone"); ab(0x20, "watc")
    lab("wdone")
    op(0xE6, NCL); br(0xD0, "wnc"); op(0xE6, NCH); lab("wnc")
    op(0x60)

    # watc: the attribute column of world column AC (8 bytes, one a 32 x 32 block row): row r gets the palettes
    # ((AC >> 2) + r + (AC >> 5)) & 3 in all four quarters; APEND cleared
    lab("watc")
    op(0xA5, ACH); op(0x0A); op(0x0A); op(0x0A); op(0x85, TMP)
    op(0xA5, ACL); op(0x4A); op(0x4A); op(0x4A); op(0x4A); op(0x4A); op(0x05, TMP); op(0x85, Q)   # AC >> 5
    op(0xA5, ACL); op(0x4A); op(0x4A); op(0x4A); op(0x4A); op(0x4A); op(0x29, 1); op(0x0A); op(0x0A); op(0x09, 0x23); op(0x85, THI)
    op(0xA5, CB); op(0x8D, 0, 0x20)                                      # increment 1
    op(0xA0, 0)
    lab("watt")
    op(0x2C, 2, 0x20); op(0xA5, THI); op(0x8D, 6, 0x20)
    op(0x98); op(0x0A); op(0x0A); op(0x0A); op(0x85, TMP)
    op(0xA5, ACL); op(0x29, 31); op(0x4A); op(0x4A); op(0x05, TMP); op(0x09, 0xC0); op(0x8D, 6, 0x20)
    op(0xA5, ACL); op(0x4A); op(0x4A); op(0x85, TMP2); op(0x98); op(0x18); op(0x65, TMP2); op(0x18); op(0x65, Q)
    op(0x29, 3); op(0xAA); ab(0xBD, "satt"); op(0x8D, 7, 0x20)
    op(0xC8); op(0xC0, 8); br(0xD0, "watt")
    op(0xA9, 0); op(0x85, APEND)
    op(0x60)

    # wwin: the whole visible window - columns WX >> 3 .. + 32 (the reset); wwstart: NC = WX >> 3 only; wwn: CNT
    # columns from NC on
    lab("wwin")
    ab(0x20, "wwstart"); op(0xA9, 33); op(0x85, CNT); ab(0x4C, "wwn")
    lab("wwstart")
    op(0xA5, WXH); op(0x85, NCH); op(0xA5, WX); op(0x85, NCL)
    for _ in range(3):
        op(0x46, NCH); op(0x66, NCL)
    op(0x60)
    lab("wwn"); ab(0x20, "wcol"); op(0xC6, CNT); br(0xD0, "wwn")
    op(0x60)

    # NMI: OAM DMA; the end screen, or a change of stretch, or the scroll moved and the entering column written
    lab("nmi")
    op(0x48); op(0x8A); op(0x48); op(0x98); op(0x48)
    op(0xA9, 2); op(0x8D, 0x14, 0x40)
    op(0xA5, ENDF); br(0xF0, "snotend"); ab(0x4C, "snmx")
    lab("snotend")
    op(0xA5, REW); br(0xF0, "snorew")                                    # rewriting the window: 11 columns a frame
    op(0xA9, 1); op(0x85, IMM); op(0xA9, 11); op(0x85, CNT); ab(0x20, "wwn"); op(0xA9, 0); op(0x85, IMM)
    op(0xC6, REW); br(0xD0, "srewx"); op(0xA9, 1); op(0x85, OFFF)       # the last third: rendering on next frame
    lab("srewx"); ab(0x4C, "sfin")
    lab("snorew")
    op(0xA5, OFFF); br(0xF0, "schk"); op(0xA9, 0); op(0x85, OFFF); op(0xA9, 0x18); op(0x8D, 1, 0x20)
    lab("schk")
    op(0xA6, PH); op(0xA5, FR); ab(0xDD, "phl"); br(0xD0, "snorm"); op(0xA5, FRH); ab(0xDD, "phh"); br(0xD0, "snorm")
    op(0xE6, PH); op(0xA9, 0); op(0x8D, 1, 0x20)                         # a new stretch: rendering off
    op(0xA6, PH); op(0xE0, 4); br(0xD0, "snewph")
    op(0x2C, 2, 0x20); op(0xA9, 0x3F); op(0x8D, 6, 0x20); op(0xA9, 0); op(0x8D, 6, 0x20)   # the end screen
    op(0xA9, 0x21); op(0x8D, 7, 0x20); op(0xA9, 0); op(0x8D, 6, 0x20); op(0x8D, 6, 0x20)
    op(0xA9, 1); op(0x85, ENDF); ab(0x4C, "snmx")
    lab("snewph")
    ab(0xBD, "mtab"); op(0x85, MODE); op(0x49, 1); op(0x8D, 0, 0xA0)   # MMC3: 0 vertical, 1 horizontal
    ab(0xBD, "stab"); op(0x85, SPD)
    ab(0x20, "wwstart"); op(0xA9, 3); op(0x85, REW)                       # three frames with rendering off follow
    ab(0x4C, "sfin")
    lab("snorm")
    op(0x18); op(0xA5, WX); op(0x65, SPD); op(0x85, WX); op(0xA5, WXH); op(0x69, 0); op(0x85, WXH)
    op(0xA9, 0); op(0x85, WR)
    lab("sncheck")                                                       # the column entering: (WX >> 3) + 32
    op(0xA5, WXH); op(0x85, EH); op(0xA5, WX); op(0x85, EL)
    for _ in range(3):
        op(0x46, EH); op(0x66, EL)
    op(0xA5, EL); op(0x18); op(0x69, 32); op(0x85, EL); op(0xA5, EH); op(0x69, 0); op(0x85, EH)
    op(0xA5, EL); op(0x38); op(0xE5, NCL); op(0xA5, EH); op(0xE5, NCH); br(0x90, "sattr")
    ab(0x20, "wcol"); op(0xE6, WR); ab(0x4C, "sncheck")
    lab("sattr")                                                         # no tiles this frame: a waiting attribute column
    op(0xA5, WR); br(0xD0, "sscroll"); op(0xA5, APEND); br(0xF0, "sscroll"); ab(0x20, "watc")
    lab("sscroll")                                                       # the scroll while still in the vertical blank,
    op(0x2C, 2, 0x20); op(0xA5, WXH); op(0x29, 1); op(0x05, CB); op(0x8D, 0, 0x20)   # then the IRQ and the sprites
    op(0xA5, WX); op(0x8D, 5, 0x20); op(0xA9, 0); op(0x8D, 5, 0x20)
    op(0xA9, 199); op(0x8D, 0, 0xC0); op(0x8D, 1, 0xC0); op(0x8D, 0, 0xE0); op(0x8D, 1, 0xE0)
    op(0xA2, 0); op(0xA0, 0)
    lab("ssl")
    op(0x98); op(0x0A); op(0x0A); op(0x0A); op(0x0A); op(0x0A); op(0x18); op(0x65, FR); op(0x9D, 3, 2)
    ab(0xB9, "sspy"); op(0x9D, 0, 2); ab(0xB9, "sspt"); op(0x9D, 1, 2); ab(0xB9, "sspa"); op(0x9D, 2, 2)
    op(0xE8); op(0xE8); op(0xE8); op(0xE8); op(0xC8); op(0xC0, 8); br(0xD0, "ssl")
    ab(0x4C, "sinc")
    lab("sfin")                                                          # a change of stretch: the scroll, no IRQ
    op(0x2C, 2, 0x20); op(0xA5, WXH); op(0x29, 1); op(0x05, CB); op(0x8D, 0, 0x20)
    op(0xA5, WX); op(0x8D, 5, 0x20); op(0xA9, 0); op(0x8D, 5, 0x20)
    lab("sinc")
    op(0xE6, FR); br(0xD0, "snx"); op(0xE6, FRH); lab("snx")
    lab("snmx")
    op(0x68); op(0xA8); op(0x68); op(0xAA); op(0x68); op(0x40)

    # IRQ (near line 200): the horizontal scroll 0 and table 0 from the next line (a fixed strip, mid-line writes)
    lab("irq")
    op(0x48); op(0x8D, 0, 0xE0)
    op(0x2C, 2, 0x20); op(0xA9, 0x88); op(0x8D, 0, 0x20); op(0xA9, 0); op(0x8D, 5, 0x20)
    op(0x68); op(0x40)

    starts = (1200, 2400, 3300, 3600, 0xFFFF)                            # the frame each next stretch starts at
    lab("phl"); op(*[f & 255 for f in starts]); lab("phh"); op(*[f >> 8 for f in starts])
    lab("mtab"); op(0, 1, 1, 0, 0); lab("stab"); op(1, 2, 3, 2, 0)
    lab("satt"); op(0x00, 0x55, 0xAA, 0xFF)
    lab("sspy"); op(*[40 + 20 * k for k in range(8)])
    lab("sspt"); op(*[3 + k for k in range(8)])
    lab("sspa"); op(*[(k & 3) | (0x20 if k & 4 else 0) | (0x40 if k & 2 else 0) for k in range(8)])


SCROLL = "--scroll" in sys.argv[2:]
scroll_program() if SCROLL else nametable_program()

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
