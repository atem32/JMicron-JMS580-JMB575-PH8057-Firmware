"""Shared configuration for offline tests; never locates or opens devices."""
import os

if not __debug__:
    raise RuntimeError("Offline regression suites require assertions; do not use python -O")
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
COMPONENT = HERE.parent
sys.path[:0] = [str(COMPONENT), str(HERE)]
for candidate in (Path(os.environ.get("PH8057_COMMON", "/nonexistent")),
                  COMPONENT.parent / "common", COMPONENT.parent.parent / "emulator"):
    if (candidate / "mcs51.py").is_file():
        sys.path.insert(0, str(candidate))
        break
STOCK_PATH = Path(os.environ.get("PH8057_STOCK", "firmware/original/PH8057_FACTORY_COMPLETE_READBACK_DO_NOT_FLASH.bin"))
EVIDENCE_PATH = Path(os.environ.get("PH8057_E5_EVIDENCE", str(COMPONENT / "e5_replay_fixture.json")))
RESULTS = Path(os.environ.get("PH8057_TEST_RESULTS", str(COMPONENT / "test_results")))
RESULTS.mkdir(parents=True, exist_ok=True)
