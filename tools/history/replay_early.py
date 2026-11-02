#!/usr/bin/env python3
"""Reproduce early offline checks from immutable, locally extracted history.

This runner executes ONLY the reviewed offline test entry points below, never
the hardware collector main functions. It copies all inputs into a temporary
tree. No expected results are edited. Sources remain historical, not canonical.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

from provenance import verify_history


def replay(root, output):
    root = root.resolve()
    provenance = verify_history(root, "early", output=output)
    output.mkdir(parents=True, exist_ok=True)
    source = Path(provenance["root"])
    github = source / "0766e3a6b43c6423/PH8057_JMS580_GITHUB_REPOSITORY_2026-11-02"
    stock = source / "f3b3148c740947cb/PH8057_HANDOVER_V2-V29_2026-11-02/firmware/PH8057_FACTORY_COMPLETE_READBACK_DO_NOT_FLASH.bin"
    short = github / "firmware/stock/ph8057-original.bin"
    donor = source / "f3b3148c740947cb/PH8057_HANDOVER_V2-V29_2026-11-02/donor_JMS580"
    if hashlib.sha256(stock.read_bytes()).hexdigest() != "ef5ad9af3f3b290c565a4dc65933d539b7bb8b8051ac9bd45386932a77862c09":
        raise ValueError("Unrecognized full stock image")
    if hashlib.sha256(short.read_bytes()).hexdigest() != "131bab19b558a25745c881c3c4193fd1f9fb541c0a6c89c7961bad31cecc60b2":
        raise ValueError("Unrecognized historical SPI prefix")
    results = []
    with tempfile.TemporaryDirectory(prefix="ph8057_historical_") as td:
        work = Path(td)
        guard = work / "guard"
        guard.mkdir()
        (guard / "sitecustomize.py").write_text('''import sys, os
def offline_hook(event, args):
    if event == "open" and args and isinstance(args[0], (str, bytes, os.PathLike)):
        path = os.fsdecode(args[0])
        if path.startswith("/dev/") and path != "/dev/null":
            raise RuntimeError("Historical offline test attempted device access")
    if event in ("socket.connect", "socket.bind"):
        raise RuntimeError("Historical offline test attempted network access")
sys.addaudithook(offline_hook)
''')
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONOPTIMIZE"] = "0"
        env["PYTHONPATH"] = str(guard)

        def run(label, cwd, argv, entry_source, notes=""):
            cp = subprocess.run([sys.executable, *map(str, argv)], cwd=cwd,
                                env=env, text=True, capture_output=True, timeout=180)
            log = output / (label + ".log")
            log.write_text(cp.stdout + cp.stderr)
            result = {"name": label, "exit_code": cp.returncode,
                      "source": str(entry_source.relative_to(root)),
                      "entry_sha256": hashlib.sha256(entry_source.read_bytes()).hexdigest(),
                      "log": log.name, "notes": notes,
                      "classification": "historical offline replay; not hardware qualification"}
            results.append(result)
            print(label, "PASS" if cp.returncode == 0 else "FAIL", flush=True)

        # These earliest scripts have their own toy interpreters. Keep their
        # original tests and image identities separate from the current emulator.
        # The child also preserves v3's original missing-dependency failure before
        # running its available wrapper tests with an explicitly labeled adapter.
        lab_runner = Path(__file__).with_name("replay_labs.py")
        lab_output = output / "early_labs"
        lab_cp = subprocess.run([sys.executable, str(lab_runner), str(source),
                                 "--out", str(lab_output)], cwd=work, env=env,
                                text=True, capture_output=True, timeout=180)
        lab_log = output / "general_pio_labs.log"
        lab_log.write_text(lab_cp.stdout + lab_cp.stderr)
        results.append({"name": "general_pio_labs", "exit_code": lab_cp.returncode,
            "source": "canonical:replay_labs.py",
            "entry_sha256": hashlib.sha256(lab_runner.read_bytes()).hexdigest(),
            "log": lab_log.name, "detail": "early_labs/summary.json",
            "notes": "General14, PIOv2 12, PIOv3 15 original cases; v3 uses new binary-backed missing-dependency adapter; original missing source tests not claimed",
            "classification": "historical offline replay with explicit supplied/reconstructed provenance"})
        print("general_pio_labs", "PASS" if lab_cp.returncode == 0 else "FAIL", flush=True)

        v4 = source / "3ae05787128a03db/PH8057_v4_ownership_audit.py"
        copy4 = work / "v4.py"
        shutil.copy2(v4, copy4)
        run("v4_ownership", work, [copy4, short], v4)

        src6 = source / "7787098b62e65087/PH8057_v6_stock_checkpoint"
        v6 = work / "v6"
        shutil.copytree(src6, v6, ignore=shutil.ignore_patterns("__pycache__"))
        (v6 / "upload").mkdir(exist_ok=True)
        shutil.copy2(short, v6 / "upload/ph8057-original.bin")
        shutil.copytree(donor, v6 / "ph8057_references", dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__"))
        script6 = v6 / "ph8057_work/run_v6_audits.py"
        run("v5_v6_nine_groups", v6, [script6, "--root", v6, "--log", output / "v6_detail.log"],
            src6 / "ph8057_work/run_v6_audits.py",
            "Includes four v5 groups, BOT sense, storage lifecycle, donor, CRC, SPI callback models and mocked collector tests")

        src7 = source / "e694bc16bd7e8a13/ph8057_v7"
        v7 = work / "v7"
        shutil.copytree(src7, v7, ignore=shutil.ignore_patterns("__pycache__"))
        for name in ("PH8057_v7_repacker_tests.py", "PH8057_v7_negative_tests.py"):
            run(name[:-3], v7, [v7 / name], src7 / name)

        groups = [
            ("v10", "3b6d2e8f6c9fd828", "test_offline_v10.py"),
            ("v11", "e8f7b86cd97d1e0d", "test_offline_v11.py"),
            ("v11_1", "2075b11d7c2e3a6f", "test_offline_v11_1.py"),
            ("v11_2", "14a0deee73d1b2b1", "test_offline_v11_2.py"),
            ("v11_3", "099ccf51bb21a0eb", "test_offline_v11_3.py"),
            ("v11_4", "d55cd3b6e282d226", "test_offline_v11_4.py"),
            ("v12", "1ec26d90517c3337", "PH8057_v12_offline_tests.py"),
            ("v13", "d9efe2b53d05d3fd", "PH8057_v13_offline_tests.py"),
            ("v14", "73fdb73f0bd878ab", "PH8057_v14_offline_tests.py"),
        ]
        for label, digest, script in groups:
            src = source / digest
            target = work / label
            shutil.copytree(src, target, ignore=shutil.ignore_patterns("__pycache__"))
            if label == "v14":
                shutil.copy2(stock, target / stock.name)
            run(label + "_collector_offline", target, [target / script], src / script,
                "Collector implementation imported for constant/parser/mock tests; main not executed")
    (output / "summary.json").write_text(json.dumps({"groups": results,
        "passed": sum(x["exit_code"] == 0 for x in results), "total": len(results),
        "live_device_operations": 0, "reviewed_history": provenance}, indent=2) + "\n")
    return int(any(x["exit_code"] for x in results))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("root", type=Path)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    raise SystemExit(replay(a.root, a.out.resolve()))
