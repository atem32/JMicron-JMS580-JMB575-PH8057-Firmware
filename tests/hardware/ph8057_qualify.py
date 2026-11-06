#!/usr/bin/env python3
"""PH8057/JMS580+JMB575 destructive multi-LUN firmware qualification.

Only use on disposable disks. The optional excluded disk is verified and never
sent a fio write command, but a firmware LUN-routing bug might still affect it.
Production disks MUST be physically unplugged from this bridge.
"""
import argparse
import dataclasses
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import select
import subprocess
import sys
import tarfile
import threading
import time

from scsi_protocol import run_suite
from usbmon_trace import capture
from smart import parse_smart, compare_smart

GIB = 1024**3
MIB = 1024**2
EXPECTED_BRIDGE = ('152d', 'a562')
MIN_DISK_BYTES = 40 * GIB
MAX_DISK_BYTES = 3_000_000_000_000  # reject 4TB+ production media
FATAL_KERNEL = re.compile(r'usb .*reset (?:SuperSpeed|high-speed|full-speed)|USB disconnect|I/O error|timed out|uas_eh_abort_handler|hostbyte=|device offline|rejecting I/O|blk_update_request', re.I)


class Abort(RuntimeError):
    pass


def run(args, timeout=30):
    try:
        return subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=timeout, text=True, errors='replace', check=False)
    except subprocess.TimeoutExpired as exc:
        raise Abort('Command timed out: ' + ' '.join(map(str, args))) from exc


def require_tools():
    for name in ('fio', 'sg_raw', 'smartctl', 'lsblk', 'wipefs', 'journalctl'):
        if not shutil.which(name):
            raise Abort('Missing ' + name + '; run: apt install -y fio sg3-utils smartmontools sdparm usbutils')
    v = run(['fio', '--version'], timeout=8).stdout.strip()
    if not v.startswith('fio-'):
        raise Abort(f'Wrong fio executable ({v!r}). Need Linux fio 3.x (not Fiona).')


def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')


def safe_serial_from_smart(dev):
    p = run(['smartctl', '-d', 'sat', '-i', dev], timeout=90)
    match = re.search(r'^Serial Number:\s*(\S+)', p.stdout, re.M)
    model = re.search(r'^Device Model:\s*(.+)$', p.stdout, re.M)
    if p.returncode < 0 or p.returncode & 0x07 or not match or not model:
        raise Abort(f'Cannot confirm ATA identity for {dev}; smartctl rc={p.returncode}: {p.stdout[-600:]} {p.stderr[-300:]}')
    return match.group(1), model.group(1).strip()


def usb_ancestor(devname):
    sysblock = Path('/sys/class/block') / devname
    if not sysblock.exists():
        raise Abort(f'No sysfs device: {devname}')
    real = sysblock.resolve()
    for anc in (real, *real.parents):
        vendor, product = anc / 'idVendor', anc / 'idProduct'
        if vendor.exists() and product.exists():
            try:
                vid, pid = vendor.read_text().strip().lower(), product.read_text().strip().lower()
                bus = int((anc / 'busnum').read_text())
                devnum = int((anc / 'devnum').read_text())
            except (OSError, ValueError) as exc:
                raise Abort(f'Invalid USB sysfs for {devname}: {exc}') from exc
            return (str(anc), vid, pid, bus, devnum)
    raise Abort(f'Not a USB disk according to sysfs: {devname}')


def whole_disk_name(device):
    real = Path(device).resolve(strict=True)
    if not str(real).startswith('/dev/') or not real.name.startswith('sd'):
        raise Abort('Refusing non-/dev/sdX target ' + str(real))
    if not (Path('/sys/class/block') / real.name / 'device').exists():
        raise Abort('No SCSI device in sysfs: ' + str(real))
    return real.name


def stable_path(realpath):
    directory = Path('/dev/disk/by-path')
    if not directory.exists():
        raise Abort('Missing /dev/disk/by-path; cannot pin target LUN')
    paths = []
    for path in directory.iterdir():
        if '-part' in path.name or not path.is_symlink():
            continue
        if path.resolve() == Path(realpath):
            paths.append(str(path))
    if not paths:
        raise Abort('No stable by-path link for ' + realpath)
    paths.sort(key=lambda x: (0 if 'scsi' in x else 1, len(x), x))
    return paths[0]


def lsblk_column(device, col):
    p = run(['lsblk', '-dn', '-o', col, '--', device], timeout=15)
    if p.returncode:
        raise Abort(f'lsblk failure on {device}: {p.stderr}')
    return p.stdout.strip()


def base_checks(devname):
    device = '/dev/' + devname
    if lsblk_column(device, 'TYPE') != 'disk':
        raise Abort(f'Not a whole disk: {device}')
    if lsblk_column(device, 'TRAN') != 'usb':
        raise Abort(f'Not a USB transport: {device}')
    if lsblk_column(device, 'RO') != '0':
        raise Abort(f'Read-only/block-disabled disk: {device}')
    nodes = run(['lsblk', '-nr', '-o', 'TYPE', '--', device], timeout=15)
    if nodes.returncode or nodes.stdout.split() != ['disk']:
        raise Abort(f'Partitions, RAID, LVM or children detected: {device}')
    mounts = run(['lsblk', '-nr', '-o', 'MOUNTPOINTS', '--', device], timeout=15)
    if mounts.returncode or mounts.stdout.strip():
        raise Abort(f'Mounted device or unavailable mount inventory: {device}')
    sig = run(['wipefs', '--no-act', '--noheadings', '--output', 'TYPE', '--', device], timeout=90)
    if sig.returncode or sig.stdout.strip():
        raise Abort(f'Filesystem/RAID signature detected: {device}, wipefs={sig.stdout.strip()} {sig.stderr.strip()}')
    holderdir = Path('/sys/class/block') / devname / 'holders'
    if holderdir.is_dir() and any(holderdir.iterdir()):
        raise Abort(f'Active device-mapper/RAID holders: {device}')
    if any(line.split()[0] == device for line in Path('/proc/swaps').read_text().splitlines()[1:] if line.split()):
        raise Abort(f'Swap in use: {device}')
    try:
        size = int((Path('/sys/class/block') / devname / 'size').read_text().strip()) * 512
        logical = int((Path('/sys/class/block') / devname / 'queue/logical_block_size').read_text().strip())
    except Exception as exc:
        raise Abort(f'Cannot read size: {device}: {exc}') from exc
    if not (MIN_DISK_BYTES <= size < MAX_DISK_BYTES):
        raise Abort(f'Refusing disk outside safe 40GiB..3TB interval: {device}, {size} bytes')
    if logical not in (512, 4096):
        raise Abort(f'Unexpected logical sector {logical} on {device}')
    return size, logical


@dataclasses.dataclass
class Target:
    input: str
    path: str
    device: str
    devname: str
    size: int
    sector: int
    serial: str
    model: str
    usb_parent: str
    vid: str
    pid: str
    bus: int
    devnum: int
    lun: str


def inspect_target(input_name):
    devname = whole_disk_name(input_name)
    device = '/dev/' + devname
    size, sector = base_checks(devname)
    parent, vid, pid, bus, devnum = usb_ancestor(devname)
    if (vid, pid) != EXPECTED_BRIDGE:
        raise Abort(f'Unexpected USB bridge {vid}:{pid} for {device} (need 152d:a562)')
    serial, model = safe_serial_from_smart(device)
    scsi_id = (Path('/sys/class/block') / devname / 'device').resolve().name
    if not re.fullmatch(r'\d+:\d+:\d+:\d+', scsi_id):
        raise Abort(f'Unexpected SCSI LUN identity: {scsi_id}')
    return Target(input_name, stable_path(device), device, devname, size, sector,
                  serial, model, parent, vid, pid, bus, devnum, scsi_id)


