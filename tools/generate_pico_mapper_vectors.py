"""Generate deterministic bank markers for on-board mapper diagnostics (no game ROMs)."""
from pathlib import Path
from pico_cartridge import decode_chr
ROOT=Path(__file__).resolve().parents[1]

def main():
    raw=b''.join(bytes([n])*1024 for n in range(32))
    prg=b''.join(bytes([n])*8192 for n in range(8))
    # The decoded CHR is its own file: the Pico W's diagnostic includes it, the RP2350's computes it into
    # RAM from MapperChr (mappers.picow MapperDecodeChr) - 32 KB that keeps that image below the ROM store.
    for name,blocks in [('mapper_vectors.pico',[('MapperPrg',prg),('MapperChr',raw)]),
                        ('mapper_vectors_decoded.pico',[('MapperDecoded',decode_chr(raw))])]:
        result='DataSection\n'
        for label,blob in blocks:
            result+=label+':\n'
            for n in range(0,len(blob),32):
                result+='  Data.a '+','.join(map(str,blob[n:n+32]))+'\n'
        result+='EndDataSection\n'
        (ROOT/'rp2040/Diagnostics'/name).write_text(result)

if __name__=='__main__': main()
