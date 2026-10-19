"""Bounded Pico cartridge layouts. No guest CPU/video/audio adaptations."""
from dataclasses import replace
from pathlib import Path
from anvil_cartridge import read_anvil_rom
from rom_catalog import prg_views

COMMON={0,2,3,7,11,34,41,66,71,79,144,148,232}
ADVANCED={1,4,5,13,47,118,119,206}
ENDS={'rp2040':0xFF000,'rp2350':0x1FF000}

def _read_pico_rom(path,target='rp2040'):
    if target not in ENDS: raise ValueError('choose rp2040 or rp2350')
    cart,header=read_anvil_rom(path)
    allowed=COMMON | (ADVANCED if target=='rp2350' else set())
    if cart.mapper not in allowed:
        raise ValueError(f'{path.name}: mapper {cart.mapper} is unavailable on {target}; supported: {sorted(allowed)}')
    if header[6]&8: raise ValueError('Pico four-screen boards are not supported')
    if cart.mapper==34 and not cart.chr and (header[7]&12)!=8:
        cart=replace(cart,ram_size=0)
    if cart.ram_size and cart.mapper not in ADVANCED and not (cart.mapper==34 and cart.chr):
        raise ValueError('this Pico discrete board has no PRG RAM')
    if cart.mapper==34 and cart.chr:
        # NINA-001 register writes also hit cartridge RAM; RP2040 cannot fit it.
        if target=='rp2040':
            raise ValueError('NINA-001 PRG RAM requires the RP2350 build; BNROM CHR-RAM boards work on both')
    if cart.mapper==34 and cart.chr and (len(cart.prg)>65536 or len(cart.chr)>65536):
        raise ValueError('NINA-001 supports at most 64 KiB PRG and 64 KiB CHR')
    if cart.mapper==47 and len(cart.prg)>262144:
        raise ValueError('mapper 47 supports at most 256 KiB PRG')
    if cart.mapper==144 and len(cart.chr)>131072:
        raise ValueError('mapper 144 supports at most 128 KiB CHR')
    if cart.mapper==232 and len(cart.prg)!=262144:
        raise ValueError('BF9096 requires 256 KiB PRG')
    if cart.mapper==41 and (len(cart.prg)>262144 or len(cart.chr)>131072):
        raise ValueError('Caltron cartridge exceeds addressable banks')
    if cart.mapper==144: cart=replace(cart,conflicts=True)
    if cart.mapper==148: cart=replace(cart,conflicts=True)
    return cart

def pico_prg(cart):
    """Immutable 32 KiB windows for the original RP2040 flat fetch engine."""
    if cart.mapper==71:
        return b''.join(cart.prg[n:n+16384]+cart.prg[-16384:] for n in range(0,len(cart.prg),16384))
    if cart.mapper==232:
        return b''.join(cart.prg[(outer*4+inner)*16384:(outer*4+inner+1)*16384]+
                        cart.prg[(outer*4+3)*16384:(outer*4+4)*16384]
                        for outer in range(4) for inner in range(4))
    return prg_views(cart)

def decode_chr(raw):
    """Exactly PpuDecode's row representation, computed at upload time."""
    result=bytearray(len(raw))
    for tile in range(0,len(raw),16):
        for y in range(8):
            lo,hi=raw[tile+y],raw[tile+y+8]
            bits=sum((((lo>>(7-x))&1)|(((hi>>(7-x))&1)<<1))<<(x*2) for x in range(8))
            result[tile+y*2:tile+y*2+2]=bits.to_bytes(2,'little')
    return bytes(result)

def stored_chr(cart):
    return cart.chr+(decode_chr(cart.chr) if cart.mapper not in (0,2,66) else b'')


def read_pico_rom(path,target='rp2040'):
    path=Path(path)
    try:
        return _read_pico_rom(path,target)
    except ValueError as error:
        message=str(error).replace('Anvil mapper','Pico mapper')
        if not message.startswith(path.name+':'): message=path.name+': '+message
        raise ValueError(message) from None