def enumerate_bridge_disk_names(parent):
    found = set()
    for x in Path('/sys/class/block').glob('sd*'):
        if not (x / 'device').exists():
            continue
        try:
            par, *_ = usb_ancestor(x.name)
        except Abort:
            continue
        if par == parent:
            # Some multi-bay bridges expose empty, zero-capacity LUN stubs.
            try:
                capacity_sectors = int((x / 'size').read_text().strip())
            except (OSError, ValueError):
                capacity_sectors = 1  # fail closed on unreadable capacity
            if capacity_sectors > 0:
                found.add(x.name)
    return found


class Guard:
    def __init__(self, names, excluded_device=None, excluded_serial=None):
        if len(names) not in (2, 3):
            raise Abort('Exactly two or three explicit disposable test disks required')
        if bool(excluded_device) != bool(excluded_serial):
            raise Abort('Provide BOTH --excluded-device and --excluded-serial, or neither')
        if excluded_device and len(names) != 2:
            raise Abort('An explicitly excluded bridge disk is only allowed with two test disks')
        self.targets = [inspect_target(x) for x in names]
        self.excluded = inspect_target(excluded_device) if excluded_device else None
        if self.excluded is not None and self.excluded.serial != excluded_serial:
            raise Abort(f'Excluded disk ATA serial mismatch: {self.excluded.serial} != {excluded_serial}')
        all_disks = self.targets + ([self.excluded] if self.excluded else [])
        if len({t.usb_parent for t in all_disks}) != 1:
            raise Abort('Selected and excluded disks must belong to the SAME JMS580 bridge')
        if len({t.lun for t in all_disks}) != len(all_disks) or len({t.serial for t in all_disks}) != len(all_disks):
            raise Abort('Duplicate SCSI LUN or ATA serial; refusing ambiguous routing')
        if len({t.path for t in all_disks}) != len(all_disks):
            raise Abort('Duplicate by-path LUN detected')
        self.usb_parent = self.targets[0].usb_parent
        self.all_disks = all_disks
        self.expected_members = {t.devname for t in all_disks}
        present = enumerate_bridge_disk_names(self.usb_parent)
        if present != self.expected_members:
            raise Abort(f'Extra/missing disks on same bridge: detected={sorted(present)} target/explicitly_excluded={sorted(self.expected_members)}. Physically unplug any production LUNs; list each nonproduction excluded disk explicitly.')

    def light(self):
        present = enumerate_bridge_disk_names(self.usb_parent)
        if present != self.expected_members:
            raise Abort(f'Bridge LUN set changed: {sorted(present)} != {sorted(self.expected_members)}')
        for t in self.all_disks:
            if str(Path(t.path).resolve()) != t.device:
                raise Abort(f'by-path rebind: {t.path}')
            current, vid, pid, bus, devnum = usb_ancestor(t.devname)
            if current != t.usb_parent or (vid, pid) != (t.vid, t.pid):
                raise Abort(f'USB route changed: {t.device}')
            if (Path('/sys/class/block') / t.devname / 'device').resolve().name != t.lun:
                raise Abort(f'SCSI LUN mapping changed: {t.device}')
            if int((Path('/sys/class/block') / t.devname / 'size').read_text()) * 512 != t.size:
                raise Abort(f'Size changed: {t.device}')
            if bus != t.bus or devnum != t.devnum:
                raise Abort(f'USB device re-enumerated: {t.device} (from {t.devnum} to {devnum})')

    def deep(self):
        self.light()
        for t in self.all_disks:
            size, logical = base_checks(t.devname)
            if (size, logical) != (t.size, t.sector):
                raise Abort(f'Device size/sector changed: {t.device}')
            serial, model = safe_serial_from_smart(t.path)
            if serial != t.serial or model != t.model:
                raise Abort(f'ATA identity changed: {t.path}')



def rand64k_regions(targets):
    """Keep random fio verification data away from LBA0.

    The Linux Atari/AHDI partition parser accepts weak on-disk signatures;
    running randwrite at offset zero can cause bogus sdc1/sdc2 to appear,
    correctly triggering our non-empty-partition safety guard. This returns
    a 256 MiB scratch window at 512 MiB, disjoint from the rand4k window at
    1 GiB and sequential windows starting at 2 GiB.
    """
    off, length = 512 * MIB, 256 * MIB
    for t in targets:
        if off + length > t.size:
            raise Abort('Disk too small for offset-safe rand64k region')
    return [(off, length) for _ in targets]


def fio_jobfile(targets, offsets_sizes, *, rw, bs, depth, verify='crc32c', backlog=None):
    if len(targets) not in (1, 2, 3) or len(offsets_sizes) != len(targets):
        raise Abort('Fio requires one to three explicit, bounded target regions')
    if backlog is not None and (not isinstance(backlog, int) or backlog < 1):
        raise Abort('verify_backlog must be a positive block count or None')
    lines = ['[global]', 'ioengine=libaio', 'direct=1', 'thread=1',
             'allow_file_create=0', 'allow_mounted_write=0', 'group_reporting=0',
             'iodepth=%d' % depth, 'rw=' + rw, 'bs=' + bs,
             'verify=' + verify, 'do_verify=1', 'verify_fatal=1',
             'verify_dump=1', 'end_fsync=1', 'randrepeat=0']
    if backlog is not None:
        lines.append('verify_backlog=%d' % backlog)
    for idx, (t, (offset, size)) in enumerate(zip(targets, offsets_sizes), 1):
        if offset < 0 or size < 4096 or offset + size > t.size:
            raise Abort(f'Out-of-bounds fio job disk{idx}: {offset}+{size}>{t.size}')
        lines += ['', f'[disk{idx}]', 'filename=' + t.path.replace('\\', '\\\\').replace(':', r'\:'),
                  f'offset={offset}', f'size={size}']
    return '\n'.join(lines) + '\n'


def align_down(n, unit):
    return n - (n % unit)


def window_for(t, index, window_bytes):
    # 2GiB low-LBA scratch region is reserved for random passes.
    start = 2 * GIB
    usable = align_down(t.size - start, MIB)
    if usable < MIB:
        raise Abort('Device too small for sequential window')
    window_count = (usable + window_bytes - 1) // window_bytes
    pos = (index % window_count) * window_bytes
    off = start + pos
    size = align_down(min(window_bytes, usable - pos), MIB)
    return off, size


