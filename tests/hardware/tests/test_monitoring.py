"""Offline regressions for missing kernel evidence and final result status."""
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ph8057_qualify import Background, Recorder, kernel_final
from test_offline import fake_targets


class KernelMonitoring(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.rec = Recorder(str(Path(self.temp.name) / 'out'))
        self.guard = SimpleNamespace(usb_parent='/sys/fake-usb', targets=fake_targets())
        self.bg = Background(self.guard, self.rec, SimpleNamespace())

    def test_premature_monitor_exit_is_a_warning(self):
        process = MagicMock()
        process.poll.return_value = 1
        with patch('ph8057_qualify.subprocess.Popen', return_value=process):
            self.bg.worker(self.bg.kernel_thread)
        self.assertEqual(self.rec.counters['monitor_warnings'], 1)
        self.assertFalse(self.bg.failed.is_set())

    def test_premature_monitor_eof_is_a_warning(self):
        process = MagicMock()
        process.poll.return_value = None
        with patch('ph8057_qualify.subprocess.Popen', return_value=process), \
             patch('ph8057_qualify.select.select', return_value=([process.stdout], [], [])), \
             patch('ph8057_qualify.os.read', return_value=b''):
            self.bg.worker(self.bg.kernel_thread)
        self.assertEqual(self.rec.counters['monitor_warnings'], 1)
        process.terminate.assert_called_once()

    def test_requested_monitor_shutdown_is_not_a_warning(self):
        self.bg.stop.set()
        process = MagicMock()
        with patch('ph8057_qualify.subprocess.Popen', return_value=process):
            self.bg.worker(self.bg.kernel_thread)
        self.assertEqual(self.rec.counters['monitor_warnings'], 0)

    def test_failed_final_journal_acquisition_preserves_diagnostic_and_fails(self):
        process = SimpleNamespace(returncode=1, stdout='', stderr='Permission denied')
        with patch('ph8057_qualify.run', return_value=process):
            with self.assertRaisesRegex(RuntimeError, 'kernel log acquisition failed'):
                kernel_final(self.rec, '2026-01-05 00:00:00', self.guard)
        self.assertIn('Permission denied', (self.rec.dir / 'kernel.log').read_text())

    def test_successful_empty_kernel_log_is_available(self):
        process = SimpleNamespace(returncode=0, stdout='', stderr='')
        with patch('ph8057_qualify.run', return_value=process):
            self.assertEqual(kernel_final(self.rec, '2026-01-05 00:00:00', self.guard), [])

    def test_final_acquisition_exception_prevents_clean_result(self):
        from test_workloads import ModeTests
        helper = ModeTests()
        helper.setUp()
        _, report = helper.fake_main('benchmark', ['--no-usbmon'],
                                     kernel_error=TimeoutError('journal timed out'))
        self.assertFalse(report['kernel_log_complete'])
        self.assertEqual(report['counters']['monitor_warnings'], 1)
        self.assertEqual(report['result'], 'COMPLETE_WITH_WARNINGS_REVIEW_LOGS')
        self.assertNotEqual(helper.last_exit_code, 0)


if __name__ == '__main__':
    unittest.main()
