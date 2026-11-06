#!/usr/bin/env python3
"""Short, size-limited Linux usbmon text captures and BOT CSW parsing.

This is a sampling tool, NOT complete 24h BOT coverage.
"""
import gzip
import os
import re
import select
import shutil
import subprocess
import time
from pathlib import Path

PACKET_RE = re.compile(rb'\b(?:B[io]|C[io]):(\d+):(\d+):\d+')
HEX_RE = re.compile(rb'\b[0-9a-fA-F]+\b')
CBW_SIG = bytes.fromhex('55534243')
CSW_SIG = bytes.fromhex('55534253')


def decode_bot_payload(line):
    if b'=' not in line:
        return None
    suffix = line.split(b'=', 1)[1]
    hx = b''.join(HEX_RE.findall(suffix))
    try:
        return bytes.fromhex(hx.decode('ascii'))
    except ValueError:
        return None


def analyze_lines(lines):
    stats = {'cbw': 0, 'csw': 0, 'csw_pass': 0, 'csw_cmd_failed': 0,
             'csw_phase_error': 0, 'csw_invalid_status': 0,
             'csw_residue_gt_requested': 0, 'matched_tag': 0, 'unmatched_tag': 0}
    tags = {}
    examples = []
    for line in lines:
        data = decode_bot_payload(line)
        if not data:
            continue
        if data.startswith(CBW_SIG) and len(data) >= 31:
            tag = int.from_bytes(data[4:8], 'little')
            requested = int.from_bytes(data[8:12], 'little')
            tags[tag] = (requested, data[13], data[15])
            stats['cbw'] += 1
        elif data.startswith(CSW_SIG) and len(data) >= 13:
            tag = int.from_bytes(data[4:8], 'little')
            residue = int.from_bytes(data[8:12], 'little')
            status = data[12]
            stats['csw'] += 1
            if status == 0:
                stats['csw_pass'] += 1
            elif status == 1:
                stats['csw_cmd_failed'] += 1
            elif status == 2:
                stats['csw_phase_error'] += 1
            else:
                stats['csw_invalid_status'] += 1
            if tag in tags:
                stats['matched_tag'] += 1
                requested, lun, opcode = tags.pop(tag)
                if residue > requested:
                    stats['csw_residue_gt_requested'] += 1
                    if len(examples) < 10:
                        examples.append({'error': 'residue_gt_requested', 'tag': tag,
                                         'residue': residue, 'requested': requested,
                                         'lun': lun, 'opcode': opcode})
            else:
                stats['unmatched_tag'] += 1
            if status >= 2 and len(examples) < 10:
                examples.append({'error': 'bad_status', 'tag': tag, 'status': status})
    return {'stats': stats, 'examples': examples,
            'note': 'Unmatched tags can be normal at the start/end of a short capture.'}


def make_usbmon_available(bus):
    folder = Path('/sys/kernel/debug/usb/usbmon')
    path = folder / f'{bus}u'
    if path.exists():
        return path
    if shutil.which('modprobe'):
        subprocess.run(['modprobe', 'usbmon'], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=10, check=False)
    if not folder.is_dir() and shutil.which('mount'):
        subprocess.run(['mount', '-t', 'debugfs', 'debugfs', '/sys/kernel/debug'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=10, check=False)
    return path if path.exists() else None


def capture(bus, devnum, dest_prefix, seconds=12, cap_bytes=16*1024*1024):
    source = make_usbmon_available(bus)
    if source is None:
        return {'available': False, 'reason': 'usbmon interface not available'}
    dest = str(dest_prefix) + '.usbmon.gz'
    proc = subprocess.Popen(['cat', str(source)], stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, start_new_session=True)
    start = time.monotonic()
    size = 0
    saved = 0
    lines = []
    partial = b''
    # Keep a bounded in-memory subset to analyze BOT headers.
    try:
        with gzip.open(dest, 'wb', compresslevel=1) as f:
            while time.monotonic() - start < seconds and size < cap_bytes:
                ready, _, _ = select.select([proc.stdout], [], [], 0.8)
                if not ready:
                    continue
                block = os.read(proc.stdout.fileno(), 65536)
                if not block:
                    break
                partial += block
                *complete, partial = partial.split(b'\n')
                for line in complete:
                    m = PACKET_RE.search(line)
                    if not m or int(m.group(1)) != bus or int(m.group(2)) != devnum:
                        continue
                    row = line + b'\n'
                    f.write(row)
                    size += len(row)
                    saved += 1
                    if len(lines) < 100000:
                        lines.append(row)
                    if size >= cap_bytes:
                        break
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)
        proc.stdout.close()
    report = analyze_lines(lines)
    report.update({'available': True, 'bus': bus, 'device_number': devnum,
                   'duration_seconds': round(time.monotonic() - start, 2),
                   'saved_rows': saved, 'uncompressed_bytes': size,
                   'path': dest, 'partial_analysis': len(lines) >= 100000})
    return report
