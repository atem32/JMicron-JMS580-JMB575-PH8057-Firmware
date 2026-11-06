# Revised CK_COND updater package

The source-only builder applies the revised CK_COND patch to the exact owner readback. No vendor-derived BIN or flash writer is included.

| Property | Value |
|---|---|
| Output | `PH8057_SMART_CKCOND_REVISED_67072_EXPERIMENTAL.bin` |
| Size | 67,072 bytes |
| Whole-file SHA256 | `f8406e8b83e9f97695ce4ae395a90b29e28d8210bc40c09087f3f6b43f33fd5b` |
| Input | Exact original `1.bin` described in [original](../original/README.md) |
| Corresponding 70,144-byte full-image SHA256 | `2aaece707763b5dab32c46cf10c17c88345d73b8635365a354dcffe8817b422b` — this is a whole-file hash, not CODE-only |
| Scope | Command-owned ATA Return Descriptor and native-abort snapshot invalidation |
| OEM in the image | All 512 bytes unchanged |
| UDMA residue | Unchanged; no confirmed fix |
| Evidence | **OFFLINE VALIDATED**; limited **HARDWARE OBSERVED** SMART success; no post-flash readback or general hardware qualification |

From the repository root:

```bash
mkdir -p build/device
python3 firmware/ph8057-device/modified/build_from_1bin.py \
  --stock /private/1.bin \
  --output build/device/PH8057_SMART_CKCOND_REVISED_67072_EXPERIMENTAL.bin
python3 firmware/ph8057-device/modified/verify_device_build.py \
  --candidate build/device/PH8057_SMART_CKCOND_REVISED_67072_EXPERIMENTAL.bin \
  --stock /private/1.bin
```

The builder uses [ckcond_revised_patch_records.json](ckcond_revised_patch_records.json), validates exact source/old bytes, overlap and trailer limits, wrapper/CODE/metadata/full CRCs, OEM equality and the expected output hash. The verifier compares local bytes; it does not read firmware from a device.

The owner reported installing this package and observed valid SMART STATUS and active/idle CHECK POWER MODE descriptors on one WD disk. [Testing](../../../docs/testing.md#hardware-evidence) preserves those transactions and later two-disk workload summaries with their provenance and limits. [Patch semantics](../../../docs/patches.md) explains the revised guard and remaining hardware assumptions.
