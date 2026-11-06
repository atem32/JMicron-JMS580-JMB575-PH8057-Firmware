"""SMART format, serial ownership, acquisition and final-result regressions."""
import dataclasses
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from smart import parse_smart, compare_smart
from ph8057_qualify import (Abort, Recorder, smart_delta, smart_raw_attributes,
                            smart_snapshot, safe_serial_from_smart)
from test_offline import fake_targets

FIXTURES = Path(__file__).parent / 'fixtures'


def fixture(name='smartctl_extended.txt'):
    return (FIXTURES / name).read_text()


class SmartFormats(unittest.TestCase):
    def test_standard_and_extended_tables_keep_every_available_attribute(self):
        for name in ('smartctl_standard.txt', 'smartctl_extended.txt'):
            with self.subTest(name=name):
                data = parse_smart(fixture(name))
                self.assertTrue(data['parse_complete'], data['errors'])
                self.assertTrue(data['acquisition_complete'])
                self.assertEqual(data['serial'], 'TEST-SERIAL-A')
                self.assertEqual(len(data['attributes']), 8)
                self.assertEqual({k: data['attributes'][k]['raw_value'] for k in ('5','197','198','199')},
                                 {'5': 0, '197': 0, '198': 0, '199': 231})
                self.assertIn('Min/Max', data['attributes']['194']['raw'])

    def test_actual_redacted_sat_outputs_keep_seventeen_attributes(self):
        for disk, crc in ((1, 231), (2, 28)):
            with self.subTest(disk=disk):
                data = parse_smart(fixture(f'smartctl_sat_optional_error_disk{disk}.txt'))
                self.assertEqual(len(data['attributes']), 17)
                self.assertTrue(data['parse_complete'], data['errors'])
                self.assertFalse(data['acquisition_complete'])
                self.assertEqual(data['exit_code'], 4)
                self.assertIn('smartctl_acquisition_error:4', data['acquisition_errors'])
                self.assertEqual(data['attributes']['199']['raw_value'], crc)
                self.assertEqual(data['attributes']['192']['name'], 'Power-Off_Retract_Count')
                # Numeric temperature histories and log indices are not ATA rows.
                self.assertNotIn('255', data['attributes'])

    def test_json_attributes_and_serial(self):
        data = parse_smart(fixture('smartctl.json'))
        self.assertTrue(data['parse_complete'])
        self.assertTrue(data['acquisition_complete'])
        self.assertEqual(data['attributes']['199']['raw_value'], 231)
        self.assertEqual(len(data['attributes']), 8)

    def test_outer_process_exit_status_governs_wrapped_json(self):
        for rc in (4, -9):
            with self.subTest(rc=rc):
                data = parse_smart(f'$ smartctl -j -x /dev/fake\nExit code: {rc}\n' + fixture('smartctl.json'))
                self.assertEqual(data['exit_code'], rc)
                self.assertFalse(data['acquisition_complete'])
                self.assertTrue(data['parse_complete'])
                self.assertTrue(any('exit_status_disagreement' in error
                                    for error in data['acquisition_errors']))

    def test_explicit_process_status_and_json_status_disagreement_is_not_clean(self):
        data = parse_smart(fixture('smartctl.json'), exit_code=4)
        self.assertEqual(data['exit_code'], 4)
        self.assertFalse(data['acquisition_complete'])
        self.assertTrue(any('exit_status_disagreement' in error
                            for error in data['acquisition_errors']))
        # Even a successful outer command cannot hide a failing embedded status.
        data = parse_smart('Exit code: 0\n' + fixture('smartctl.json').replace('"exit_status": 0', '"exit_status": 8'))
        self.assertFalse(data['acquisition_complete'])
        self.assertTrue(data['health_alert'])

    def test_trailing_or_malformed_json_cannot_be_complete(self):
        data = parse_smart(fixture('smartctl.json') + '\nunexpected trailing diagnostic')
        self.assertFalse(data['parse_complete'])
        self.assertIn('unexpected_trailing_json_content', data['errors'])
        data = parse_smart('Exit code: 0\n{"smartctl": ')
        self.assertFalse(data['parse_complete'])
        self.assertIn('invalid_json_payload', data['errors'])

    def test_named_compatibility_view_includes_noncritical_attributes(self):
        values = smart_raw_attributes(FIXTURES / 'smartctl_extended.txt')
        self.assertEqual(values['Power_On_Hours'], 10024)
        self.assertEqual(values['UDMA_CRC_Error_Count'], 231)
        self.assertEqual(len(values), 8)

    def test_missing_attribute_is_not_zero(self):
        data = parse_smart('\n'.join(line for line in fixture().splitlines()
                                     if not line.startswith('198 ')))
        self.assertFalse(data['parse_complete'])
        self.assertNotIn('198', data['attributes'])
        self.assertIn('198', data['missing_required_ids'])

    def test_non_numeric_raw_value_is_preserved_as_unknown(self):
        data = parse_smart(fixture().replace('000    -    231', '000    -    unknown'))
        self.assertIsNone(data['attributes']['199']['raw_value'])
        self.assertEqual(data['attributes']['199']['raw'], 'unknown')
        self.assertFalse(data['parse_complete'])

    def test_read_failure_and_standby_have_no_fabricated_counters(self):
        for name in ('smartctl_read_error.txt', 'smartctl_standby.txt'):
            data = parse_smart(fixture(name))
            self.assertEqual(data['attributes'], {})
            self.assertFalse(data['parse_complete'])
            self.assertFalse(data['acquisition_complete'])

    def test_exit_bitmask_health_is_distinct_from_acquisition(self):
        data = parse_smart(fixture().replace('Exit code: 0', 'Exit code: 8'))
        self.assertTrue(data['parse_complete'])
        self.assertTrue(data['acquisition_complete'])
        self.assertTrue(data['health_alert'])
        data = parse_smart(fixture().replace('Exit code: 0', 'Exit code: 64'))
        self.assertTrue(data['acquisition_complete'])
        self.assertFalse(data['health_alert'])
        self.assertEqual(data['exit_status_bits'], [6])

    def test_missing_exit_status_is_not_confirmed_acquisition(self):
        data = parse_smart(fixture().replace('Exit code: 0', ''))
        self.assertTrue(data['parse_complete'])
        self.assertFalse(data['acquisition_complete'])

    def test_unknown_header_extra_spacing_and_hex_raw(self):
        text = fixture().replace('000    -    231', '000    -    0x000000e7')
        data = parse_smart(text)
        self.assertEqual(data['attributes']['199']['raw_value'], 231)
        self.assertTrue(data['parse_complete'])

    def test_duplicate_attribute_ids_are_not_silently_overwritten(self):
        line = next(line for line in fixture().splitlines() if line.startswith('199 '))
        data = parse_smart(fixture() + '\n' + line)
        self.assertFalse(data['parse_complete'])
        self.assertIn('duplicate_attribute_id:199', data['errors'])

    def test_all_changes_are_recorded_but_hours_temperature_are_not_media_failure(self):
        left = parse_smart(fixture('smartctl_standard.txt'))
        right = parse_smart(fixture())
        data, concerning = compare_smart(left, right)
        self.assertEqual(data['changes']['9']['delta'], 24)
        self.assertEqual(data['changes']['194']['delta'], 2)
        self.assertTrue(data['parse_complete'])
        self.assertFalse(concerning)

    def test_attribute_name_changes_compare_by_id(self):
        left = parse_smart(fixture())
        right = parse_smart(fixture().replace('UDMA_CRC_Error_Count', 'Interface_CRC_Errors')
                            .replace('000    -    231', '000    -    232'))
        data, concerning = compare_smart(left, right)
        self.assertEqual(data['changes']['199']['delta'], 1)
        self.assertTrue(concerning)

    def test_monotonic_counter_decrease_requires_review(self):
        data, concerning = compare_smart(parse_smart(fixture()),
            parse_smart(fixture().replace('000    -    231', '000    -    0')))
        self.assertFalse(data['parse_complete'])
        self.assertEqual(data['counter_decreases'], ['199'])


