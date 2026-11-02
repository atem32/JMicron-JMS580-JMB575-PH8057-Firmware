#!/usr/bin/env python3
"""Replay the unchanged historical v8 suites in a temporary copy; no hardware."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from provenance import verify_history


def replay(evidence, out):
    evidence, out = Path(evidence).resolve(), Path(out).resolve()
    provenance = verify_history(evidence, "v8", output=out)
    evidence = Path(provenance["root"])
    source = evidence / "6d36298a2afad5e4/ph8057_v8"
    if not (source / "work_v8/run_all.py").is_file():
        raise ValueError("The original v8 package is absent from extracted history")
    if not __debug__:
        raise RuntimeError("Historical test assertions must remain enabled")
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ph8057_original_v8_") as td:
        tree = Path(td) / "ph8057_v8"
        shutil.copytree(source, tree, ignore=shutil.ignore_patterns("__pycache__"))
        env = os.environ.copy()
        env.pop("PYTHONOPTIMIZE", None)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        cp = subprocess.run([sys.executable, "-B", str(tree / "work_v8/run_all.py")],
                            cwd=tree, env=env, text=True, capture_output=True, timeout=300)
        (out / "historical_v8.log").write_text(cp.stdout + cp.stderr)
        for name in ("test_summary.json", "build_report.json"):
            p = tree / "work_v8/build" / name
            if p.exists():
                shutil.copyfile(p, out / name)
        logdir = tree / "work_v8/build/testlogs"
        if logdir.is_dir():
            shutil.copytree(logdir, out / "testlogs", dirs_exist_ok=True)
        if cp.returncode:
            raise RuntimeError("Original v8 replay failed; see historical_v8.log")
        raw = (tree / "work_v8/build/PH8057_v8_EXPERIMENTAL_DO_NOT_FLASH.bin").read_bytes()
        if hashlib.sha256(raw).hexdigest() != "4b7ac3e5bd124d8e44281e9aa79b7b65f7b62c54410ffd1abd8af4a586d74e11":
            raise RuntimeError("Historical v8 reconstruction changed")
    (out / "reviewed_history.json").write_text(json.dumps(provenance, indent=2) + "\n")
    print("PASS historical v8 ten suites and byte-for-byte rebuild; source expectations unchanged")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("evidence", type=Path)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    replay(a.evidence, a.out)
