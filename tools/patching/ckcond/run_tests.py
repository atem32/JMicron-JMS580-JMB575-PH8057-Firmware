#!/usr/bin/env python3
"""Run canonical offline CK_COND tests, with explicit stock-dependent skips.

No device paths, SG_IO calls, USB operations, or SPI operations are present.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
PUBLIC_SUITES = ("test_asm51.py", "test_independent.py")
STOCK_SUITES = ("test_capture_wrappers.py", "test_sense_patch.py",
                "test_sense_contract.py", "test_sat12_path.py",
                "test_integrated_patch.py", "test_terminal_edge_paths.py",
                "test_build_and_capture_replay.py", "test_port_ownership.py")


def main():
    if not __debug__:
        raise RuntimeError("Regression tests cannot run with Python assertions disabled")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stock", type=Path)
    parser.add_argument("--out", type=Path, default=HERE / "test_results")
    parser.add_argument("--legacy-capture-generator", type=Path)
    args = parser.parse_args()
    from image import guard_output_tree
    selected_stock = args.stock or Path(os.environ.get("PH8057_STOCK", "/nonexistent"))
    guard_output_tree(selected_stock, args.out)
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.pop("PYTHONOPTIMIZE", None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PH8057_TEST_RESULTS"] = str(args.out)
    if args.stock:
        env["PH8057_STOCK"] = str(args.stock.resolve())
    if args.legacy_capture_generator:
        env["PH8057_LEGACY_CAPTURE_GENERATOR"] = str(args.legacy_capture_generator.resolve())
    stock = Path(env.get("PH8057_STOCK", "/nonexistent"))
    stock_present = stock.is_file()
    if stock_present:
        from image import read_stock
        read_stock(stock)
    records = []
    for suite in (*PUBLIC_SUITES, *STOCK_SUITES):
        if suite in STOCK_SUITES and not stock_present:
            records.append({"suite": suite, "status": "SKIPPED_REQUIRES_STOCK"})
            continue
        source = HERE / "tests" / suite
        start = time.monotonic()
        process = subprocess.run([sys.executable, "-B", str(source)], env=env,
                                 cwd=HERE, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True, timeout=120)
        (args.out / (source.stem + ".log")).write_text(process.stdout)
        record = {"suite": suite, "exit_code": process.returncode,
                  "status": "PASS" if process.returncode == 0 else "FAIL",
                  "seconds": round(time.monotonic()-start, 3),
                  "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
        records.append(record)
        print(f"{record['status']} {suite}", flush=True)
        if process.returncode:
            print(process.stdout, flush=True)
    failed = any(r["status"] == "FAIL" for r in records)
    report = {"status": ("FAIL" if failed else "PASS_OFFLINE_WITH_STOCK" if stock_present
                         else "PASS_PUBLIC_SYNTHETIC_ONLY"),
              "suites": records,
              "stock_sha256": hashlib.sha256(stock.read_bytes()).hexdigest() if stock_present else None,
              "candidate_hardware_validation": "NOT_PERFORMED",
              "hardware_operations": 0,
              "scope": "Instruction fixtures, image guards and native code paths; no device model"}
    (args.out / "ckcond_suite_results.json").write_text(json.dumps(report, indent=2) + "\n")
    print(report["status"], flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
