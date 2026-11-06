#!/usr/bin/env python3
"""One offline entry point for PH8057 inspection, OEM decoding and patch builds."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
for relative in ("tools/emulator", "tools/analysis", "tools/patching/ckcond", "tools/patching/udma"):
    sys.path.insert(0, str(ROOT / relative))

NAMES = {
    "ckcond-revised": "PH8057_CKCOND_REVISED_DO_NOT_FLASH.bin",
    "udma-trace": "PH8057_UDMA_TRACE_ONLY_DO_NOT_FLASH.bin",
    "combined-revised-trace": "PH8057_CKCOND_REVISED_UDMA_TRACE_ONLY_DO_NOT_FLASH.bin",
}
BASELINES = {"ckcond-v8": "PH8057_CKCOND_V8_REGRESSION_BASELINE_DO_NOT_FLASH.bin"}


def construct(stock, variant):
    """Compose current variants or the v8 regression baseline from exact stock."""
    import build_ckcond
    import trace_patch
    from image import repackage, validate_stock, changed_ranges, check_crc, sha
    validate_stock(stock)
    changes, symbols = [], {}
    if variant in ("ckcond-v8", "ckcond-revised", "combined-revised-trace"):
        ck_variant = "v8" if variant == "ckcond-v8" else "revised"
        changes, symbols = build_ckcond.collect_patches(stock, ck_variant)
    if variant in ("udma-trace", "combined-revised-trace"):
        changes.extend(trace_patch.collect_patches(stock))
        symbols.update(udma_observe_before=0xE700, udma_observe_after=0xE705)
    if variant not in NAMES and variant not in BASELINES:
        raise ValueError("Unknown candidate variant")
    normalized = [{**p, "cpu": int(p["cpu"], 16) if isinstance(p["cpu"], str) else p["cpu"]}
                  for p in changes]
    normalized.sort(key=lambda p: p["cpu"])
    candidate = repackage(stock, normalized)
    if variant.startswith("ckcond-"):
        reference, _, _ = build_ckcond.build(stock, "v8" if variant == "ckcond-v8" else "revised")
        if candidate != reference:
            raise ValueError("Composite builder differs from CK_COND builder")
    report = {
        "variant": variant, "filename": {**NAMES, **BASELINES}[variant],
        "status": ("REGRESSION BASELINE / DO NOT FLASH" if variant in BASELINES
                   else "EXPERIMENTAL / DO NOT FLASH"),
        "role": "regression_baseline" if variant in BASELINES else "candidate",
        "image_format": "full_spi",
        "artifact_hardware_status": "NOT TESTED",
        "source_sha256": sha(stock), "candidate_sha256": sha(candidate),
        "image_size": len(candidate), "crc": check_crc(candidate),
        "changed_bytes_vs_stock": sum(a != b for a, b in zip(stock, candidate)),
        "oem_unchanged": stock[0x11000:] == candidate[0x11000:],
        "udma_residue_fix": False,
        "udma_trace_only": "trace" in variant,
        "ckcond_abort_guard": variant in ("ckcond-revised", "combined-revised-trace"),
        "patches": [{"cpu": f"0x{p['cpu']:04X}", "file_offset": f"0x{p['cpu']+0x1000:05X}",
                     "length": len(bytes.fromhex(p["new"])), "old": p["old"], "new": p["new"]}
                    for p in normalized],
        "actual_byte_differences": changed_ranges(stock, candidate),
        "symbols": {key: f"0x{value:04X}" for key, value in symbols.items()},
        "qualification": "This 70,144-byte SPI artifact is validated offline. Limited hardware observations refer to the separate 67,072-byte updater package; no SPI execution/readback qualification is implied.",
    }
    return candidate, report


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
    build = sub.add_parser("build", help="Build an experimental image; never opens a device")
    build.add_argument("variant", choices=NAMES)
    build.add_argument("--stock", type=Path, required=True)
    build.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    if args.action == "inspect":
        from firmware_inspect import inspect_file
        print(json.dumps(inspect_file(args.image, explicit_cpu=args.raw_cpu), indent=2))
    else:
        from image import read_stock, guard_outputs
        stock = read_stock(args.stock)
        if args.action == "oem":
            from oem import write_outputs
            write_outputs(stock, args.out, include_sensitive=args.include_sensitive, source_path=args.stock)
            print("OEM atlas and register table generated; exact stock validated")
        else:
            candidate, report = construct(stock, args.variant)
            output = args.out / NAMES[args.variant]
            manifest = args.out / (args.variant + "_manifest.json")
            guard_outputs(args.stock, [output, manifest])
            args.out.mkdir(parents=True, exist_ok=True)
            output.write_bytes(candidate)
            manifest.write_text(json.dumps(report, indent=2) + "\n")
            print(json.dumps({key: report[key] for key in
                              ("variant", "status", "candidate_sha256", "changed_bytes_vs_stock",
                               "udma_residue_fix")}, indent=2))


if __name__ == "__main__":
    main()
