#!/usr/bin/env python3
"""Read-only inspection of sector 0 and Atari/AHDI phantom partition entries.

Does NOT write to the target block device. Copies a 512-byte evidence sample
under /root and checks disk identity via ATA serial before reading it.
"""
import argparse
from pathlib import Path
import re
import subprocess
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('device', help='e.g. /dev/sdc')
    ap.add_argument('expected_serial', help='e.g. TEST-SERIAL-B')
    args = ap.parse_args()
    d = Path(args.device).resolve(strict=True)
    if not re.fullmatch(r'sd[a-z]+', d.name) or str(d) != '/dev/' + d.name:
        sys.exit('Refusing non-/dev/sdX target')
    ident = subprocess.run(['smartctl', '-d', 'sat', '-i', str(d)],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           text=True, timeout=90, check=False)
    m = re.search(r'^Serial Number:\s*(\S+)', ident.stdout, re.M)
    if not m or m.group(1) != args.expected_serial:
        sys.exit(f'SERIAL MISMATCH: got {m.group(1) if m else None}, expected {args.expected_serial}')
    sectors = int((Path('/sys/class/block') / d.name / 'size').read_text().strip())
    with d.open('rb', buffering=0) as f:
        sector0 = f.read(512)
    if len(sector0) != 512:
        sys.exit(f'Failed to read 512 bytes from {d}')
    evidence = Path('/root') / f'ph8057-{args.expected_serial}-sector0-before.bin'
    evidence.write_bytes(sector0)
    print('ATA serial:', args.expected_serial)
    print('Sectors:', sectors)
    print('Saved LBA0 sample:', evidence)
    print('AHDI primary entries (based on Linux block/partitions/atari.h):')
    any_valid = False
    for n in range(4):
        off = 0x1c6 + 12*n
        flag = sector0[off]
        ident = sector0[off+1:off+4]
        st = int.from_bytes(sector0[off+4:off+8], 'big')
        size = int.from_bytes(sector0[off+8:off+12], 'big')
        ascii_alnum = all(48 <= b <= 57 or 65 <= b <= 90 or 97 <= b <= 122 for b in ident)
        valid = bool(flag & 1) and ascii_alnum and st <= sectors and st+size <= sectors
        any_valid |= valid
        print(f'  slot {n+1}: flag=0x{flag:02x}, id={ident!r}, start={st}, size={size}, valid={valid}')
    print('Kernel-style AHDI recognition would be:', 'YES' if any_valid else 'NO')
    print('NOTE: kernel partition entries can be stale if LBA0 was rewritten since the last rescan.')
    return 0

if __name__ == '__main__':
    sys.exit(main())
