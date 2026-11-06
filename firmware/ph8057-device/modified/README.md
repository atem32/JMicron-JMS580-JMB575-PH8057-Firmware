# SMART Fixed / CK_COND updater

The builder applies the `ckcond` patch to the exact factory updater readback.
The resulting CODE matches the CK_COND SPI output; the file wrapper is specific
to the updater format.

| Property | Value |
|---|---|
| Output | `PH8057_CKCOND_UPDATER.bin` |
| Size | 67,072 bytes |
| Whole-file SHA256 | `f8406e8b83e9f97695ce4ae395a90b29e28d8210bc40c09087f3f6b43f33fd5b` |
| Input | Exact factory `1.bin` described in [original](../original/README.md) |
| Corresponding SPI output | 70,144 bytes; whole-file SHA256 `2aaece707763b5dab32c46cf10c17c88345d73b8635365a354dcffe8817b422b` |
| Scope | Command-owned ATA Return Descriptors and invalidation of unpublished results on native abort exits |
| OEM block | All 512 bytes unchanged |
| UDMA residue | Native accounting retained; the known defect is not repaired |

From the repository root:

```bash
python3 ph8057.py build ckcond --stock /private/1.bin --out build/ckcond
```

The format is selected automatically. The common command writes the image,
`ckcond_manifest.json` and `ckcond_patch_records.json`.
[build_from_1bin.py](build_from_1bin.py) implements the container-specific
checks using the committed [patch records](ckcond_patch_records.json): exact
source/old bytes, overlap, trailer bounds, wrapper/CODE/metadata/full CRCs,
OEM equality and the expected output hash.

To compare a local output against a fresh rebuild:

```bash
python3 firmware/ph8057-device/modified/verify_device_build.py \
  --candidate build/ckcond/PH8057_CKCOND_UPDATER.bin \
  --stock /private/1.bin
```

The verifier compares local files and never reads or writes a device. The
owner's reported SMART RETURN STATUS and CHECK POWER MODE responses, and the
three successful BOT workloads, are documented in
[testing](../../../docs/testing.md#hardware-evidence) and
[patch semantics](../../../docs/patches.md#physical-scope). Format-specific
installation boundaries are in [firmware layout](../../../docs/firmware-layout.md).
