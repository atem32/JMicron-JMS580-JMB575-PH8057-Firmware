import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

"""Offline safety and profile tests. These do NOT access any block devices."""
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from ph8057_qualify import (Abort, Background, Recorder, GIB, MIB,
                            fio_jobfile, expected_fio_sizes, validate_fio_results,
                            main)
from test_offline import fake_targets


class FioTests(unittest.TestCase):
    def setUp(self):
        self.targets = fake_targets()
        self.regions = [(2 * GIB, 8 * GIB)] * 3

    def test_full_sequential_does_not_interleave_verification(self):
        job = fio_jobfile(self.targets, self.regions, rw='write', bs='1m', depth=4)
        self.assertIn('verify=crc32c', job)
        self.assertIn('do_verify=1', job)
        self.assertNotIn('verify_backlog=', job)
        self.assertEqual(expected_fio_sizes(job), {'disk1': 8 * GIB, 'disk2': 8 * GIB, 'disk3': 8 * GIB})

    def test_legacy_contention_has_4096_block_backlog(self):
        job = fio_jobfile(self.targets, self.regions, rw='write', bs='1m', depth=4, backlog=4096)
        self.assertIn('verify_backlog=4096\n', job)
        with self.assertRaises(Abort):
            fio_jobfile(self.targets, self.regions, rw='write', bs='1m', depth=4, backlog=0)

    def test_reject_missing_target_region_and_invalid_fio_json(self):
        with self.assertRaises(Abort):
            fio_jobfile(self.targets, self.regions[:2], rw='write', bs='1m', depth=1)
        with self.assertRaises(Abort):
            expected_fio_sizes('[disk1]\nsize=3\n[disk3]\nsize=5')
        good = self._json()
        validated = validate_fio_results(good, {'disk1': 8 * GIB, 'disk2': 8 * GIB, 'disk3': 8 * GIB}, self.targets)
        self.assertEqual(len(validated), 3)
        self.assertEqual(sum(x['read_bytes'] for x in validated), 24 * GIB)
        bad = self._json()
        bad['jobs'][1]['read']['io_bytes'] -= MIB
        with self.assertRaisesRegex(Abort, 'incomplete read/write'):
            validate_fio_results(bad, {'disk1': 8 * GIB, 'disk2': 8 * GIB, 'disk3': 8 * GIB}, self.targets)
        bad = self._json()
        bad['jobs'][0]['error'] = 84
        with self.assertRaisesRegex(Abort, 'error=84'):
            validate_fio_results(bad, {'disk1': 8 * GIB, 'disk2': 8 * GIB, 'disk3': 8 * GIB}, self.targets)
        bad = self._json()
        bad['jobs'][0]['jobname'] = 'disk2'
        with self.assertRaisesRegex(Abort, 'identity'):
            validate_fio_results(bad, {'disk1': 8 * GIB, 'disk2': 8 * GIB, 'disk3': 8 * GIB}, self.targets)

    @staticmethod
    def _json():
        return {'jobs': [
            {'jobname': f'disk{i}', 'error': 0,
             'read': {'io_bytes': 8 * GIB, 'total_ios': 8192, 'bw': 1234},
             'write': {'io_bytes': 8 * GIB, 'total_ios': 8192, 'bw': 2345}}
            for i in (1, 2, 3)]}

    def test_accumulate_logical_bytes_only_from_completed_phases(self):
        with tempfile.TemporaryDirectory() as root:
            rec = Recorder(str(Path(root) / 'out'))
            rep = validate_fio_results(self._json(),
                                       {'disk1': 8 * GIB, 'disk2': 8 * GIB, 'disk3': 8 * GIB},
                                       self.targets)
            rec.verified_phase('first', rep, 100.0)
            rec.verified_phase('second', rep, 200.0)
            self.assertEqual(rec.verified_by_serial[self.targets[0].serial]['read_bytes'], 16 * GIB)
            self.assertEqual(len((rec.dir / 'phase_summary.jsonl').read_text().splitlines()), 2)


