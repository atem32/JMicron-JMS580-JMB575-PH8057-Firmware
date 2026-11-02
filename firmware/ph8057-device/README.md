# Owner PH8057 firmware — original and modified

This directory documents the **specific enclosure** for which the 67,072-byte JMicron update package was built and subsequently used. It is not a universal JMS580 firmware.

- [original/](original/README.md) — original readback `1.bin`, identification, hashes and restrictions.
- [modified/](modified/README.md) — SMART-only CK_COND revision, reproducible source-only builder, hash and limited post-flash evidence.

The public repository **does not contain either vendor-derived BIN**. The original includes OEM/device identity data; copyright and redistribution rights have not been established for the manufacturer's code. The modified image still contains most of that proprietary code. The user can keep both originals locally and use the provided builder.

No UDMA CSW residue fix, UASP or hot-swap was added. For physical test results, see [post-flash evidence](../../docs/postflash-hardware-check-2026-11-02.md).
