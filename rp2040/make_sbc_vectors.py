"""Generate deterministic SBC oracle bytes; compiled firmware runs only on the board."""
import math, random, re
from pathlib import Path
ROOT = Path(__file__).resolve().parent
source = (ROOT/'sbc_encoder.pico').read_text()
def table(label):
 text=source.split(label+':',1)[1].split('\nSbc',1)[0].split('EndDataSection',1)[0]
 return [int(v) for line in text.splitlines() if 'Data.w ' in line for v in line.split('Data.w ',1)[1].split(',')]
proto=table('SbcProto');cs=table('SbcCos');hist=[0]*80
assert len(proto)==80 and len(cs)==128
def encode(pcm,stereo=False):
 width=16 if stereo else 8
 sub=[]
 for block in range(16):
  hist[8:]=hist[:-8];hist[:8]=pcm[block*8:block*8+8][::-1]
  y=[sum(hist[i+16*j]*proto[i+16*j] for j in range(5))>>16 for i in range(16)]
  sub.append([max(-32767,min(32767,sum(y[i]*cs[k*16+i] for i in range(16))>>12)) for k in range(8)])
  if stereo:sub[-1]=sub[-1]*2
 scale=[];need=[]
 for k in range(width):
  peak=max(abs(row[k]) for row in sub);v=0
  while v<15 and peak>=(1<<(v+1)):v+=1
  scale.append(v)
  loud=v-[-4,0,0,0,0,0,1,2][k&7]
  need.append(-5 if v==0 else loud//2 if loud>0 else loud)
 bitcount=0;slicecount=0;sl=max(need)+1
 while True:
  sl-=1;bitcount+=slicecount;slicecount=0
  for x in need:
   if x>sl+1 and x<sl+16:slicecount+=1
   elif x==sl+1:slicecount+=2
  if bitcount+slicecount>=28:break
 if bitcount+slicecount==28:bitcount+=slicecount;sl-=1
 bits=[0 if x<sl+2 else min(x-sl,16) for x in need]
 for step in range(width):
  k=((step>>1)|((step&1)<<3)) if stereo else step
  if bitcount>=28:break
  if bits[k]>=2 and bits[k]<16:bits[k]+=1;bitcount+=1
  elif need[k]==sl+1 and 28>bitcount+1:bits[k]=2;bitcount+=2
 for step in range(width):
  k=((step>>1)|((step&1)<<3)) if stereo else step
  if bitcount>=28:break
  if bits[k]<16:bits[k]+=1;bitcount+=1
 assert sum(bits)==28
 packed=[0x9c,(0xf9 if stereo else 0xf1),28,0]+[(scale[k]<<4)|scale[k+1] for k in range(0,width,2)]
 crc=15
 for byte in packed[1:3]+packed[4:8+4*stereo]:
  for n in range(7,-1,-1):
   flag=((crc>>7)^((byte>>n)&1))&1;crc=(crc<<1)&255
   if flag:crc^=0x1d
 packed[3]=crc
 value=0;size=0
 for row in sub:
  for k in range(width):
   b=bits[k]
   if not b:continue
   levels=(1<<b)-1
   q=(((row[k]*levels)>>(scale[k]+1))+levels)>>1
   q=max(0,min(levels,q))
   value=(value<<b)|q;size+=b
   while size>=8:
    size-=8;packed.append((value>>size)&255)
 assert len(packed)==64+4*stereo
 return bytes(packed)

def vectors():
 rng=random.Random(6502)
 for block in range(64):
  if block<8:a=[0]*128
  elif block<16:a=[20000]*128
  elif block<24:a=[-20000]*128
  elif block<40:a=[int(30000*math.sin(2*math.pi*(750 if block<32 else 6000)*i/48000)) for i in range(128)]
  elif block<48:a=[30000 if i&1 else -30000 for i in range(128)]
  elif block<56:a=[rng.randrange(-32768,32768) for i in range(128)]
  else:a=[0]*128
  yield a

if __name__=='__main__':
 blocks=list(vectors());pcm=sum(blocks,[])
 lines=['; Deterministic PCM and independently calculated SBC bytes, no cartridge content.','DataSection','CodecVectorPcm:']
 for i in range(0,len(pcm),16):lines.append('  Data.w '+','.join(map(str,pcm[i:i+16])))
 for stereo,label in [(False,'CodecVectorExpected'),(True,'CodecVectorStereo')]:
  hist[:]=[0]*80
  encoded=b''.join(encode(block,stereo) for block in blocks)
  lines.append(label+':')
  for i in range(0,len(encoded),16):lines.append('  Data.a '+','.join('$%02X'%v for v in encoded[i:i+16]))
 lines.append('EndDataSection')
 (ROOT/'Diagnostics/sbc_vectors.pico').write_text('\n'.join(lines)+'\n')
