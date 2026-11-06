#!/usr/bin/env python3
"""PH8057: bounded stock firmware readback and register observation, Linux only.

Default is PLAN ONLY: inspect sysfs/proc, issue no SG_IO and do not open a disk.
--run executes one explicitly selected phase, with no application retry:
  registers: E5 CK_COND=0 -> DF/FD XDATA[6300:6314] -> protocol15 (14 bytes).
  flash-tail: known 1024-byte prefix comparison -> cached flash ID RAM read ->
              five aligned missing-tail reads, returning 0x10000..0x111FF.
              No write/erase subcommands and no new JEDEC probe are issued.
Use an isolated, idle enclosure with test disks; no mounted/claimed USB sibling
is allowed.  This is not a firmware updater, full flash reader, SRAM test,
atomic-snapshot proof, or firmware qualification.  O_RDONLY is not a universal
SCSI safety policy: the fixed CDB allowlist below is part of the restriction.
"""
import argparse
import ctypes
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time
import zlib

SG_IO = 0x2285
ORIGINAL_SHA256 = '131bab19b558a25745c881c3c4193fd1f9fb541c0a6c89c7961bad31cecc60b2'
COMMANDS = (
    ('e5_no_ckcond', bytes.fromhex('85 06 00 00 00 00 00 00 00 00 00 00 00 00 E5 00'), 0),
    ('xdata_6300_6313', bytes.fromhex('DF 10 00 00 14 00 63 00 00 00 00 FD'), 20),
    ('protocol15', bytes.fromhex('85 1E 00 00 00 00 00 00 00 00 00 00 00 00 00 00'), 14),
)
FLASH_COMMANDS = (
    ('flash_prefix_00000', bytes.fromhex('DF 10 00 04 00 00 00 00 00 00 00 FA'), 1024),
    ('cached_flash_id_411e_4131', bytes.fromhex('DF 10 00 00 14 00 41 1E 00 00 00 FD'), 20),
    ('flash_tail_10000', bytes.fromhex('DF 10 00 04 00 00 00 00 01 00 00 FA'), 1024),
    ('flash_tail_10400', bytes.fromhex('DF 10 00 04 00 00 00 00 01 04 00 FA'), 1024),
    ('flash_tail_10800', bytes.fromhex('DF 10 00 04 00 00 00 00 01 08 00 FA'), 1024),
    ('flash_tail_10c00', bytes.fromhex('DF 10 00 04 00 00 00 00 01 0C 00 FA'), 1024),
    ('flash_tail_11000', bytes.fromhex('DF 10 00 02 00 00 00 00 01 10 00 FA'), 512),
)


class SgIoHdr(ctypes.Structure):
    # Linux <scsi/sg.h>, SG v3 ABI. Native pointer widths/alignment are required.
    _fields_ = [
        ('interface_id', ctypes.c_int), ('dxfer_direction', ctypes.c_int),
        ('cmd_len', ctypes.c_ubyte), ('mx_sb_len', ctypes.c_ubyte),
        ('iovec_count', ctypes.c_ushort), ('dxfer_len', ctypes.c_uint),
        ('dxferp', ctypes.c_void_p), ('cmdp', ctypes.c_void_p), ('sbp', ctypes.c_void_p),
        ('timeout', ctypes.c_uint), ('flags', ctypes.c_uint), ('pack_id', ctypes.c_int),
        ('usr_ptr', ctypes.c_void_p), ('status', ctypes.c_ubyte),
        ('masked_status', ctypes.c_ubyte), ('msg_status', ctypes.c_ubyte),
        ('sb_len_wr', ctypes.c_ubyte), ('host_status', ctypes.c_ushort),
        ('driver_status', ctypes.c_ushort), ('resid', ctypes.c_int),
        ('duration', ctypes.c_uint), ('info', ctypes.c_uint),
    ]


def read_text(path):
    return Path(path).read_text().strip()


def usb_parent(path):
    for p in (path, *path.parents):
        if (p / 'idVendor').is_file() and (p / 'idProduct').is_file():
            return p
    raise RuntimeError('The selected block device has no USB ancestor in sysfs.')


