"""Reproduce v15-v22 offline-only audits in temporary copies.

Only v20 needs a source-path substitution for its historical /mnt/data root.
Expected results and original assertions remain unchanged. All peripheral
interactions are CPU fixtures; no disk, USB or SPI command is executed.
"""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile

from provenance import replay_environment, verify_emulator, verify_history

SPECS = {
    15: ("fdb0ee9bc9651427", "PH8057_v15_OFFLINE_STATIC_AUDIT.py", "PH8057_v15_offline_audit.json"),
    16: ("313e011c2a6ae390/PH8057_v16_HOTPLUG_PACKAGE", "PH8057_v16_HOTPLUG_OFFLINE_AUDIT.py", "PH8057_v16_HOTPLUG_AUDIT_RESULTS.json"),
    17: ("fa6ec7ad5e2757a8/PH8057_v17_OEM_HOTPLUG_OFFLINE", "PH8057_v17_OEM_HOTPLUG_OFFLINE_AUDIT.py", "PH8057_v17_OEM_HOTPLUG_AUDIT_RESULTS.json"),
    18: ("98bf61fee856443d/PH8057_v18_HOTPLUG_TRACE_OFFLINE", "PH8057_v18_NATIVE_TRACE.py", "PH8057_v18_NATIVE_TRACE_RESULTS.json"),
    19: ("87aa20fb4d0d0964/PH8057_v19_STAGE1_OFFLINE", "PH8057_v19_F3_RESCAN_TRACE.py", "PH8057_v19_TEST_RESULTS.json"),
    20: ("3447fcd9890f43b6/PH8057_v20_COMPARATIVE_OFFLINE", "PH8057_v20_compare_images.py", "PH8057_v20_comparison_results.json"),
    21: ("c5ecdc090f4e69d6/PH8057_v21_OEM_FEATURES_OFFLINE", "PH8057_v21_selftest.py", "PH8057_v21_selftest_results.json"),
    22: ("7ae6afcf698f2426", "test_v22_gate_offline.py", "results.json"),
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replay(evidence, emulator, out):
    evidence, emulator, out = evidence.resolve(), emulator.resolve(), out.resolve()
    provenance = verify_history(evidence, "legacy_early", output=out)
    evidence = Path(provenance["root"])
    emulator_sha256 = verify_emulator(emulator)
    out.mkdir(parents=True, exist_ok=True)
    hand = evidence / "f3b3148c740947cb" / "PH8057_HANDOVER_V2-V29_2026-11-02"
    stock = hand / "firmware" / "PH8057_FACTORY_COMPLETE_READBACK_DO_NOT_FLASH.bin"
    v8 = hand / "firmware" / "PH8057_v8_EXPERIMENTAL_DO_NOT_FLASH.bin"
    donors = hand / "donor_JMS580"
    manifest = {"emulator_sha256": emulator_sha256, "runs": [], "hardware_access": False,
                "reviewed_history": provenance}
    for version, (relative, filename, result_name) in SPECS.items():
        original = evidence / relative
        with tempfile.TemporaryDirectory(prefix=f"ph8057_legacy_{version}_") as temp:
            root = Path(temp)
            work = root / "work"
            shutil.copytree(original, work, ignore=shutil.ignore_patterns("__pycache__"))
            shutil.copyfile(emulator, work / "mcs51.py")
            script = work / filename
            report = work / result_name
            adaptation = ["temporary source copy; canonical mcs51 emulator substituted"]
            if version == 15:
                tree = root / "ph8057_v8"
                shutil.copytree(evidence / "6d36298a2afad5e4" / "ph8057_v8", tree,
                                ignore=shutil.ignore_patterns("__pycache__"))
                shutil.copyfile(emulator, tree / "work_v8" / "tooling" / "mcs51.py")
                args = ["--tree", str(tree), "--out", str(report)]
                fixtures = ["factory BIN", "original v8 BIN", "original v8 patch_manifest.json", "v8 package tree"]
            elif version == 17:
                args = [str(stock), str(emulator), str(donors / "JMS580_HIKSEMI-PSSD-131.06.00.01.BIN"),
                        str(donors / "JMS580_Sandbox-v255.01.00.02-20190701.BIN")]
                fixtures = ["factory BIN", "two original v17 donor inputs"]
            elif version in (16, 18, 19):
                args = [str(stock), str(emulator), str(report)]
                fixtures = ["factory BIN"]
            elif version == 20:
                data = root / "data"
                data.mkdir()
                for donor in donors.iterdir():
                    if donor.is_file():
                        shutil.copyfile(donor, data / donor.name)
                tree = data / "ph8057_audit/PH8057_COMPLETE_HANDOVER_2026-11-02/working_v8/ph8057_v8"
                (tree / "ph8057_v7").mkdir(parents=True)
                (tree / "work_v8/tooling").mkdir(parents=True)
                shutil.copyfile(stock, tree / "ph8057_v7" / stock.name)
                shutil.copyfile(emulator, tree / "work_v8/tooling/mcs51.py")
                source = script.read_text()
                old = "DATA = Path('/mnt/data')"
                if source.count(old) != 1:
                    raise AssertionError("v20 DATA declaration changed")
                script.write_text(source.replace(old, "DATA = Path(" + repr(str(data)) + ")"))
                adaptation.append("v20 DATA constant replaced with temporary private directory; all expected values unchanged")
                args = []
                fixtures = ["factory BIN", "all nine donor BINs"]
            elif version == 21:
                args = ["--factory", str(stock), "--v8", str(v8), "--emulator", str(emulator), "--out", str(report)]
                fixtures = ["factory BIN", "original v8 BIN", "original OEM configurator module"]
            else:
                args = [str(stock), "--out", str(report)]
                fixtures = ["factory BIN"]
            command = [sys.executable, str(script), *args]
            result = subprocess.run(command, cwd=work, text=True, capture_output=True,
                                    timeout=180, env=replay_environment())
            (out / f"v{version}.log").write_text(result.stdout + result.stderr)
            record = {"version": version, "source": str((original / filename).relative_to(evidence)),
                      "source_sha256": sha(original / filename), "executed_source_sha256": sha(script),
                      "command_template": [filename, *["<temp>" if str(root) in s else "<stock>" if s == str(stock)
                                                       else "<v8>" if s == str(v8) else "<emulator>" if s == str(emulator)
                                                       else "<donor:" + Path(s).name + ">" if str(donors) in s else s for s in args]],
                      "required_fixtures": fixtures, "adaptations": adaptation,
                      "returncode": result.returncode, "assertions_or_expectations_changed": False}
            if result.returncode:
                record["status"] = "FAIL"
                manifest["runs"].append(record)
                (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
                raise RuntimeError(f"v{version} historical replay failed; see log")
            shutil.copyfile(report, out / f"v{version}.json")
            data = json.loads(report.read_text())
            record["status"] = "PASS"
            record["reported_count"] = next((data[k] for k in ("pass_count", "passed", "total", "case_count") if isinstance(data.get(k), int)), None)
            if version == 15:
                record["scope_note"] = "Bounded static CFG with unresolved indirect control flow; no homogeneous test counter"
            if version == 16:
                record["scope_note"] = "Historical setup field labels interchanged; corrected canonical regression tests asymmetric wValue/wIndex"
            if version == 22:
                record["scope_note"] = "20 native slice scenarios plus8 static anchors; in-memory preview only, no UASP BIN emitted"
            manifest["runs"].append(record)
            print("Legacy", version, "PASS", record["reported_count"], flush=True)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("evidence", type=Path)
    p.add_argument("emulator", type=Path)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    replay(a.evidence, a.emulator, a.out)
