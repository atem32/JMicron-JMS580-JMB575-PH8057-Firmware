# PH8057 updater container

This directory contains the reference identity and implementation for the
**67,072-byte updater format**. Factory and SMART Fixed / CK_COND are the same
two firmware states documented at the repository root. The updater container
has a different wrapper and whole-file hash from the 70,144-byte SPI format.

- [Factory reference](original/README.md): exact source identity and layout.
- [SMART Fixed / CK_COND](modified/README.md): patch records, builder and verifier.

The common build command accepts either exact factory format:

```bash
python3 ph8057.py build ckcond --stock /private/factory.bin --out build/ckcond
```

The updater input produces `PH8057_CKCOND_UPDATER.bin`; it preserves the factory
OEM block and applies the same CODE patch as the SPI output. The reported
hardware setup used this updater format; results are in
[testing](../../docs/testing.md#hardware-evidence).

Vendor-derived BINs are not distributed. They contain manufacturer code and
may include device identity data; [NOTICE](../../NOTICE.md) defines the
redistribution and public-data boundaries.
