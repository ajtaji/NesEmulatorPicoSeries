"""Load NES games into the Pico W / Pico 2 W ROM store over USB serial.

The firmware holds no games. This tool checks each named iNES file, lays the
games out in the board's ROM store (flash offset $50000, directory first,
data from $51000 to $FF000 (W) or $1FF000 (2 W); the next sector is reserved
for board checks and radio firmware starts at $100000 / $200000 respectively) and sends them to the
boot menu's loader, which erases, writes, reads back and CRC-checks every
4 KiB on the board itself. The directory is erased first and written last,
so an interrupted load leaves an empty store (the built-in demo), never a
half-valid one. Afterwards the board's menu lists the new games.

    py -3 tools/rom_loader.py "My Game.nes" "Another Game.nes"
    py -3 tools/rom_loader.py --clear          # empty the store
    py -3 tools/rom_loader.py --dry-run ROM... # check and lay out only
    tools/rom_loader_ui.pyw                  # the same, in a window, for users

Only files named on the command line are read. The board must be running
the NES firmware; by default the tool reboots it into the boot menu first.
"""
import argparse, struct, sys, time, zlib
from pathlib import Path
from pico_cartridge import read_pico_rom, pico_pal, pico_prg, stored_chr, ENDS

DIRECTORY = 0x50000
DATA = 0x51000
END = 0xFF000   # $FF000 is the board-check sector
SECTOR = 4096
CHUNK = 4096
MAX_GAMES = 63


def signed(crc):
    return crc - (1 << 32) if crc & 0x80000000 else crc


def ram_code(cart):
    """MMC5 only: its PRG-RAM size in flag bits 3-5 (0 none, n = 8 KiB << (n-1)); the firmware maps
    RAM banks by it. Every other board leaves the bits clear, as older firmware requires."""
    if cart.mapper != 5 or not cart.ram_size:
        return 0
    return cart.ram_size.bit_length() - 13


