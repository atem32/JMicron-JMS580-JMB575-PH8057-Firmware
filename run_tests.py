#!/usr/bin/env python3
"""Run current offline regressions; absent private inputs produce explicit skips."""
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
    p.add_argument("--stock", type=Path, help="Exact 70,144-byte factory SPI image")
    p.add_argument("--device-stock", type=Path, help="Exact 67,072-byte original updater package")
    p.add_argument("--donors", type=Path, help="Directory containing the identified JMS580 donor packages; requires --stock")
    p.add_argument("--out", type=Path, default=ROOT / "build/validation")
    args = p.parse_args()
    guard_results_directory(args.out)
    out = args.out.resolve()
    for source in (args.stock, args.device_stock):
        if source and source.resolve().is_relative_to(out):
            p.error("Output directory must not contain an immutable firmware input")
    if args.donors:
        if not args.stock:
            p.error("--donors requires --stock")
        donors = args.donors.resolve()
        if not donors.is_dir() or donors.is_relative_to(out) or out.is_relative_to(donors):
            p.error("Donors must be a directory separate from the results tree")
    out.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.pop("PYTHONOPTIMIZE", None)
    for key in ("PH8057_STOCK", "PH8057_DEVICE_STOCK", "PH8057_V8", "PH8057_REVISED_CKCOND"):
        env.pop(key, None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PH8057_COMMON"] = str(ROOT / "tools/emulator")
    env["PH8057_TEST_RESULTS"] = str(out / "ckcond")
    paths = [ROOT, *(ROOT / rel for rel in
             ("tools/emulator", "tools/analysis", "tools/patching/ckcond", "tools/patching/udma",
              "firmware/ph8057-device/modified"))]
    env["PYTHONPATH"] = os.pathsep.join(map(str, paths))
    sys.path[:0] = list(map(str, paths))
    if args.device_stock:
        from build_from_1bin import read_stock_package
        read_stock_package(args.device_stock)
        env["PH8057_DEVICE_STOCK"] = str(args.device_stock.resolve())
    records = []

    def run(name, argv):
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
                  "classification": "offline checks", "log": name + ".log"}
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
            if any(r["status"].startswith("SKIPPED") or r["status"] == "PASS_WITH_SKIPS"
                   for r in ck["suites"]) and code == 0:
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
            from image import read_stock
            from ph8057 import construct
            raw = read_stock(stock)
            env["PH8057_STOCK"] = str(stock)
            for variant, key in (("ckcond-v8", "PH8057_V8"), ("ckcond-revised", "PH8057_REVISED_CKCOND")):
                candidate, _ = construct(raw, variant)
                path = Path(td) / (variant + ".bin")
                path.write_bytes(candidate)
                env[key] = str(path)
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
            if args.donors:
                udma_args += ["--donors", args.donors.resolve()]
            run("native_udma", udma_args)
        else:
            skip("native_oem", "Exact local factory BIN required")
            skip("native_udma", "Exact local factory BIN required")
        if not args.donors:
            skip("donor_comparison", "Optional identified donor packages not supplied")
    failed = any(row["status"] == "FAIL" for row in records)
    source_hashes = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                     for folder in (ROOT / "tools", ROOT / "tests")
                     for path in sorted(folder.rglob("*"))
                     if path.is_file() and path.suffix in (".py", ".c", ".h", ".json")
                     and not any(part in ("test_results", "__pycache__") for part in path.parts)}
    for name in ("run_tests.py", "ph8057.py", "research/oem/registers.json", "firmware/manifests/images.json",
                 "firmware/ph8057-device/modified/build_from_1bin.py",
                 "firmware/ph8057-device/modified/verify_device_build.py",
                 "firmware/ph8057-device/modified/ckcond_revised_patch_records.json"):
        source_hashes[name] = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
    skipped = any(row["status"] in ("SKIPPED", "PASS_WITH_SKIPS") for row in records)
    report = {"status": "FAIL" if failed else "PASS_WITH_EXPLICIT_SKIPS" if skipped else "PASS_OFFLINE",
              "groups": records, "stock_sha256": hashlib.sha256(stock.read_bytes()).hexdigest() if stock else None,
              "device_stock_sha256": hashlib.sha256(args.device_stock.read_bytes()).hexdigest() if args.device_stock else None,
              "source_sha256": source_hashes, "hardware_operations": 0,
              "evidence_level": "OFFLINE VALIDATED" if not failed else "OFFLINE CHECKS FAILED",
              "hardware_tests_in_this_run": "NOT TESTED",
              "interpretation": "PASS applies only to executed checks. Skips, fixture assumptions, and hardware uncertainty remain explicit."}
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(report["status"], flush=True)
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