def inspect_target(device, expected_serial):
    selected = Path(device).resolve(strict=True)
    st = selected.stat()
    if not stat.S_ISBLK(st.st_mode):
        raise RuntimeError('Select a whole USB block device, not a regular file or sg character device.')
    devnum = f'{os.major(st.st_rdev)}:{os.minor(st.st_rdev)}'
    target = (Path('/sys/dev/block') / devnum).resolve(strict=True)
    if (target / 'partition').exists():
        raise RuntimeError('Select the whole disk, not a partition.')
    usb = usb_parent(target)
    vid, pid = read_text(usb / 'idVendor'), read_text(usb / 'idProduct')
    serial = read_text(usb / 'serial')
    if (vid.lower(), pid.lower()) != ('152d', 'a562'):
        raise RuntimeError(f'USB identity is {vid}:{pid}, not this project\'s 152d:a562.')
    if serial != expected_serial:
        raise RuntimeError('USB serial does not match the explicit --usb-serial argument.')
    drivers = [p.joinpath('driver').resolve().name for p in target.parents if p.joinpath('driver').is_symlink()]
    if 'usb-storage' not in drivers:
        raise RuntimeError('This first observation requires the studied usb-storage BOT path.')
    siblings = []
    for p in sorted(Path('/sys/class/block').iterdir()):
        resolved = p.resolve()
        if usb not in resolved.parents:
            continue
        siblings.append(dict(name=p.name, sysfs=str(resolved), dev=read_text(p / 'dev'),
                             partition=(p / 'partition').exists(),
                             holders=[x.name for x in (p / 'holders').iterdir()]))
    numbers = {x['dev'] for x in siblings}
    mounts = [line for line in Path('/proc/self/mountinfo').read_text().splitlines()
              if len(line.split()) > 2 and line.split()[2] in numbers]
    swaps = []
    for line in Path('/proc/swaps').read_text().splitlines()[1:]:
        name = line.split()[0]
        try:
            sw = Path(name).stat()
            number = f'{os.major(sw.st_rdev)}:{os.minor(sw.st_rdev)}'
            if stat.S_ISBLK(sw.st_mode) and number in numbers:
                swaps.append(name)
        except OSError:
            pass
    smartd = []
    for p in Path('/proc').iterdir():
        if not p.name.isdigit():
            continue
        try:
            if read_text(p / 'comm') == 'smartd':
                smartd.append(int(p.name))
        except OSError:
            pass
    blocked = []
    if mounts:
        blocked.append('A disk/partition in this enclosure is mounted.')
    if swaps:
        blocked.append('A disk/partition in this enclosure is active swap.')
    if any(x['holders'] for x in siblings):
        blocked.append('A disk/partition in this enclosure has a device-mapper/MD holder.')
    if smartd:
        blocked.append('smartd is running; use the intended quiet test environment.')
    return dict(selected_device=str(selected), selected_devnum=devnum,
                usb_sysfs=str(usb), usb_bus_port=usb.name, usb_vid=vid, usb_pid=pid,
                usb_serial=serial, usb_busnum=read_text(usb / 'busnum'),
                usb_devnum=read_text(usb / 'devnum'), drivers=drivers, siblings=siblings,
                mounts=mounts, swaps=swaps, smartd_pids=smartd, blocked=blocked,
                kernel=os.uname().release)


def verify_same_identity(before, after):
    for key in ('selected_device', 'selected_devnum', 'usb_sysfs', 'usb_bus_port',
                'usb_vid', 'usb_pid', 'usb_serial', 'usb_busnum', 'usb_devnum', 'drivers', 'siblings'):
        if before.get(key) != after.get(key):
            raise RuntimeError(f'Device identity/topology changed ({key}); no further SG_IO is allowed.')
    if after['blocked']:
        raise RuntimeError(' '.join(after['blocked']))


def accept_result(result):
    if result.get('ioctl_errno') is not None or result.get('ioctl_rc', 0) != 0:
        return False, 'SG_IO system call failed.'
    for key in ('host_status', 'driver_status', 'status', 'msg_status'):
        if result[key] != 0:
            return False, f'Nonzero {key}; no subsequent command is allowed.'
    if result['info'] & 1:
        return False, 'SG_INFO_CHECK; no subsequent command is allowed.'
    if result['resid'] != 0:
        return False, 'Unexpected short/overrun transfer.'
    if result['sb_len_wr']:
        return False, 'Unexpected sense bytes for this CK_COND=0/read sequence.'
    return True, 'Transport and SCSI status clean, requested length completed.'