def layout(paths, target="rp2040"):
    """Return (games, directory bytes, [(offset, data)]) or raise ValueError."""
    if len(paths) > MAX_GAMES:
        raise ValueError(f'{len(paths)} games named; the directory holds {MAX_GAMES}')
    games, blobs, entries = [], [], b''
    at = DATA
    for path in paths:
        cart = read_pico_rom(Path(path),target)
        prg = pico_prg(cart)
        chr_data = stored_chr(cart)
        title = cart.title.encode('ascii', 'replace')[:31]
        prg_at = at
        at += -(-len(prg) // SECTOR) * SECTOR
        chr_at = at
        at += -(-len(chr_data) // SECTOR) * SECTOR
        if at > ENDS[target]:
            raise ValueError(f'{Path(path).name} does not fit: the ROM store ends at ${ENDS[target]:X} and these games '
                             f'need up to ${at:X} ({at - DATA} of {ENDS[target] - DATA} bytes)')
        blobs += [(prg_at, prg)] + ([(chr_at, chr_data)] if chr_data else [])
        entries += struct.pack('<32sBBBBHHIIIIII', title, cart.mapper, cart.mirror, int(cart.conflicts)|(cart.submapper<<4),
                               int(not chr_data)|(4 if cart.ram_size else 0)|(2 if cart.chr and cart.mapper not in (0,2,66) else 0)|
                               (ram_code(cart) << 3)|(64 if pico_pal(path) else 0), len(prg) // 32768,
                               len(cart.chr) // 8192 if cart.chr else 2,
                               prg_at, len(prg), chr_at, len(chr_data),
                               zlib.crc32(prg), zlib.crc32(chr_data))
        games.append((cart, prg_at, len(prg), chr_at, len(chr_data)))
    head = b'NESR' + struct.pack('<HHII', 2, len(games), zlib.crc32(entries), 0)
    return games, head + entries, blobs


class Board:
    def __init__(self, port, reset):
        import serial
        if reset:
            # The firmware's ordinary reboot request (2417 baud); 1200 would be BOOTSEL.
            with serial.Serial(port, 2417, timeout=0.1):
                time.sleep(0.2)
            time.sleep(1)
        # The board re-enumerates on USB after a reboot; wait for its port.
        deadline = time.monotonic() + 10
        while True:
            try:
                self.port = serial.Serial(port, 115200, timeout=0.2)
                break
            except serial.SerialException:
                if time.monotonic() > deadline:
                    raise TimeoutError(f'{port} did not come back within 10 s of the reboot request; '
                                       'check the USB cable and that the board runs the NES firmware')
                time.sleep(0.25)

    def line(self, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            raw = self.port.readline()
            if raw:
                text = raw.decode(errors='replace').strip()
                if text:
                    return text
        raise TimeoutError(f'the board sent nothing for {timeout} s')

    def expect(self, prefix, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            text = self.line(max(0.1, deadline - time.monotonic()))
            # A marker can arrive glued to the tail of a menu line, so search for it.
            if prefix in text:
                return text[text.index(prefix):]
            if text.startswith('ERR') or 'ROMLOAD refused' in text:
                raise RuntimeError(f'board: {text}')
        raise TimeoutError(f'no "{prefix}" from the board within {timeout} s')

    def command(self, text, payload=b'', timeout=10):
        self.port.write(text.encode() + b'\n' + payload)
        return self.expect('OK' if text[0] in 'EW' else 'CRC', timeout)

    def enter_loader(self):
        self.port.reset_input_buffer()
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            self.port.write(b'L')
            try:
                ready = self.expect('ROMLOAD READY', 2)
            except TimeoutError:
                continue
            # End any line of repeated 'L's, then start from a clean input.
            self.port.write(b'\n')
            time.sleep(0.3)
            self.port.reset_input_buffer()
            return ready
        raise TimeoutError('the board did not enter the ROM loader in 60 s: it must be in the NES boot menu '
                           '(run without --no-reset, or reboot it)')

    def erase(self, offset, count):
        while count > 0:
            step = min(count, 65536 - (offset & 0xFFFF))
            self.command(f'E {offset} {step}')
            offset += step
            count -= step

    def write(self, offset, data):
        data = data + b'\xff' * (-len(data) % 256)
        for at in range(0, len(data), CHUNK):
            chunk = data[at:at + CHUNK]
            self.command(f'W {offset + at} {len(chunk)} {signed(zlib.crc32(chunk))}', chunk)

    def verify(self, offset, data):
        reply = self.command(f'C {offset} {len(data)}')
        if int(reply.split()[1]) != signed(zlib.crc32(data)):
            raise RuntimeError(f'flash at ${offset:X} ({len(data)} bytes) does not match after loading')


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('roms', nargs='*', type=Path)
    p.add_argument('--target',choices=['rp2040','rp2350'],default='rp2040',help='firmware target; Pico 2 W enables advanced mappers and its larger store')
    p.add_argument('--port', help='serial port of the board; found automatically when only one Pico is attached')
    p.add_argument('--clear', action='store_true', help='empty the ROM store (the board shows its built-in demo)')
    p.add_argument('--dry-run', action='store_true', help='check and lay out the games; do not touch the board')
    p.add_argument('--no-reset', action='store_true', help='the board is already in the boot menu')
    a = p.parse_args()
    if bool(a.roms) == a.clear:
        p.error('name the .nes files to load, or --clear')
    try:
        games, directory, blobs = layout(a.roms,a.target) if a.roms else ([], b'', [])
    except (ValueError,OSError) as error:
        sys.exit(f'Refused: {error}')
    for cart, prg_at, prg_len, chr_at, chr_len in games:
        print(f'{cart.title}: mapper {cart.mapper}, PRG {prg_len} bytes at ${prg_at:X}'
              + (f', CHR {chr_len} bytes at ${chr_at:X}' if chr_len else ', CHR RAM')
              + (', PAL (50 Hz)' if pico_pal(cart.path) else ''))
    if games:
        used = max(o + len(d) for o, d in blobs) - DATA
        print(f'{len(games)} game(s), {used} of {ENDS[a.target] - DATA} ROM store bytes')
    if a.dry_run:
        return
    if not a.port:
        ports = find_ports()
        if len(ports) != 1:
            sys.exit(f'Found {len(ports)} Pico serial ports ({", ".join(ports) or "none"}); name one with --port')
        a.port = ports[0]
    load_store(directory, blobs, a.port, not a.no_reset, lambda text, done: print(text, flush=True))


def find_ports():
    """Serial ports of attached Raspberry Pi Pico boards (USB vendor 2E8A)."""
    from serial.tools import list_ports
    return [p.device for p in list_ports.comports() if p.vid == 0x2E8A]


def load_store(directory, blobs, port, reset, report):
    """Write a laid-out store to the board. report(text, fraction_done) is
    called as it goes. Used by this command line and by rom_loader_ui.pyw."""
    total = sum(len(d) for _, d in blobs) + len(directory) or 1
    done = 0
    report(f'Connecting to {port}' + (' (rebooting it into the boot menu)' if reset else ''), 0.0)
    board = Board(port, reset)
    try:
        ready=board.enter_loader()
        report(ready,0.0)
        import re
        match=re.search(r'end=(\d+)',ready)
        if not match: raise RuntimeError('Firmware did not advertise its ROM boundary')
        limit=int(match.group(1))
        if directory and struct.unpack_from('<H',directory,4)[0]==2:
            if 'pack=2' not in ready:
                board.port.write(b'Q\n')
                raise ValueError('Update the board firmware before loading version-2 mapper packs')
            if 'profile=1' in ready:
                from pico_cartridge import ADVANCED
                if any(directory[n] in ADVANCED or (directory[n]==34 and (directory[n+3]&1)==0) for n in range(48,len(directory),64)):
                    board.port.write(b'Q\n')
                    raise ValueError('This ROM pack needs Pico 2 W cartridge RAM; the connected board is Pico W')
        if any(offset<DATA or offset+len(data)>limit for offset,data in blobs):
            board.port.write(b'Q\n')
            raise ValueError("ROM pack exceeds this connected board's advertised store; choose the matching target")
        start = time.monotonic()
        board.erase(DIRECTORY, SECTOR)
        for offset, data in blobs:
            board.erase(offset, -(-len(data) // SECTOR) * SECTOR)
            board.write(offset, data)
            board.verify(offset, data)
            done += len(data)
            report(f'  wrote ${offset:X} ({len(data)} bytes)', done / total)
        if directory:
            board.write(DIRECTORY, directory)
            board.verify(DIRECTORY, directory)
        board.port.write(b'Q\n')
        board.expect('ROMLOAD BYE', 5)
        summary = board.expect('ROMSTORE', 30)
        report(summary, 1.0)
        if blobs:
            report(f'Loaded in {time.monotonic() - start:.1f} s; the board is back in its boot menu.', 1.0)
        else:
            report('The ROM store is empty; the board shows its built-in demo.', 1.0)
        return summary
    finally:
        board.port.close()


if __name__ == '__main__':
    main()
