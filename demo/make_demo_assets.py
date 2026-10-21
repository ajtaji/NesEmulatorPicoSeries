"""Build the PureMetal NES demo's graphics and music into demo/demo_assets.nes6502.

    py -3 demo/make_demo_assets.py            # write demo/demo_assets.nes6502 (+ preview PNGs in demo/preview/)
    py -3 demo/make_demo_assets.py --check    # exit 1 if the committed file is not what this tool writes

Everything the demo shows or plays is DATA here and CODE in demo/demo.nes6502: this tool renders and
encodes once, on the PC; the cartridge's PureMetal program copies the tiles into CHR RAM and plays the
song. Nothing here runs on the NES.

  Logo     "PUREMETAL" rendered from Lato Regular (fonts/source/lato, SIL OFL 1.1), thickened, outlined
           and shaded into NES 2-bit tiles: colour 1 outline, 2 body, 3 the light band along the top.
  Font     the demo's own bold 7x7 capitals, drawn in this file - the marquee (background) and the
           sine text (sprites) use it.
  Stars    three small sprite tiles.
  Tables   a 256-entry sine (0..255 around 128), the 2A03's note periods for NTSC (pulse and triangle).
  Song     an original tune: four channels (two pulse, triangle, noise), 16 rows a pattern.
"""
import argparse, math, os, sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
LATO = ROOT / 'fonts/source/lato/Lato-Regular.ttf'
OUT = HERE / 'demo_assets.nes6502'
PREVIEW = HERE / 'preview'

CLOCK = 1789773           # NTSC CPU clock
FONT_CHARS = ' ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.,!-:/\'?'
FONT_BASE = 0xC0          # background tile number of the font's first glyph ("space")


# ---------------------------------------------------------------- tiles
def tile_bytes(px):
    """8x8 of colour numbers 0-3 -> the NES's 16 bytes: 8 bytes of bit 0, then 8 of bit 1."""
    lo, hi = [], []
    for y in range(8):
        b0 = b1 = 0
        for x in range(8):
            c = px[y][x]
            b0 |= (c & 1) << (7 - x)
            b1 |= ((c >> 1) & 1) << (7 - x)
        lo.append(b0); hi.append(b1)
    return lo + hi


def dilate(img, n=1):
    for _ in range(n):
        img = img.filter(ImageFilter.MaxFilter(3))
    return img


def render_logo():
    """The logo as a 256 x 48 picture of colour numbers, then its tiles and nametable."""
    text = 'PUREMETAL'
    size = 38
    font = ImageFont.truetype(str(LATO), size, layout_engine=ImageFont.Layout.BASIC)
    box = font.getbbox(text)
    w, h = box[2] - box[0], box[3] - box[1]
    W, H = 256, 48
    mask = Image.new('L', (W, H), 0)
    ox = (W - w) // 2 - box[0]
    oy = (H - h) // 2 - box[1]
    ImageDraw.Draw(mask).text((ox, oy), text, font=font, fill=255)
    body = dilate(mask.point(lambda v: 255 if v >= 110 else 0), 1)       # bolder
    outline = dilate(body, 1)
    top = min(y for y in range(H) for x in range(W) if body.getpixel((x, y)))
    bot = max(y for y in range(H) for x in range(W) if body.getpixel((x, y)))
    band = top + (bot - top) // 3
    pic = [[0] * W for _ in range(H)]
    for y in range(H):
        for x in range(W):
            if body.getpixel((x, y)):
                pic[y][x] = 3 if y <= band else 2
            elif outline.getpixel((x, y)):
                pic[y][x] = 1
    return pic


