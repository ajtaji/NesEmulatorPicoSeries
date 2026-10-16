"""Repeatable USB-input, telemetry and framebuffer tests on real Pico hardware.

Requires pyserial and Pillow. Replaces the board's ROM menu. Firmware must
already be installed; the supplied UF2 is hashed, not uploaded or read back.
Bluetooth connection flags do not certify sound quality. No ROMs are bundled.
"""
import serial,time,sys,re,json,struct,hashlib
from pathlib import Path
from PIL import Image
import argparse
from rom_loader import layout, load_store

parser = argparse.ArgumentParser(description="Finite physical-board ROM smoke tests; returns to boot menu after every game.")
parser.add_argument('--port', required=True)
parser.add_argument('--target', choices=('rp2040', 'rp2350'), required=True)
parser.add_argument('--firmware', type=Path, required=True, help='Exact already-installed UF2, used for result provenance')
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--seconds', type=int, default=40)
parser.add_argument('--deep-start', action='store_true', help='Additional Start presses at 12/18 seconds for long introductions')
parser.add_argument('rom', type=Path, nargs='+', help='Owned .nes files; installs a replacement ROM menu')
args = parser.parse_args()
if not 1 <= len(args.rom) <= 10 or args.seconds < 10:
 parser.error('Use 1..10 ROMs and at least 10 seconds per game')
port, target, out = args.port, args.target, args.output
out.mkdir(parents=True, exist_ok=True)
firmware_hash = hashlib.sha256(args.firmware.read_bytes()).hexdigest()
games, directory, blobs = layout(args.rom, target)
print(target, 'loading', sum(len(b) for _,b in blobs), flush=True)
load_store(directory, blobs, port, True, lambda msg,p:print(msg, flush=True))
start_index = 0
results=[]
def open_port(baud):
 deadline=time.monotonic()+20
 while True:
  try:return serial.Serial(port,baud,timeout=.2)
  except serial.SerialException:
   if time.monotonic()>deadline:raise
   time.sleep(.4)
def reset():
 deadline=time.monotonic()+12
 while True:
  try:
   with open_port(2417):time.sleep(.2)
   break
  except serial.SerialException:
   if time.monotonic()>deadline:raise
   time.sleep(.4)
 time.sleep(2)
for index,(cart,*_) in enumerate(games):
 if index<start_index:continue
 reset();s=open_port(115200);lines=[];t=time.monotonic();ready=None;sent=set();s.write(str(index).encode());slug=f'{target}-{cart.mapper}-{cart.path.stem}'
 try:
  while time.monotonic()-t<100:
   line=s.readline().decode(errors='replace').strip()
   if line:lines.append(line)
   if 'NES PureMetal RP' in line:ready=time.monotonic()
   if ready:
    elapsed=time.monotonic()-ready
    for at,key in ([(2,b's'),(8,b'R'),(10,b'a'),(13,b'0')]+([(5,b's')] if cart.mapper in (4,66,47,118,119,206) else [])+([(12,b's'),(14,b'R'),(18,b's'),(22,b'a'),(25,b'0')] if args.deep_start else [])+([(5,b's'),(12,b's')] if cart.mapper==1 else [])):
     if elapsed>=at and at not in sent:s.write(key);sent.add(at)
    if elapsed>=args.seconds:break
  if not ready:raise RuntimeError('No game startup header: '+repr(lines[-5:]))
  s.write(b'mi');time.sleep(.3)
  for _ in range(3):
   line=s.readline().decode(errors='replace').strip()
   if line:lines.append(line);print(line if line.startswith(('MAPPER','APU')) else 'diagnostic telemetry',flush=True)
  s.reset_input_buffer();s.write(b'p');buf=b'';deadline=time.monotonic()+15;marker=b'RGB_BEGIN\r\n'
  while marker not in buf and time.monotonic()<deadline:buf+=s.read(4096)
  if marker not in buf:raise RuntimeError('No frame capture')
  payload=buf.split(marker,1)[1]
  while len(payload)<122880 and time.monotonic()<deadline:payload+=s.read(122880-len(payload))
  if len(payload)<122880:raise RuntimeError('Incomplete frame capture')
  pixels=struct.unpack('<61440H',payload[:122880]);im=Image.new('RGB',(256,240));im.putdata([(((v>>11)&31)*255//31,((v>>5)&63)*255//63,(v&31)*255//31) for v in pixels]);im.save(out/(slug+'.png'))
  rows=[]
  for line in lines:
   row={k:int(v) for k,v in re.findall(r'(\w+)=(-?\d+)',line)}
   if {'cycles','frames','lcd','us','err','stop'}<=row.keys():rows.append(row)
  if len(rows)<10:raise RuntimeError(f'Only {len(rows)} telemetry rows')
  us=sum(row['us'] for row in rows);result={k:sum(row[k] for row in rows)*1e6/us for k in ['cycles','frames','lcd','samples']};result.update(firmware_sha256=firmware_hash,title=cart.path.name,mapper=cart.mapper,target=target,seconds=us/1e6,errors=max(row['err'] for row in rows),stopped=max(row['stop'] for row in rows),debt_first=rows[0]['debt'],debt_last=rows[-1]['debt'],bt_live=min(row.get('bt_live',0) for row in rows),colours=len(set(pixels)))
  # Startup buffering is separate from playback. The framebuffer dump occurs
  # after these rows and deliberately pauses emulation, so it is excluded.
  steady=rows[2:] or rows
  first=steady[0].get('audio_underrun',steady[0].get('bt_underrun',0))
  last=steady[-1].get('audio_underrun',steady[-1].get('bt_underrun',0))
  result.update(audio_underrun_first=first,audio_underrun_last=last,audio_underrun_steady_delta=last-first)
  results.append(result);(out/(slug+'.json')).write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True)
  if result['errors'] or result['stopped']:raise RuntimeError('Board error or stopped CPU')
 finally:
  s.close();(out/(slug+'.txt')).write_text('\n'.join(line for line in lines if 'peer' not in line.lower() and 'address' not in line.lower())+'\n');reset()
(out/'games.json').write_text(json.dumps(results,indent=2)+'\n')
print('STOPPED boot menu',port,flush=True)
