"""Fail-closed disk checks and refusal before any destructive operation."""
import contextlib
import io
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ph8057_qualify import Abort, base_checks, main
from test_offline import fake_targets


def done(stdout='', returncode=0):
    return SimpleNamespace(stdout=stdout, stderr='', returncode=returncode)


class DiskChecks(unittest.TestCase):
    def check(self, node_types='disk\n', mounts='', mount_rc=0, signature='', holder=False, swap=False):
        def command(args, timeout):
            if args[:4] == ['lsblk','-nr','-o','TYPE']:
                return done(node_types)
            if args[:4] == ['lsblk','-nr','-o','MOUNTPOINTS']:
                return done(mounts, mount_rc)
            if args[0] == 'wipefs':
                return done(signature)
            raise AssertionError('Unexpected command: ' + repr(args))

        def text(path, *args, **kwargs):
            value = str(path)
            if value == '/proc/swaps':
                return 'Filename Type Size Used Priority\n' + ('/dev/sdz partition 100 0 -2\n' if swap else '')
            if value.endswith('/size'):
                return '976773168\n'
            if value.endswith('/logical_block_size'):
                return '512\n'
            raise AssertionError('Unexpected read: ' + value)

        with patch('ph8057_qualify.lsblk_column', side_effect=lambda device,col: {'TYPE':'disk','TRAN':'usb','RO':'0'}[col]), \
             patch('ph8057_qualify.run', side_effect=command), \
             patch('ph8057_qualify.Path.is_dir', return_value=holder), \
             patch('ph8057_qualify.Path.iterdir', return_value=iter([Path('/fake/holder')])), \
             patch('ph8057_qualify.Path.read_text', text):
            return base_checks('sdz')

    def test_unmounted_bare_disposable_usb_disk_passes(self):
        self.assertEqual(self.check(), (500107862016,512))

    def test_mounted_whole_disk_is_rejected(self):
        with self.assertRaisesRegex(Abort, 'Mounted device'):
            self.check(mounts='/\n')

    def test_failed_mount_inventory_is_rejected(self):
        with self.assertRaisesRegex(Abort, 'unavailable mount inventory'):
            self.check(mount_rc=1)

    def test_mounted_child_partition_is_rejected(self):
        with self.assertRaisesRegex(Abort, 'children detected'):
            self.check(node_types='disk\npart\n', mounts='/boot\n')

    def test_lvm_raid_and_children_are_rejected(self):
        for kind in ('part','lvm','raid1','crypt'):
            with self.subTest(kind=kind), self.assertRaisesRegex(Abort, 'children detected'):
                self.check(node_types='disk\n'+kind+'\n')

    def test_filesystem_signature_is_rejected(self):
        with self.assertRaisesRegex(Abort, 'signature detected'):
            self.check(signature='ext4\n')

    def test_active_holders_are_rejected(self):
        with self.assertRaisesRegex(Abort, 'holders'):
            self.check(holder=True)

    def test_swap_use_is_rejected(self):
        with self.assertRaisesRegex(Abort, 'Swap in use'):
            self.check(swap=True)

    def test_nonusb_system_disk_is_rejected(self):
        with patch('ph8057_qualify.lsblk_column', side_effect=['disk','sata']), \
             patch('ph8057_qualify.run') as command:
            with self.assertRaisesRegex(Abort, 'Not a USB transport'):
                base_checks('sda')
        command.assert_not_called()


class PrivilegeChecks(unittest.TestCase):
    def test_nonroot_is_refused_before_hardware_or_lock_access(self):
        args = ['test', '--devices', '/dev/sdc', '/dev/sdd', '/dev/sde', '--run']
        with patch('ph8057_qualify.sys.argv', args), \
             patch('ph8057_qualify.os.geteuid', return_value=1000), \
             patch('ph8057_qualify.require_tools') as tools, \
             patch('ph8057_qualify.Guard') as guard, \
             patch('ph8057_qualify.run') as command, \
             patch('ph8057_qualify.Path.open') as open_file, \
             patch('ph8057_qualify.Recorder') as recorder, \
             patch('ph8057_qualify.run_fio_phase') as fio:
            with self.assertRaisesRegex(Abort, 'Run as root'):
                main()
            for operation in (tools, guard, command, open_file, recorder, fio):
                operation.assert_not_called()


class ExplicitConfirmation(unittest.TestCase):
    def check_refusal(self, tty, answer='incorrect'):
        targets = fake_targets()
        guard = SimpleNamespace(targets=targets, all_disks=targets, excluded=None,
                                usb_parent='/sys/fake-usb')
        args = ['test','--devices','/dev/sdc','/dev/sdd','/dev/sde','--run','--mode','io']
        with patch('ph8057_qualify.sys.argv',args), \
             patch('ph8057_qualify.os.geteuid', return_value=0), \
             patch('ph8057_qualify.require_tools'), \
             patch('ph8057_qualify.Guard', return_value=guard), \
             patch('ph8057_qualify.Path.open', return_value=io.StringIO()), \
             patch('ph8057_qualify.fcntl.flock'), \
             patch('ph8057_qualify.sys.stdin', SimpleNamespace(isatty=lambda:tty)), \
             patch('builtins.input', return_value=answer), \
             patch('ph8057_qualify.Recorder') as recorder, \
             patch('ph8057_qualify.run_fio_phase') as fio, \
             contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(Abort,'confirmation'):
                main()
            recorder.assert_not_called()
            fio.assert_not_called()

    def test_noninteractive_input_cannot_authorize_writes(self):
        self.check_refusal(False)

    def test_wrong_serial_derived_token_cannot_authorize_writes(self):
        self.check_refusal(True)

    def test_preflight_never_creates_recorder_or_launches_io(self):
        targets = fake_targets()
        guard = SimpleNamespace(targets=targets, all_disks=targets, excluded=None,
                                usb_parent='/sys/fake-usb')
        args = ['test','--devices','/dev/sdc','/dev/sdd','/dev/sde','--preflight']
        with patch('ph8057_qualify.sys.argv',args), \
             patch('ph8057_qualify.os.geteuid', return_value=0), \
             patch('ph8057_qualify.require_tools'), \
             patch('ph8057_qualify.Guard', return_value=guard), \
             patch('ph8057_qualify.Path.open', return_value=io.StringIO()), \
             patch('ph8057_qualify.fcntl.flock'), \
             patch('ph8057_qualify.Recorder') as recorder, \
             patch('ph8057_qualify.run_fio_phase') as fio, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(),0)
            recorder.assert_not_called()
            fio.assert_not_called()
