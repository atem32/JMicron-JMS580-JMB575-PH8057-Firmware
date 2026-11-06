#!/usr/bin/env python3
"""Offline PH8057 inspection, OEM decoding and the CK_COND SMART patch."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
for relative in ("tools/emulator", "tools/analysis", "tools/patching/ckcond",
                 "firmware/ph8057-device/modified"):
    sys.path.insert(0, str(ROOT / relative))

NAMES = {"ckcond": "PH8057_CKCOND_SPI.bin"}
UPDATER_NAME = "PH8057_CKCOND_UPDATER.bin"
PATCH_RECORDS = ROOT / "firmware/ph8057-device/modified/ckcond_patch_records.json"


def construct(stock, variant="ckcond"):
    """Build the single SMART patch in the exact input's container format."""
    if variant not in NAMES:
        raise ValueError("Unknown firmware variant; only ckcond is supported")
    import build_ckcond
    from image import IMAGE_SIZE, changed_ranges, sha
    from build_from_1bin import BIN_SIZE, CODE_OFF, OEM_OFF, build, check_record
    if len(stock) == IMAGE_SIZE:
        candidate, changes, symbols = build_ckcond.build(stock)
        return candidate, build_ckcond.metadata(stock, candidate, changes, symbols)
    if len(stock) != BIN_SIZE:
        raise ValueError("Expected a complete 70,144-byte SPI or 67,072-byte updater image")
    records = json.loads(PATCH_RECORDS.read_text())
    candidate = build(stock, records)
    changes = [{**p, "cpu": int(p["cpu"], 16) if isinstance(p["cpu"], str) else p["cpu"]}
               for p in records]
    report = {
        "firmware": "SMART Fixed / CK_COND",
        "variant": "ckcond", "filename": UPDATER_NAME,
        "role": "smart_fixed", "status": "OFFLINE VALIDATED",
        "image_format": "updater", "image_size": len(candidate),
        "source_sha256": sha(stock), "candidate_sha256": sha(candidate),
        "crc": check_record(candidate),
        "changed_bytes_vs_stock": sum(a != b for a, b in zip(stock, candidate)),
        "oem_unchanged": stock[OEM_OFF:] == candidate[OEM_OFF:],
        "wrapper_unchanged": stock[:0x200] == candidate[:0x200],
        "udma_residue_fix": False, "ckcond_abort_guard": True,
        "artifact_hardware_status": "HARDWARE OBSERVED",
        "hardware_scope": "SMART STATUS, CHECK POWER MODE and the documented dual-HDD BOT workloads; see docs/testing.md for the tested scope",
        "patches": [{**p, "file_offset": f"0x{p['cpu']+CODE_OFF:05X}",
                     "length": len(bytes.fromhex(p["new"]))} for p in changes],
        "actual_byte_differences": changed_ranges(stock, candidate,
                                                  code_offset=CODE_OFF, code_end=OEM_OFF),
    }
    return candidate, report


def read_factory(path):
    """Identify by exact length and pinned hash; never open a device node."""
    from image import IMAGE_SIZE, read_stock
    from build_from_1bin import read_stock_package
    path = Path(path)
    if not path.is_file():
        raise ValueError("Factory input must be a regular local file")
    if path.stat().st_size == IMAGE_SIZE:
        return read_stock(path)
    return read_stock_package(path)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="action", required=True)
    ins = sub.add_parser("inspect", help="Identify a local image without printing OEM identifiers")
    ins.add_argument("image", type=Path)
    ins.add_argument("--raw-cpu", action="store_true")
    oem = sub.add_parser("oem", help="Decode the OEM block and export the register atlas; identifiers redacted by default")
    oem.add_argument("--stock", type=Path, required=True)
    oem.add_argument("--out", type=Path, required=True)
    oem.add_argument("--include-sensitive", action="store_true")
    build = sub.add_parser("build", help="Build CK_COND from an exact SPI or updater file; no device access")
    build.add_argument("variant", choices=NAMES)
    build.add_argument("--stock", type=Path, required=True)
    build.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    if args.action == "inspect":
        from firmware_inspect import inspect_file
        print(json.dumps(inspect_file(args.image, explicit_cpu=args.raw_cpu), indent=2))
    elif args.action == "oem":
        from image import read_stock
        from oem import write_outputs
        stock = read_stock(args.stock)
        write_outputs(stock, args.out, include_sensitive=args.include_sensitive, source_path=args.stock)
        print("OEM atlas and register table generated; exact stock validated")
    else:
        from image import guard_outputs
        stock = read_factory(args.stock)
        candidate, report = construct(stock, args.variant)
        output = args.out / report["filename"]
        manifest = args.out / "ckcond_manifest.json"
        records = args.out / "ckcond_patch_records.json"
        targets = [output, manifest, records]
        guard_outputs(args.stock, targets)
        guard_outputs(PATCH_RECORDS, targets)
        args.out.mkdir(parents=True, exist_ok=True)
        output.write_bytes(candidate)
        manifest.write_text(json.dumps(report, indent=2) + "\n")
        records.write_text(json.dumps([{key: row[key] for key in ("cpu", "old", "new")}
                                       for row in report["patches"]], indent=2) + "\n")
        print(json.dumps({key: report[key] for key in
                          ("variant", "image_format", "filename", "status", "candidate_sha256",
                           "changed_bytes_vs_stock", "udma_residue_fix")}, indent=2))


if __name__ == "__main__":
    main()
