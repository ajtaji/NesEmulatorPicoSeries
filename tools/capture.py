"""Capture a stable framebuffer or PCM ring FROM THE BOARD over USB CDC."""
import argparse, time, struct, wave
from pathlib import Path
import serial

p=argparse.ArgumentParser()
p.add_argument('output',type=Path)
p.add_argument('--port',required=True)
p.add_argument('--keys',default='')
p.add_argument('--wait',type=float,default=1)
p.add_argument('--pcm',action='store_true')
p.add_argument('--reference',action='store_true')
a=p.parse_args()
with serial.Serial(a.port,115200,timeout=.2) as s:
 for key in a.keys:
  s.write(key.encode()); time.sleep(1)
 deadline=time.monotonic()+a.wait
 while time.monotonic()<deadline:
  s.read(4096)
 s.reset_input_buffer()
 marker=b'PCM_BEGIN\r\n' if a.pcm else b'RGB_BEGIN\r\n'
 s.write(b'w' if a.pcm else (b'z' if a.reference else b'p'))
 buf=b'';deadline=time.monotonic()+30
 while marker not in buf:
  buf+=s.read(4096)
  if time.monotonic()>deadline:raise TimeoutError('No capture header from board')
 payload=buf.split(marker,1)[1]
 size=8192 if a.pcm else 122880
 while len(payload)<size:
  payload+=s.read(size-len(payload))
  if time.monotonic()>deadline:raise TimeoutError(f'Truncated capture {len(payload)}/{size}')
 payload=payload[:size]
a.output.parent.mkdir(parents=True,exist_ok=True)
if a.pcm:
 with wave.open(str(a.output),'wb') as w:
  w.setnchannels(1);w.setsampwidth(2);w.setframerate(48000);w.writeframes(payload)
 samples=struct.unpack('<4096h',payload)
 print('PCM samples=4096 min=',min(samples),'max=',max(samples),'nonzero=',sum(x!=0 for x in samples))
else:
 from PIL import Image
 pixels=struct.unpack('<61440H',payload)
 image=Image.new('RGB',(256,240))
 image.putdata([(((v>>11)&31)*255//31,((v>>5)&63)*255//63,(v&31)*255//31) for v in pixels])
 image.save(a.output)
 print('RGB framebuffer from board:',a.output,'unique colours=',len(set(pixels)))