class Recorder:
    def __init__(self, out):
        self.dir = Path(out).expanduser().resolve()
        self.dir.mkdir(parents=True, exist_ok=False)
        self.lock = threading.Lock()
        self.started_at = utc_now()
        self.counters = {'fio_passes': 0, 'fio_errors': 0, 'sg_calls': 0,
                         'sg_rejected_or_failed': 0, 'sg_host_timeouts': 0,
                         'sg_expected_success_failures': 0, 'sg_slow_calls': 0,
                         'usbmon_captures': 0, 'usb_csw_phase_errors': 0,
                         'usb_csw_residue_anomalies': 0, 'kernel_suspects': 0,
                         'monitor_warnings': 0}
        self.verified_by_serial = {}  # logical bytes, only after both fio passes pass
        self.phase_summaries = {}
        self.events('start', output=str(self.dir))

    def append_json(self, name, record):
        with self.lock:
            with (self.dir / name).open('a', encoding='utf-8') as f:
                f.write(json.dumps(record, sort_keys=True, ensure_ascii=True) + '\n')

    def events(self, kind, **data):
        rec = {'time': utc_now(), 'type': kind, **data}
        self.append_json('events.jsonl', rec)
        print(f'[{rec["time"]}] {kind}: {json.dumps(data, ensure_ascii=True)[:500]}', flush=True)

    def sg_event(self, entry):
        self.append_json('sg_results.jsonl', entry)
        slow = entry.get('elapsed_s', 0) >= 2.0
        with self.lock:
            self.counters['sg_calls'] += 1
            if slow:
                self.counters['sg_slow_calls'] += 1
            if entry['classification'] == 'HOST_TIMEOUT':
                self.counters['sg_host_timeouts'] += 1
            elif entry['classification'] == 'rejected_or_failed':
                self.counters['sg_rejected_or_failed'] += 1
                if entry.get('expected_success'):
                    self.counters['sg_expected_success_failures'] += 1
        if slow:
            self.events('scsi_slow_response', case=entry.get('case'),
                        device=entry.get('device'), elapsed_s=entry['elapsed_s'],
                        classification=entry['classification'])

    def verified_phase(self, name, per_disk, seconds):
        with self.lock:
            for item in per_disk:
                serial = item['serial']
                totals = self.verified_by_serial.setdefault(serial, {'write_bytes': 0, 'read_bytes': 0})
                totals['write_bytes'] += item['write_bytes']
                totals['read_bytes'] += item['read_bytes']
            self.phase_summaries[name] = {'seconds': seconds, 'disks': per_disk}
        self.append_json('phase_summary.jsonl', {'phase': name, 'seconds': seconds, 'disks': per_disk})

    def capture_event(self, entry):
        self.append_json('usbmon_results.jsonl', entry)
        with self.lock:
            if entry.get('available'):
                self.counters['usbmon_captures'] += 1
            stats = entry.get('stats', {})
            self.counters['usb_csw_phase_errors'] += stats.get('csw_phase_error', 0) + stats.get('csw_invalid_status', 0)
            self.counters['usb_csw_residue_anomalies'] += stats.get('csw_residue_gt_requested', 0)


class Background:
    def __init__(self, guard, rec, args):
        self.guard, self.rec, self.args = guard, rec, args
        self.stop = threading.Event()
        self.failed = threading.Event()
        self.errors = []
        self.threads = []

    def fail(self, msg):
        self.errors.append(msg)
        self.rec.events('MONITOR_FATAL', reason=msg)
        self.failed.set()
        self.stop.set()

    def start(self):
        # Pure I/O mode MUST NOT inject active SCSI or SMART commands during fio.
        # Even a host-side sg_raw timeout formerly aborted the whole data test.
        workers = [self.guard_thread, self.kernel_thread, self.usbmon_thread]
        if self.args.mode in ('io', 'benchmark', 'diagnose', 'protocol-load'):
            workers.append(self.io_progress_thread)
        if self.args.mode == 'protocol-load':
            workers.extend((self.smart_thread, self.protocol_thread))
        for func in workers:
            th = threading.Thread(target=self.worker, args=(func,), daemon=True,
                                  name=func.__name__)
            self.threads.append(th)
            th.start()

    def worker(self, func):
        try:
            func()
        except Exception as exc:
            # Passive monitors and protocol probes must not kill a valid fio
            # integrity run just because their own read-only request failed.
            if func in (self.usbmon_thread, self.kernel_thread,
                        self.smart_thread, self.protocol_thread,
                        self.io_progress_thread):
                with self.rec.lock:
                    self.rec.counters['monitor_warnings'] += 1
                self.rec.events('MONITOR_UNAVAILABLE', worker=func.__name__, error=str(exc))
            else:
                self.fail(f'{func.__name__}: {exc}')

    def guard_thread(self):
        while not self.stop.is_set():
            self.guard.light()
            self.stop.wait(5)

    def smart_thread(self):
        smartdir = self.rec.dir / 'smart'
        smartdir.mkdir(exist_ok=True)
        seq = 0
        while not self.stop.is_set():
            for idx, t in enumerate(self.guard.targets, 1):
                if self.stop.is_set():
                    return
                try:
                    p = run(['smartctl', '-d', 'sat', '-n', 'standby,3', '-A', '-H', t.path], timeout=90)
                    detail = f'rc={p.returncode}\n{p.stdout}\n{p.stderr}'
                    standby = (p.returncode == 3 and 'STANDBY' in p.stdout.upper())
                    if not standby and (p.returncode < 0 or p.returncode & 0x1f):
                        with self.rec.lock:
                            self.rec.counters['monitor_warnings'] += 1
                        self.rec.events('SMART_POLL_WARNING', disk=idx, serial=t.serial,
                                        returncode=p.returncode)
                except Abort as exc:
                    detail = f'host_timeout_or_error={exc}'
                    with self.rec.lock:
                        self.rec.counters['monitor_warnings'] += 1
                    self.rec.events('SMART_POLL_WARNING', disk=idx, reason=str(exc))
                (smartdir / f'poll_disk{idx}.log').open('a').write(
                    f'\n==== {utc_now()} SMART {detail}\n')
            seq += 1
            if seq % 60 == 0 and shutil.which('sdparm'):
                for idx, t in enumerate(self.guard.targets, 1):
                    p = run(['sdparm', '--page=po', t.path], timeout=20)
                    (smartdir / f'power_disk{idx}.log').open('a').write(
                        f'\n==== {utc_now()} rc={p.returncode} ====\n{p.stdout}\n{p.stderr}\n')
            self.stop.wait(self.args.smart_interval)

    def io_progress_thread(self):
        # /sys is passive: no SMART/SCSI commands, no intentional media wakeups.
        # Linux block stat fields: rd ios, merges, sectors, rd ms,
        # wr ios, merges, sectors, wr ms, inflight, io ms, weighted ms.
        def stats(devname):
            values = [int(x) for x in (Path('/sys/class/block') / devname / 'stat').read_text().split()]
            if len(values) < 11:
                raise Abort('Malformed block stats for ' + devname)
            return values

        baseline = {t.serial: stats(t.devname) for t in self.guard.targets}
        previous = baseline
        last = time.monotonic()
        while not self.stop.wait(self.args.progress_interval):
            self.guard.light()
            now = time.monotonic()
            elapsed = max(now - last, 0.001)
            data = {}
            current = {}
            for t in self.guard.targets:
                cur = stats(t.devname)
                current[t.serial] = cur
                prev = previous[t.serial]
                base = baseline[t.serial]
                rd_ios = cur[0] - prev[0]
                wr_ios = cur[4] - prev[4]
                data[t.serial] = {
                    'read_gib': round((cur[2] - base[2]) * 512 / GIB, 3),
                    'written_gib': round((cur[6] - base[6]) * 512 / GIB, 3),
                    'interval_read_mib_s': round((cur[2] - prev[2]) * 512 / MIB / elapsed, 2),
                    'interval_write_mib_s': round((cur[6] - prev[6]) * 512 / MIB / elapsed, 2),
                    'interval_read_await_ms': round((cur[3] - prev[3]) / rd_ios, 2) if rd_ios > 0 else None,
                    'interval_write_await_ms': round((cur[7] - prev[7]) / wr_ios, 2) if wr_ios > 0 else None,
                    'interval_busy_pct': round((cur[9] - prev[9]) / (elapsed * 10), 1),
                    'inflight': cur[8],
                }
            self.rec.events('io_progress', interval_seconds=round(elapsed, 2), disks=data)
            previous, last = current, now

    def protocol_thread(self):
        seq = 0
        while not self.stop.is_set():
            self.guard.light()
            before = self.rec.counters['sg_host_timeouts']
            run_suite([t.path for t in self.guard.targets], self.args.fuzz_count,
                      self.rec.sg_event, self.stop, seed=0x8057 + seq,
                      timeout=self.args.sg_timeout)
            seq += 1
            self.rec.events('protocol_round_complete', round=seq,
                            commands=self.rec.counters['sg_calls'],
                            new_host_timeouts=self.rec.counters['sg_host_timeouts'] - before)
            # A read-only SCSI request timing out is a finding, not an excuse
            # to discard the ongoing independent fio CRC verification.
            self.stop.wait(self.args.protocol_interval)

    def kernel_thread(self):
        # Kernel log is collected again in full at shutdown; this live stream
        # stops writes quickly if this particular bridge resets or loses I/O.
        p = subprocess.Popen(['journalctl', '-k', '-f', '--since', 'now', '--no-pager', '-o', 'short-iso'],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             bufsize=0)
        pending = b''
        try:
            while not self.stop.is_set() and p.poll() is None:
                ready, _, _ = select.select([p.stdout], [], [], 0.8)
                if not ready:
                    continue
                block = os.read(p.stdout.fileno(), 65536)
                if not block:
                    break
                pending += block
                *rows, pending = pending.split(b'\n')
                for raw in rows:
                    line = raw.decode('utf-8', 'replace')
                    if not FATAL_KERNEL.search(line):
                        continue
                    if self.guard.usb_parent.rsplit('/', 1)[-1] in line or any(
                            re.search(r'\b' + re.escape(t.devname) + r'\b', line)
                            for t in self.guard.targets):
                        self.rec.append_json('kernel_live_suspects.jsonl',
                                             {'time': utc_now(), 'line': line})
                        with self.rec.lock:
                            self.rec.counters['kernel_suspects'] += 1
                        self.fail('Kernel I/O/USB error: ' + line[-350:])
                        return
            if not self.stop.is_set():
                # EOF or process termination means live evidence is missing,
                # even if a final journal query later succeeds.
                raise RuntimeError(f'Kernel monitor ended unexpectedly: rc={p.poll()}')
        finally:
            p.terminate()
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait(timeout=3)
            p.stdout.close()

    def usbmon_thread(self):
        if self.args.no_usbmon:
            return
        capture_idx = 0
        folder = self.rec.dir / 'usbmon'
        folder.mkdir(exist_ok=True)
        while not self.stop.is_set():
            t = self.guard.targets[0]
            prefix = folder / f'capture_{capture_idx:03d}'
            report = capture(t.bus, t.devnum, prefix, seconds=12, cap_bytes=16*MIB)
            self.rec.capture_event(report)
            if not report.get('available'):
                self.rec.events('usbmon_unavailable', reason=report.get('reason', 'unknown'))
                return
            stats = report.get('stats', {})
            if stats.get('csw_phase_error', 0) or stats.get('csw_invalid_status', 0) or stats.get('csw_residue_gt_requested', 0):
                self.fail('Captured BOT CSW phase/residue anomaly')
                return
            capture_idx += 1
            self.stop.wait(self.args.usbmon_interval)

    def shutdown(self):
        self.stop.set()
        # Give an in-flight SCSI request enough time to hit its bounded
        # subprocess timeout and exit; never archive a still-writing thread.
        for th in self.threads:
            th.join(timeout=max(65, self.args.sg_timeout + 20))
            if th.is_alive():
                self.rec.events('BACKGROUND_STILL_RUNNING', worker=th.name)


