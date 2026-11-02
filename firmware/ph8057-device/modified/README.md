# Revised SMART/CK_COND firmware (owner-device update package)

This folder contains a **reproducible patch**, not a vendor-derived firmware binary. The modified firmware has been installed on one PH8057. The owner-supplied OMV test shows correct CK_COND ATA Return Descriptors for `SMART STATUS` and `CHECK POWER MODE` on one WD HDD.

| Property | Value |
|---|---|
| Local output name | `PH8057_SMART_CKCOND_REVISED_67072_EXPERIMENTAL.bin` |
| Size | 67,072 bytes |
| SHA256 | `f8406e8b83e9f97695ce4ae395a90b29e28d8210bc40c09087f3f6b43f33fd5b` |
| Base input | exact `../original/1.bin` per published SHA256 |
| Audited 70,144-byte revised CODE SHA256 | `2aaece707763b5dab32c46cf10c17c88345d73b8635365a354dcffe8817b422b` |
| Scope | SMART/CK_COND and abort-snapshot correction only |
| UDMA residue accounting | NOT FIXED |
| OEM/NVRAM configuration in the image | Unchanged |
| Qualification | Bounded hardware check on one LUN; otherwise experimental |

To rebuild using **your locally held** original file:

```bash
python3 build_from_1bin.py \
  --stock /path/to/1.bin \
  --patches ckcond_revised_patch_records.json \
  --output PH8057_SMART_CKCOND_REVISED_67072_EXPERIMENTAL.bin
python3 verify_device_build.py \
  --candidate PH8057_SMART_CKCOND_REVISED_67072_EXPERIMENTAL.bin \
  --stock /path/to/1.bin
```

The builder checks the original SHA256, exact old bytes at all patch sites, patch overlap, all update-format checksums, original wrapper and unchanged 512-byte OEM; it does not access hardware. Do not blindly flash a reconstructed image on another device.

See [the limited hardware verification](../../../docs/postflash-hardware-check-2026-11-02.md) and [the main technical fix documentation](../../../docs/smart-ckcond-fix.md).
