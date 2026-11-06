#!/usr/bin/env python3
"""Offline-only validation of a rebuilt 67,072-byte PH8057 CK_COND update package."""
from pathlib import Path
import argparse
import json
from build_from_1bin import build, check_record, sha, read_package, read_stock_package, EXPECTED_OUT_SHA

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--candidate', required=True, type=Path)
    p.add_argument('--stock', type=Path, help='Optional exact original 1.bin for byte-for-byte rebuild')
    args=p.parse_args()
    c=read_package(args.candidate)
    if sha(c) != EXPECTED_OUT_SHA:
        raise ValueError('Unexpected candidate SHA256')
    check_record(c)
    if args.stock:
        raw=read_stock_package(args.stock)
        records=json.loads(Path(__file__).with_name('ckcond_revised_patch_records.json').read_text())
        if build(raw,records)!=c:
            raise ValueError('Candidate does not match deterministic rebuild')
        if c[0x10400:] != raw[0x10400:]:
            raise ValueError('OEM was changed')
        print('PASS: byte-for-byte verified against original readback')
    print('PASS: candidate SHA256, size and CRC verified')
    print('Scope: offline validation only; limited physical SMART success is documented separately')

if __name__=='__main__':
    main()
