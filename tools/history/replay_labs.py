#!/usr/bin/env python3
"""Replay supplied general/v2/v3 labs without claiming a missing source exists.

The original v3 common-builder source is absent. Its common bytecode survives in
the supplied PIOv3 image. A newly written, explicitly labeled dependency adapter
loads those verified bytes so the unchanged, supplied PIOv3 wrapper tests can run.
This is historical reproduction, never a current firmware builder or a flash tool.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

from provenance import verify_history


PREFIX_SHA = "131bab19b558a25745c881c3c4193fd1f9fb541c0a6c89c7961bad31cecc60b2"
GENERAL_SHA = "22d4ef8f7adaa679c2b11b0e634a84c0888d65104044269b9bd32aefe3bc3e53"
PIO_V2_SHA = "0a9bc1e1c9ab90a8ad19e9d9f2df271549e5f6d509db62daf0b00dd4be70ba8f"
PIO_V3_SHA = "94b093ab7293bfe3f94587e8a4a4cbdd1692fc17e99663b72c5ee3529831c35f"
RESTRICTED_SHA = "0a351e85149027ea63f16694cca15de594065396ea7a4759a08179411d8463ee"
MISSING_NAME = "PH8057_general_ckcond_lab_v3_restricted.py"
MISSING_SHA = "0c836343efeec7810e1d662b2b8727eb17cfeb4d51f229c590c1d8061ba77d48"
MISSING_SIZE = 11275
RECORDED_LOG_SHA = "656b94494d6d37a06edb97e28056b63465a4e21258e8d51afb1b441e3b95969d"
REPORT_SHA = "4bdff10a660b13d08a646e9dd21c4eadefe3b00361db3738407405258598a9c2"
GENERAL_IMAGE = "PH8057_GENERAL_CKCOND_LAB_DO_NOT_FLASH.img"
V2_IMAGE = "PH8057_PIO_COMPLETION_LAB_V2_DO_NOT_FLASH.img"
V3_IMAGE = "PH8057_PIO_DATAIN_LAB_V3_DO_NOT_FLASH.img"
COMMON_START, COMMON_END = 0xF300, 0xF47A
HOOK_START, HOOK_END = 0xA982, 0xA985

# This is new adapter source, not a reconstruction of the missing Python file.
# No proprietary image or bytecode payload is embedded in this public runner.
ADAPTER_SOURCE = '''"""NEW BINARY-BACKED ADAPTER; NOT THE MISSING HISTORICAL SOURCE.

Exports only the original common bytecode recovered from a verified supplied IMG.
Does not recreate or execute the absent common-builder's fifteen original tests.
"""
from pathlib import Path
import hashlib

raw = (Path(__file__).resolve().parent / "supplied_pio_v3.img").read_bytes()
if len(raw) != 65536 or hashlib.sha256(raw).hexdigest() != "94b093ab7293bfe3f94587e8a4a4cbdd1692fc17e99663b72c5ee3529831c35f":
    raise ValueError("Unrecognized supplied PIOv3 image for historical adapter")
asm = bytearray(raw[0xF300:0xF47A])
print("ADAPTER: recovered 378 common bytes from verified supplied PIOv3 IMG; missing original common tests NOT executed")
'''


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def require_image(path, expected):
    raw = Path(path).read_bytes()
    if len(raw) != 65536 or sha(raw) != expected:
        raise ValueError("Unexpected historical 65536-byte image: " + str(path))
    return raw


def reconstruct_restricted(prefix, pio_v3):
    """Recover an old incomplete image from source-owned bytes, with exact hashes."""
    if len(prefix) != 65536 or sha(prefix) != PREFIX_SHA:
        raise ValueError("Unrecognized historical stock prefix")
    if len(pio_v3) != 65536 or sha(pio_v3) != PIO_V3_SHA:
        raise ValueError("Unrecognized supplied PIOv3 image")
    if prefix[HOOK_START:HOOK_END + 1] != bytes.fromhex("75 5c 12 22"):
        raise ValueError("Historical common hook preimage mismatch")
    if prefix[COMMON_START:COMMON_END] != bytes(COMMON_END - COMMON_START):
        raise ValueError("Historical common cave is not empty")
    restricted = bytearray(prefix)
    restricted[HOOK_START:HOOK_END] = pio_v3[HOOK_START:HOOK_END]
    restricted[COMMON_START:COMMON_END] = pio_v3[COMMON_START:COMMON_END]
    if sha(restricted) != RESTRICTED_SHA:
        raise ValueError("Recovered restricted-only image does not match recorded hash")
    return bytes(restricted)


def fenced_blocks(raw):
    """Keep exact bytes, including each fenced body's final line ending."""
    return [m.group(1) for m in re.finditer(
        rb"^```[^\r\n]*\r?\n(.*?)^```[^\r\n]*(?:\r?\n|$)",
        raw, re.MULTILINE | re.DOTALL)]


