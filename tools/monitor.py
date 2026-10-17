"""Read real-board USB output for a bounded interval; never emulates firmware.

A board can leave the USB bus and come back during the window: right after an
upload an RP2350 may still be re-enumerating when the port first opens, and a
program that reboots does the same. The capture reopens the port and carries on.
A port that stays gone for --gone seconds ends the capture with an error,
because a board that has really dropped off USB does not come back by itself.
"""
import argparse
from pathlib import Path
import sys
import time
import serial

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--port', required=True)
p.add_argument('--seconds', type=float, default=12)
p.add_argument('--output', type=Path, required=True)
p.add_argument('--gone', type=float, default=10,
               help='seconds the port may stay missing before the capture fails (default 10)')
a = p.parse_args()


def note(text):
    print(f'monitor: {text}', file=sys.stderr, flush=True)


start = time.monotonic()
end = start + a.seconds
port = None
missing_since = None      # when the port was last seen gone, or None while open
with a.output.open('w', encoding='utf-8', newline='\n') as out:
    while time.monotonic() < end:
        now = time.monotonic()
        if port is None:
            try:
                port = serial.Serial(a.port, 115200, timeout=.2)
            except serial.SerialException:
                if missing_since is None:
                    missing_since = now
                if now - missing_since > a.gone:
                    note(f'{a.port} has been missing for {a.gone:g} s; the board is off USB '
                         f'(captured {now - start:.1f} s of output)')
                    sys.exit(2)
                time.sleep(.25)
                continue
            if missing_since is not None and now - start > .5:
                note(f'{a.port} back after {now - missing_since:.1f} s; capture continues')
            missing_since = None
        try:
            line = port.readline().decode(errors='replace').rstrip('\r\n')
        except (serial.SerialException, OSError) as error:
            note(f'{a.port} left the bus at {time.monotonic() - start:.1f} s ({type(error).__name__}); reopening')
            try:
                port.close()
            except (serial.SerialException, OSError):
                pass
            port = None
            missing_since = time.monotonic()
            continue
        if line:
            print(line, flush=True)
            out.write(line + '\n')
            out.flush()
    if port is not None:
        port.close()