def sg_read(fd, spec, ioctl_fn=None):
    if spec not in COMMANDS + FLASH_COMMANDS:
        raise ValueError('CDB is outside the fixed read/non-data command allowlist.')
    name, cdb, size = spec
    cmd = ctypes.create_string_buffer(cdb, len(cdb))
    data = ctypes.create_string_buffer(max(1, size))
    sense = ctypes.create_string_buffer(96)
    h = SgIoHdr()
    h.interface_id = ord('S')
    h.dxfer_direction = -3 if size else -1
    h.cmd_len = len(cdb)
    h.mx_sb_len = len(sense)
    h.dxfer_len = size
    h.dxferp = ctypes.addressof(data) if size else None
    h.cmdp = ctypes.addressof(cmd)
    h.sbp = ctypes.addressof(sense)
    h.timeout = 60000
    if ioctl_fn is None:
        libc = ctypes.CDLL(None, use_errno=True)
        libc.ioctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.POINTER(SgIoHdr)]
        libc.ioctl.restype = ctypes.c_int
        ioctl_fn = libc.ioctl
    started = time.monotonic()
    rc = ioctl_fn(fd, SG_IO, ctypes.byref(h))  # exactly one call; never retry
    elapsed = time.monotonic() - started
    errno_value = ctypes.get_errno() if rc < 0 else None
    received = max(0, min(size, size - h.resid)) if rc >= 0 else 0
    result = dict(name=name, cdb_hex=cdb.hex(' '), requested_bytes=size,
                  ioctl_rc=rc, ioctl_errno=errno_value, elapsed_seconds=round(elapsed, 6),
                  status=h.status, masked_status=h.masked_status, msg_status=h.msg_status,
                  host_status=h.host_status, driver_status=h.driver_status,
                  resid=h.resid, duration_ms=h.duration, info=h.info, sb_len_wr=h.sb_len_wr,
                  sense_hex=bytes(sense.raw[:min(h.sb_len_wr, 96)]).hex(' '),
                  data_hex=bytes(data.raw[:received]).hex(' '))
    result['accepted'], result['assessment'] = accept_result(result)
    return result


def load_original(path):
    raw = path.read_bytes()
    if len(raw) != 65536 or hashlib.sha256(raw).hexdigest() != ORIGINAL_SHA256:
        raise ValueError('The flash-tail phase requires the exact supplied ph8057-original.bin.')
    return raw


def crc_jms(data):
    if len(data) % 4:
        raise ValueError('CRC input length must be word aligned.')
    words = b''.join(data[i:i+4][::-1] for i in range(0, len(data), 4))
    value = zlib.crc32(words) ^ 0xFFFFFFFF
    return int(f'{value:032b}'[::-1], 2)


def assess_tail(original, tail):
    if len(original) != 0x10000 or len(tail) != 0x1200:
        raise ValueError('Unexpected original or missing-tail size.')
    observed = original + tail
    code = observed[0x1000:0x11000]
    header = observed[0xE00:0x1000]
    code_calculated = crc_jms(code[:0xFFF8])
    full_calculated = crc_jms(header + code[:0xFFFC])
    code_stored = int.from_bytes(code[0xFFF8:0xFFFC], 'big')
    full_stored = int.from_bytes(code[0xFFFC:0x10000], 'big')
    metadata_full = int.from_bytes(original[12:16], 'big')
    return dict(tail_length=len(tail), tail_sha256=hashlib.sha256(tail).hexdigest(),
                code_crc_calculated=f'{code_calculated:08X}', code_crc_stored=f'{code_stored:08X}',
                code_crc_matches=code_calculated == code_stored,
                full_crc_calculated=f'{full_calculated:08X}', full_crc_stored=f'{full_stored:08X}',
                metadata_full_crc=f'{metadata_full:08X}',
                full_crc_matches=full_calculated == full_stored == metadata_full,
                nvram_candidate_offset='11000', nvram_candidate_length=512,
                nvram_candidate_sha256=hashlib.sha256(tail[0x1000:]).hexdigest(),
                limitation='Observed required region, not a physical-capacity measurement or proven complete SPI backup. OEM use of the final512 bytes must be checked offline. No patched firmware was generated.')