def inspect_missing_source(evidence, report, output):
    """Read-only source/block search; recover only the original recorded test log."""
    files = sorted(p for p in evidence.rglob("*")
                   if p.is_file() and "__pycache__" not in p.parts)
    named = [str(p.relative_to(evidence)) for p in files if p.name == MISSING_NAME]
    matches, block_matches, references = [], [], []
    markdown_count = block_count = 0
    for path in files:
        # The recorded original source has an exact byte length and SHA256.
        if path.stat().st_size == MISSING_SIZE and sha(path.read_bytes()) == MISSING_SHA:
            matches.append(str(path.relative_to(evidence)))
        if path.suffix.lower() != ".md":
            continue
        markdown_count += 1
        raw = path.read_bytes()
        if MISSING_NAME.encode() in raw:
            references.append({"path": str(path.relative_to(evidence)), "sha256": sha(raw)})
        for block in fenced_blocks(raw):
            block_count += 1
            # Test common LF/CRLF and final-newline spellings without changing
            # any recovered evidence. A match would require review, not fallback.
            lf = block.replace(b"\r\n", b"\n")
            variants = (block, lf, lf.rstrip(b"\n"), lf.rstrip(b"\n") + b"\n",
                        lf.replace(b"\n", b"\r\n"))
            if any(sha(value) == MISSING_SHA for value in variants):
                block_matches.append(str(path.relative_to(evidence)))
    if named or matches or block_matches:
        raise ValueError("Original restricted-wrapper source may be present; adapter fallback refused")

    report_raw = report.read_bytes()
    if sha(report_raw) != REPORT_SHA:
        raise ValueError("Unexpected full handover report")
    recovered = [b for b in fenced_blocks(report_raw) if sha(b) == RECORDED_LOG_SHA]
    if len(recovered) != 1 or len(recovered[0]) != 1724:
        raise ValueError("Original restricted test log not recoverable exactly from report")
    log_name = "restricted_common_RECORDED_NOT_REEXECUTED.log"
    (output / log_name).write_bytes(recovered[0])
    return {
        "expected_source_name": MISSING_NAME,
        "recorded_source_sha256": MISSING_SHA, "recorded_source_bytes": MISSING_SIZE,
        "named_source_matches": named, "exact_file_hash_matches": matches,
        "exact_fenced_source_hash_matches": block_matches,
        "searched_files": len(files), "searched_markdown_files": markdown_count,
        "searched_fenced_blocks": block_count, "referencing_reports": references,
        "finding": "No original source file or complete source found in supplied Markdown; report references, assembly excerpts and recorded logs do not recreate the source",
        "recorded_test_log": {"file": log_name, "sha256": RECORDED_LOG_SHA,
            "bytes": 1724, "source_report": str(report.relative_to(evidence)),
            "source_report_sha256": REPORT_SHA,
            "classification": "Recovered verbatim historical output; NOT newly executed tests",
            "recorded_pass_lines": 15, "newly_executed_common_cases": 0},
    }


