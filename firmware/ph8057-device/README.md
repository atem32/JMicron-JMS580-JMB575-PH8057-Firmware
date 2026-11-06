# PH8057 owner-device updater package

This directory describes the exact **67,072-byte updater format** used for the owner's PH8057. It differs from the 70,144-byte full SPI research image.

- [Original readback](original/README.md): pinned source identity and layout.
- [Modified package](modified/README.md): source-only revised CK_COND builder and verifier.

Vendor-derived BINs are not distributed. Both contain manufacturer code and the OEM block may include device identity data; rights and public-data boundaries are in [NOTICE](../../NOTICE.md).

The owner reported installing the revised package and supplied bounded SMART results, followed by two-disk BOT workload summaries. The exact evidence and missing readback/logs are recorded in [testing](../../docs/testing.md#hardware-evidence). No UDMA residue repair, UASP or hot-swap change is included.
