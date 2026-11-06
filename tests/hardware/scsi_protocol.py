#!/usr/bin/env python3
"""Bounded, deterministic, read-only SCSI/SAT negative probes.

Important safety invariant: no SCSI WRITE, FORMAT, UNMAP, SECURITY OUT,
ATA write/erase, vendor-specific opcode, or sg_raw data-out is used.
The target is still an experimental USB/SATA bridge; firmware faults are possible.
"""
import dataclasses
import json
import random
import subprocess
import time
from typing import List

SAFE_OPCODES = frozenset({0x00, 0x03, 0x12, 0x1A, 0x25, 0x28, 0x5A, 0x85, 0x9E, 0xA0})
SAFE_ATA = frozenset({0xE5, 0xEC})  # CHECK POWER MODE, IDENTIFY DEVICE

@dataclasses.dataclass(frozen=True)
class Case:
    name: str
    cdb: bytes
    alloc: int = 0
    should_succeed: bool = False


def case(name, cdb, alloc=0, should_succeed=False):
    result = Case(name, bytes.fromhex(cdb), alloc, should_succeed)
    assert_case_is_read_only(result)
    return result


def assert_case_is_read_only(c):
    if not (6 <= len(c.cdb) <= 16):
        raise ValueError('Refusing unusual CDB length')
    if c.cdb[0] not in SAFE_OPCODES:
        raise ValueError('Refusing unapproved opcode')
    if c.cdb[0] == 0x85 and c.cdb[14] not in SAFE_ATA:
        raise ValueError('Refusing unapproved ATA command')
    if c.alloc < 0 or c.alloc > 512:
        raise ValueError('Refusing excessive data-in allocation')
    if c.cdb[0] == 0x28:
        # READ(10): never read more than one 512-byte sector and no huge LBA.
        lba = int.from_bytes(c.cdb[2:6], 'big')
        count = int.from_bytes(c.cdb[7:9], 'big')
        if lba > 8 or count > 1:
            raise ValueError('READ(10) outside bounded test range')
    return True


def baseline_cases():
    return [
        case('test_unit_ready', '00 00 00 00 00 00', 0, True),
        case('request_sense', '03 00 00 00 12 00', 18, True),
        case('inquiry_standard', '12 00 00 00 60 00', 96, True),
        case('inquiry_vpd_pages', '12 01 00 00 ff 00', 255),
        case('inquiry_vpd_invalid_page', '12 01 fe 00 40 00', 64),
        case('inquiry_reserved_bit', '12 80 00 00 24 00', 36),
        case('inquiry_zero_alloc', '12 00 00 00 00 00'),
        case('inquiry_short_alloc', '12 00 00 00 01 00', 1),
        case('mode_sense6_all', '1a 00 3f 00 c0 00', 192),
        case('mode_sense6_bad_page', '1a 00 3e 00 40 00', 64),
        case('mode_sense6_reserved_bit', '1a 80 3f 00 40 00', 64),
        case('read_capacity10', '25 00 00 00 00 00 00 00 00 00', 8, True),
        case('read_capacity10_invalid_flag', '25 80 00 00 00 00 00 00 00 00', 8),
        case('mode_sense10_all', '5a 00 3f 00 00 00 00 00 c0 00', 192),
        case('mode_sense10_invalid_page', '5a 00 3e 00 00 00 00 00 40 00', 64),
        case('report_luns', 'a0 00 00 00 00 00 00 00 00 80 00 00', 128),
        case('report_luns_invalid_select', 'a0 00 7f 00 00 00 00 00 00 80 00 00', 128),
        case('report_luns_short_alloc', 'a0 00 00 00 00 00 00 00 00 08 00 00', 8),
        case('read10_zero_blocks', '28 00 00 00 00 00 00 00 00 00'),
        case('read_capacity16', '9e 10 00 00 00 00 00 00 00 00 00 00 00 20 00 00', 32),
        case('read_capacity16_bad_service_action', '9e 1f 00 00 00 00 00 00 00 00 00 00 00 20 00 00', 32),
        case('ata_check_power_mode_ckcond', '85 06 20 00 00 00 00 00 00 00 00 00 00 00 e5 00'),
        case('ata_check_power_mode_no_ckcond', '85 06 00 00 00 00 00 00 00 00 00 00 00 00 e5 00'),
        case('ata_check_power_mode_invalid_protocol', '85 e6 20 00 00 00 00 00 00 00 00 00 00 00 e5 00'),
        case('ata_identify_pio_in', '85 08 0e 00 01 00 00 00 00 00 00 00 00 00 ec 00', 512),
        case('ata_identify_ckcond', '85 08 2e 00 01 00 00 00 00 00 00 00 00 00 ec 00', 512),
    ]


