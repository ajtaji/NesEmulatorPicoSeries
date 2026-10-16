"""Read real-board USB output for a bounded interval; never emulates firmware."""
import argparse
from pathlib import Path
import time
import serial

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--port', required=True)
p.add_argument('--seconds', type=float, default=12)
p.add_argument('--output', type=Path, required=True)
a = p.parse_args()
with serial.Serial(a.port, 115200, timeout=.2) as s, a.output.open('w', encoding='utf-8', newline='\n') as out:
    end = time.monotonic() + a.seconds
    while time.monotonic() < end:
        line = s.readline().decode(errors='replace').rstrip('\r\n')
        if line:
            print(line, flush=True)
            out.write(line + '\n')
            out.flush()
