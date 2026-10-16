"""Generate independent CPU-state vectors, executed only on the physical board."""
from pathlib import Path
from py65.devices.mpu6502 import MPU
rows=[]
for op,(name,mode) in enumerate(MPU.disassemble):
 if mode not in ('zpg','zpx','zpy','inx','iny') or name=='???':continue
 for variant in range(4):
  mem=[0]*65536
  for i in range(2048):mem[i]=(i*7+11)&255
  x=[0,1,127,255][variant];y=[0,3,128,255][variant];a=[0,127,128,255][variant]
  operand=0x80;p=[0x20,0x21,0x64,0xe3][variant]
  if mode in ('inx','iny'):
   ptr=(operand+x)&255 if mode=='inx' else operand
   mem[ptr]=0;mem[(ptr+1)&255]=3
   target=0x300+(y if mode=='iny' else 0)
  else:target=(operand+(x if mode=='zpx' else y if mode=='zpy' else 0))&255
  mem[0x400]=op;mem[0x401]=operand
  cpu=MPU(memory=mem,pc=0x400);cpu.a=a;cpu.x=x;cpu.y=y;cpu.p=p;cpu.sp=0xfd
  cpu.step()
  rows.append([op,operand,x,y,a,p,cpu.a,cpu.x,cpu.y,cpu.p&0xef,cpu.processorCycles,target&255,target>>8,mem[target]])
lines=['; Generated with py65 as an independent expected-state oracle.','DataSection','ZpVectors:']
lines += ['  Data.a '+','.join(map(str,row)) for row in rows]
lines += ['EndDataSection',f'#ZP_VECTOR_COUNT={len(rows)}']
Path(__file__).with_name('zp_vectors.pico').write_text('\n'.join(lines)+'\n')
print('Generated',len(rows),'zero-page and indirect board vectors')