def smart_snapshot(guard, rec, label):
    smartdir = rec.dir / 'smart'
    smartdir.mkdir(exist_ok=True)
    for i, t in enumerate(guard.targets, 1):
        command = ['smartctl', '-d', 'sat', '-x', t.path]
        try:
            p = run(command, timeout=60)
            text = f'$ {" ".join(command)}\nExit code: {p.returncode}\n{p.stdout}\n{p.stderr}'
            snapshot = parse_smart(p.stdout, p.returncode)
        except (Abort, OSError) as exc:
            text = f'$ {" ".join(command)}\nAcquisition error: {exc}\n'
            snapshot = parse_smart('')
            snapshot['acquisition_errors'].append('acquisition_error:' + str(exc))
        (smartdir / f'{label}_disk{i}.txt').write_text(text, encoding='utf-8')
        snapshot.update(expected_serial=t.serial, path=t.path, device=t.device,
                        captured_at=utc_now())
        (smartdir / f'{label}_disk{i}.json').write_text(
            json.dumps(snapshot, indent=2), encoding='utf-8')
        if snapshot['serial'] is not None and snapshot['serial'] != t.serial:
            raise Abort(f'ATA identity changed during SMART snapshot: {t.path}')
        if (not snapshot['parse_complete'] or not snapshot['acquisition_complete'] or
                snapshot['health_alert']):
            with rec.lock:
                rec.counters['monitor_warnings'] += 1
            rec.events('SMART_SNAPSHOT_WARNING', disk=i, serial=t.serial,
                       label=label, errors=snapshot['errors'],
                       acquisition_errors=snapshot['acquisition_errors'],
                       health_alert=snapshot['health_alert'])
    if shutil.which('sdparm'):
        for i, t in enumerate(guard.targets, 1):
            p = run(['sdparm', '--page=po', t.path], timeout=20)
            (smartdir / f'{label}_power_disk{i}.txt').write_text(
                f'$ sdparm --page=po {t.path}\nExit code: {p.returncode}\n{p.stdout}\n{p.stderr}', encoding='utf-8')


def capture_host_environment(rec):
    for key, cmd in [('lsblk.txt', ['lsblk', '-o', 'NAME,PATH,SIZE,TYPE,MODEL,SERIAL,TRAN,FSTYPE,MOUNTPOINTS']),
                     ('uname.txt', ['uname', '-a']),
                     ('usb_tree.txt', ['lsusb', '-t'])]:
        if not shutil.which(cmd[0]):
            continue
        p = run(cmd, timeout=20)
        (rec.dir / key).write_text(p.stdout + '\n' + p.stderr, encoding='utf-8')


def expected_fio_sizes(job_text):
    """Recover exact byte count for each generated fio job; no implicit truncation."""
    sizes = {}
    current = None
    for line in job_text.splitlines():
        if re.fullmatch(r'\[disk[1-3]\]', line):
            current = line[1:-1]
        elif current is not None and line.startswith('size='):
            if current in sizes:
                raise Abort(f'Duplicate fio size: {current}')
            sizes[current] = int(line.split('=', 1)[1])
    if not sizes or set(sizes) != {f'disk{i}' for i in range(1, len(sizes) + 1)} or min(sizes.values()) <= 0:
        raise Abort('Malformed/generated fio job sizes')
    return sizes


