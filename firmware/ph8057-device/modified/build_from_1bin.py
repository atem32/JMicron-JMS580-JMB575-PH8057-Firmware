#!/usr/bin/env python3
"""Offline-only re-packager for the exact PH8057 user readback.

No device access; no firmware flashing. Maps original 67,072-byte JMicron
readback to the audited 70,144-byte CK_COND-revised CODE delta and computes
all four bridge CRC fields. Inputs are checked against pinned SHA256.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import stat
import zlib

STOCK_SHA = '481e62548a3a7b9cf07e8552fa2e2a9d66a5f89d222a66301ad22982c8aca7c5'
STOCK_FULL_SHA = 'ef5ad9af3f3b290c565a4dc65933d539b7bb8b8051ac9bd45386932a77862c09'
FULL_REVISED_SHA = '2aaece707763b5dab32c46cf10c17c88345d73b8635365a354dcffe8817b422b'
EXPECTED_OUT_SHA = 'f8406e8b83e9f97695ce4ae395a90b29e28d8210bc40c09087f3f6b43f33fd5b'
CODE_OFF = 0x400
OEM_OFF = 0x10400
BIN_SIZE = 0x10600


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def rev(v: int, bits: int) -> int:
    out = 0
    for i in range(bits):
        out = out << 1 | (v >> i & 1)
    return out


def crc(data: bytes) -> int:
    if len(data) % 4:
        raise ValueError('Unaligned CRC input')
    words = b''.join(data[i:i+4][::-1] for i in range(0,len(data),4))
    return rev(zlib.crc32(words) ^ 0xffffffff, 32)


def check_record(data: bytes, *, allow_blank_header_crc: bool = False) -> dict:
    if len(data) != BIN_SIZE:
        raise ValueError(f'File length {len(data)} instead of {BIN_SIZE}')
    if data[:10] != bytes.fromhex('01 00 15 2d 05 80 03 03 05 05'):
        raise ValueError('Wrong JMicron JMS580 package header')
    if data[0x200:0x204] != bytes.fromhex('5a c3 69 e1'):
        raise ValueError('Wrong metadata header signature')
    values = {
        'metadata_header_crc': crc(data[:0x200] + data[0x200:0x3fc]),
        'code_crc': crc(data[CODE_OFF:CODE_OFF+0xfff8]),
        'full_crc': crc(data[:0x200] + data[CODE_OFF:CODE_OFF+0xfffc]),
    }
    if int.from_bytes(data[0x3fc:0x400], 'big') not in ({0,values['metadata_header_crc']} if allow_blank_header_crc else {values['metadata_header_crc']}):
        raise ValueError('Metadata header CRC invalid')
    if values['code_crc'] != int.from_bytes(data[0x103f8:0x103fc], 'big'):
        raise ValueError('CODE CRC invalid')
    if values['full_crc'] != int.from_bytes(data[0x103fc:0x10400], 'big'):
        raise ValueError('Full CRC invalid')
    if data[0x20c:0x210] != data[0x103fc:0x10400]:
        raise ValueError('Full CRC header mirror invalid')
    return {k: f'{v:08x}' for k,v in values.items()}


def build(source: bytes, patch_records: list) -> bytes:
    if len(source) != BIN_SIZE or sha(source) != STOCK_SHA:
        raise ValueError('Wrong input. Must be the exact original user 1.bin, SHA256 ' + STOCK_SHA)
    check_record(source, allow_blank_header_crc=True)
    candidate = bytearray(source)
    visited = set()
    for item in patch_records:
        cpu = int(item['cpu'],16) if isinstance(item['cpu'],str) else item['cpu']
        old = bytes.fromhex(item['old'])
        new = bytes.fromhex(item['new'])
        if cpu < 0 or cpu + len(old) > 0xffec or not old or len(old)!=len(new):
            raise ValueError(f'Unsafe patch at {cpu:04x}')
        places = set(range(cpu,cpu+len(old)))
        if visited & places:
            raise ValueError(f'Overlapping patch at {cpu:04x}')
        visited.update(places)
        at = CODE_OFF + cpu
        if candidate[at:at+len(old)] != old:
            raise ValueError(f'Input bytes mismatch at CPU {cpu:04x}')
        candidate[at:at+len(old)] = new
    candidate[0x103f8:0x103fc] = crc(candidate[CODE_OFF:0x103f8]).to_bytes(4,'big')
    candidate[0x103fc:0x10400] = crc(candidate[:0x200] + candidate[CODE_OFF:0x103fc]).to_bytes(4,'big')
    candidate[0x20c:0x210] = candidate[0x103fc:0x10400]
    candidate[0x3fc:0x400] = crc(candidate[:0x200] + candidate[0x200:0x3fc]).to_bytes(4,'big')
    result = bytes(candidate)
    check_record(result)
    if result[0:0x200] != source[0:0x200]:
        raise ValueError('Wrapper changed unexpectedly')
    if result[0x10400:] != source[0x10400:]:
        raise ValueError('OEM was modified')
    allowed = {CODE_OFF + addr for addr in visited} | set(range(0x103f8,0x10400)) | set(range(0x20c,0x210)) | set(range(0x3fc,0x400))
    if any(a!=b and i not in allowed for i,(a,b) in enumerate(zip(source,result))):
        raise ValueError('Unexpected difference from original file')
    if EXPECTED_OUT_SHA != '__REPLACE_AFTER_BUILD__' and sha(result) != EXPECTED_OUT_SHA:
        raise ValueError('Unexpected candidate SHA256')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stock',required=True,type=Path,help='Exact 67,072-byte original 1.bin')
    parser.add_argument('--patches',default=Path(__file__).with_name('ckcond_revised_patch_records.json'),type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    if not args.stock.is_file() or not stat.S_ISREG(args.stock.stat().st_mode):
        raise ValueError('Source must be a regular file')
    if args.output.is_symlink() or args.output.resolve() == args.stock.resolve() or args.output.is_dir() or (args.output.exists() and args.output.stat().st_nlink>1):
        raise ValueError('Refusing to overwrite source or symlink/hardlinked output')
    records=json.loads(args.patches.read_text())
    out=build(args.stock.read_bytes(),records)
    args.output.write_bytes(out)
    print('WROTE',args.output,'SIZE',len(out),'SHA256',sha(out))
    print('STATUS: EXPERIMENTAL / NOT HARDWARE QUALIFIED / NO SPI ACTION PERFORMED')

if __name__=='__main__':
    main()
