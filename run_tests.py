#!/usr/bin/env python3
"""Unified offline regressions. Firmware-dependent checks are explicit skips without stock.

With --history-root, also replay reviewed archived offline entry points in
temporary copies. This does not run hardware collector main functions.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent


def guard_results_directory(path):
    """Reject existing log aliases before a suite can replace any result file."""
    path = Path(path)
    if path.is_symlink():
        raise ValueError("Results directory must not be a symbolic link")
    if not path.exists():
        return
    if not path.is_dir():
        raise ValueError("Results path must be a directory")
    for parent, directories, files in os.walk(path, followlinks=False):
        for name in directories:
            if (Path(parent) / name).is_symlink():
                raise ValueError("Results directory contains a symbolic link")
        for name in files:
            metadata = (Path(parent) / name).lstat()
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise ValueError("Results directory contains a linked or special file")


def main():
    if not __debug__:
        raise RuntimeError("Tests require assertions: python -O is not supported")
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--stock", type=Path)
    p.add_argument("--history-root", type=Path, help="Content-addressed extraction directory, normally audit_input")
    p.add_argument("--out", type=Path, default=ROOT / "build/validation")
    args = p.parse_args()
    guard_results_directory(args.out)
    out = args.out.resolve()
    if args.stock and args.stock.resolve().is_relative_to(out):
        p.error("Output directory must not contain the immutable stock input")
    if args.history_root:
        evidence = args.history_root.resolve()
        if evidence.is_relative_to(out) or out.is_relative_to(evidence):
            p.error("Output and immutable historical evidence trees must be separate")
    out.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.pop("PYTHONOPTIMIZE", None)
    for key in ("PH8057_STOCK", "PH8057_V8", "PH8057_REVISED_CKCOND"):
        env.pop(key, None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PH8057_COMMON"] = str(ROOT / "tools/emulator")
    env["PH8057_TEST_RESULTS"] = str(out / "ckcond")
    paths = [ROOT, *(ROOT / rel for rel in
             ("tools/emulator", "tools/analysis", "tools/patching/ckcond", "tools/patching/udma", "tools/history"))]
    env["PYTHONPATH"] = os.pathsep.join(map(str, paths))
    if args.history_root:
        sys.path[:0] = list(map(str, paths))
        from provenance import verify_history
        provenance = verify_history(args.history_root, "v8", output=out)
        args.history_root = Path(provenance["root"])
        env["PH8057_LEGACY_CAPTURE_GENERATOR"] = str(
            args.history_root / "6d36298a2afad5e4/ph8057_v8/work_v8/completion/capture_wrappers.py")
    records = []

    def run(name, argv, kind="canonical offline"):
        start = time.monotonic()
        try:
            cp = subprocess.run([sys.executable, "-B", *map(str, argv)], cwd=ROOT, env=env,
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=600)
            text, code = cp.stdout, cp.returncode
        except subprocess.TimeoutExpired as exc:
            text, code = str(exc), 124
        (out / (name + ".log")).write_text(text)
        record = {"group": name, "status": "PASS" if code == 0 else "FAIL",
                  "exit_code": code, "seconds": round(time.monotonic() - start, 3),
                  "classification": kind, "log": name + ".log"}
        if len(argv) >= 2 and list(argv[:2]) == ["-m", "unittest"]:
            match = re.search(r"Ran (\d+) tests? in ", text)
            skips = re.search(r"\bskipped=(\d+)", text)
            total = int(match[1]) if match else 0
            skipped = int(skips[1]) if skips else 0
            record.update(test_methods_reported=total, skipped_methods=skipped,
                          executed_methods=total - skipped)
            if total == 0:
                record.update(status="FAIL", reason="No unittest methods executed or reported")
            elif skipped and code == 0:
                record["status"] = "PASS_WITH_SKIPS"
        if name == "ckcond" and (out / "ckcond/ckcond_suite_results.json").is_file():
            ck = json.loads((out / "ckcond/ckcond_suite_results.json").read_text())
            record["subsuite_status"] = {r["suite"]: r["status"] for r in ck["suites"]}
            if any(r["status"].startswith("SKIPPED") for r in ck["suites"]) and code == 0:
                record["status"] = "PASS_WITH_SKIPS"
        records.append(record)
        print(record["status"], name, flush=True)
        if code:
            print(text, flush=True)

    def skip(name, reason):
        records.append({"group": name, "status": "SKIPPED", "reason": reason})
        print("SKIP", name, reason, flush=True)

    with tempfile.TemporaryDirectory(prefix="ph8057_current_tests_") as td:
        stock = args.stock.resolve() if args.stock else None
        if stock:
            sys.path[:0] = list(map(str, paths))
            from image import read_stock
            from ph8057 import construct
            raw = read_stock(stock)
            env["PH8057_STOCK"] = str(stock)
            for variant, key in (("ckcond-v8", "PH8057_V8"), ("ckcond-revised", "PH8057_REVISED_CKCOND")):
                candidate, _ = construct(raw, variant)
                path = Path(td) / (variant + ".bin")
                path.write_bytes(candidate)
                env[key] = str(path)
        if args.history_root:
            run("supplied_input_integrity", [ROOT / "tools/history/verify_supplied.py", args.history_root,
                                            "--out", out / "supplied_input_integrity.json"],
                "all supplied extracted file hashes; no historical execution")
        run("emulator", ["-m", "unittest", "discover", "-s", ROOT / "tools/emulator/tests", "-v"])
        run("oem", ["-m", "unittest", "discover", "-s", ROOT / "tests/regression", "-p", "test_oem.py", "-v"])
        run("integration", ["-m", "unittest", "discover", "-s", ROOT / "tests/integration", "-v"])
        ck_args = [ROOT / "tools/patching/ckcond/run_tests.py", "--out", out / "ckcond"]
        if stock:
            ck_args += ["--stock", stock]
        run("ckcond", ck_args)
        run("udma", ["-m", "unittest", "discover", "-s", ROOT / "tools/patching/udma/tests", "-v"])
        if stock:
            run("native_oem", [ROOT / "tools/analysis/native_oem.py", stock, "--out", out / "native_oem.json"])
            udma_args = [ROOT / "tools/patching/udma/run_audit.py", "--stock", stock,
                         "--v8", env["PH8057_V8"], "--revised-ckcond", env["PH8057_REVISED_CKCOND"],
                         "--out", out / "udma_native"]
            if args.history_root:
                hand = args.history_root.resolve() / "f3b3148c740947cb/PH8057_HANDOVER_V2-V29_2026-11-02"
                udma_args += ["--donors", hand / "donor_JMS580"]
            run("native_udma", udma_args)
        else:
            skip("native_oem", "Exact local factory BIN required")
            skip("native_udma", "Exact local factory BIN required")
        if args.history_root:
            evidence = args.history_root.resolve()
            emulator = ROOT / "tools/emulator/mcs51.py"
            run("historical_early", [ROOT / "tools/history/replay_early.py", evidence, "--out", out / "historical_early"], "historical replay")
            run("historical_original_v8", [ROOT / "tools/history/replay_original_v8.py", evidence, "--out", out / "historical_v8"], "historical replay")
            for script, label in (("replay_legacy_early.py", "historical_v15_v22"),
                                  ("replay_legacy_oem.py", "historical_v23_v29_final"),
                                  ("count_legacy_assertions.py", "historical_count_audit")):
                run(label, [ROOT / "tools/history" / script, evidence, emulator, "--out", out / label], "historical replay, original expectations")
        else:
            skip("historical_replay", "Use --history-root with the private extracted evidence")
    failed = any(row["status"] == "FAIL" for row in records)
    source_hashes = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                     for folder in (ROOT / "tools", ROOT / "tests")
                     for path in sorted(folder.rglob("*"))
                     if path.is_file() and path.suffix in (".py", ".c", ".h")}
    for name in ("run_tests.py", "ph8057.py"):
        source_hashes[name] = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
    report = {"status": "FAIL" if failed else "PASS_OFFLINE_WITH_STOCK" if stock else "PASS_PUBLIC_WITH_EXPLICIT_SKIPS",
              "groups": records, "stock_sha256": hashlib.sha256(stock.read_bytes()).hexdigest() if stock else None,
              "source_sha256": source_hashes, "hardware_operations": 0,
              "candidate_hardware_qualification": "NOT_PERFORMED",
              "interpretation": "PASS applies only to executed checks. Skips, fixture assumptions, and hardware uncertainty remain explicit."}
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(report["status"], flush=True)
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
