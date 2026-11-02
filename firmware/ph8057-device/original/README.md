# Original PH8057 update-container (owner readback)

**Not distributed in the public repository.** The user read this BIN back from the PH8057 via Windows.

| Property | Value |
|---|---|
| Expected local filename | `1.bin` |
| Size | 67,072 bytes (`0x10600`) |
| SHA256 | `481e62548a3a7b9cf07e8552fa2e2a9d66a5f89d222a66301ad22982c8aca7c5` |
| CODE offset in update container | `0x400` |
| OEM offset in update container | `0x10400` |
| CPU CODE length | `0x10000` |
| OEM length | 512 bytes |

This is a **JMicron updater-style package**, not the 70,144-byte full factory research capture. Its CODE and OEM match the audited factory image; the packaging/header differ. The original readback included a zero metadata CRC field; the update-image builder populates all required CRC fields.

Keep the original readback offline. It may contain device identifiers and vendor copyrighted material.

Check your own file:

```bash
sha256sum 1.bin
```
