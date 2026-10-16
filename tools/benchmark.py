"""Measure a real-board game with repeatable USB controller input.

Rates are wall-clock telemetry; this does not certify audio fidelity. Results
include every sampled second, including startup, rather than a selected window.
"""
import argparse
import json
from pathlib import Path
import re
import time
import serial

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--port', required=True)
p.add_argument('--index', type=int, required=True)
p.add_argument('--seconds', type=int, default=40)
p.add_argument('--output', type=Path, required=True)
p.add_argument('--reset', action='store_true')
a = p.parse_args()
if not 0 <= a.index <= 9:
    p.error('USB menu selection supports indices 0..9')
if a.reset:
    with serial.Serial(a.port, 2417, timeout=.1):
        time.sleep(.2)
    time.sleep(2)
lines, rows, sent = [], [], set()
events = [(3, b's'), (12, b'R'), (25, b'a')]
if a.index == 0:
    events.insert(1, (7, b's'))
a.output.parent.mkdir(parents=True, exist_ok=True)
connect_deadline = time.monotonic() + 15
while True:
    try:
        connection = serial.Serial(a.port, 115200, timeout=.2)
        break
    except serial.SerialException:
        if time.monotonic() >= connect_deadline:
            raise
        time.sleep(.25)
with connection as s:
    s.write(str(a.index).encode())
    deadline = time.monotonic() + 120
    game_start = None
    while time.monotonic() < deadline:
        line = s.readline().decode(errors='replace').strip()
        if line:
            lines.append(line)
            print(line, flush=True)
        if 'NES PureMetal ' in line and 'mapper=' in line:
            game_start = time.monotonic()
        if game_start is not None:
            elapsed = time.monotonic() - game_start
            for at, key in events:
                if elapsed >= at and at not in sent:
                    s.write(key)
                    sent.add(at)
            row = {k: int(v) for k, v in re.findall(r'(\w+)=(-?\d+)', line)}
            if {'us', 'cycles', 'frames', 'lcd', 'samples', 'err', 'stop'} <= row.keys():
                rows.append(row)
            if elapsed >= a.seconds:
                break
a.output.with_suffix('.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')
if len(rows) < a.seconds - 2:
    raise SystemExit(f'Insufficient telemetry: {len(rows)} intervals')
duration = sum(r['us'] for r in rows)
result = {k: sum(r[k] for r in rows) * 1e6 / duration
          for k in ('cycles', 'frames', 'lcd', 'samples')}
result.update(seconds=duration / 1e6, intervals=len(rows),
              minimum_frames=min(r['frames'] for r in rows),
              errors=max(r['err'] for r in rows), stopped=max(r['stop'] for r in rows),
              debt_first=rows[0]['debt'], debt_last=rows[-1]['debt'],
              audio_live=min(r.get('audio_live', r.get('bt_live', 0)) for r in rows),
              underrun_first=rows[0].get('audio_underrun', rows[0].get('bt_underrun', 0)),
              underrun_last=rows[-1].get('audio_underrun', rows[-1].get('bt_underrun', 0)))
if all('bt_live' in r for r in rows):
    result['bt_live'] = min(r['bt_live'] for r in rows)
print(json.dumps(result, indent=2))
a.output.with_suffix('.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8', newline='\n')
if result['errors'] or result['stopped']:
    raise SystemExit('Board reported an emulator error or stopped CPU')
