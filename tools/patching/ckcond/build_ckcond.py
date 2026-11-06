#!/usr/bin/env python3
"""Build the revised CK_COND candidate offline; no device or SPI operations."""
import argparse
import json
from pathlib import Path

import core_patch
import capture_wrappers
import sense_patch
import abort_guard
from image import (sha, check_crc, repackage, validate_stock, read_stock, changed_ranges,
                   ORIGINAL_V8_SHA, REVISED_CKCOND_SHA, STOCK_FULL_SHA, guard_outputs)

def collect_patches(stock, variant="revised"):
    if variant not in ("v8", "revised"):
        raise ValueError("variant must be v8 or revised")
    validate_stock(stock)
    code = stock[0x1000:0x11000]
    changes = core_patch.build_patches(code) + capture_wrappers.build_patches(code)
    sense = sense_patch.build_sense_patch()
    changes.extend({"cpu": p["address"], "old": p["expected"], "new": p["replacement"]}
                   for p in sense["patches"])
    if variant == "revised":
        changes.extend(abort_guard.build_patches(code))
    for patch in changes:
        if isinstance(patch["cpu"], str):
            patch["cpu"] = int(patch["cpu"], 16)
    changes.sort(key=lambda p: p["cpu"])
    symbols = dict(core_patch.SYMBOLS)
    symbols.update(capture_wrappers.SYMBOLS)
    symbols.update(sense["symbols"])
    if variant == "revised":
        symbols.update(abort_guard.SYMBOLS)
    return changes, symbols


def build(stock, variant="revised"):
    changes, symbols = collect_patches(stock, variant=variant)
    candidate = repackage(stock, changes)
    if variant == "v8" and sha(candidate) != ORIGINAL_V8_SHA:
        raise ValueError("Audited v8 reconstruction differs from the original v8 image")
    if variant == "revised" and sha(candidate) != REVISED_CKCOND_SHA:
        raise ValueError("Revised candidate differs from the audited reproducible image")
    return candidate, changes, symbols


def metadata(stock, candidate, changes, symbols, variant="revised"):
    return {
        "candidate": ("CK_COND original v8" if variant == "v8" else
                      "CK_COND revised: invalidate capture on native USB-wait abort"),
        "variant": variant,
        "status": "REGRESSION BASELINE / DO NOT FLASH" if variant == "v8" else "EXPERIMENTAL / DO NOT FLASH",
        "image_format": "full_spi",
        "source_sha256": sha(stock), "candidate_sha256": sha(candidate),
        "original_v8_preserved_byte_for_byte": sha(candidate) == ORIGINAL_V8_SHA,
        "artifact_hardware_status": "NOT TESTED",
        "hardware_scope": "Limited observations apply to the separate 67,072-byte updater package, not this SPI artifact",
        "image_size": len(candidate),
        "changed_bytes_vs_stock": sum(a != b for a, b in zip(stock, candidate)),
        "oem_unchanged": stock[0x11000:] == candidate[0x11000:],
        "crc": check_crc(candidate),
        "patches": [{**p, "file_offset": f"0x{p['cpu']+0x1000:05X}",
                     "length": len(bytes.fromhex(p['new']))} for p in changes],
        "actual_byte_differences": changed_ranges(stock, candidate),
        "symbols": {k: f"0x{v:04X}" for k, v in symbols.items()},
        "constraints": [
            "Serialized BOT only; UASP and hot-swap are not implemented",
            "4D00..4DFF and 4E00..4E1F XDATA allocation requires hardware validation",
            "6300 completion-bank provenance and atomicity require hardware validation",
            "Additional stack usage and interrupt timing require hardware validation",
            "SPI capacity, loader execution and recovery are not qualified",
            "UDMA residue is unchanged by this candidate",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stock", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    stock = read_stock(args.stock)
    candidate, changes, symbols = build(stock)
    output = args.out / "PH8057_CKCOND_REVISED_DO_NOT_FLASH.bin"
    manifest = args.out / "ckcond_revised_manifest.json"
    records = args.out / "ckcond_revised_patch_records.json"
    guard_outputs(args.stock, [output, manifest, records])
    args.out.mkdir(parents=True, exist_ok=True)
    output.write_bytes(candidate)
    report = metadata(stock, candidate, changes, symbols)
    manifest.write_text(json.dumps(report, indent=2) + "\n")
    records.write_text(json.dumps(changes, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "sha256": sha(candidate),
                      "changed_bytes": report["changed_bytes_vs_stock"]}, indent=2))


if __name__ == "__main__":
    main()