class SmartCaptureOwnership(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.rec = Recorder(str(Path(self.tmp.name) / 'out'))
        (self.rec.dir / 'smart').mkdir()
        self.targets = [dataclasses.replace(t, serial=f'TEST-SERIAL-{chr(65+i)}')
                        for i, t in enumerate(fake_targets()[:2])]
        self.guard = SimpleNamespace(targets=self.targets)

    def write(self, name, text):
        (self.rec.dir / 'smart' / name).write_text(text)

    def seed(self):
        for i, serial in ((1, 'A'), (2, 'B')):
            for label in ('before', 'end_on_exit'):
                self.write(f'{label}_disk{i}.txt', fixture().replace('TEST-SERIAL-A', 'TEST-SERIAL-' + serial))

    def test_changed_device_names_and_file_order_keep_serial_ownership(self):
        self.seed()
        self.write('end_on_exit_disk1.txt', fixture().replace('TEST-SERIAL-A','TEST-SERIAL-B')
                   .replace('000    -    231','000    -    234').replace('fake-scsi-lun0','fake-scsi-lun9'))
        self.write('end_on_exit_disk2.txt', fixture().replace('fake-scsi-lun0','fake-scsi-lun8'))
        records, concerning = smart_delta(self.rec, self.guard)
        self.assertTrue(concerning)
        self.assertEqual(records[0]['serial'], 'TEST-SERIAL-A')
        self.assertEqual(records[0]['changes'], {})
        self.assertEqual(records[1]['changes']['199']['delta'], 3)
        self.assertTrue(all(x['parse_complete'] for x in records))

    def test_missing_serial_does_not_fall_back_to_disk_number(self):
        self.seed()
        self.write('end_on_exit_disk1.txt', fixture().replace('Serial Number:    TEST-SERIAL-A',''))
        records, _ = smart_delta(self.rec, self.guard)
        self.assertEqual(records[0]['end'], {})
        self.assertFalse(records[0]['parse_complete'])

    def test_duplicate_serial_is_ambiguous(self):
        self.seed()
        self.write('end_on_exit_disk2.txt', fixture())
        records, _ = smart_delta(self.rec, self.guard)
        self.assertTrue(all(not x['parse_complete'] for x in records))
        self.assertIn('duplicate_serial', ' '.join(records[0]['capture_errors']))

    def test_missing_end_capture_is_incomplete(self):
        self.seed()
        (self.rec.dir / 'smart' / 'end_on_exit_disk2.txt').unlink()
        records, _ = smart_delta(self.rec, self.guard)
        self.assertFalse(records[1]['parse_complete'])
        self.assertFalse(records[1]['acquisition_complete'])
        self.assertEqual(records[1]['end'], {})

    def test_snapshot_timeout_retains_diagnostic_and_continues_other_target(self):
        completed = SimpleNamespace(returncode=0, stdout=fixture().replace('TEST-SERIAL-A','TEST-SERIAL-B'), stderr='')
        with patch('ph8057_qualify.run', side_effect=[Abort('Command timed out'), completed]), \
             patch('ph8057_qualify.shutil.which', return_value=None):
            smart_snapshot(self.guard, self.rec, 'before')
        first = json.loads((self.rec.dir/'smart'/'before_disk1.json').read_text())
        second = json.loads((self.rec.dir/'smart'/'before_disk2.json').read_text())
        self.assertFalse(first['acquisition_complete'])
        self.assertEqual(first['expected_serial'], 'TEST-SERIAL-A')
        self.assertEqual(second['serial'], 'TEST-SERIAL-B')
        self.assertEqual(self.rec.counters['monitor_warnings'], 1)

    def test_snapshot_identity_mismatch_stops_before_more_commands(self):
        wrong = SimpleNamespace(returncode=0, stdout=fixture().replace('TEST-SERIAL-A','UNKNOWN-DISK'), stderr='')
        with patch('ph8057_qualify.run', return_value=wrong) as command:
            with self.assertRaisesRegex(Abort, 'ATA identity changed'):
                smart_snapshot(self.guard, self.rec, 'before')
        command.assert_called_once()

    def test_identity_read_error_is_not_accepted_even_with_text(self):
        p = SimpleNamespace(returncode=2, stdout=fixture(), stderr='open failure')
        with patch('ph8057_qualify.run', return_value=p):
            with self.assertRaisesRegex(Abort, 'Cannot confirm ATA identity'):
                safe_serial_from_smart('/dev/fake')


class SmartSummaryStatus(unittest.TestCase):
    def test_delta_exception_cannot_be_clean_completion(self):
        from test_workloads import ModeTests
        helper = ModeTests()
        helper.setUp()
        _, report = helper.fake_main('benchmark', ['--no-usbmon'], smart_error=ValueError('broken input'))
        self.assertFalse(report['smart_delta_complete'])
        self.assertEqual(report['result'], 'COMPLETE_WITH_WARNINGS_REVIEW_LOGS')

    def test_empty_delta_list_cannot_be_clean_completion(self):
        from test_workloads import ModeTests
        helper = ModeTests()
        helper.setUp()
        _, report = helper.fake_main('benchmark', ['--no-usbmon'], smart_result=([], False))
        self.assertFalse(report['smart_delta_complete'])
        self.assertEqual(report['result'], 'COMPLETE_WITH_WARNINGS_REVIEW_LOGS')

    def test_optional_log_error_keeps_counters_but_warns_on_acquisition(self):
        from test_workloads import ModeTests
        helper = ModeTests()
        helper.setUp()
        data = parse_smart(fixture('smartctl_sat_optional_error_disk1.txt'))
        delta, worse = compare_smart(data, data)
        _, report = helper.fake_main('benchmark', ['--no-usbmon'], smart_result=([delta]*3, worse))
        self.assertTrue(report['smart_delta'][0]['parse_complete'])
        self.assertFalse(report['smart_delta_complete'])
        self.assertEqual(report['result'], 'COMPLETE_WITH_WARNINGS_REVIEW_LOGS')