def bounded_fuzz(count, seed=0x8057):
    """Mutate only approved read/no-data command *fields*, not opcodes.

    No arbitrary ATA command register mutation. No data-out. All lengths bounded.
    """
    rng = random.Random(seed)
    cases = []
    for idx in range(count):
        kind = idx % 5
        if kind == 0:
            # Malformed INQUIRY EVPD page and short allocations.
            page = rng.choice([0, 0x80, 0x83, 0xFE, 0xFF])
            alloc = rng.choice([0, 1, 2, 3, 5, 8, 36, 96, 255])
            b = bytes([0x12, 1, page, 0, alloc, 0])
            c = Case(f'fuzz_inquiry_{idx}', b, alloc)
        elif kind == 1:
            # MODE SENSE(6): invalid page and reserved-field combinations.
            page = rng.choice([0x3F, 0x3E, 0x1F, 0x00, 0x2A])
            alloc = rng.choice([0, 1, 4, 8, 16, 32, 64, 192])
            b = bytes([0x1A, rng.choice([0, 0x80]), page, 0, alloc, 0])
            c = Case(f'fuzz_mode6_{idx}', b, alloc)
        elif kind == 2:
            # REPORT LUNS with invalid select report or truncated buffers.
            sr = rng.choice([0, 1, 2, 3, 0x7F, 0xFF])
            alloc = rng.choice([0, 4, 8, 12, 16, 32, 128])
            b = bytearray(12)
            b[0], b[2] = 0xA0, sr
            b[6:10] = alloc.to_bytes(4, 'big')
            c = Case(f'fuzz_luns_{idx}', bytes(b), alloc)
        elif kind == 3:
            # READ CAPACITY(10) invalid reserved bits; read only.
            b = bytes([0x25, rng.choice([0x00, 0x01, 0x80, 0xFF]), 0, 0, 0, 0, 0, 0, 0, 0])
            c = Case(f'fuzz_capacity_{idx}', b, 8)
        else:
            # ATA non-data CHECK POWER MODE with CK_COND/protocol mutations.
            # ATA command stays E5, a pure status query.
            b = bytearray(bytes.fromhex('85 06 20 00 00 00 00 00 00 00 00 00 00 00 e5 00'))
            b[1] = rng.choice([0x06, 0x16, 0x26, 0xE6])
            b[2] = rng.choice([0x00, 0x20, 0x80, 0xA0])
            c = Case(f'fuzz_sat_e5_{idx}', bytes(b), 0)
        assert_case_is_read_only(c)
        cases.append(c)
    return cases


def send_case(device, c, timeout=45):
    assert_case_is_read_only(c)
    cmd = ['sg_raw', '--readonly', '--timeout=%s' % timeout]
    if c.alloc:
        cmd += ['--request=%d' % c.alloc]
    cmd += [device] + ['%02x' % b for b in c.cdb]
    start = time.monotonic()
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           timeout=timeout + 10, check=False)
        result = {'rc': p.returncode,
                  'stdout': p.stdout[:1024].hex(),
                  'stderr': p.stderr[:2048].decode('utf-8', 'replace')}
        result['classification'] = 'accepted' if p.returncode == 0 else 'rejected_or_failed'
    except subprocess.TimeoutExpired:
        result = {'rc': None, 'classification': 'HOST_TIMEOUT', 'stderr': 'subprocess timed out'}
    result.update({'device': device, 'case': c.name, 'cdb': c.cdb.hex(),
                   'data_in_bytes': c.alloc, 'expected_success': c.should_succeed,
                   'elapsed_s': round(time.monotonic() - start, 3), 'epoch': time.time()})
    return result


def run_suite(devices: List[str], count: int, emit, stop_event=None, seed=0x8057, timeout=45):
    suite = baseline_cases() + bounded_fuzz(count, seed)
    for i, c in enumerate(suite):
        for device in devices:
            if stop_event is not None and stop_event.is_set():
                return
            emit(send_case(device, c, timeout=timeout))
            time.sleep(0.025)
