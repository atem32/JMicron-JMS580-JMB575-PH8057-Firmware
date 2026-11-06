#!/usr/bin/env python3
"""Run local UDMA audit and produce evidence JSON/disassembly. No device I/O."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ckcond"))
from image import guard_outputs, sha as sha256

from audit import (ROOT, DEFAULT_STOCK, DEFAULT_CKCOND, load_sources, hardware_excerpt,
                   static_checks, completion_matrix, arithmetic_native_checks,
                   rejected_prototype_counterexamples)
from fixtures import completion_case
from mcs51 import disassemble


RANGES = [
    (0x7BF4, 0x7C48, "CBW fields and admission"),
    (0x247A, 0x2490, "Protocol11 command state"),
    (0x385A, 0x38C4, "BOT DMA dispatch"),
    (0xC789, 0xC7B6, "UDMA Data-Out launch"),
    (0x8CA3, 0x8CF8, "SATA taskfile programming"),
    (0x7308, 0x73A9, "ATA completion dispatch"),
    (0xAEF4, 0xAF40, "Direction-dependent accounting"),
    (0xCBE3, 0xCC09, "USB completion/abort wait"),
    (0xE140, 0xE149, "Wait termination predicate"),
    (0x94F9, 0x9565, "BOT CSW assembly"),
    (0xC7C5, 0xC7E3, "PIO arithmetic initialization"),
    (0xD1D7, 0xD1F4, "PIO chunk arithmetic"),
    (0xB3C4, 0xB409, "PIO arithmetic result consumption"),
    (0x9711, 0x977B, "Timer comparison/arithmetic hypothesis"),
]


def donor_record(raw, name):
    """Explicit layout of the nine supplied JMS580 updater containers.

    CPU CODE is file0400..103FF, followed by512 OEM bytes at10400.
    Do not pass a SPI readback or bare64KiB CODE under this layout.
    """
    if len(raw) != 0x10600 or raw[:6] != bytes.fromhex("0100152d0580"):
        raise ValueError("Expected the supplied 67,072-byte JMS580 updater-container layout")
    code = raw[0x400:0x10400]
    if any(code[pc] != 0x02 for pc in (0, 3, 8, 11)) or code[6:8] != bytes.fromhex("7f08"):
        raise ValueError("Expected reset/interrupt-vector anchors at donor file0400")
    branch = bytes.fromhex("e559b4640be4f558f557f556f555")
    gate = bytes.fromhex("85ac5885ad5785ae56e5af543ff555")
    sites = lambda sig: [i for i in range(len(code) - len(sig) + 1)
                         if code[i:i + len(sig)] == sig]
    a, b = sites(branch), sites(gate)
    if len(a) != 1 or len(b) != 1:
        raise AssertionError((name, a, b))
    return {"file": name, "sha256": sha256(raw),
            "container_bytes": len(raw), "code_file_offset": "0x00400", "oem_file_offset": "0x10400",
            "branch_cpu_offset": f"0x{a[0]:04X}",
            "branch_file_offset": f"0x{a[0] + 0x400:05X}",
            "sfr_copy_cpu_offset": f"0x{b[0]:04X}",
            "sfr_copy_file_offset": f"0x{b[0] + 0x400:05X}",
            "proof": "Explicit container layout and vector anchors, plus two matching instruction signatures; no physical donor testing"}


def donor_checks(directory):
    identities = json.loads((ROOT / "firmware/manifests/images.json").read_text())["donors"]
    known = {row["sha256"]: row["filename"] for row in identities}
    results = []
    seen = set()
    for path in sorted(Path(directory).iterdir()):
        if not path.is_file() or path.suffix.lower() != ".bin":
            continue
        if path.stat().st_size != 0x10600:
            raise ValueError("Donor package has the wrong size: " + path.name)
        raw = path.read_bytes()
        digest = sha256(raw)
        if digest not in known:
            raise ValueError("Unidentified donor package SHA256: " + path.name)
        if digest not in seen:
            row = donor_record(raw, path.name)
            row["identified_package"] = known[digest]
            results.append(row)
            seen.add(digest)
    if not results:
        raise ValueError("No identified donor packages supplied")
    return results


def run(stock, ckcond, donors=None):
    reproduced, _ = completion_case(stock)
    fixed_result, _ = completion_case(ckcond)
    return {
        "status": "ROOT_CAUSE_LOCALIZED__UNSAFE_COUNTER_PATCH_REJECTED__NO_QUALIFIED_RESIDUE_FIX",
        "source_hashes": {"factory": sha256(stock), "ckcond": sha256(ckcond)},
        "hardware_excerpt": hardware_excerpt(),
        "native_static_checks": static_checks(stock),
        "staged_native_reproduction": reproduced,
        "ckcond_native_reproduction": fixed_result,
        "native_completion_matrix": completion_matrix(stock, ckcond),
        "arithmetic_hypothesis": arithmetic_native_checks(stock),
        "rejected_prototype_counterexamples": rejected_prototype_counterexamples(stock, ckcond),
        "donors": donor_checks(donors) if donors else [],
        "donor_comparison_status": "OFFLINE VALIDATED" if donors else "NOT TESTED",
        "coverage_boundaries": {
            "native": "CBW parsing, SAT16 decoding, programmed launch, completion gates, arithmetic consumers, CSW assembly",
            "modeled": "Explicit MMIO samples, 48-bit ALU hypothesis, dual-DPTR select convention, fixed LUN mapping",
            "not_modeled": "USB/SATA payload movement, interrupts, physical reset, DMA, actual timers, real SRAM ownership, flash execution",
            "function_stubs_in_native_replay": 0,
            "new_device_io": False,
        },
        "release_blocker": "No qualified, stable, per-command count of Data-Out bytes processed, including short/error/recovery semantics",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stock", type=Path, default=DEFAULT_STOCK)
    parser.add_argument("--donors", type=Path)
    parser.add_argument("--ckcond", type=Path, default=DEFAULT_CKCOND,
                        help="Exact CK_COND SPI image; built in memory from factory when omitted")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    targets = [args.out / "udma_audit_results.json", args.out / "udma_native_disassembly.txt"]
    for source in (args.stock, args.ckcond):
        if source is not None:
            guard_outputs(source, targets)
    stock, ckcond = load_sources(args.stock, args.ckcond)
    report = run(stock, ckcond, args.donors)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "udma_audit_results.json").write_text(json.dumps(report, indent=2) + "\n")
    lines = ["Factory CPU CODE addresses; full-image file offset = CPU +0x1000.",
             "Native instruction listings; data embedded in Keil helpers is marked by surrounding context."]
    for start, end, label in RANGES:
        lines.extend(["", f"## {label}: {start:04X}..{end - 1:04X}"])
        lines.extend(str(ins) for ins in disassemble(stock[0x1000:0x11000], start, end))
    (args.out / "udma_native_disassembly.txt").write_text("\n".join(lines) + "\n")
    print(json.dumps({"status": report["status"],
                      "native_factory_and_ckcond_cases": len(report["native_completion_matrix"]),
                      "rejected_prototype_counterexamples": len(report["rejected_prototype_counterexamples"]),
                      "native_function_stubs": 0, "new_device_io": False}, indent=2))


if __name__ == "__main__":
    main()
