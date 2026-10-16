"""Build a returning Pi 4 application against an explicit Anvil checkout.

The dependency is source-only. This tool never builds or replaces Anvil.
Private game wrappers and generated dependency bindings stay in --out's folder.
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import re

ROOT=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--compiler',required=True,type=Path)
    p.add_argument('--anvil',required=True,type=Path)
    p.add_argument('--out',required=True,type=Path)
    p.add_argument('--rom',type=Path)
    p.add_argument('--no-selector',action='store_true',help='use the embedded demo instead of the exFAT ROM menu')
    p.add_argument('--seconds',type=int,default=0,help='automatic test exit in seconds; 0 plays until Exit')
    p.add_argument('--bluetooth-peer-wrapper',type=Path,help='private Pico wrapper containing one six-byte peer Data.a')
    p.add_argument('--bluetooth-bond',type=Path,help="private 64-byte record: 'BOND' + Anvil's 22-byte bond at 0, optionally 'ADDR' + this board's controller address (MSB first) at 0x30")
    p.add_argument('--video-plugin',type=Path,default=ROOT/'anvil/video_neon.pi4')
    p.add_argument('--input-plugin',type=Path,default=ROOT/'anvil/input_touch.pi4')
    p.add_argument('--audio-plugin',type=Path,help='custom audio plugin; default silent, or Bluetooth when peer is supplied')
    p.add_argument('--verify-audio',action='store_true',help='run deterministic SBC vectors and return without emulation')
    p.add_argument('--verify-core',action='store_true',help='run CPU vectors and packed CHR differential checks')
    p.add_argument('--verify-mappers',action='store_true',help='run MMC1/MMC3 register, RAM, mirroring, IRQ and reset tests')
    p.add_argument('--verify-rom',action='store_true',help='run on-board loader tests against the three exFAT test games')
    a=p.parse_args()
    a.out=a.out.resolve(); a.anvil=a.anvil.resolve()
    a.out.parent.mkdir(parents=True,exist_ok=True)
    if a.seconds<0: p.error('--seconds must be nonnegative')
    if a.bluetooth_peer_wrapper and a.audio_plugin:
        p.error('choose --audio-plugin or --bluetooth-peer-wrapper, not both')
    if sum(map(bool,(a.verify_rom,a.verify_core,a.verify_audio,a.verify_mappers)))>1:
        p.error('choose only one verification mode')
    if a.verify_rom and (a.rom or a.no_selector or a.verify_core or a.verify_audio):
        p.error('--verify-rom requires selector mode and no other verification mode')
    includes=['RaspberryPi4/Lib/uart.pi4','RaspberryPi4/Lib/timer.pi4',
      'RaspberryPi4/Lib/mailbox.pi4','RaspberryPi4/Lib/mmu.pi4',
      'RaspberryPi4/Lib/dma.pi4','RaspberryPi4/Lib/display.pi4',
      'RaspberryPi4/Lib/v3dqpu.pi4','RaspberryPi4/Lib/v3d.pi4',
      'RaspberryPi4/Lib/neon.pi4','Anvil/Graphics/Vulkan/vk_api.pbi',
      'Anvil/Graphics/Vulkan/vk_spirv_fixtures.pbi',
      'Anvil/Graphics/Vulkan/vk_v3d_shader.pi4','RaspberryPi4/Board/vulkan_dma.pi4',
      'Anvil/Graphics/Vulkan/vk_v3d_backend.pi4',
      'Anvil/Graphics/Vulkan/neon_vk_chrome.pi4']
    if a.bluetooth_peer_wrapper:
        includes += ['RaspberryPi4/Lib/gpio.pi4']
    source=f'#NES_VERIFY_MAPPERS={int(a.verify_mappers)}\n#NES_BT_SESSION={int(bool(a.bluetooth_peer_wrapper))}\n#DSP_DMA_LINKED=1\n#NES_NATIVE_TIMER=1\n#NES_VERIFY_CODEC={int(a.verify_audio)}\n#NES_VERIFY_CORE={int(a.verify_core)}\n#NES_VERIFY_ROM={int(a.verify_rom)}\n#NES_ROM_SELECTOR={int(not (a.rom or a.no_selector or a.verify_core or a.verify_audio))}\n'
    source+='\n'.join(f'XIncludeFile "{(a.anvil/f).as_posix()}"' for f in includes)+'\n'
    if a.bluetooth_peer_wrapper:
        # Anvil's Bluetooth stack, unchanged (2026-10-16). The BT_ON polarity
        # readback this script used to splice in is Anvil's own now.
        source+='\n'.join(f'XIncludeFile "{(a.anvil/f).as_posix()}"' for f in (
          'RaspberryPi4/Lib/bt_uart.pi4','RaspberryPi4/Board/hw_bt_payload.pi4',
          'Anvil/Net/hci.pbi','Anvil/Audio/sbc.pbi','Anvil/Net/l2cap.pbi','Anvil/Net/a2dp.pbi'))+'\n'
    source+='\n'.join(['#CPU_TIMING=1','#CPU_ASM_TAIL=0','#NES_SPLIT=0',
      '#CART_CHR_BANKS=128','#PPU_PROFILE=0',f'#TEST_SECONDS={a.seconds}',
      '#NES_VIDEO_BACKEND=2',f'#NES_AUDIO_BACKEND={2 if a.bluetooth_peer_wrapper or a.audio_plugin else 0}'])+'\n'
    def inc(path):
        return f'XIncludeFile "{Path(path).resolve().as_posix()}"\n'
    source+=inc(ROOT/'anvil/core.pi4')+inc(a.video_plugin)+inc(a.input_plugin)
    for name in ('hud','platform'):
        source+=inc(ROOT/f'anvil/{name}.pi4')
    if a.video_plugin.resolve()==(ROOT/'anvil/video_neon.pi4').resolve():
        source+=inc(ROOT/'anvil/ui.pi4')+inc(ROOT/'anvil/video_menu_neon.pi4')
    if a.bluetooth_peer_wrapper:
        patch=(a.anvil/'Firmware/CYW43455/BCM4345C0.hcd').read_bytes()
        source+=f'#BT_PATCH_BYTES={len(patch)}\n'
        source+=inc(ROOT/'anvil/audio_bluetooth.pi4')
        values=re.findall(r'Data\.a\s+([^\r\n]+)',a.bluetooth_peer_wrapper.read_text())
        if len(values)!=1: raise ValueError('peer wrapper must contain exactly one Data.a line')
        peer=[int(x.strip().replace('$','0x'),0) for x in values[0].split(',')]
        if len(peer)!=6 or any(x<0 or x>255 for x in peer): raise ValueError('invalid six-byte peer')
        bond=a.bluetooth_bond.read_bytes() if a.bluetooth_bond else b''
        if bond and (len(bond)<0x36 or bond[:4]!=b'BOND'): raise ValueError('bond record must start with BOND')
        own=bond[0x34:0x3A] if bond[0x30:0x34]==b'ADDR' else b''
        config='  NesBluetoothSetPeer(?PrivatePeer)\n'
        if bond: config+='  NesBluetoothSetBond(?PrivateBond, '+('?PrivateOwnAddr' if own else '0')+')\n'
        source+='Procedure AudioConfigure()\n'+config+'EndProcedure\nDataSection\nPrivatePeer: Data.a '+','.join(map(str,peer))+'\n'
        if bond: source+='PrivateBond: Data.a '+','.join(map(str,bond[4:26]))+'\n'
        if own: source+='PrivateOwnAddr: Data.a '+','.join(map(str,own))+'\n'
        source+='BtPatch:\n'
        source+=''.join('  Data.a '+','.join(map(str,patch[i:i+24]))+'\n' for i in range(0,len(patch),24))
        source+='BtPatchEnd:\nEndDataSection\n'
    else:
        source+=inc(a.audio_plugin or ROOT/'anvil/audio_null.pi4')
        source+='Procedure AudioConfigure()\nEndProcedure\n'
    for name in ('audio_session','runtime','guest_reset','scheduler'):
        source+=inc(ROOT/f'anvil/{name}.pi4')
    if a.verify_audio:
        if not a.bluetooth_peer_wrapper: p.error('--verify-audio currently requires the Bluetooth codec build')
        source+=inc(ROOT/'anvil/Tests/sbc.pi4')
    if a.verify_core:
        source+=inc(ROOT/'anvil/Tests/core.pi4')
    if a.verify_rom:
        source+=inc(ROOT/'anvil/Tests/rom_loader.pi4')
    if a.verify_mappers:
        source+=inc(ROOT/'anvil/Tests/mappers.pi4')
    cart=(ROOT/'anvil/cartridge.pi4').read_text()
    if a.rom:
        from rom_catalog import validate,prg_views
        from anvil_cartridge import read_anvil_rom,EXTRA
        c,header=read_anvil_rom(a.rom)
        if c.mapper in (1,3,4,5,7,11):
            if c.mapper in (1,4) and (header[7]&12)!=8 and header[8]>1:
                raise ValueError('unsupported Anvil MMC PRG RAM size')
            if c.mapper!=5 and c.ram_size>(8192 if c.mapper in (1,4) else 0):
                raise ValueError('unsupported Anvil cartridge RAM')
            if c.mapper==5 and (c.ram_size>131072 or (c.ram_size and (c.ram_size<8192 or c.ram_size&(c.ram_size-1)))):
                raise ValueError('unsupported MMC5 RAM geometry')
            if c.mapper==5 and (header[7]&12)==8 and header[11]:
                raise ValueError('MMC5 CHR RAM boards are unsupported')
            prg_max={1:262144,3:32768,4:524288,5:1048576,7:262144,11:131072}[c.mapper]
            chr_max={1:131072,3:32768,4:262144,5:1048576,7:0,11:131072}[c.mapper]
            if c.trainer or len(c.prg)>prg_max or len(c.chr)>chr_max or (c.submapper>2 if c.mapper in (3,7,11) else c.submapper!=0):
                raise ValueError('unsupported Anvil mapper geometry')
            if c.mapper in (3,5,11) and not c.chr:
                raise ValueError('mapper requires CHR ROM')
        elif c.mapper not in EXTRA:
            validate(c)
        chr_ram_bytes={6:32768,13:16384}.get(c.mapper,8192)
        prg=prg_views(c)
        cart=cart[:cart.index('CartridgeData:')]
        def data(name,blob):
            return name+':\n'+''.join('  Data.a '+','.join(map(str,blob[i:i+24]))+'\n' for i in range(0,len(blob),24))
        cart+=data('CartridgeData',prg)+data('ChrData',c.chr or bytes(chr_ram_bytes))+'EndDataSection\n'
        cart+=f'''Procedure CartSelectBuiltin(number.i)
  CartSubmapper={c.submapper}
  CartMapper={c.mapper} : CartPrgBanks={len(prg)//32768} : CartChrBanks={len(c.chr)//8192 or 2}
  CartPrg=?CartridgeData : CartChr=?ChrData : CartChrRam={int(not c.chr)}
  CartConflicts={int(c.conflicts)} : PpuMirroring={c.mirror}
  MapPrgBytes={len(c.prg)} : MapChrBytes={len(c.chr) or chr_ram_bytes} : MapChrRam={int(not c.chr)}
  MapBattery={int(c.battery)} : MapFourScreen={int(bool(header[6]&8))} : MapRamBytes={65536 if c.mapper==5 and (header[7]&12)!=8 and header[8]==0 else c.ram_size}
EndProcedure
'''
    private=a.out.with_suffix('.cartridge.pi4'); private.write_text(cart)
    source+=f'XIncludeFile "{private.as_posix()}"\n'
    wrapper=a.out.with_suffix('.pi4');wrapper.write_text(source)
    # Anvil owns its include root; the compiler still owns its intrinsics.
    env=os.environ.copy();env['PMF_ROOT']=str(a.anvil)
    cmd=[str(a.compiler),'--compile',str(wrapper),'-t','pi4','--load-addr','0x01000000',
      '--bss-addr','0x02000000','--stack-addr','0x03000000','--entry-returns',
      '--wants-services','-S','-o',str(a.out)]
    # A failed compiler must never leave a previous loadable sidecar looking
    # like the product of this build. Only remove this explicitly named output.
    sidecar=Path(str(a.out)+'.pmf')
    sidecar.unlink(missing_ok=True)
    r=subprocess.run(cmd,cwd=a.anvil,env=env,capture_output=True,text=True)
    a.out.with_suffix('.build.log').write_text(r.stdout+'\n'+r.stderr)
    print(r.stdout);print(r.stderr,file=sys.stderr)
    if r.returncode or not Path(str(a.out)+'.pmf').exists(): raise SystemExit(r.returncode or 1)

if __name__=='__main__':main()