def validate_fio_results(data, sizes, targets):
    """Require exact logical write and readback bytes and zero job errors.

    Full readback is necessary but a PASS still depends on fio's CRC checking.
    Physical /sys bytes are logged separately because they may include retries.
    """
    jobs = data.get('jobs')
    if not isinstance(jobs, list) or len(jobs) != len(targets) or len(targets) not in (1, 2, 3):
        raise Abort(f'Unexpected fio job count: {len(jobs) if isinstance(jobs, list) else None}')
    names = {j.get('jobname') for j in jobs}
    if names != set(sizes) or len(names) != len(jobs):
        raise Abort(f'Unexpected fio job identity/order: {names}')
    report = []
    for job in jobs:
        name = job['jobname']
        idx = int(name.removeprefix('disk')) - 1
        if job.get('error', -1) != 0:
            raise Abort(f'Fio JSON job {name}: error={job.get("error")}')
        read, write = job.get('read', {}), job.get('write', {})
        read_bytes, write_bytes = read.get('io_bytes'), write.get('io_bytes')
        expected = sizes[name]
        if not all(isinstance(v, int) for v in (read_bytes, write_bytes)) or \
                read_bytes != expected or write_bytes != expected:
            raise Abort(f'Fio {name} incomplete read/write: read={read_bytes}, write={write_bytes}, expected={expected}')
        if read.get('total_ios', 0) < 1 or write.get('total_ios', 0) < 1:
            raise Abort(f'Fio {name}: no verified reads or writes')
        report.append({'name': name, 'serial': targets[idx].serial,
                       'read_bytes': read_bytes, 'write_bytes': write_bytes,
                       'read_ios': read['total_ios'], 'write_ios': write['total_ios'],
                       'read_bw_kib': read.get('bw'), 'write_bw_kib': write.get('bw'),
                       'read_mean_lat_ns': read.get('clat_ns', {}).get('mean'),
                       'write_mean_lat_ns': write.get('clat_ns', {}).get('mean')})
    return sorted(report, key=lambda x: x['name'])


def make_diagnostic_result(name, phase):
    seconds = max(phase['seconds'], 0.001)
    disks = phase['disks']
    total_io = sum(x['read_bytes'] + x['write_bytes'] for x in disks)
    return {
        'phase': name,
        'seconds': seconds,
        'aggregate_verified_mib_s': round(total_io / MIB / seconds, 2),
        'disks': [{
            'serial': d['serial'],
            'read_mib_s': round(d['read_bw_kib'] / 1024, 2) if isinstance(d['read_bw_kib'], (int, float)) else None,
            'write_mib_s': round(d['write_bw_kib'] / 1024, 2) if isinstance(d['write_bw_kib'], (int, float)) else None,
        } for d in disks],
    }


def write_diagnostic_result(rec, name):
    result = make_diagnostic_result(name, rec.phase_summaries[name])
    rec.events('diagnostic_result', **result)


