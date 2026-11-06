import dataclasses
import sys
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ph8057_qualify import (Target, Guard, fio_jobfile, window_for, GIB, MIB,
                            Abort, smart_raw_attributes)
from scsi_protocol import Case, baseline_cases, bounded_fuzz, assert_case_is_read_only
from usbmon_trace import analyze_lines


def fake_targets():
    return [Target('/dev/sd' + letter, f'/dev/disk/by-path/fake-scsi-lun{n}',
                   '/dev/sd' + letter, 'sd' + letter, 500_107_862_016,
                   512, f'TEST-SERIAL-{n}', f'Test HDD {n}', '/sys/fake-usb',
                   '152d', 'a562', 3, 2, f'6:0:0:{n}')
            for n, letter in enumerate('cde')]


class OfflineSuite(unittest.TestCase):
    def test_no_write_or_vendor_specific_scsi_opcode(self):
        cases = baseline_cases() + bounded_fuzz(2000)
        self.assertGreater(len(cases), 2000)
        for c in cases:
            self.assertTrue(assert_case_is_read_only(c))
            self.assertNotIn(c.cdb[0], [0x0A, 0x2A, 0x8A, 0x2E, 0x93, 0x04, 0x42])
            self.assertLessEqual(c.alloc, 512)

    def test_reject_destructive_ata_command(self):
        cdb = bytearray(bytes.fromhex('85 06 20 00 00 00 00 00 00 00 00 00 00 00 e5 00'))
        cdb[14] = 0xF4  # ATA SECURITY ERASE UNIT must never be sent
        with self.assertRaises(ValueError):
            assert_case_is_read_only(Case('bad', bytes(cdb)))

    def test_fio_jobs_have_explicit_bounds_and_guards(self):
        targets = fake_targets()
        text = fio_jobfile(targets, [(2*GIB, 8*GIB)]*3,
                           rw='write', bs='1m', depth=4)
        self.assertEqual(text.count('filename='), 3)
        self.assertIn('allow_file_create=0', text)
        self.assertIn('allow_mounted_write=0', text)
        self.assertIn('do_verify=1', text)
        self.assertNotIn('time_based=1', text)
        with self.assertRaises(Abort):
            fio_jobfile(targets, [(0, 20*GIB)]*2 + [(0, 501*GIB)],
                        rw='write', bs='1m', depth=1)

    def test_fio_escaped_by_path_for_colon_delimiter(self):
        targets = fake_targets()
        for i, t in enumerate(targets):
            t.path = f'/dev/disk/by-path/pci-0000:01:1b.0-usb-0:1:1.0-scsi-0:0:0:{i}'
        job = fio_jobfile(targets, [(0, 4096)] * 3,
                          rw='write', bs='4k', depth=1)
        actual = [line for line in job.splitlines() if line.startswith('filename=')]
        expected = ['filename=' + t.path.replace(':', r'\:') for t in targets]
        self.assertEqual(actual, expected)
        self.assertEqual(len(actual), 3)

    def test_rotating_windows_cover_all_full_megabytes(self):
        t = fake_targets()[0]
        window = 8*GIB
        usable = ((t.size - 2*GIB) // MIB) * MIB
        n = (usable + window - 1) // window
        windows = [window_for(t, i, window) for i in range(n)]
        self.assertEqual(windows[0][0], 2*GIB)
        self.assertEqual(windows[-1][0] + windows[-1][1], 2*GIB + usable)
        self.assertEqual(sum(x[1] for x in windows), usable)
        self.assertEqual(window_for(t, n, window), windows[0])

    def test_refuse_any_extra_lun_on_bridge(self):
        target_names = ['sdc', 'sdd', 'sde']
        with patch('ph8057_qualify.inspect_target', side_effect=fake_targets()), \
             patch('ph8057_qualify.enumerate_bridge_disk_names',
                   return_value={'sdb', 'sdc', 'sdd', 'sde'}):
            with self.assertRaisesRegex(Abort, 'Extra/missing disks'):
                Guard(['/dev/' + name for name in target_names])

    def test_parse_bot_csw_bad_status(self):
        rows = [
            b'0 0 S Bo:3:002:2 -115 31 = 55534243 01000000 00000000 80000612 000000600000000000000000000000\n',
            b'0 0 C Bi:3:002:1 0 13 = 55534253 01000000 01000000 02\n',
        ]
        stats = analyze_lines(rows)['stats']
        self.assertEqual(stats['csw_phase_error'], 1)
        self.assertEqual(stats['csw_residue_gt_requested'], 1)
        self.assertEqual(stats['matched_tag'], 1)

    def test_parse_smart_counters(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / 'smart.txt'
            f.write_text('  5 Reallocated_Sector_Ct 0x0033 100 100 036 Pre-fail Always - 0\n'
                         '199 UDMA_CRC_Error_Count 0x0032 200 200 000 Old_age Always - 3\n')
            self.assertEqual(smart_raw_attributes(f),
                             {'Reallocated_Sector_Ct': 0, 'UDMA_CRC_Error_Count': 3})


if __name__ == '__main__':
    unittest.main()

# Regression tests: workload isolation and protocol timeout reporting.
class WorkloadIsolationTests(unittest.TestCase):
    def test_io_background_never_starts_smart_or_fuzz(self):
        from types import SimpleNamespace
        from ph8057_qualify import Background
        spawned = []

        class StubThread:
            def __init__(self, target, args, daemon, name):
                self.name = name
                spawned.append(name)
            def start(self):
                pass

        with patch('ph8057_qualify.threading.Thread', StubThread):
            b = Background(object(), object(), SimpleNamespace(mode='io', sg_timeout=45))
            b.start()
        self.assertEqual(set(spawned), {'guard_thread', 'kernel_thread', 'usbmon_thread', 'io_progress_thread'})
        self.assertNotIn('protocol_thread', spawned)
        self.assertNotIn('smart_thread', spawned)

    def test_protocol_load_starts_active_scsi_workers(self):
        from types import SimpleNamespace
        from ph8057_qualify import Background
        spawned = []

        class StubThread:
            def __init__(self, target, args, daemon, name):
                self.name = name
                spawned.append(name)
            def start(self):
                pass

        with patch('ph8057_qualify.threading.Thread', StubThread):
            b = Background(object(), object(), SimpleNamespace(mode='protocol-load', sg_timeout=45))
            b.start()
        self.assertEqual(len(spawned), 6)
        self.assertIn('protocol_thread', spawned)
        self.assertIn('smart_thread', spawned)

    def test_one_scsi_host_timeout_does_not_abort_running_fio(self):
        from types import SimpleNamespace
        from ph8057_qualify import Background
        import threading
        class FakeRecorder:
            def __init__(self):
                self.counters = {'sg_calls': 0, 'sg_host_timeouts': 0}
                self.entries = []
            def sg_event(self, entry):
                self.entries.append(entry)
                self.counters['sg_calls'] += 1
                self.counters['sg_host_timeouts'] += (entry['classification'] == 'HOST_TIMEOUT')
            def events(self, kind, **data):
                self.entries.append((kind, data))

        rec = FakeRecorder()
        guard = SimpleNamespace(light=lambda: None, targets=[SimpleNamespace(path='/dev/sdb')])
        args = SimpleNamespace(fuzz_count=10, protocol_interval=300, sg_timeout=45)
        b = Background(guard, rec, args)
        def fake_run_suite(devices, count, emit, stop_event, seed, timeout):
            emit({'classification': 'HOST_TIMEOUT'})
            stop_event.set()

        with patch('ph8057_qualify.run_suite', fake_run_suite):
            b.protocol_thread()
        self.assertFalse(b.failed.is_set())
        self.assertEqual(rec.counters['sg_host_timeouts'], 1)
        self.assertIn(('protocol_round_complete', {
            'round': 1, 'commands': 1, 'new_host_timeouts': 1}), rec.entries)

    def test_scsi_invokes_readonly_flag_and_timeout(self):
        from scsi_protocol import send_case
        from unittest.mock import MagicMock
        import subprocess
        fake = MagicMock(returncode=0, stdout=b'', stderr=b'')
        with patch('scsi_protocol.subprocess.run', return_value=fake) as mocked:
            result = send_case('/dev/sdb', baseline_cases()[0], timeout=45)
        cmd = mocked.call_args.args[0]
        self.assertEqual(cmd[:3], ['sg_raw', '--readonly', '--timeout=45'])
        self.assertEqual(mocked.call_args.kwargs['timeout'], 55)
        self.assertEqual(result['classification'], 'accepted')

class MainSmokeTests(unittest.TestCase):
    def test_main_both_io_and_readonly_modes_via_fake_hardware(self):
        import tempfile
        import time
        import json
        import hashlib
        import threading
        from types import SimpleNamespace
        from ph8057_qualify import main
        from hardware_fixtures import mock_root_and_lock
        targets = fake_targets()

        class StubGuard:
            def __init__(self, names):
                self.targets = targets
                self.excluded = None
                self.all_disks = targets
                self.usb_parent = '/sys/fake-usb'
            def light(self):
                return None
            def deep(self):
                return None

        class StubBackground:
            def __init__(self, guard, rec, args):
                self.stop = threading.Event()
                self.failed = threading.Event()
                self.errors = []
            def start(self):
                return None
            def shutdown(self):
                return None

        token = 'ERASE-' + hashlib.sha256('|'.join(t.serial for t in targets).encode()).hexdigest()[:8].upper()
        with tempfile.TemporaryDirectory() as d:
            for mode in ('io', 'protocol-idle', 'protocol-load'):
                out = str(Path(d) / ('out_' + mode))
                argv = ['test', '--devices', '/dev/sdc', '/dev/sdd', '/dev/sde',
                        '--run', '--mode', mode, '--output-dir', out]
                if mode != 'protocol-idle':
                    argv += ['--hours', '0.00005']
                if mode == 'io':
                    argv += ['--no-full-surface', '--idle-check-minutes', '0']

                def fake_phase(guard, rec, bg, name, job, phase_timeout=7200):
                    rec.events('phase_verified', phase=name)
                    time.sleep(0.1)  # Avoid infinitely fast cycles during the smoke test.

                fake_delta = ([{'disk': n, 'parse_complete': True, 'acquisition_complete': True} for n in (1, 2, 3)], False)
                with mock_root_and_lock(), \
                     patch('ph8057_qualify.sys.argv', argv), \
                     patch('ph8057_qualify.require_tools'), \
                     patch('ph8057_qualify.Guard', StubGuard), \
                     patch('ph8057_qualify.Background', StubBackground), \
                     patch('ph8057_qualify.smart_snapshot'), \
                     patch('ph8057_qualify.capture_host_environment'), \
                     patch('ph8057_qualify.smart_delta', return_value=fake_delta), \
                     patch('ph8057_qualify.kernel_final', return_value=[]), \
                     patch('ph8057_qualify.idle_check'), \
                     patch('ph8057_qualify.run_fio_phase', side_effect=fake_phase), \
                     patch('ph8057_qualify.run_suite'), \
                     patch('ph8057_qualify.sys.stdin', SimpleNamespace(isatty=lambda: True)), \
                     patch('builtins.input', return_value=token):
                    rc = main()
                self.assertEqual(rc, 1)  # No usbmon captures in synthetic smoke test.
                summary = json.loads((Path(out) / 'summary.json').read_text())
                self.assertEqual(summary['mode'], mode)
                self.assertEqual(summary['result'], 'COMPLETE_WITH_WARNINGS_REVIEW_LOGS')
                if mode == 'protocol-idle':
                    self.assertEqual(summary['cycles'], 0)
                else:
                    self.assertGreaterEqual(summary['cycles'], 1)
