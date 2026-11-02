#!/usr/bin/env python3
"""Build an offline-only trace candidate; this does not fix UDMA residue."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

local_integrity = Path(__file__).resolve().parent.parent / "ckcond"
if local_integrity.is_dir():
    sys.path.insert(0, str(local_integrity))
# The packaged public runner supplies patching/ckcond on PYTHONPATH.
from image import repackage, check_crc, changed_ranges, guard_outputs

from audit import read_exact_image
from trace_patch import STOCK_SHA256, collect_patches, manifest, sha256


def build(stock):
    changes = collect_patches(stock)
    candidate = repackage(stock, changes)
    report = manifest(stock)
    report.update({
        "filename": "PH8057_UDMA_TRACE_ONLY_DO_NOT_FLASH.bin",
        "candidate_sha256": sha256(candidate), "candidate_length": len(candidate),
        "crc": check_crc(candidate),
        "actual_changed_ranges": changed_ranges(stock, candidate),
        "changed_bytes": sum(a != b for a, b in zip(stock, candidate)),
        "oem_preserved": stock[0x11000:] == candidate[0x11000:],
        "crc_validity_does_not_qualify_hardware_execution": True,
    })
    return candidate, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stock", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    stock = read_exact_image(args.stock, STOCK_SHA256)
    candidate, report = build(stock)
    guard_outputs(args.stock, [args.out / report["filename"], args.out / "udma_trace_manifest.json"])
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / report["filename"]).write_bytes(candidate)
    (args.out / "udma_trace_manifest.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"classification": report["classification"],
                      "sha256": report["candidate_sha256"],
                      "changed_bytes": report["changed_bytes"]}, indent=2))


if __name__ == "__main__":
    main()
