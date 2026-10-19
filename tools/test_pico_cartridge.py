"""Host cartridge tests. Run python -m unittest discover -s tools -p test_pico_cartridge.py."""
import struct, tempfile, unittest, zlib
from pathlib import Path
from unittest.mock import patch
from pico_cartridge import read_pico_rom, pico_pal, pico_prg, decode_chr, ENDS
from dataclasses import replace
from rom_loader import layout, load_store, DATA

class CartridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/'fixture.nes'
    def tearDown(self): self.temp.cleanup()
    def rom(self,mapper,prg=2,chr=1,ram=0,sub=0):
        h=bytearray(b'NES\x1a'+bytes(12));h[4]=prg;h[5]=chr
        h[6]=(mapper&15)<<4;h[7]=(mapper&240)|8;h[8]=sub<<4;h[10]=ram
        self.path.write_bytes(h+bytes(prg*16384)+bytes(chr*8192))
        return self.path
    def test_decoded_planes(self):
        raw=bytearray()
        for lo in range(256):
            for hi in range(256):raw.extend(bytes([lo])*8+bytes([hi])*8)
        decoded=decode_chr(raw)
        for lo in range(256):
            for hi in range(256):
                word=int.from_bytes(decoded[(lo*256+hi)*16:(lo*256+hi)*16+2],'little')
                for x in range(8):
                    self.assertEqual((word>>(x*2))&3,((lo>>(7-x))&1)|(((hi>>(7-x))&1)<<1))
    def test_layout(self):
        p=self.rom(3,chr=4)
        games,d,blobs=layout([p])
        self.assertEqual(struct.unpack_from('<H',d,4)[0],2)
        self.assertEqual(zlib.crc32(d[16:]),struct.unpack_from('<I',d,8)[0])
        self.assertTrue(d[51]&2)
        self.assertEqual(len(blobs[1][1]),65536)
        self.assertTrue(all(DATA<=a and a+len(b)<=ENDS['rp2040'] for a,b in blobs))
    def test_pal(self):
        # The NES 2.0 TV-system field or a PAL-only region tag marks PAL (flag bit 6); shared tags stay NTSC;
        # Dendy is refused.
        p=self.rom(2,chr=0); self.assertFalse(pico_pal(p))
        h=bytearray(p.read_bytes()); h[12]=1; p.write_bytes(h); self.assertTrue(pico_pal(p))
        self.assertEqual(layout([p],'rp2350')[1][16+35]&64,64)
        h[12]=3; p.write_bytes(h)
        with self.assertRaisesRegex(ValueError,'Dendy'): read_pico_rom(p,'rp2350')
        h[12]=0; data=bytes(h)
        for name,pal in (('Game (E).nes',True),('Game (Europe).nes',True),('Game (E) [!].nes',True),('Game (A).nes',True),
                         ('Game (U).nes',False),('Game (UE).nes',False),('Game (USA, Europe).nes',False),('Game (J).nes',False)):
            q=Path(self.temp.name)/name; q.write_bytes(data)
            self.assertEqual(pico_pal(q),pal,name)
            self.assertEqual(layout([q],'rp2350')[1][16+35]>>6&1,int(pal),name)
    def test_prg_views(self):
        c=read_pico_rom(self.rom(71,prg=16,chr=0))
        c=replace(c,prg=b''.join(bytes([n])*16384 for n in range(16)))
        blob=pico_prg(c)
        for n in range(16):
            self.assertEqual(blob[n*32768:n*32768+16384],bytes([n])*16384)
            self.assertEqual(blob[n*32768+16384:(n+1)*32768],bytes([15])*16384)
        c=replace(c,mapper=232);blob=pico_prg(c)
        for outer in range(4):
            for inner in range(4):
                at=(outer*4+inner)*32768
                self.assertEqual(blob[at:at+16384],bytes([outer*4+inner])*16384)
                self.assertEqual(blob[at+16384:at+32768],bytes([outer*4+3])*16384)
    def test_profile_restrictions(self):
        p=self.rom(1,chr=0,ram=7)
        with self.assertRaises(ValueError):read_pico_rom(p,'rp2040')
        self.assertEqual(read_pico_rom(p,'rp2350').ram_size,8192)
        _,d,_=layout([p],'rp2350');self.assertTrue(d[51]&4)
        p=self.rom(34,chr=1,ram=7,sub=1)
        with self.assertRaises(ValueError):read_pico_rom(p,'rp2040')
        self.assertEqual(read_pico_rom(p,'rp2350').mapper,34)
    def test_geometry(self):
        p=self.rom(232,prg=2,chr=0)
        with self.assertRaises(ValueError):read_pico_rom(p)
        p=self.rom(3,prg=3)
        with self.assertRaises(ValueError):read_pico_rom(p)
        p=self.rom(3);self.path.write_bytes(p.read_bytes()[:-1])
        with self.assertRaises(ValueError):read_pico_rom(p)
    def test_refuse_before_erase(self):
        class Board:
            def __init__(self,*a):self.port=self;self.commands=[]
            def enter_loader(self):return 'ROMLOAD READY area=327680 end=1044480 pack=2 profile=1'
            def write(self,b):self.commands.append(b)
            def close(self):pass
            def erase(self,*a):raise AssertionError('must refuse before erasing')
        p=self.rom(1,ram=7);_,d,b=layout([p],'rp2350')
        with patch('rom_loader.Board',Board):
            with self.assertRaisesRegex(ValueError,'Pico 2 W'):load_store(d,b,'COM0',False,lambda *a:None)
            with self.assertRaisesRegex(ValueError,'exceeds'):load_store(b'',[(0x100000,b'x')],'COM0',False,lambda *a:None)

if __name__=='__main__':unittest.main()