def compare_registers(snapshot, descriptor):
    if len(snapshot) != 20 or len(descriptor) != 14:
        raise ValueError('Exact register payload lengths are required.')
    expected = bytes((9, 12, 0, snapshot[13], snapshot[1], snapshot[0],
                      snapshot[8], snapshot[4], snapshot[9], snapshot[5],
                      snapshot[10], snapshot[6], snapshot[7], snapshot[14]))
    labels = {0:'Count low', 1:'Count high', 4:'LBA low', 5:'LBA mid', 6:'LBA high',
              7:'Device', 8:'LBA low EXP', 9:'LBA mid EXP', 10:'LBA high EXP',
              13:'Error from getter15', 14:'Status from getter15',
              15:'630F, protocol-dependent meaning', 18:'6312, observed value only',
              19:'6313, observed value only'}
    return dict(expected_getter_hex=expected.hex(' '), actual_getter_hex=descriptor.hex(' '),
                matches=expected == descriptor,
                registers=[dict(address=f'{0x6300+i:04X}', value=f'{b:02X}', meaning=labels.get(i, 'unresolved'))
                           for i, b in enumerate(snapshot)],
                limitation='Two sequential reads; agreement does not prove atomicity, all-protocol freshness, or ownership under concurrent/internal commands.')


def kernel_log():
    proc = subprocess.run(['dmesg', '--raw'], capture_output=True, text=True, timeout=5)
    if proc.returncode:
        raise RuntimeError('Cannot read dmesg; aborting before further device commands.')
    return proc.stdout


def kernel_alerts(before, after, identity):
    previous = set(before.splitlines())
    tokens = [identity['usb_bus_port']] + [x['name'] for x in identity['siblings']]
    changed = [line for line in after.splitlines() if line not in previous]
    relevant = [line for line in changed if any(re.search(r'(?<![\w.-])' + re.escape(t) + r'(?![\w.-])', line) for t in tokens)]
    return [line for line in relevant if re.search(r'reset|disconnect|error|fail|timed? ?out|abort|offline', line, re.I)]