def run_fio_phase(guard, rec, background, name, content, phase_timeout=7200, job_targets=None):
    guard.deep()
    job_targets = guard.targets if job_targets is None else job_targets
    if not job_targets or any(t not in guard.targets for t in job_targets):
        raise Abort('Fio job includes target outside guarded bridge')
    if background.failed.is_set():
        raise Abort('; '.join(background.errors))
    sizes = expected_fio_sizes(content)
    file = rec.dir / (name + '.fio')
    output = rec.dir / (name + '.json')
    log = rec.dir / (name + '.stderr.log')
    file.write_text(content, encoding='ascii')
    rec.events('phase_begin', phase=name, jobfile=file.name,
               expected_bytes_per_lun=sizes, timeout_seconds=phase_timeout)
    with log.open('w') as f:
        p = subprocess.Popen(['fio', '--output-format=json', '--output=' + str(output), str(file)],
                             stdout=f, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, start_new_session=True,
                             cwd=str(rec.dir))
        began = time.monotonic()
        try:
            while p.poll() is None:
                if background.failed.is_set():
                    raise Abort('; '.join(background.errors))
                if time.monotonic() - began > phase_timeout:
                    raise Abort(f'Fio phase timeout {name}: {phase_timeout} s')
                guard.light()
                time.sleep(3)
        except (BaseException, KeyboardInterrupt):
            # Stop the fio process group, including its children.
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(p.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                p.wait(timeout=10)
            raise
    if background.failed.is_set():
        raise Abort('; '.join(background.errors))
    if p.returncode:
        rec.counters['fio_errors'] += 1
        raise Abort(f'Fio phase {name} returned {p.returncode}; inspect {log} and {output}')
    try:
        data = json.loads(output.read_text())
        report = validate_fio_results(data, sizes, job_targets)
    except (Abort, OSError, KeyError, ValueError, TypeError) as exc:
        rec.counters['fio_errors'] += 1
        raise Abort(f'Fio result/CRC evidence invalid for {name}: {exc}') from exc
    seconds = round(time.monotonic() - began, 1)
    rec.counters['fio_passes'] += 1
    rec.verified_phase(name, report, seconds)
    rec.events('phase_verified', phase=name, seconds=seconds, jobs=report,
               combined_logical_read_gib=round(sum(j['read_bytes'] for j in report)/GIB, 3),
               combined_logical_write_gib=round(sum(j['write_bytes'] for j in report)/GIB, 3))
    return report


def kernel_final(rec, start_local, guard):
    p = run(['journalctl', '-k', '--since', start_local, '--no-pager', '-o', 'short-iso'], timeout=90)
    (rec.dir / 'kernel.log').write_text(p.stdout + '\n' + p.stderr, encoding='utf-8')
    if p.returncode != 0:
        raise RuntimeError(f'Final kernel log acquisition failed: rc={p.returncode}')
    matches = [ln for ln in p.stdout.splitlines() if FATAL_KERNEL.search(ln)]
    selected = [ln for ln in matches if guard.usb_parent.rsplit('/', 1)[-1] in ln or any(
        re.search(r'\b' + re.escape(t.devname) + r'\b', ln) for t in guard.targets)]
    (rec.dir / 'kernel_suspects.txt').write_text('\n'.join(matches) + '\n', encoding='utf-8')
    (rec.dir / 'kernel_target_errors.txt').write_text('\n'.join(selected) + '\n', encoding='utf-8')
    return selected


def smart_raw_attributes(file):
    """Compatibility view of numeric attributes from either smartctl table."""
    if not file.exists():
        return {}
    parsed = parse_smart(file.read_text(errors='replace'))
    return {row['name']: row['raw_value'] for row in parsed['attributes'].values()
            if row['raw_value'] is not None}


def smart_delta(rec, guard):
    """Match baseline/end captures by their ATA serial, never by /dev/sdX."""
    smartdir = rec.dir / 'smart'
    expected = {t.serial for t in guard.targets}
    records = {}
    capture_errors = []
    for label in ('before', 'end_on_exit'):
        by_serial = {}
        for file in sorted(smartdir.glob(label + '_disk*.txt')):
            parsed = parse_smart(file.read_text(errors='replace'))
            parsed['file'] = file.name
            serial = parsed['serial']
            if serial not in expected:
                capture_errors.append(f'{file.name}:unconfirmed_or_unexpected_serial')
                continue
            if serial in by_serial:
                capture_errors.append(f'{label}:duplicate_serial:{serial}')
                by_serial[serial]['errors'].append('duplicate_serial_capture')
                by_serial[serial]['parse_complete'] = False
                continue
            by_serial[serial] = parsed
        records[label] = by_serial
    deltas = []
    concerning = False
    for idx, target in enumerate(guard.targets, 1):
        begin = records['before'].get(target.serial, parse_smart(''))
        end = records['end_on_exit'].get(target.serial, parse_smart(''))
        item, worse = compare_smart(begin, end)
        item.update(disk=idx, serial=target.serial,
                    baseline_file=begin.get('file'), end_file=end.get('file'),
                    baseline_errors=begin['errors'], end_errors=end['errors'],
                    baseline_acquisition_errors=begin['acquisition_errors'],
                    end_acquisition_errors=end['acquisition_errors'],
                    baseline_exit_code=begin['exit_code'], end_exit_code=end['exit_code'],
                    capture_errors=list(capture_errors))
        item['parse_complete'] &= not capture_errors
        deltas.append(item)
        concerning |= worse
    (rec.dir / 'smart_delta.json').write_text(json.dumps(deltas, indent=2), encoding='utf-8')
    return deltas, concerning


def idle_check(guard, rec, minutes):
    if minutes <= 0:
        return
    guard.deep()
    rec.events('idle_begin', minutes=minutes,
               caution='No host-side SMART or protocol polling during idle; other OMV services may poll.')
    deadline = time.monotonic() + minutes * 60
    while time.monotonic() < deadline:
        time.sleep(min(30, max(0, deadline - time.monotonic())))
        guard.light()
    for idx, t in enumerate(guard.targets, 1):
        p = run(['smartctl', '-d', 'sat', '-n', 'standby,3', '-i', t.path], timeout=30)
        (rec.dir / f'idle_power_disk{idx}.txt').write_text(
            f'Command: smartctl -d sat -n standby,3 -i {t.path}\n'
            f'Exit: {p.returncode}\n{p.stdout}\n{p.stderr}', encoding='utf-8')
        rec.events('idle_check', disk=idx, rc=p.returncode,
                   power_lines=[x for x in p.stdout.splitlines() if 'Power mode' in x or 'STANDBY' in x])


def archive(rec):
    filename = Path(str(rec.dir) + '.tar.gz')
    with tarfile.open(filename, 'w:gz', compresslevel=4) as tf:
        tf.add(rec.dir, arcname=rec.dir.name)
    return filename


def main():
    parser = argparse.ArgumentParser(description='Protected PH8057 data-integrity and separate SCSI qualification')
    parser.add_argument('--devices', nargs='+', required=True, metavar='DISK')
    parser.add_argument('--excluded-device', metavar='DISK',
                        help='optional disposable third LUN which is checked but NOT used by fio (only with 2 test disks)')
    parser.add_argument('--excluded-serial', metavar='ATA_SERIAL',
                        help='mandatory exact ATA serial when --excluded-device is given')
    parser.add_argument('--expected-serials', nargs='+', metavar='ATA_SERIAL',
                        help='exact ATA serials of the test targets, in --devices order (mandatory with two targets)')
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--preflight', action='store_true', help='read-only hardware/identity audit')
    action.add_argument('--run', action='store_true', help='run selected mode (writes require ERASE confirmation)')
    parser.add_argument('--mode', choices=('io', 'diagnose', 'benchmark', 'protocol-idle', 'protocol-load'), default='io',
                        help='diagnose=short CRC one-LUN vs multi-LUN matrix; io=CRC stress; benchmark=long A/B; separate protocol tests')
    parser.add_argument('--hours', type=float, default=None,
                        help='io defaults to 24 hours, protocol-load to 2 hours; 0h for benchmark/idle')
    parser.add_argument('--window-gib', type=int, default=8)
    parser.add_argument('--sequential-only', action='store_true',
                        help='io: skip slow random 64K/4K phases for throughput diagnosis')
    parser.add_argument('--seq-qd', type=int, default=0,
                        help='io: fixed sequential QD 1/4/8/16; 0 rotates 1/4/8/16 (default)')
    parser.add_argument('--diagnose-mib', type=int, default=256,
                        help='diagnose: CRC write+read per LUN, one or all selected disks at a time')
    parser.add_argument('--diagnose-timeout-sec', type=int, default=180,
                        help='diagnose: hard timeout for EACH phase (4 with two disks, 5 with three); cancels on stall')
    parser.add_argument('--phase-timeout-sec', type=int, default=900,
                        help='io cyclic/benchmark: hard timeout per fio phase (full-surface exempt)')
    parser.add_argument('--duration-basis', choices=('total', 'after-surface'), default='total',
                        help='io: total=clock starts before full surface; after-surface=24h cycles AFTER full verified pass')
    parser.add_argument('--smart-interval', type=int, default=300)
    parser.add_argument('--protocol-interval', type=int, default=300)
    parser.add_argument('--fuzz-count', type=int, default=64, help='bounded mutated CDBs per target per round')
    parser.add_argument('--sg-timeout', type=int, default=45, help='sg_raw timeout in seconds (host adds 10s)')
    parser.add_argument('--usbmon-interval', type=int, default=7200)
    parser.add_argument('--progress-interval', type=int, default=15,
                        help='read-only /sys block I/O and latency sampling interval in seconds')
    parser.add_argument('--no-usbmon', action='store_true')
    parser.add_argument('--no-full-surface', action='store_true',
                        help='skip initial full disk verification in io mode')
    parser.add_argument('--idle-check-minutes', type=int, default=35,
                        help='io mode only: wait after load before checking power mode')
    parser.add_argument('--output-dir', default='', help='new non-existing directory on OMV system filesystem')
    args = parser.parse_args()

    if os.geteuid() != 0:
        raise Abort('Run as root on OMV VM')
    if args.hours is None:
        args.hours = 24.0 if args.mode == 'io' else (2.0 if args.mode == 'protocol-load' else 0.0)
    if args.window_gib < 1 or args.window_gib > 64 or args.fuzz_count < 0 or args.sg_timeout < 10 or args.sg_timeout > 180:
        raise Abort('Invalid window, fuzz-count or SCSI timeout')
    if args.mode in ('protocol-idle', 'benchmark', 'diagnose') and args.hours != 0:
        raise Abort('protocol-idle, benchmark and diagnose are finite tests; omit --hours')
    if args.mode in ('io', 'protocol-load') and args.hours <= 0:
        raise Abort('Duration must be positive')
    if args.mode != 'io' and args.no_full_surface:
        raise Abort('--no-full-surface only applies to io mode')
    if args.mode != 'io' and (args.sequential_only or args.seq_qd != 0):
        raise Abort('--sequential-only and --seq-qd only apply to io mode')
    if args.seq_qd not in (0, 1, 4, 8, 16):
        raise Abort('Invalid sequential QD; choose 0, 1, 4, 8 or 16')
    if args.duration_basis != 'total' and args.mode != 'io':
        raise Abort('--duration-basis only applies to io mode')
    if min(args.smart_interval, args.protocol_interval, args.usbmon_interval) < 5 or args.progress_interval < 10:
        raise Abort('Polling/capture intervals must be >= 5 seconds, progress >= 10 seconds')
    if (args.diagnose_mib < 64 or args.diagnose_mib > 1024 or args.diagnose_mib % 4 or
            not 30 <= args.diagnose_timeout_sec <= 3600 or
            not 30 <= args.phase_timeout_sec <= 86400):
        raise Abort('Invalid diagnostic size or phase timeout')
    if args.idle_check_minutes < 0:
        raise Abort('Invalid idle duration')
    if len(args.devices) == 2 and not args.expected_serials:
        raise Abort('--expected-serials is mandatory for two-target tests')
    if args.expected_serials and len(args.expected_serials) != len(args.devices):
        raise Abort('--expected-serials count must match --devices count')
    require_tools()
    lock_file = Path('/run/lock/ph8057-qualify.lock')
    with lock_file.open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise Abort('Another PH8057 qualification is running') from exc
        guard = (Guard(args.devices, excluded_device=args.excluded_device,
                       excluded_serial=args.excluded_serial)
                 if args.excluded_device or args.excluded_serial else Guard(args.devices))
        if args.expected_serials and [t.serial for t in guard.targets] != args.expected_serials:
            raise Abort('Target ATA serial mismatch: expected ' + str(args.expected_serials)
                        + ', got ' + str([t.serial for t in guard.targets]))
        print('\nPH8057/JMS580 BRIDGE / VERIFIED TARGETS')
        for idx, t in enumerate(guard.targets, 1):
            print(f'{idx}: {t.device:9s}  {t.size/1e9:.2f} GB  {t.model}  '
                  f'SERIAL={t.serial}  LUN={t.lun}  BYPATH={t.path}')
        print(f'USB controller: {guard.usb_parent} [{EXPECTED_BRIDGE[0]}:{EXPECTED_BRIDGE[1]}]')
        if guard.excluded:
            print(f'EXCLUDED (NO FIO WRITES): {guard.excluded.device} SERIAL={guard.excluded.serial} LUN={guard.excluded.lun}')
        print(f'Bridge contains EXACTLY {len(guard.all_disks)} accounted-for LUNs: {len(guard.targets)} test targets, {int(bool(guard.excluded))} excluded.')
        if args.preflight:
            print('PREFLIGHT PASS: no blocks were written. This does not prove firmware correctness.')
            return 0

        destructive = args.mode in ('io', 'benchmark', 'diagnose', 'protocol-load')
        if destructive:
            token = 'ERASE-' + hashlib.sha256('|'.join(t.serial for t in guard.targets).encode()).hexdigest()[:8].upper()
            scope = ('ENTIRE SURFACES' if args.mode == 'io' and not args.no_full_surface
                     else 'SELECTED DISK REGIONS')
            print(f'WARNING: {scope} OF ALL {len(guard.targets)} TEST TARGETS MAY BE DESTROYED.')
            print('No firmware updates or SCSI data-out commands. Production disks MUST remain unplugged.')
            if guard.excluded:
                print('WARNING: excluded disk receives no intentional fio writes; broken firmware could still misroute commands.')
            print('Type', token, 'to confirm the precise ATA serial numbers above.')
            if not sys.stdin.isatty() or input('Confirmation: ').strip() != token:
                raise Abort('No interactive confirmation; refusing to write')
        else:
            print('READ-ONLY PROTOCOL TEST: no fio and no SCSI data-out.')
        guard.deep()
        start_local = dt.datetime.now().astimezone().isoformat(timespec='seconds')
        stamp = dt.datetime.now().strftime('%Y%m%d-%H%M%S')
        out = args.output_dir or ('/root/ph8057-' + args.mode + '-' + stamp)
        realparent = Path(out).expanduser().resolve().parent
        if not realparent.exists() or str(realparent).startswith('/dev'):
            raise Abort('Output path must be an existing system filesystem directory')
        rec = Recorder(out)
        report = {'start': rec.started_at, 'mode': args.mode,
                  'duration_hours_requested': args.hours, 'duration_basis': args.duration_basis,
                  'full_surface_requested': args.mode == 'io' and not args.no_full_surface,
                  'targets': [dataclasses.asdict(t) for t in guard.targets],
                  'excluded_target': dataclasses.asdict(guard.excluded) if guard.excluded else None,
                  'result': 'RUNNING', 'cycles': 0, 'verified_windows': [0] * len(guard.targets)}
        (rec.dir / 'manifest.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        capture_host_environment(rec)
        background = None
        rc = 1
        began = time.monotonic()
        deadline = began + args.hours * 3600
        full_surface_done = False
        tail_done = False
        uncovered_tail_bytes = []
        rec.events('duration_contract', mode=args.mode, hours=args.hours,
                   basis=args.duration_basis,
                   explanation=('Cycles run for the requested hours AFTER full-surface verification; total runtime is longer'
                                if args.mode == 'io' and args.duration_basis == 'after-surface' and not args.no_full_surface
                                else 'Overall deadline counts from test start; bounded phases may finish after deadline'))
        try:
            smart_snapshot(guard, rec, 'before')
            background = Background(guard, rec, args)
            background.start()
            if args.mode == 'protocol-idle':
                # Negative tests are single-pass and physically read-only.
                rec.events('protocol_idle_begin', fuzz_count=args.fuzz_count, sg_timeout=args.sg_timeout)
                run_suite([t.path for t in guard.targets], args.fuzz_count,
                          rec.sg_event, background.stop, seed=0x8057,
                          timeout=args.sg_timeout)
                rec.events('protocol_idle_complete', commands=rec.counters['sg_calls'],
                           host_timeouts=rec.counters['sg_host_timeouts'])
            elif args.mode == 'diagnose':
                # Deliberately finite (four or five bounded fio passes): isolate
                # a single bad HDD/LUN from multi-LUN BOT/QEMU contention.
                # Each pass writes a contiguous 256MiB region then fully reads
                # the same region with fio CRC32C. No fuzz or active SMART.
                region_bytes = args.diagnose_mib * MIB
                for idx, t in enumerate(guard.targets, 1):
                    phase = f'diag_single_disk{idx}_qd1'
                    regions = [window_for(t, 0, region_bytes)]
                    job = fio_jobfile([t], regions, rw='write', bs='1m', depth=1)
                    run_fio_phase(guard, rec, background, phase, job,
                                  phase_timeout=args.diagnose_timeout_sec, job_targets=[t])
                    write_diagnostic_result(rec, phase)
                regions = [window_for(t, 0, region_bytes) for t in guard.targets]
                for qd in (1, 4):
                    phase = f'diag_{"two" if len(guard.targets) == 2 else "three"}_qd{qd}'
                    job = fio_jobfile(guard.targets, regions, rw='write', bs='1m', depth=qd)
                    run_fio_phase(guard, rec, background, phase, job,
                                  phase_timeout=args.diagnose_timeout_sec)
                    write_diagnostic_result(rec, phase)
                rec.events('diagnostic_complete', phases=list(rec.phase_summaries))
            elif args.mode == 'benchmark':
                # Same selected LUN regions, exact CRC/QD/BS. Controlled A/B
                # profiles: no backlog vs v4 4096-block interleaving.
                regions = [window_for(t, 0, args.window_gib * GIB) for t in guard.targets]
                rec.events('benchmark_begin', note='Order is sequential then legacy; cache/thermal order bias possible')
                for name, backlog in (('benchmark_sequential', None),
                                      ('benchmark_legacy_backlog4096', 4096)):
                    job = fio_jobfile(guard.targets, regions, rw='write', bs='1m',
                                      depth=4, backlog=backlog)
                    run_fio_phase(guard, rec, background, name, job,
                                  phase_timeout=args.phase_timeout_sec)
                rec.events('benchmark_complete', phases=list(rec.phase_summaries))
            else:
                if args.mode == 'io' and not args.no_full_surface:
                    regions = [(0, align_down(t.size, MIB)) for t in guard.targets]
                    # fio verifies after completing the write phase.
                    # v4's verify_backlog=4096 alternated every 4GiB.
                    job = fio_jobfile(guard.targets, regions, rw='write', bs='1m',
                                      depth=4, backlog=None)
                    run_fio_phase(guard, rec, background, 'full_surface', job,
                                  phase_timeout=max(7200, args.hours * 3600 + 7200))
                    full_surface_done = True
                    # If after-surface, 24h refers to full 24h of subsequent
                    # cyclic stress, NOT the first surface write/read.
                    if args.duration_basis == 'after-surface':
                        deadline = time.monotonic() + args.hours * 3600
                        rec.events('stress_clock_started', hours=args.hours)
                cycle = 0
                while time.monotonic() < deadline:
                    if background.failed.is_set():
                        raise Abort('; '.join(background.errors))
                    cycle += 1
                    win = args.window_gib * GIB
                    regions = [window_for(t, cycle - 1, win) for t in guard.targets]
                    run_fio_phase(guard, rec, background, f'cycle{cycle:04d}_seq1m',
                                  fio_jobfile(guard.targets, regions, rw='write', bs='1m',
                                              depth=(args.seq_qd or (1, 4, 8, 16)[(cycle - 1) % 4])),
                                  phase_timeout=args.phase_timeout_sec)
                    for idx, (_, size) in enumerate(regions):
                        report['verified_windows'][idx] += size
                    if not args.sequential_only and time.monotonic() < deadline:
                        regions64 = rand64k_regions(guard.targets)
                        run_fio_phase(guard, rec, background, f'cycle{cycle:04d}_rand64k',
                                      fio_jobfile(guard.targets, regions64,
                                                  rw='randwrite', bs='64k', depth=8),
                                      phase_timeout=args.phase_timeout_sec)
                    if not args.sequential_only and time.monotonic() < deadline:
                        regions4 = [(GIB, 64 * MIB) for _ in guard.targets]
                        run_fio_phase(guard, rec, background, f'cycle{cycle:04d}_rand4k',
                                      fio_jobfile(guard.targets, regions4,
                                                  rw='randwrite', bs='4k', depth=16, verify='sha256'),
                                      phase_timeout=args.phase_timeout_sec)
                    report['cycles'] = cycle
                    rec.events('cycle_progress', count=cycle,
                               elapsed_hours=round((time.monotonic() - began) / 3600, 2))
                if args.mode == 'io' and not args.no_full_surface:
                    tail = []
                    for t in guard.targets:
                        base = align_down(t.size, MIB)
                        aligned = align_down(t.size, 4096)
                        uncovered_tail_bytes.append(t.size - aligned)
                        if aligned - base >= 4096:
                            tail.append((base, aligned - base))
                        else:
                            tail.append((aligned - 4096, 4096))
                    run_fio_phase(guard, rec, background, 'tail_4k',
                                  fio_jobfile(guard.targets, tail, rw='write', bs='4k', depth=1))
                    tail_done = True
                    if any(uncovered_tail_bytes):
                        rec.events('coverage_warning', uncovered_tail_bytes=uncovered_tail_bytes)
            background.shutdown()
            if background.failed.is_set():
                raise Abort('; '.join(background.errors))
            smart_snapshot(guard, rec, 'after_load')
            if args.mode == 'io':
                idle_check(guard, rec, args.idle_check_minutes)
            smart_snapshot(guard, rec, 'after')
            rc = 0
            report['result'] = 'COMPLETE_WITHOUT_DETECTED_ERROR'
        except Exception as exc:
            report['result'] = 'ABORTED_OR_FAILED'
            report['reason'] = str(exc)
            rec.events('FATAL', reason=str(exc))
            rc = 1
        except KeyboardInterrupt:
            report['result'] = 'ABORTED_OR_FAILED'
            report['reason'] = 'User interrupted'
            rec.events('FATAL', reason='User interrupted')
            rc = 130
        finally:
            if background:
                background.shutdown()
            try:
                guard.light()
                smart_snapshot(guard, rec, 'end_on_exit')
            except Exception as exc:
                rec.events('smart_end_unavailable', reason=str(exc))
            kernel_faults = []
            report['kernel_log_complete'] = False
            try:
                kernel_faults = kernel_final(rec, start_local, guard)
                report['kernel_log_complete'] = True
            except Exception as exc:
                rec.counters['monitor_warnings'] += 1
                rec.events('kernel_log_unavailable', reason=str(exc))
            report['smart_delta_complete'] = False
            try:
                delta, smart_worse = smart_delta(rec, guard)
                report['smart_delta'] = delta
                report['smart_delta_complete'] = (len(delta) == len(guard.targets) and
                    all(item.get('parse_complete', False) and
                        item.get('acquisition_complete', False) for item in delta))
            except Exception as exc:
                smart_worse = False
                rec.events('smart_delta_unavailable', reason=str(exc))
            report['kernel_target_error_count'] = len(kernel_faults)
            report['verified_logical_bytes_by_serial'] = rec.verified_by_serial
            report['verified_logical_bytes_total'] = {
                k: sum(v[k] for v in rec.verified_by_serial.values())
                for k in ('write_bytes', 'read_bytes')
            }
            report['verified_phases'] = list(rec.phase_summaries)
            report['full_surface_write_read_done'] = full_surface_done
            report['tail_4k_done'] = tail_done
            report['uncovered_tail_bytes'] = uncovered_tail_bytes
            if args.mode == 'diagnose':
                report['diagnostics'] = [make_diagnostic_result(phase, data) for phase, data in rec.phase_summaries.items()]
            if args.mode == 'benchmark' and all(p in rec.phase_summaries for p in (
                    'benchmark_sequential', 'benchmark_legacy_backlog4096')):
                seq_s = rec.phase_summaries['benchmark_sequential']['seconds']
                old_s = rec.phase_summaries['benchmark_legacy_backlog4096']['seconds']
                report['benchmark'] = {'sequential_seconds': seq_s,
                                       'legacy_seconds': old_s,
                                       'legacy_over_sequential_duration_ratio': round(old_s / max(seq_s, 0.001), 3),
                                       'caveat': 'same regions; order/cache/thermal bias; compare latency logs too'}
            if args.mode == 'io' and not args.no_full_surface and report['cycles'] == 0:
                rec.events('coverage_warning', reason='No cyclic stress executed within configured deadline')
                report['no_stress_cycles'] = True

            report['smart_concerning_delta'] = smart_worse
            protocol_findings = (rec.counters['sg_host_timeouts'] > 0 or
                                 rec.counters['sg_expected_success_failures'] > 0)
            report['protocol_findings'] = bool(protocol_findings)
            if report['result'] == 'COMPLETE_WITHOUT_DETECTED_ERROR' and protocol_findings:
                report['result'] = 'COMPLETE_WITH_PROTOCOL_FINDINGS'
                rc = 1
            if report['result'] == 'COMPLETE_WITHOUT_DETECTED_ERROR' and (
                    kernel_faults or smart_worse or report.get('no_stress_cycles') or
                    (args.mode == 'io' and full_surface_done and any(uncovered_tail_bytes)) or
                    (not args.no_usbmon and rec.counters['usbmon_captures'] == 0) or
                    rec.counters['usb_csw_phase_errors'] or rec.counters['usb_csw_residue_anomalies'] or
                    rec.counters['monitor_warnings'] or
                    not report['smart_delta_complete']):
                report['result'] = 'COMPLETE_WITH_WARNINGS_REVIEW_LOGS'
                rc = 1
            report['end'] = utc_now()
            report['elapsed_hours'] = round((time.monotonic() - began) / 3600, 3)
            report['counters'] = dict(rec.counters)
            report['full_surface_coverage_note'] = (
                'All full-MiB extents and the remaining 4K tail were written and CRC verified.'
                if full_surface_done and tail_done and not any(uncovered_tail_bytes)
                else 'Full physical surface verification NOT proven (not requested, incomplete, or partial 4K tail).')
            (rec.dir / 'summary.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
            try:
                package = archive(rec)
                print(f'\nRESULT: {report["result"]}. REPORT: {package}\n', flush=True)
            except Exception as exc:
                print('Could not package results: ', exc, 'Raw files:', rec.dir, file=sys.stderr)
            return rc


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (Abort, OSError) as exc:
        print('PRE-RUN ABORT:', exc, file=sys.stderr)
        sys.exit(2)