class ModeTests(unittest.TestCase):
    def setUp(self):
        self.targets = fake_targets()

    def fake_main(self, mode, extra_args, smart_result=None, smart_error=None, kernel_error=None):
        phases = []
        events = []
        targets = self.targets

        class FakeGuard:
            def __init__(self, names):
                self.targets = targets
                self.excluded = None
                self.all_disks = targets
                self.usb_parent = '/sys/fake-usb'
            def light(self):
                return None
            def deep(self):
                return None

        class FakeBackground:
            def __init__(self, guard, rec, args):
                self.failed = threading.Event()
                self.stop = threading.Event()
                self.errors = []
            def start(self):
                return None
            def shutdown(self):
                return None

        def fake_fio(guard, rec, bg, name, content, phase_timeout=7200):
            sizes = expected_fio_sizes(content)
            phases.append((name, content, sizes))
            rec.events('phase_verified', phase=name)
            # Distinguishes stress clock logic and prevents infinite fast spin.
            time.sleep(0.012)

        def fake_events(self, kind, **data):
            events.append((kind, data))

        import hashlib
        token = 'ERASE-' + hashlib.sha256('|'.join(t.serial for t in targets).encode()).hexdigest()[:8].upper()
        with tempfile.TemporaryDirectory() as d:
            out = str(Path(d) / 'out')
            args = ['test', '--devices', '/dev/sdc', '/dev/sdd', '/dev/sde',
                    '--run', '--mode', mode, '--output-dir', out] + extra_args
            with patch('ph8057_qualify.sys.argv', args), \
                 patch('ph8057_qualify.require_tools'), \
                 patch('ph8057_qualify.Guard', FakeGuard), \
                 patch('ph8057_qualify.Background', FakeBackground), \
                 patch('ph8057_qualify.smart_snapshot'), \
                 patch('ph8057_qualify.capture_host_environment'), \
                 patch('ph8057_qualify.smart_delta', side_effect=smart_error,
                       return_value=(smart_result if smart_result is not None else
                         ([{'parse_complete': True, 'acquisition_complete': True}] * 3, False))), \
                 patch('ph8057_qualify.kernel_final', return_value=[], side_effect=kernel_error), \
                 patch('ph8057_qualify.idle_check'), \
                 patch('ph8057_qualify.run_fio_phase', side_effect=fake_fio), \
                 patch('ph8057_qualify.sys.stdin', SimpleNamespace(isatty=lambda: True)), \
                 patch('builtins.input', return_value=token):
                self.last_exit_code = main()
            summary = json.loads((Path(out) / 'summary.json').read_text())
            return phases, summary

    def test_benchmark_runs_sequential_then_legacy(self):
        phases, summary = self.fake_main('benchmark', ['--window-gib', '2'])
        self.assertEqual([name for name, *_ in phases],
                         ['benchmark_sequential', 'benchmark_legacy_backlog4096'])
        self.assertNotIn('verify_backlog=', phases[0][1])
        self.assertIn('verify_backlog=4096', phases[1][1])
        self.assertEqual(set(phases[0][2].values()), {2 * GIB})
        self.assertEqual(summary['mode'], 'benchmark')
        self.assertFalse(summary['full_surface_requested'])

    def test_after_surface_runs_cycles_after_full_pass_even_if_start_budget_expired(self):
        phases, summary = self.fake_main('io', ['--hours', '0.000003',
                                               '--duration-basis', 'after-surface',
                                               '--idle-check-minutes', '0'])
        names = [p[0] for p in phases]
        self.assertEqual(names[0], 'full_surface')
        self.assertNotIn('verify_backlog=', phases[0][1])
        self.assertTrue(any(x.startswith('cycle') for x in names))
        self.assertEqual(names[-1], 'tail_4k')
        self.assertTrue(summary['full_surface_write_read_done'])
        self.assertTrue(summary['tail_4k_done'])
        self.assertEqual(summary['duration_basis'], 'after-surface')
        self.assertEqual(summary['uncovered_tail_bytes'], [0, 0, 0])

    def test_total_budget_can_finish_surface_with_no_cycles_and_warns(self):
        phases, summary = self.fake_main('io', ['--hours', '0.000001',
                                               '--duration-basis', 'total',
                                               '--idle-check-minutes', '0'])
        self.assertEqual([p[0] for p in phases], ['full_surface', 'tail_4k'])
        self.assertTrue(summary['no_stress_cycles'])
        self.assertEqual(summary['result'], 'COMPLETE_WITH_WARNINGS_REVIEW_LOGS')

    def test_benchmark_has_passive_io_progress(self):
        spawned = []
        class StubThread:
            def __init__(self, target, args, daemon, name):
                spawned.append(name)
            def start(self):
                pass
        with patch('ph8057_qualify.threading.Thread', StubThread):
            bg = Background(object(), object(), SimpleNamespace(mode='benchmark', sg_timeout=45))
            bg.start()
        self.assertIn('io_progress_thread', spawned)
        self.assertNotIn('smart_thread', spawned)
        self.assertNotIn('protocol_thread', spawned)


if __name__ == '__main__':
    unittest.main()
