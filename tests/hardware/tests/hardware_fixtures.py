"""Process fixtures for main() tests that replace all hardware operations."""
from contextlib import contextmanager
from pathlib import Path
import tempfile
from unittest.mock import patch


@contextmanager
def mock_root_and_lock():
    """Emulate root without using the host's qualification lock file."""
    original_open = Path.open
    host_lock = Path('/run/lock/ph8057-qualify.lock')
    with tempfile.TemporaryDirectory(prefix='ph8057-offline-lock-') as directory:
        test_lock = Path(directory) / 'qualification.lock'

        def open_with_test_lock(path, *args, **kwargs):
            return original_open(test_lock if path == host_lock else path, *args, **kwargs)

        with patch('ph8057_qualify.os.geteuid', return_value=0), \
             patch('ph8057_qualify.Path.open', open_with_test_lock):
            yield