def save_report(path, report):
    tmp = path.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    tmp.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device', required=True, help='Explicit whole disk; no default /dev/sdb.')
    parser.add_argument('--usb-serial', required=True, help='Exact enclosure USB serial, not HDD serial.')
    parser.add_argument('--phase', choices=('registers','flash-tail'), default='registers')
    parser.add_argument('--original', type=Path, help='Exact original 65536-byte dump; required for flash-tail.')
    parser.add_argument('--run', action='store_true', help='Execute only the selected fixed phase after preflight. Default only prints/saves a plan.')
    parser.add_argument('--output', type=Path, help='New empty output directory; must not already exist.')
    args = parser.parse_args()
    if sys.platform != 'linux':
        parser.error('Linux is required.')
    if args.phase == 'flash-tail' and args.original is None:
        parser.error('--phase flash-tail requires --original ph8057-original.bin.')
    commands = FLASH_COMMANDS if args.phase == 'flash-tail' else COMMANDS
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out = args.output or Path(f'PH8057_stock_read_{stamp}')
    out.mkdir(parents=True, exist_ok=False)
    report_path = out / 'stock_probe.json'
    report = dict(tool='PH8057 stock read-only acquisition', utc=stamp, execute_requested=args.run,
                  phase=args.phase,
                  command_plan=[dict(name=n, cdb_hex=c.hex(' '), requested_bytes=l) for n,c,l in commands],
                  observations=[], status='STARTED',
                  restrictions='No write/erase/reset, no application retries; all hardware commands fixed. Kernel error handling may outlast the 60s SG_IO timeout and perform its own recovery.')
    fds = []
    try:
        original = load_original(args.original) if args.phase == 'flash-tail' else None
        if original is not None:
            report['original_sha256'] = ORIGINAL_SHA256
            report['flash_read_extent'] = 'USB payload10000..111FF; final physical SPI read11000..113FF. No bytes are programmed.'
        ident = inspect_target(args.device, args.usb_serial)
        report['identity'] = ident
        save_report(report_path, report)
        if ident['blocked']:
            raise RuntimeError(' '.join(ident['blocked']))
        if not args.run:
            report['status'] = 'PLAN_ONLY_NO_SG_IO'
            print('PLAN ONLY. No disk was opened and no SG_IO was sent.')
            return 0
        if os.geteuid() != 0:
            raise RuntimeError('--run requires root for this controlled SG_IO observation.')
        before = kernel_log()
        # Claim all whole disks on this enclosure. Kernel block claims also catch
        # mounted Btrfs members that are not the mountinfo source device.
        selected_fd = None
        for sibling in ident['siblings']:
            if sibling['partition']:
                continue
            path = '/dev/' + sibling['name']
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC | os.O_EXCL)
            fds.append(fd)
            st = os.fstat(fd)
            if not stat.S_ISBLK(st.st_mode) or f'{os.major(st.st_rdev)}:{os.minor(st.st_rdev)}' != sibling['dev']:
                raise RuntimeError('Block-device identity changed during exclusive open.')
            if sibling['dev'] == ident['selected_devnum']:
                selected_fd = fd
        if selected_fd is None:
            raise RuntimeError('Selected disk was not found in the USB sibling set.')
        verify_same_identity(ident, inspect_target(args.device, args.usb_serial))
        for spec in commands:
            verify_same_identity(ident, inspect_target(args.device, args.usb_serial))
            current = kernel_log()
            alerts = kernel_alerts(before, current, ident)
            if alerts:
                report['kernel_alerts'] = alerts
                raise RuntimeError('Target-related kernel recovery/error observed before the command; no SG_IO sent for it.')
            before = current
            result = sg_read(selected_fd, spec)
            report['observations'].append(result)
            save_report(report_path, report)
            after = kernel_log()
            alerts = kernel_alerts(before, after, ident)
            if alerts:
                report['kernel_alerts'] = alerts
                raise RuntimeError('Target-related kernel recovery/error observed; stopped without another command.')
            before = after
            if not result['accepted']:
                raise RuntimeError(result['assessment'])
            if spec[0] == 'flash_prefix_00000':
                prefix = bytes.fromhex(result['data_hex'])
                report['prefix_matches_original'] = prefix == original[:1024]
                save_report(report_path, report)
                if not report['prefix_matches_original']:
                    raise RuntimeError('Flash prefix differs from the supplied stock image; no high-address reads sent.')
            elif spec[0] == 'cached_flash_id_411e_4131':
                cached = bytes.fromhex(result['data_hex'])
                report['cached_flash_id'] = dict(id_bytes=cached[:3].hex(' '),
                                                kind_4130=f'{cached[18]:02X}',
                                                last_probe_opcode_4131=f'{cached[19]:02X}',
                                                limitation='Boot/probe cache, no fresh JEDEC command; capacity interpretation requires valid probe opcode and matching chip documentation.')
        if args.phase == 'registers':
            report['comparison'] = compare_registers(bytes.fromhex(report['observations'][1]['data_hex']),
                                                     bytes.fromhex(report['observations'][2]['data_hex']))
        else:
            tail = b''.join(bytes.fromhex(x['data_hex']) for x in report['observations'] if x['name'].startswith('flash_tail_'))
            report['tail_analysis'] = assess_tail(original, tail)
            tail_path = out / 'ph8057-stock-10000-111ff.bin'
            tail_path.write_bytes(tail)
            report['tail_file'] = tail_path.name
            if not report['tail_analysis']['code_crc_matches'] or not report['tail_analysis']['full_crc_matches']:
                raise RuntimeError('Read tail saved, but code/full CRC differs from the known image; stop for offline analysis.')
        report['status'] = 'CAPTURED_INITIAL_STOCK_OBSERVATION'
        print('Captured the selected phase. Send its output files for analysis; do not repeat automatically.')
        return 0
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        report['status'] = 'STOPPED'
        report['reason'] = str(exc)
        print(f'STOPPED: {exc}', file=sys.stderr)
        return 1
    finally:
        for fd in fds:
            os.close(fd)
        save_report(report_path, report)
        print(str(report_path.resolve()))


if __name__ == '__main__':
    raise SystemExit(main())