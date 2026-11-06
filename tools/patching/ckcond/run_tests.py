#!/usr/bin/env python3
"""Run canonical offline CK_COND tests, with explicit stock-dependent skips.

No device paths, SG_IO calls, USB operations, or SPI operations are present.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
PUBLIC_SUITES = ("test_asm51.py", "test_native_paths.py")
STOCK_SUITES = ("test_capture_wrappers.py", "test_sense_patch.py",
                "test_sense_contract.py", "test_sat12_path.py",
                "test_integrated_patch.py", "test_terminal_edge_paths.py",
                "test_build_and_capture_replay.py", "test_port_ownership.py")
SCENARIO_RESULTS = {
    "test_capture_wrappers.py": ("capture_wrapper_test_results.json", (
        "wrapper_abi_current_register_bank_dps_ea_cases", "pio_transport_guard_cases",
        "authentic_nondata_branches_with_actual_wrapper", "native_mapper_against_original_AA9F_inputs")),
    "test_sense_patch.py": ("sense_test_results.json", ("total_scenarios",)),
    "test_sat12_path.py": ("sat12_test_results.json", ("total_scenarios",)),
    "test_port_ownership.py": ("port_owner_results.json", ("cases",)),
}


def main():
    if not __debug__:
        raise RuntimeError("Regression tests cannot run with Python assertions disabled")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stock", type=Path)
    parser.add_argument("--out", type=Path, default=HERE / "test_results")
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
        if suite in SCENARIO_RESULTS:
            (args.out / SCENARIO_RESULTS[suite][0]).unlink(missing_ok=True)
        start = time.monotonic()
        process = subprocess.run([sys.executable, "-B", str(source)], env=env,
                                 cwd=HERE, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True, timeout=120)
        (args.out / (source.stem + ".log")).write_text(process.stdout)
        record = {"suite": suite, "exit_code": process.returncode,
                  "status": "PASS" if process.returncode == 0 else "FAIL",
                  "seconds": round(time.monotonic()-start, 3),
                  "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
        if suite not in SCENARIO_RESULTS:
            match = re.search(r"Ran (\d+) tests? in ", process.stdout)
            skips = re.search(r"\bskipped=(\d+)", process.stdout)
            total = int(match[1]) if match else 0
            skipped = int(skips[1]) if skips else 0
            record.update(test_methods_reported=total, skipped_methods=skipped,
                          executed_methods=total - skipped)
            if not total:
                record.update(status="FAIL", reason="No unittest methods executed or reported")
            elif skipped and process.returncode == 0:
                record["status"] = "PASS_WITH_SKIPS"
        else:
            record["runner"] = "native scenario script; exit status includes every assertion"
            filename, counts = SCENARIO_RESULTS[suite]
            try:
                result = json.loads((args.out / filename).read_text())
                if result.get("status") != "PASS" or any(type(result.get(key)) is not int or result[key] <= 0 for key in counts):
                    raise ValueError("Scenario report lacks successful executed cases")
                record["result"] = filename
            except (OSError, ValueError) as exc:
                record.update(status="FAIL", reason=str(exc))
        records.append(record)
        print(f"{record['status']} {suite}", flush=True)
        if record["status"] == "FAIL":
            if record.get("reason"):
                print(record["reason"], flush=True)
            print(process.stdout, flush=True)
    failed = any(r["status"] == "FAIL" for r in records)
    report = {"status": ("FAIL" if failed else "PASS_OFFLINE_WITH_STOCK" if stock_present
                         else "PASS_PUBLIC_SYNTHETIC_ONLY"),
              "suites": records,
              "stock_sha256": hashlib.sha256(stock.read_bytes()).hexdigest() if stock_present else None,
              "hardware_tests_in_this_run": "NOT TESTED",
              "hardware_operations": 0,
              "scope": "Instruction fixtures, image guards and native code paths; no device model"}
    (args.out / "ckcond_suite_results.json").write_text(json.dumps(report, indent=2) + "\n")
    print(report["status"], flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
