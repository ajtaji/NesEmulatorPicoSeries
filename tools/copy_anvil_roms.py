"""Copy an explicitly supplied ROM folder to Pi exFAT 2:/NES, with readback.

Requires an explicit Anvil checkout for its network tools and MMU library.
Does not change boot files, monitor firmware, settings, or any other folder.
The native copier skips identical files; differing namesakes are replaced.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--directory',type=Path,required=True)
    p.add_argument('--anvil',type=Path,required=True)
    p.add_argument('--compiler',type=Path,required=True)
    p.add_argument('--ip',required=True)
    p.add_argument('--out',type=Path,required=True,help='private working folder for bundle and copy records')
    a=p.parse_args(); a.anvil=a.anvil.resolve(); a.out=a.out.resolve()
    a.out.mkdir(parents=True,exist_ok=True)
    files=sorted((f for f in a.directory.glob('*.nes') if f.is_file()),key=lambda f:f.name.casefold())
    if not 1<=len(files)<=4096: p.error('directory must contain 1..4096 .nes files')
    seen=set(); table=bytearray(); offset=32+272*len(files); manifest=[]
    for f in files:
        name=f.name.encode('utf-8'); key=f.name.casefold(); n=f.stat().st_size
        if key in seen or not 5<=len(name)<=255 or any(c in f.name for c in '/\\:') or any(c<32 for c in name):
            p.error('duplicate or unsafe ROM basename: '+f.name)
        if not 1<=n<=8388608: p.error('file exceeds copier size bound: '+f.name)
        seen.add(key); table+=name.ljust(256,b'\0')+struct.pack('<QQ',offset,n)
        manifest.append(dict(name=f.name,bytes=n,sha256=hashlib.sha256(f.read_bytes()).hexdigest()))
        offset+=n
    if offset>0x10000000: p.error('bundle exceeds 256 MiB; copy smaller folders separately')
    bundle=a.out/'roms.pack'
    with bundle.open('wb') as out:
        out.write(struct.pack('<8sQQQ',b'NESPACK1',len(files),offset,32+272*len(files)));out.write(table)
        for f,item in zip(files,manifest):
            data=f.read_bytes()
            if hashlib.sha256(data).hexdigest()!=item['sha256']: raise RuntimeError('file changed: '+f.name)
            out.write(data)
    (a.out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    wrapper=a.out/'copy.pi4'
    wrapper.write_text('#NES_NATIVE_TIMER=0\nXIncludeFile "'+(a.anvil/'RaspberryPi4/Lib/mmu.pi4').as_posix()+'"\nXIncludeFile "'+(ROOT/'anvil/Tools/copy_roms.pi4').as_posix()+'"\n')
    image=a.out/'copy.img'; sidecar=Path(str(image)+'.pmf');sidecar.unlink(missing_ok=True)
    env=os.environ.copy();env['PMF_ROOT']=str(a.anvil)
    r=subprocess.run([str(a.compiler),'--compile',str(wrapper),'-t','pi4','--load-addr','0x01000000','--bss-addr','0x02000000','--stack-addr','0x03000000','--entry-returns','--wants-services','-o',str(image)],env=env,capture_output=True,text=True)
    (a.out/'copy.build.log').write_text(r.stdout+r.stderr)
    if r.returncode or not sidecar.exists(): raise RuntimeError('copier compilation failed; see copy.build.log')
    sys.path.insert(0,str(a.anvil/'tools'))
    from board_run import NetConsole,stream_file,parse_recv_verdict,RECV_SHA_RE
    c=NetConsole(a.ip)
    try:
        c.settle();c.send('mount');mount=c.read_until(['pmf>'],15)
        if '2:  exFAT' not in mount: raise RuntimeError('partition 2 is not reported as exFAT')
        c.send('ls 2:/NES');listing=c.read_until(['pmf>'],15)
        if 'Directory 2:/NES' not in listing:
            c.send('mkdir 2:/NES');reply=c.read_until(['pmf>'],20)
            if 'Made the directory' not in reply: raise RuntimeError(reply)
        data=bundle.read_bytes();want=hashlib.sha256(data).hexdigest()
        line=f'net recv 5001 40000000 {len(data):X}';c.send(line)
        listen,why=c.read_until_or_prompt(line,['for ONE connection'],15)
        if why!='needle': raise RuntimeError(listen)
        print(f'Streaming {len(files)} ROMs ({len(data)} bytes)...',flush=True)
        stream_file(a.ip,5001,data)
        verdict,_=c.read_until_or_prompt(line,[RECV_SHA_RE],1200,seen=listen)
        count,_,digest=parse_recv_verdict(listen+verdict)
        if count!=len(data) or digest!=want: raise RuntimeError('staging digest mismatch; no files copied')
        c.read_until(['pmf>'],10)
    finally:
        c.close()
    print('Staging digest verified. Copying and comparing exFAT files...',flush=True)
    subprocess.run([sys.executable,str(a.anvil/'tools/board_run.py'),str(sidecar),'--console-ip',a.ip,'--timeout','1200','--settle','0','--trace','2f00200:40','--no-shot','--out',str(a.out/'board')],check=True)
    trace=(a.out/'board/copy.img.trace.bin').read_bytes()
    result,written,skipped,index,total=struct.unpack('<5Q',trace)
    if result or written+skipped!=len(files): raise RuntimeError(f'copy incomplete at index {index}, result {result}')
    print(f'Verified {written+skipped} files, {total} bytes; {written} written, {skipped} already identical.')

if __name__=='__main__':main()
