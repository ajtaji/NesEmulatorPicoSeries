from pathlib import Path
import math
root=Path(__file__).resolve().parent
rom=bytearray([0xea])*32768
code=bytearray(); labels={}; fixes=[]
def emit(*b): code.extend(b)
def label(name): labels[name]=0x8000+len(code)
def absolute(op,addr): emit(op,addr&255,addr>>8)
def jump(op,name,relative=False):
    emit(op); fixes.append((len(code),name,relative)); emit(0) if relative else emit(0,0)
def write(addr,val): emit(0xa9,val); absolute(0x8d,addr)
label('reset');emit(0x78,0xd8,0xa2,0xff,0x9a)
write(0x2000,0);write(0x2001,0)
for name in ('wait1','wait2'):
    label(name);absolute(0x2c,0x2002);jump(0x10,name,True)
write(0x2006,0x3f);write(0x2006,0);emit(0xa2,0)
label('palette');absolute(0xbd,0x9000);absolute(0x8d,0x2007);emit(0xe8,0xe0,32);jump(0xd0,'palette',True)
write(0x2006,0x20);write(0x2006,0);emit(0xa0,4,0xa2,0)
label('names');emit(0x8a,0x29,15);absolute(0x8d,0x2007);emit(0xe8);jump(0xd0,'names',True);emit(0x88);jump(0xd0,'names',True)
emit(0xa2,0,0xa9,255)
label('hide');absolute(0x9d,0x0200);emit(0xe8);jump(0xd0,'hide',True)
for i in range(4):
    for off,value in enumerate((80+i*12,1+i,i&3,64+i*32)): write(0x0200+i*4+off,value)
write(0x4014,2)
write(0x4017,0x40);write(0x4015,0x0f)
for addr,val in [(0x4000,0xbf),(0x4001,8),(0x4002,253),(0x4003,0),
                 (0x4004,0x78),(0x4005,8),(0x4006,0x7d),(0x4007,1),
                 (0x4008,0xc0),(0x400a,253),(0x400b,0),
                 (0x400c,0x33),(0x400e,8),(0x400f,0),
                 (0x4010,0x4f),(0x4011,64),(0x4012,0x40),(0x4013,1),(0x4015,31)]:write(addr,val)
write(0x2005,0);write(0x2005,0);write(0x2000,0x80);write(0x2001,0x1e)
label('idle');jump(0x4c,'idle')
label('nmi');emit(0x48,0x8a,0x48,0x98,0x48,0xe6,0)
emit(0xa5,0);absolute(0x8d,0x2005);write(0x2005,0)
absolute(0xee,0x0203);write(0x4014,2)
emit(0x68,0xa8,0x68,0xaa,0x68,0x40)
label('irq');emit(0x40)
for pos,name,rel in fixes:
    addr=labels[name]
    if rel:
        displacement=addr-(0x8000+pos+1);assert -128<=displacement<=127
        code[pos]=displacement&255
    else:code[pos:pos+2]=addr.to_bytes(2,'little')
rom[:len(code)]=code
palette=[0x0f,0x01,0x21,0x31,0x0f,0x06,0x16,0x26,0x0f,0x09,0x19,0x29,0x0f,0x02,0x12,0x22]*2
rom[0x1000:0x1020]=bytes(palette)
rom[0x5000:0x5011]=bytes([0x55,0x55,0xaa,0xaa]*4+[0x55])
for offset,name in [(0x7ffa,'nmi'),(0x7ffc,'reset'),(0x7ffe,'irq')]:rom[offset:offset+2]=labels[name].to_bytes(2,'little')
chr=bytearray(8192)
for tile in range(512):
    for y in range(8):
        for x in range(8):
            colour=((x//2+y//2+tile)%3)+1
            if tile%16==0:colour=0
            chr[tile*16+y]|=(colour&1)<<(7-x)
            chr[tile*16+y+8]|=(colour>>1)<<(7-x)
rgbhex='666666 002A88 1412A7 3B00A4 5C007E 6E0040 6C0600 561D00 333500 0B4800 005200 004F08 00404D 000000 000000 000000 ADADAD 155FD9 4240FF 7527FE A01ACC B71E7B B53120 994E00 6B6D00 388700 0C9300 008F32 007C8D 000000 000000 000000 FFFFFF 64B0FF 9290FF C676FF F36AFF FE6ECC FE8170 EA9E22 BCBE00 88D800 5CE430 45E082 48CDDE 4F4F4F 000000 000000 FFFFFF C0DFFF D3D2FF E8C8FF FBC2FF FEC4EA FECCC5 F7D8A5 E4E594 CFEF96 BDF4AB B3F3CC B5EBF2 B8B8B8 000000 000000'.split()
rgb=[]
for emphasis in range(8):
    for value in rgbhex:
        c=int(value,16);r=c>>16;g=(c>>8)&255;b=c&255
        if emphasis&1:g=g*3//4;b=b*3//4
        if emphasis&2:r=r*3//4;b=b*3//4
        if emphasis&4:r=r*3//4;g=g*3//4
        rgb.append(((r&248)<<8)|((g&252)<<3)|(b>>3))
tables={'LengthData':('a',[10,254,20,2,40,4,80,6,160,8,60,10,14,12,26,14,12,16,24,18,48,20,96,22,192,24,72,26,16,28,32,30]),
        'NoiseData':('u',[4,8,16,32,64,96,128,160,202,254,380,508,762,1016,2034,4068]),
        'DmcData':('u',[428,380,340,320,286,254,226,214,190,160,142,128,106,85,72,54]),
        'PulseData':('u',[0]+[round(32767*95.88/(8128/i+100)) for i in range(1,31)]),
        'TndData':('u',[0]+[round(32767*163.67/(24329/i+100)) for i in range(1,203)]),
        'RgbData':('u',rgb),'CartridgeData':('a',rom),'ChrData':('a',chr)}
lines=['; Generated demonstration cartridge and APU/RGB lookup data.','DataSection']
for name,(kind,values) in tables.items():
    lines.append(name+':')
    for start in range(0,len(values),24):lines.append(f'  Data.{kind} '+','.join(str(x) for x in values[start:start+24]))
lines.append('EndDataSection')
lines.append('''; The built-in cartridge; rom_store.pico's CartSelect uses it when the
; board's ROM store holds no games.
Procedure CartSelectBuiltin(number.i)
  CartCount=1 : CartTitle=?DemoTitle
  CartMapper=0 : CartPrgBanks=1 : CartChrBanks=1
  CartPrg=?CartridgeData : CartChr=?ChrData : CartChrRam=0
  CartConflicts=0 : PpuMirroring=1
EndProcedure
DataSection
DemoTitle: Data.a 68,69,77,79,0
EndDataSection''')
(root/'cartridge.pico').write_text('\n'.join(lines)+'\n')
(root/'demo.nes').write_bytes(b'NES\x1a'+bytes([2,1,1,0])+bytes(8)+rom+chr)
(root/'demo-symbols.txt').write_text('\n'.join(f'{k}=${v:04X}' for k,v in labels.items())+'\n')
print('Generated mapper-0 demo:',len(code),'code bytes')
