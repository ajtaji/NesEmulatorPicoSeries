"""Regenerate the cartridge header correction lookup; no ROMs are read."""
from pathlib import Path
import csv

root=Path(__file__).resolve().parents[1]
with (root/'rom_metadata.csv').open(newline='') as f:
    entries=sorted((int(r['crc32'],16),int(r['mapper'])) for r in csv.DictReader(f))
assert len({c for c,m in entries})==len(entries)
text='; Header mapper corrections from MesenNesDB; CRC32 of PRG+CHR, never filenames.\n'
text+='; Metadata only: no timing, CPU, video or audio overrides.\n'
text+='Procedure.i RomDatabaseMapper(crc.i)\n  Select crc&$FFFFFFFF\n'
for crc,mapper in entries:
    text+=f'    Case ${crc:08X} : ProcedureReturn {mapper}\n'
text+='  EndSelect\n  ProcedureReturn -1\nEndProcedure\n'
(root/'rom_metadata.pi4').write_text(text)