def replay(root, output):
    root, output = Path(root).resolve(), Path(output).resolve()
    provenance = verify_history(root, "lab_general_pio", output=output)
    evidence = Path(provenance["root"])
    handover = evidence / "63fb1545420cb03d/PH8057_COMPLETE_HANDOVER_2026-11-02"
    lab = handover / "archives/historical_lab_do_not_flash"
    stock = evidence / "0766e3a6b43c6423/PH8057_JMS580_GITHUB_REPOSITORY_2026-11-02/firmware/stock/ph8057-original.bin"
    prefix = require_image(stock, PREFIX_SHA)
    supplied = {GENERAL_IMAGE: require_image(lab / GENERAL_IMAGE, GENERAL_SHA),
                V2_IMAGE: require_image(lab / V2_IMAGE, PIO_V2_SHA),
                V3_IMAGE: require_image(lab / V3_IMAGE, PIO_V3_SHA)}
    output.mkdir(parents=True, exist_ok=True)
    absence = inspect_missing_source(evidence,
        handover / "reports/PH8057_CKCOND_v2_v3_v4_FULL_HANDOVER_2026-11-02.md", output)
    restricted = reconstruct_restricted(prefix, supplied[V3_IMAGE])
    groups = []
    with tempfile.TemporaryDirectory(prefix="ph8057_early_labs_") as td:
        work = Path(td)
        guard = work / "guard"
        guard.mkdir()
        (guard / "sitecustomize.py").write_text('''import os, sys
def offline_hook(event, args):
    if event == "open" and args and isinstance(args[0], (str, bytes, os.PathLike)):
        path = os.fsdecode(args[0])
        if path.startswith("/dev/") and path != "/dev/null":
            raise RuntimeError("Historical offline lab attempted device access")
    if event in ("socket.connect", "socket.bind"):
        raise RuntimeError("Historical offline lab attempted network access")
sys.addaudithook(offline_hook)
''')
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONOPTIMIZE"] = "0"
        env["PYTHONPATH"] = str(guard)

        def prepare(name, entries):
            target = work / name
            target.mkdir()
            (target / "ph8057-original.bin").write_bytes(prefix)
            for entry in entries:
                shutil.copy2(lab / entry, target / entry)
            return target

        def execute(label, target, entry):
            cp = subprocess.run([sys.executable, str(target / entry)], cwd=target,
                env=env, text=True, capture_output=True, timeout=60)
            (output / (label + ".log")).write_text(cp.stdout + cp.stderr)
            original = lab / entry
            if (target / entry).read_bytes() != original.read_bytes():
                raise ValueError("Original historical source was modified during replay")
            return cp, {"name": label, "exit_code": cp.returncode,
                "source": str(original.relative_to(evidence)),
                "entry_sha256": sha(original.read_bytes()), "log": label + ".log",
                "original_source_modified": False, "expectations_modified": False}

        general_entry = "PH8057_general_ckcond_lab.py"
        v2_entry = "PH8057_pio_completion_lab_v2.py"
        v3_entry = "PH8057_pio_datain_lab_v3.py"
        for label, entry, deps, image, case_count, pio_count in (
            ("general_original", general_entry, [general_entry], GENERAL_IMAGE, 14, 0),
            ("pio_v2_original", v2_entry, [general_entry, v2_entry], V2_IMAGE, 26, 12)):
            target = prepare(label, deps)
            cp, result = execute(label, target, entry)
            if cp.returncode != 0:
                raise ValueError("Historical lab failed; see " + result["log"])
            actual = (target / image).read_bytes()
            if actual != supplied[image]:
                raise ValueError("Rebuilt historical image differs from supplied image: " + image)
            count = sum(line.startswith("PASS ") for line in cp.stdout.splitlines())
            if count != case_count:
                raise ValueError("Historical emitted case count changed")
            result.update({"classification": "Unchanged original source and embedded tests",
                "pass_lines": count, "pio_cases": pio_count,
                "general_cases": case_count - pio_count,
                "rebuilt_image_name": image, "rebuilt_image_sha256": sha(actual),
                "byte_identical_to_supplied_image": True})
            groups.append(result)
            print(label + ": PASS; image equals supplied bytes", flush=True)

        target = prepare("pio_v3", [v3_entry])
        before, witness = execute("pio_v3_original_missing_dependency", target, v3_entry)
        if before.returncode == 0 or "FileNotFoundError" not in before.stderr or MISSING_NAME not in before.stderr:
            raise ValueError("Expected original v3 missing-dependency failure was not reproduced")
        if (target / V3_IMAGE).exists() or "PASS PIO:" in before.stdout:
            raise ValueError("Original failed v3 unexpectedly executed wrapper cases or wrote an image")
        witness.update({"classification": "Expected historical failure preserved before adaptation",
            "exception": "FileNotFoundError", "missing_dependency": MISSING_NAME,
            "newly_executed_cases": 0, "image_written": False})

        (target / "supplied_pio_v3.img").write_bytes(supplied[V3_IMAGE])
        (target / MISSING_NAME).write_text(ADAPTER_SOURCE)
        cp, result = execute("pio_v3_binary_adapter", target, v3_entry)
        if cp.returncode != 0:
            raise ValueError("Original PIOv3 wrapper failed with binary adapter; see " + result["log"])
        actual = (target / V3_IMAGE).read_bytes()
        if actual != supplied[V3_IMAGE]:
            raise ValueError("PIOv3 binary-adapter rebuild differs from supplied image")
        pio_count = sum(line.startswith("PASS PIO:") for line in cp.stdout.splitlines())
        if pio_count != 15:
            raise ValueError("PIOv3 original wrapper case count changed")
        result.update({"classification": "Unchanged original PIOv3 wrapper tests with new binary-backed common dependency adapter",
            "pass_lines": 15, "pio_cases": 15, "general_cases": 0,
            "missing_original_common_tests_replayed": False,
            "rebuilt_image_name": V3_IMAGE, "rebuilt_image_sha256": sha(actual),
            "byte_identical_to_supplied_image": True})
        groups.append(result)
        print("pio_v3_binary_adapter: PASS 15 unchanged wrapper cases; missing common tests not executed", flush=True)

    report = {"schema": 1,
        "classification": "Historical incomplete images and synthetic lab tests; not firmware qualification",
        "reviewed_history": provenance, "groups": groups,
        "passed_replay_groups": len(groups), "total_replay_groups": 3,
        "original_missing_dependency": witness, "missing_source_search": absence,
        "unique_available_original_cases_replayed": 41,
        "printed_case_pass_events": 55,
        "duplicate_case_events_note": "The 14 general cases run alone and again during PIOv2 import",
        "restricted_common_original_cases_not_reexecuted": 15,
        "binary_dependency_adapter": {"sha256": sha(ADAPTER_SOURCE.encode()),
            "classification": "New adapter source; NOT the absent historical Python source",
            "supplied_image": V3_IMAGE, "supplied_image_sha256": PIO_V3_SHA,
            "common_file_start": "0xF300", "common_file_end_exclusive": "0xF47A",
            "common_cpu_start": "0xE300", "common_cpu_end_exclusive": "0xE47A",
            "common_bytes": 378, "common_sha256": sha(supplied[V3_IMAGE][COMMON_START:COMMON_END])},
        "restricted_only_reconstruction": {"sha256": sha(restricted), "bytes": len(restricted),
            "matches_recorded_historical_hash": True, "supplied_as_standalone_file": False,
            "changed_bytes_vs_prefix": sum(a != b for a, b in zip(prefix, restricted)),
            "allowed_file_ranges_end_exclusive": [["0xA982", "0xA985"], ["0xF300", "0xF47A"]],
            "classification": "New binary reconstruction from supplied stock prefix and supplied PIOv3 image; no claim to recover missing source",
            "persisted_image": False},
        "live_device_operations": 0,
        "firmware_payloads_embedded_in_public_adapter": False}
    (output / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print("Restricted-only reconstruction matches recorded SHA256 " + sha(restricted), flush=True)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(replay(args.root, args.out))