def tiles_from_picture(pic, first_tile):
    """Cut into 8x8 tiles, share identical ones; the blank tile is 0. Returns (tiles, map)."""
    H, W = len(pic), len(pic[0])
    tiles = [[[0] * 8 for _ in range(8)]]
    index = {tuple(tuple(r) for r in tiles[0]): 0}
    nt = []
    for ty in range(H // 8):
        row = []
        for tx in range(W // 8):
            t = [pic[ty * 8 + y][tx * 8:tx * 8 + 8] for y in range(8)]
            key = tuple(tuple(r) for r in t)
            if key not in index:
                index[key] = len(tiles)
                tiles.append(t)
            row.append(index[key] - 1 + first_tile if index[key] else 0)   # tile k of the list is CHR tile first_tile+k-1
        nt.append(row)
    return tiles[1:], nt          # tile 0 (blank) is the CHR's tile 0 already


FONT7 = {
    ' ': ['.......'] * 7,
    'A': ['.#####.', '##...##', '##...##', '#######', '##...##', '##...##', '##...##'],
    'B': ['######.', '##...##', '##...##', '######.', '##...##', '##...##', '######.'],
    'C': ['.#####.', '##...##', '##.....', '##.....', '##.....', '##...##', '.#####.'],
    'D': ['#####..', '##..##.', '##...##', '##...##', '##...##', '##..##.', '#####..'],
    'E': ['#######', '##.....', '##.....', '######.', '##.....', '##.....', '#######'],
    'F': ['#######', '##.....', '##.....', '######.', '##.....', '##.....', '##.....'],
    'G': ['.#####.', '##...##', '##.....', '##.####', '##...##', '##...##', '.######'],
    'H': ['##...##', '##...##', '##...##', '#######', '##...##', '##...##', '##...##'],
    'I': ['######.', '..##...', '..##...', '..##...', '..##...', '..##...', '######.'],
    'J': ['...####', '....##.', '....##.', '....##.', '##..##.', '##..##.', '.####..'],
    'K': ['##...##', '##..##.', '##.##..', '####...', '##.##..', '##..##.', '##...##'],
    'L': ['##.....', '##.....', '##.....', '##.....', '##.....', '##.....', '#######'],
    'M': ['##...##', '###.###', '#######', '##.#.##', '##...##', '##...##', '##...##'],
    'N': ['##...##', '###..##', '####.##', '##.####', '##..###', '##...##', '##...##'],
    'O': ['.#####.', '##...##', '##...##', '##...##', '##...##', '##...##', '.#####.'],
    'P': ['######.', '##...##', '##...##', '######.', '##.....', '##.....', '##.....'],
    'Q': ['.#####.', '##...##', '##...##', '##...##', '##.#.##', '##..##.', '.###.##'],
    'R': ['######.', '##...##', '##...##', '######.', '##.##..', '##..##.', '##...##'],
    'S': ['.#####.', '##...##', '##.....', '.#####.', '.....##', '##...##', '.#####.'],
    'T': ['######.', '..##...', '..##...', '..##...', '..##...', '..##...', '..##...'],
    'U': ['##...##', '##...##', '##...##', '##...##', '##...##', '##...##', '.#####.'],
    'V': ['##...##', '##...##', '##...##', '##...##', '.##.##.', '..###..', '...#...'],
    'W': ['##...##', '##...##', '##...##', '##.#.##', '#######', '###.###', '##...##'],
    'X': ['##...##', '.##.##.', '..###..', '..###..', '.##.##.', '##...##', '##...##'],
    'Y': ['##..##.', '##..##.', '##..##.', '.####..', '..##...', '..##...', '..##...'],
    'Z': ['#######', '....##.', '...##..', '..##...', '.##....', '##.....', '#######'],
    '0': ['.#####.', '##..###', '##.####', '####.##', '###..##', '##...##', '.#####.'],
    '1': ['..##...', '.###...', '####...', '..##...', '..##...', '..##...', '######.'],
    '2': ['.#####.', '##...##', '.....##', '...###.', '.###...', '##.....', '#######'],
    '3': ['.#####.', '##...##', '.....##', '..####.', '.....##', '##...##', '.#####.'],
    '4': ['...###.', '..####.', '.##.##.', '##..##.', '#######', '....##.', '....##.'],
    '5': ['#######', '##.....', '######.', '.....##', '.....##', '##...##', '.#####.'],
    '6': ['.#####.', '##.....', '##.....', '######.', '##...##', '##...##', '.#####.'],
    '7': ['#######', '.....##', '....##.', '...##..', '..##...', '..##...', '..##...'],
    '8': ['.#####.', '##...##', '##...##', '.#####.', '##...##', '##...##', '.#####.'],
    '9': ['.#####.', '##...##', '##...##', '.######', '.....##', '.....##', '.#####.'],
    '.': ['.......', '.......', '.......', '.......', '.......', '..##...', '..##...'],
    ',': ['.......', '.......', '.......', '.......', '..##...', '..##...', '.##....'],
    '!': ['..##...', '..##...', '..##...', '..##...', '..##...', '.......', '..##...'],
    '-': ['.......', '.......', '.......', '######.', '.......', '.......', '.......'],
    ':': ['.......', '..##...', '..##...', '.......', '..##...', '..##...', '.......'],
    '/': ['.....##', '....##.', '...##..', '..##...', '.##....', '##.....', '.......'],
    "'": ['..##...', '..##...', '.##....', '.......', '.......', '.......', '.......'],
    '?': ['.#####.', '##...##', '.....##', '...###.', '..##...', '.......', '..##...'],
}


def render_font():
    """The demo's own 7x7 bold capitals, drawn above pixel by pixel (row 7 and column 7 are the
    gap). A TrueType font squeezed into 8x8 blurs M, N and W: NES text is drawn, not rendered."""
    glyphs = []
    for ch in FONT_CHARS:
        rows = FONT7[ch] + ['.......']
        glyphs.append([[3 if (x < 7 and rows[y][x] == '#') else 0 for x in range(8)] for y in range(8)])
    return glyphs


def divider_tiles():
    """Background tile 99: the line between the picture and the marquee - colour 1 on rows 3 and 5,
    colour 2 on row 4. Sprite tile 4: sprite 0, opaque on row 4 only, the pixel the PPU's sprite-0
    hit needs: where it meets the line the program knows the beam has reached the marquee."""
    line = [[0] * 8 for _ in range(8)]
    for x in range(8):
        line[3][x] = 1; line[4][x] = 2; line[5][x] = 1
    s0 = [[0] * 8 for _ in range(8)]
    for x in range(8):
        s0[4][x] = 2
    return line, s0


def star_tiles():
    dot = [[0] * 8 for _ in range(8)]; dot[3][3] = 3
    small = [[0] * 8 for _ in range(8)]
    for x, y in ((3, 3), (4, 3), (3, 4), (4, 4)):
        small[y][x] = 3
    cross = [[0] * 8 for _ in range(8)]
    for d in range(-2, 3):
        cross[3][3 + d] = 2 if abs(d) == 2 else 3
        cross[3 + d][3] = 2 if abs(d) == 2 else 3
    return [dot, small, cross]


# ---------------------------------------------------------------- music
NOTE_NAMES = {'C': 0, 'C#': 1, 'D': 2, 'D#': 3, 'E': 4, 'F': 5, 'F#': 6, 'G': 7, 'G#': 8, 'A': 9, 'A#': 10, 'B': 11}


def note_index(name):
    """'A3' -> index into the period tables (0 = C1)."""
    octave = int(name[-1])
    return (octave - 1) * 12 + NOTE_NAMES[name[:-1]] + 1      # 0 is "no note"


def period_tables():
    plo, phi, tlo, thi = [0], [0], [0], [0]
    for i in range(1, 73):                                   # C1 .. B6
        midi = 24 + (i - 1)                                  # C1 = MIDI 24
        f = 440.0 * 2 ** ((midi - 69) / 12)
        p = max(8, min(0x7FF, round(CLOCK / (16 * f) - 1)))
        t = max(2, min(0x7FF, round(CLOCK / (32 * f) - 1)))
        plo.append(p & 0xFF); phi.append(p >> 8)
        tlo.append(t & 0xFF); thi.append(t >> 8)
    return plo, phi, tlo, thi


def song():
    """Rows of (pulse1, pulse2, triangle, noise): note names, '' for nothing, '-' to stop.
    Noise: 'K' kick, 'S' snare, 'H' hat. Original; A minor, i - VI - III - VII."""
    chords = [('A', ['A3', 'C4', 'E4']), ('F', ['F3', 'A3', 'C4']), ('C', ['C4', 'E4', 'G4']), ('G', ['G3', 'B3', 'D4'])]
    bass = {'A': 'A2', 'F': 'F2', 'C': 'C3', 'G': 'G2'}
    lead_a = ['E5', '', 'A4', '', 'C5', 'E5', 'D5', '', 'C5', '', 'B4', '', 'A4', '', 'G4', '']
    lead_b = ['F5', '', 'C5', '', 'A4', 'C5', 'F5', '', 'E5', '', 'C5', '', 'A4', '', 'C5', '']
    lead_c = ['G5', '', 'E5', '', 'C5', 'E5', 'G5', '', 'A5', '', 'G5', '', 'E5', '', 'C5', '']
    lead_d = ['D5', '', 'B4', '', 'G4', 'B4', 'D5', '', 'G5', '', 'F#5', '', 'D5', '', 'B4', '']
    lead_e = ['A5', 'G5', 'E5', 'G5', 'A5', '', 'C6', '', 'B5', 'A5', 'G5', '', 'E5', '', '', '']
    leads = [lead_a, lead_b, lead_c, lead_d]
    drums_a = ['K', 'H', 'H', 'H', 'S', 'H', 'H', 'H', 'K', 'H', 'K', 'H', 'S', 'H', 'H', 'S']
    drums_b = ['K', 'H', 'H', 'K', 'S', 'H', 'H', 'H', 'K', 'H', 'K', 'H', 'S', 'S', 'S', 'S']
    rows = []

    def pattern(lead, root, notes, drums, arp=True, quiet_lead=False):
        out = []
        for r in range(16):
            p1 = '' if quiet_lead else lead[r]
            p2 = notes[r % 3] if arp and r % 2 == 0 else ''
            tri = bass[root] if r % 4 == 0 else (bass[root][:-1] + str(int(bass[root][-1]) + 1) if r % 4 == 2 else '')
            out.append((p1, p2, tri, drums[r]))
        return out

    # intro: chords + drums, no lead
    for k, (root, notes) in enumerate(chords):
        rows += pattern(leads[k], root, notes, drums_a, quiet_lead=True)
    # main theme twice, the second time with the fill
    for loop in range(2):
        for k, (root, notes) in enumerate(chords):
            lead = leads[k]
            if loop == 1 and k == 3:
                lead = lead_e
            rows += pattern(lead, root, notes, drums_b if k == 3 else drums_a)
    return rows


def encode_song(rows):
    """Four bytes a row: pulse 1, pulse 2, triangle (note index, 0 nothing, 255 stop) and noise
    (0 nothing, 1 kick, 2 snare, 3 hat)."""
    out = []
    for p1, p2, tri, nz in rows:
        for n in (p1, p2, tri):
            out.append(0 if n == '' else 255 if n == '-' else note_index(n))
        out.append({'': 0, 'K': 1, 'S': 2, 'H': 3}[nz])
    return out


# ---------------------------------------------------------------- output
def data_lines(label, values, per=16, kind='a'):
    lines = [label + ':']
    for i in range(0, len(values), per):
        lines.append('  Data.%s %s' % (kind, ','.join(str(v) for v in values[i:i + per])))
    return lines


def text_codes(s):
    return [FONT_BASE + FONT_CHARS.index(c) for c in s.upper()]


def generate(write_previews):
    logo_pic = render_logo()
    logo_tiles, logo_nt = tiles_from_picture(logo_pic, 1)
    font = render_font()
    stars = star_tiles()
    divider, sprite0 = divider_tiles()
    assert 1 + len(logo_tiles) <= 99, 'logo has %d tiles; tile 99 is the divider' % len(logo_tiles)
    plo, phi, tlo, thi = period_tables()
    rows = song()
    sine = [max(0, min(255, round(128 + 127 * math.sin(2 * math.pi * i / 256)))) for i in range(256)]

    if write_previews:
        PREVIEW.mkdir(exist_ok=True)
        pal = [(0, 0, 0), (30, 40, 140), (90, 170, 255), (255, 255, 255)]
        im = Image.new('RGB', (256, 48))
        for y in range(48):
            for x in range(256):
                im.putpixel((x, y), pal[logo_pic[y][x]])
        im.resize((768, 144), Image.NEAREST).save(PREVIEW / 'logo.png')
        im = Image.new('RGB', (8 * len(font), 8))
        for k, g in enumerate(font):
            for y in range(8):
                for x in range(8):
                    im.putpixel((k * 8 + x, y), pal[g[y][x]])
        im.resize((8 * len(font) * 4, 32), Image.NEAREST).save(PREVIEW / 'font.png')

    bg_chr = []
    for t in logo_tiles:
        bg_chr += tile_bytes(t)
    font_chr = []
    for g in font:
        font_chr += tile_bytes(g)
    star_chr = []
    for t in stars:
        star_chr += tile_bytes(t)
    star_chr += tile_bytes(sprite0)          # sprite tile 4
    nt = [v for row in logo_nt for v in row]

    out = ['; GENERATED by demo/make_demo_assets.py - do not edit; run it again.',
           '; Logo rendered from Lato Regular (SIL OFL 1.1, fonts/source/lato). The font and the tune',
           '; are original to this demo.',
           '#LOGO_TILES = %d' % len(logo_tiles),
           '#FONT_BASE = %d' % FONT_BASE,
           '#FONT_GLYPHS = %d' % len(font),
           '#SONG_ROWS = %d' % len(rows),
           '#LOGO_ROWS = %d' % len(logo_nt),
           '#DIVIDER_TILE = 99',
           '#SPRITE0_TILE = 4',
           'DataSection']
    out += data_lines('LogoChr', bg_chr)
    out += data_lines('FontChr', font_chr)
    out += data_lines('StarChr', star_chr)
    out += data_lines('DividerChr', tile_bytes(divider))
    out += data_lines('LogoMap', nt, 32)
    out += data_lines('Sine', sine)
    out += data_lines('PulseLo', plo)
    out += data_lines('PulseHi', phi)
    out += data_lines('TriLo', tlo)
    out += data_lines('TriHi', thi)
    out += data_lines('Song', encode_song(rows))
    scroll = ('      PUREMETAL FORGE PRESENTS A NES DEMO WRITTEN IN PUREMETAL - '
              'NO HAND ASSEMBLY - COMPILED FOR THE 6502 AND RUNNING ON A RASPBERRY PI PICO. '
              'GREETINGS TO EVERYONE AT THE FORUM!      ')
    out += data_lines('ScrollText', text_codes(scroll) + [0])
    out += data_lines('SubText', text_codes('MADE WITH PUREMETAL') + [0])
    out += data_lines('WaveText', text_codes('PUREMETAL NES') + [0])
    out.append('EndDataSection')
    return '\n'.join(out) + '\n'


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--check', action='store_true')
    a = ap.parse_args()
    text = generate(not a.check)
    if a.check:
        have = OUT.read_text(encoding='ascii').replace('\r\n', '\n') if OUT.exists() else ''
        if have != text:
            sys.exit('demo_assets.nes6502 is not what make_demo_assets.py writes: run it')
        print('demo_assets.nes6502 current')
        return
    OUT.write_text(text, encoding='ascii', newline='\n')
    print('wrote', OUT.name, len(text), 'characters')


if __name__ == '__main__':
    main()
