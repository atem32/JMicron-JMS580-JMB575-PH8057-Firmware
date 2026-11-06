import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

"""Offline target validation. No real block devices are accessed."""
import dataclasses
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from ph8057_qualify import (Abort, GIB, MIB, Guard, Recorder, expected_fio_sizes,
                            fio_jobfile, main, validate_fio_results)
from test_offline import fake_targets
from hardware_fixtures import mock_root_and_lock


class TwoDiskTests(unittest.TestCase):
    def setUp(self):
        d0, d1, d2 = fake_targets()
        self.targets = [
            dataclasses.replace(d0, serial='TEST-SERIAL-A'),
            dataclasses.replace(d1, serial='TEST-SERIAL-B'),
        ]
        self.excluded = dataclasses.replace(
            d2, device='/dev/sdb', devname='sdb', input='/dev/sdb',
            serial='TEST-SERIAL-EXCLUDED', path='/dev/disk/by-path/fake-scsi-lun2')
        self.devices = {'/dev/sdc': self.targets[0], '/dev/sdd': self.targets[1],
                        '/dev/sdb': self.excluded}

    def test_excluded_lun_is_guarded_but_is_not_selected_for_fio(self):
        with patch('ph8057_qualify.inspect_target', side_effect=self.devices.__getitem__), \
             patch('ph8057_qualify.enumerate_bridge_disk_names', return_value={'sdb','sdc','sdd'}):
            guard = Guard(['/dev/sdc', '/dev/sdd'], excluded_device='/dev/sdb',
                          excluded_serial='TEST-SERIAL-EXCLUDED')
            self.assertEqual([x.serial for x in guard.targets], ['TEST-SERIAL-A', 'TEST-SERIAL-B'])
            self.assertEqual(guard.excluded.serial, 'TEST-SERIAL-EXCLUDED')
            self.assertEqual(guard.expected_members, {'sdb', 'sdc', 'sdd'})
            job = fio_jobfile(guard.targets, [(2*GIB, 256*MIB)]*2,
                              rw='write', bs='1m', depth=1)
            self.assertEqual(expected_fio_sizes(job), {'disk1': 256*MIB, 'disk2': 256*MIB})
            self.assertNotIn('fake-scsi-lun2', job)
            self.assertEqual(job.count('filename='), 2)

    def test_excluded_serial_mismatch_rejected(self):
        with patch('ph8057_qualify.inspect_target', side_effect=self.devices.__getitem__):
            with self.assertRaisesRegex(Abort, 'Excluded disk ATA serial mismatch'):
                Guard(['/dev/sdc', '/dev/sdd'], excluded_device='/dev/sdb',
                      excluded_serial='WRONG')

    def test_unaccounted_bridge_disk_rejected(self):
        with patch('ph8057_qualify.inspect_target', side_effect=self.devices.__getitem__), \
             patch('ph8057_qualify.enumerate_bridge_disk_names', return_value={'sdb','sdc','sdd'}):
            with self.assertRaisesRegex(Abort, 'Extra/missing disks'):
                Guard(['/dev/sdc', '/dev/sdd'])

    def test_json_two_lun_verification_rejects_short_readback(self):
        sizes={'disk1': 256*MIB, 'disk2': 256*MIB}
        jobs=[]
        for i in (1,2):
            jobs.append({'jobname': f'disk{i}', 'error':0,
                         'read': {'io_bytes': 256*MIB, 'total_ios':256, 'bw':102400},
                         'write': {'io_bytes':256*MIB,'total_ios':256,'bw':102400}})
        self.assertEqual(len(validate_fio_results({'jobs':jobs}, sizes, self.targets)),2)
        jobs[1]['read']['io_bytes'] -= MIB
        with self.assertRaisesRegex(Abort, 'incomplete read/write'):
            validate_fio_results({'jobs':jobs}, sizes, self.targets)

    def test_two_lun_diagnostic_runs_four_phases_and_never_writes_excluded(self):
        targets = self.targets
        excluded = self.excluded
        runs = []
        class FakeGuard:
            def __init__(self, names, excluded_device=None, excluded_serial=None):
                self.targets = targets
                self.excluded = excluded
                self.all_disks = targets + [excluded]
                self.usb_parent = '/sys/fake-usb'
                if excluded_device != '/dev/sdb' or excluded_serial != 'TEST-SERIAL-EXCLUDED':
                    raise Abort('Unexpected excluded hardware')
            def light(self): pass
            def deep(self): pass
        class FakeBackground:
            def __init__(self, guard, rec, args):
                self.failed = threading.Event()
                self.stop = threading.Event()
                self.errors = []
            def start(self): pass
            def shutdown(self): pass
        def fake_run(guard, rec, bg, name, content, phase_timeout=7200, job_targets=None):
            actual = targets if job_targets is None else job_targets
            self.assertNotIn(excluded.path, content)
            sizes = expected_fio_sizes(content)
            self.assertEqual(len(sizes), len(actual))
            self.assertEqual(set(sizes.values()), {256*MIB})
            runs.append((name, len(actual), phase_timeout))
            rec.verified_phase(name, [{
                'name': f'disk{i}', 'serial': t.serial,
                'read_bytes':256*MIB, 'write_bytes':256*MIB,
                'read_ios':256, 'write_ios':256,
                'read_bw_kib':100000, 'write_bw_kib':100000,
                'read_mean_lat_ns':0, 'write_mean_lat_ns':0,
            } for i,t in enumerate(actual, 1)], 12)
        token = 'ERASE-' + hashlib.sha256('|'.join(t.serial for t in targets).encode()).hexdigest()[:8].upper()
        with tempfile.TemporaryDirectory() as d:
            out = str(Path(d)/'report')
            args = ['test','--devices','/dev/sdc','/dev/sdd',
                    '--expected-serials','TEST-SERIAL-A','TEST-SERIAL-B',
                    '--excluded-device','/dev/sdb', '--excluded-serial','TEST-SERIAL-EXCLUDED',
                    '--mode','diagnose','--run','--output-dir',out,
                    '--diagnose-mib','256','--diagnose-timeout-sec','120']
            with mock_root_and_lock(), \
                 patch('ph8057_qualify.sys.argv', args), \
                 patch('ph8057_qualify.require_tools'), \
                 patch('ph8057_qualify.Guard', FakeGuard), \
                 patch('ph8057_qualify.Background', FakeBackground), \
                 patch('ph8057_qualify.smart_snapshot'), \
                 patch('ph8057_qualify.capture_host_environment'), \
                 patch('ph8057_qualify.smart_delta', return_value=([{'parse_complete': True, 'acquisition_complete': True}]*2, False)), \
                 patch('ph8057_qualify.kernel_final', return_value=[]), \
                 patch('ph8057_qualify.run_fio_phase', side_effect=fake_run), \
                 patch('ph8057_qualify.sys.stdin', SimpleNamespace(isatty=lambda: True)), \
                 patch('builtins.input', return_value=token):
                rc=main()
            summary=json.loads((Path(out)/'summary.json').read_text())
            self.assertEqual(rc,1) # mocked monitors provide no usbmon
            self.assertEqual(summary['excluded_target']['serial'],'TEST-SERIAL-EXCLUDED')
            self.assertEqual(len(summary['targets']),2)
            self.assertEqual(summary['verified_logical_bytes_total']['write_bytes'],6*256*MIB)
            self.assertEqual(len(summary['diagnostics']),4)
            self.assertEqual(runs,[('diag_single_disk1_qd1',1,120),
                                   ('diag_single_disk2_qd1',1,120),
                                   ('diag_two_qd1',2,120),('diag_two_qd4',2,120)])

    def test_serial_pinning_rejects_swapped_test_disks_before_writes(self):
        targets=self.targets[::-1]
        class FakeGuard:
            def __init__(self, names):
                self.targets = targets
                self.excluded = None
                self.all_disks = targets
                self.usb_parent = '/sys/fake-usb'
        argv=['test','--devices','/dev/sdc','/dev/sdd','--expected-serials',
              'TEST-SERIAL-A','TEST-SERIAL-B','--preflight']
        with mock_root_and_lock(), \
             patch('ph8057_qualify.sys.argv', argv), \
             patch('ph8057_qualify.require_tools'), \
             patch('ph8057_qualify.Guard', FakeGuard):
            with self.assertRaisesRegex(Abort, 'Target ATA serial mismatch'):
                main()

if __name__ == '__main__': unittest.main()
