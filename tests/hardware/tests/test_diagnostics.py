import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

"""Diagnostic tests: no real drives touched; all destructive calls are mocked."""
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from ph8057_qualify import (
    Abort, MIB, fio_jobfile, expected_fio_sizes, validate_fio_results,
    make_diagnostic_result, main, Recorder,
)
from test_offline import fake_targets
from hardware_fixtures import mock_root_and_lock


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.targets = fake_targets()

    def test_single_lun_fio_job_remains_bounded_and_verified(self):
        target = self.targets[2]
        job = fio_jobfile([target], [(2 * 1024 * MIB, 256 * MIB)],
                          rw='write', bs='1m', depth=1)
        self.assertEqual(job.count('filename='), 1)
        self.assertEqual(expected_fio_sizes(job), {'disk1': 256 * MIB})
        self.assertIn('verify=crc32c', job)
        self.assertIn('do_verify=1', job)
        self.assertIn('allow_file_create=0', job)
        self.assertNotIn('verify_backlog=', job)
        self.assertNotIn('time_based=', job)
        json_data = {'jobs': [{
            'jobname': 'disk1', 'error': 0,
            'read': {'io_bytes': 256 * MIB, 'total_ios': 256, 'bw': 100000},
            'write': {'io_bytes': 256 * MIB, 'total_ios': 256, 'bw': 110000},
        }]}
        result = validate_fio_results(json_data, {'disk1': 256 * MIB}, [target])
        self.assertEqual(result[0]['serial'], target.serial)
        self.assertEqual(result[0]['read_bytes'], 256 * MIB)
        json_data['jobs'][0]['read']['io_bytes'] -= MIB
        with self.assertRaisesRegex(Abort, 'incomplete read/write'):
            validate_fio_results(json_data, {'disk1': 256 * MIB}, [target])

    def test_two_lun_job_and_unbounded_offset(self):
        job = fio_jobfile(self.targets[:2], [(2 * 1024 * MIB, 256 * MIB)] * 2,
                          rw='write', bs='1m', depth=1)
        self.assertEqual(job.count('filename='), 2)
        self.assertEqual(set(expected_fio_sizes(job)), {'disk1', 'disk2'})
        with self.assertRaises(Abort):
            fio_jobfile([self.targets[0]], [(500 * 1024 * MIB, 256 * MIB)],
                        rw='write', bs='1m', depth=1)

    def test_diagnostic_speed_summary(self):
        phase = {'seconds': 8.0, 'disks': [{
            'serial': self.targets[1].serial,
            'read_bytes': 256 * MIB, 'write_bytes': 256 * MIB,
            'read_bw_kib': 32768, 'write_bw_kib': 65536,
        }]}
        result = make_diagnostic_result('diag_single_disk2_qd1', phase)
        self.assertEqual(result['aggregate_verified_mib_s'], 64)
        self.assertEqual(result['disks'][0]['read_mib_s'], 32)
        self.assertEqual(result['disks'][0]['write_mib_s'], 64)

    def test_sequential_only_avoids_slow_random_phases_and_fixes_qd(self):
        from test_workloads import ModeTests
        fixture = ModeTests()
        fixture.setUp()
        phases, summary = fixture.fake_main('io', [
            '--no-full-surface', '--sequential-only', '--seq-qd', '1',
            '--hours', '0.000004', '--window-gib', '2',
            '--idle-check-minutes', '0',
        ])
        self.assertGreaterEqual(len(phases), 1)
        self.assertTrue(all('seq1m' in name for name, *_ in phases))
        self.assertTrue(all('iodepth=1' in content for _, content, _ in phases))
        self.assertFalse(summary['full_surface_requested'])
        self.assertEqual(summary['cycles'], len(phases))

    def test_diagnostic_order_and_scope_and_timeout(self):
        runs = []
        targets = self.targets

        class FakeGuard:
            def __init__(self, names):
                self.targets = targets
                self.excluded = None
                self.all_disks = targets
                self.usb_parent = '/sys/fake-usb'
            def deep(self):
                pass
            def light(self):
                pass

        class FakeBackground:
            def __init__(self, guard, rec, args):
                self.failed = threading.Event()
                self.stop = threading.Event()
                self.errors = []
            def start(self):
                pass
            def shutdown(self):
                pass

        def fake_run(guard, rec, bg, name, content, phase_timeout=7200, job_targets=None):
            actual = targets if job_targets is None else job_targets
            actual_regions = expected_fio_sizes(content)
            self.assertEqual(len(actual_regions), len(actual))
            self.assertEqual(set(actual_regions.values()), {256 * MIB})
            self.assertNotIn('verify_backlog=', content)
            self.assertIn('verify=crc32c', content)
            self.assertEqual(phase_timeout, 123)
            runs.append((name, len(actual), next(x for x in content.splitlines() if x.startswith('iodepth='))))
            rec.verified_phase(name, [{
                'name': f'disk{i}', 'serial': t.serial,
                'read_bytes': 256 * MIB, 'write_bytes': 256 * MIB,
                'read_ios': 256, 'write_ios': 256,
                'read_bw_kib': 100000, 'write_bw_kib': 100000,
                'read_mean_lat_ns': 0, 'write_mean_lat_ns': 0,
            } for i, t in enumerate(actual, 1)], 12.0)

        token = 'ERASE-' + hashlib.sha256('|'.join(t.serial for t in targets).encode()).hexdigest()[:8].upper()
        with tempfile.TemporaryDirectory() as d:
            out = str(Path(d) / 'out')
            argv = ['prog', '--devices', '/dev/sdc', '/dev/sdd', '/dev/sde',
                    '--run', '--mode', 'diagnose', '--diagnose-mib', '256',
                    '--diagnose-timeout-sec', '123', '--output-dir', out]
            with mock_root_and_lock(), \
                 patch('ph8057_qualify.sys.argv', argv), \
                 patch('ph8057_qualify.require_tools'), \
                 patch('ph8057_qualify.Guard', FakeGuard), \
                 patch('ph8057_qualify.Background', FakeBackground), \
                 patch('ph8057_qualify.smart_snapshot'), \
                 patch('ph8057_qualify.capture_host_environment'), \
                 patch('ph8057_qualify.smart_delta', return_value=([{'parse_complete': True, 'acquisition_complete': True}] * 3, False)), \
                 patch('ph8057_qualify.kernel_final', return_value=[]), \
                 patch('ph8057_qualify.run_fio_phase', side_effect=fake_run), \
                 patch('ph8057_qualify.sys.stdin', SimpleNamespace(isatty=lambda: True)), \
                 patch('builtins.input', return_value=token):
                rc = main()
            summary = json.loads((Path(out) / 'summary.json').read_text())
            self.assertEqual(len(summary['diagnostics']), 5)
            self.assertEqual(summary['verified_logical_bytes_total']['write_bytes'], 9 * 256 * MIB)
            self.assertIn(summary['result'], ('COMPLETE_WITH_WARNINGS_REVIEW_LOGS', 'COMPLETE_WITHOUT_DETECTED_ERROR'))
            self.assertEqual(rc, 1)  # mocked background did not capture usbmon
        self.assertEqual(runs, [
            ('diag_single_disk1_qd1', 1, 'iodepth=1'),
            ('diag_single_disk2_qd1', 1, 'iodepth=1'),
            ('diag_single_disk3_qd1', 1, 'iodepth=1'),
            ('diag_three_qd1', 3, 'iodepth=1'),
            ('diag_three_qd4', 3, 'iodepth=4'),
        ])


if __name__ == '__main__':
    unittest.main()
