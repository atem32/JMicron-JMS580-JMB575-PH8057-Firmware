"""Replay the preserved v23-v29/final reported check units using the canonical emulator.

Original archive files are read-only. Each analyzer is copied into a temporary
directory with its original arguments/expectations, replacing only mcs51.py.
The caller supplies the extracted evidence root and explicit exact-stock BIN.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from provenance import replay_environment, verify_emulator, verify_history

EXPECTED = {23: 1577, 24: 2296, 25: 1985, 26: 7981, 27: 2164, 28: 5903, 29: 10005}
SOURCES = {
    23: ("9d5bcb21b21b6032/PH8057_v23_OEM_BIT_ATLAS_OFFLINE", "PH8057_v23_bit_atlas.py"),
    24: ("cec2533eddfdd930/PH8057_v24_OEM_FUNCTIONAL_PROOFS_OFFLINE", "audit_v24.py"),
    25: ("faecfe634f107613", "audit_v25.py"),
    26: ("161fc88b00ce339a", "audit_v26.py"),
    27: ("886ff4a08bd92f83", "audit_v27.py"),
    28: ("210d3d9c4455d6ad", "audit_v28.py"),
    29: ("fe2708c6c5b50374", "audit_v29.py"),
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replay(evidence: Path, emulator: Path, out: Path):
    evidence, emulator, out = evidence.resolve(), emulator.resolve(), out.resolve()
    provenance = verify_history(evidence, "legacy_oem", output=out)
    evidence = Path(provenance["root"])
    emulator_sha256 = verify_emulator(emulator)
    out.mkdir(parents=True, exist_ok=True)
    handover = evidence / "f3b3148c740947cb" / "PH8057_HANDOVER_V2-V29_2026-11-02"
    stock = handover / "firmware" / "PH8057_FACTORY_COMPLETE_READBACK_DO_NOT_FLASH.bin"
    donors = handover / "donor_JMS580"
    summary = {"emulator_sha256": emulator_sha256, "analyzers": {}, "expectations_modified": False,
               "reviewed_history": provenance}
    for version, (relative, script) in SOURCES.items():
        original = evidence / relative
        with tempfile.TemporaryDirectory(prefix=f"ph8057_oem_legacy_{version}_") as tmp:
            root = Path(tmp) / "work"
            shutil.copytree(original, root, ignore=shutil.ignore_patterns("__pycache__"))
            shutil.copyfile(emulator, root / "mcs51.py")
            report = out / f"legacy_v{version}.json"
            destination = out / "legacy_v26" if version == 26 else report
            command = [sys.executable, str(root / script), str(stock), "--out", str(destination)]
            if version == 26:
                command += ["--donors", str(donors)]
            result = subprocess.run(command, cwd=root, text=True, capture_output=True,
                                    timeout=180, env=replay_environment())
            (out / f"legacy_v{version}.log").write_text(result.stdout + result.stderr)
            if result.returncode:
                raise RuntimeError(f"Legacy v{version} failed with corrected emulator; see log")
            if version == 26:
                report = destination / "results_v26.json"
            value = json.loads(report.read_text())
            count = next(value[key] for key in ("total_checks", "total_offline_checks", "total", "passed")
                         if isinstance(value.get(key), int))
            if count != EXPECTED[version]:
                raise AssertionError(("Unexpected historical reported-unit count", version, count, EXPECTED[version]))
            summary["analyzers"][str(version)] = {"passed": count, "analyzer_sha256": sha(original / script),
                                                  "original_emulator_sha256": sha(original / "mcs51.py"),
                                                  "source": str(original.relative_to(evidence) / script)}
            print("Legacy", version, "PASS", count, flush=True)
    with tempfile.TemporaryDirectory(prefix="ph8057_oem_legacy_final_") as tmp:
        root = Path(tmp) / "work"
        shutil.copytree(evidence / "f3b3148c740947cb", root,
                        ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copyfile(emulator, root / "sources_v29" / "mcs51.py")
        result = subprocess.run([sys.executable, str(root / "final_audit.py")], cwd=root,
                                text=True, capture_output=True, timeout=180,
                                env=replay_environment())
        (out / "legacy_final.log").write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError("Legacy final failed with corrected emulator; see log")
        report = root / "final_results" / "AUDIT_FINAL.json"
        value = json.loads(report.read_text())
        if value["passed"] != 1905:
            raise AssertionError(("Final historical count", value["passed"]))
        shutil.copyfile(report, out / "legacy_final.json")
        summary["analyzers"]["final"] = {"passed": 1905, "analyzer_sha256": sha(root / "final_audit.py")}
    summary["sum_overlapping_reported_check_units"] = sum(x["passed"] for x in summary["analyzers"].values())
    summary["scope"] = "Overlapping reported check units on bounded original CODE with synthetic memory and stubs; not 33,816 literal assertions, independent features, or hardware tests. Separate instrumentation observes 44,211 guards."
    (out / "legacy_replay_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print("PASS all", summary["sum_overlapping_reported_check_units"], "historical reported check units")
    return summary


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("evidence", type=Path)
    p.add_argument("emulator", type=Path)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    replay(a.evidence, a.emulator, a.out)
