# Original owner updater readback

The owner obtained `1.bin` from the PH8057 using Windows. This vendor-derived file is held locally and is not distributed here.

| Property | Value |
|---|---|
| Size | 67,072 bytes (`0x10600`) |
| Whole-file SHA256 | `481e62548a3a7b9cf07e8552fa2e2a9d66a5f89d222a66301ad22982c8aca7c5` |
| CODE | File `0x400..0x103FF`, 64 KiB |
| OEM | File `0x10400..0x105FF`, 512 bytes |

The exact source's CODE and OEM equal the full factory capture; its wrapper/metadata arrangement differs. The original metadata CRC at `0x3FC..0x3FF` is zero. The builder accepts that exception only for this exact source hash and fills the field in the candidate.

Check the local input with `sha256sum 1.bin`. A matching filename or size alone is insufficient. [Firmware layout](../../../docs/firmware-layout.md) defines the separate SPI/updater checksums and identities.
