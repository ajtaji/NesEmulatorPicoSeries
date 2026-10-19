"""Anvil cartridge metadata and bounded embedded diagnostic images.

Independent of the Pico loader. CRC corrections identify cartridge hardware;
there are no game-specific emulation or timing settings.
"""
import csv
from pathlib import Path
import zlib
from rom_catalog import Cartridge
import hashlib

ROOT = Path(__file__).resolve().parents[1]
EXTRA = {6,9,13,34,41,47,64,68,69,71,79,105,118,119,144,148,158,206,228,232,234}
SUPPORTED = {0,1,2,3,4,5,7,11,66} | EXTRA

def corrections():
    with (ROOT/'anvil/rom_metadata.csv').open(newline='') as f:
        return {int(r['crc32'],16):int(r['mapper']) for r in csv.DictReader(f)}

def read_anvil_rom(path, extra=frozenset(), pal_ok=False):
    """extra: mappers a caller runs beyond Anvil's own (the Pico profile's VRC6), checked like the rest.
    pal_ok: the caller runs PAL timing (the Pico profile); Anvil itself is NTSC-only."""
    data=path.read_bytes()
    if len(data)<16 or data[:4]!=b'NES\x1a':
        raise ValueError('invalid iNES header')
    h=bytearray(data[:16]); nes2=(h[7]&12)==8
    if h[6]&4 or (nes2 and h[9]):
        raise ValueError('trainers and extended size encodings are unsupported')
    p=h[4]*16384; c=h[5]*8192
    if not p or p>4194304 or c>1048576 or len(data)<16+p+c:
        raise ValueError('truncated or oversized cartridge')
    mapper=(h[6]>>4)|(h[7]&240)
    if nes2:
        mapper|=(h[8]&15)<<8
    else:
        mapper=corrections().get(zlib.crc32(data[16:16+p+c]), mapper if not any(h[12:16]) else h[6]>>4)
        if any(h[12:16]): h[8:16]=bytes(8)
    sub=h[8]>>4 if nes2 else 0
    if mapper not in SUPPORTED | set(extra):
        raise ValueError(f'unsupported Anvil mapper {mapper}')
    if (h[7]&3) or ((h[6]&8) and mapper not in (4,206)):
        raise ValueError('unsupported console or four-screen board')
    if nes2 and (h[12]&3)==3:
        raise ValueError('Dendy timing is unsupported')
    if not pal_ok and ((nes2 and (h[12]&3)==1) or (not nes2 and h[9]&1)):
        raise ValueError('PAL timing is unsupported')
    if (p&(p-1) and mapper!=228) or (c and c&(c-1)):
        raise ValueError('non-power-of-two cartridge banks')
    limits={0:(32768,8192),1:(262144,131072),2:(524288,0),3:(32768,32768),
            4:(524288,262144),5:(1048576,1048576),7:(262144,0),11:(131072,131072),
            66:(131072,16384),9:(131072,131072),13:(32768,0),68:(131072,262144),
            71:(262144,0),79:(65536,65536),105:(262144,0),118:(524288,131072),
            119:(524288,65536),148:(65536,65536),158:(524288,131072),206:(131072,65536),
            228:(4194304,1048576),232:(262144,0),234:(524288,524288)}
    pm,cm=limits.get(mapper,(524288,262144))
    if p>pm or c>cm: raise ValueError('unsupported cartridge board size')
    if mapper in (3,5,11,66) and not c: raise ValueError('cartridge requires CHR ROM')
    if mapper==66 and p%32768: raise ValueError('GxROM PRG must contain full 32 KiB banks')
    allowed={6:set(range(8)),3:{0,1,2},7:{0,1,2},11:{0,1,2},34:{0,1,2},71:{0,1},232:{0,1}}
    if sub not in allowed.get(mapper,{0}): raise ValueError('unsupported cartridge submapper')
    if mapper==34 and ((sub==1 and not c) or (sub==2 and c)):
        raise ValueError('BNROM/NINA submapper mismatch')
    ram=0
    if nes2:
        ram=sum(64<<n for n in (h[10]&15,h[10]>>4) if n)
        cr=sum(64<<n for n in (h[11]&15,h[11]>>4) if n)
        if h[11]>>4 or cr>({6:32768,13:16384}.get(mapper,8192)):
            raise ValueError('unsupported CHR RAM geometry')
        if mapper==5 and cr: raise ValueError('MMC5 CHR RAM is unsupported')
    elif mapper in (1,4,5,6,9,34,47,68,69,105,118,119):
        ram=(h[8] or (8 if mapper==5 else 1))*8192
    cap={5:131072,69:32768}.get(mapper,8192)
    if ram>cap or (ram and (ram<8192 or ram&(ram-1))):
        raise ValueError('unsupported PRG RAM geometry')
    prg=data[16:16+p]; chrdata=data[16+p:16+p+c]
    if p==16384: prg*=2
    conflicts=(mapper in (2,3,66) and sub!=1) or (mapper in (7,11) and sub==2) or (mapper==34 and not c)
    cart=Cartridge(path,path.stem,mapper,sub,h[6]&1,bool(h[6]&2),conflicts,ram,
                   prg,chrdata,b'',hashlib.sha256(data).hexdigest())
    return cart,h
