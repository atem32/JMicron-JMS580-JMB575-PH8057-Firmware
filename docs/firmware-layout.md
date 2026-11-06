# Firmware layouts and integrity

All ranges below are inclusive unless written as Python slices. A container size is not a measurement of the board's flash capacity. The canonical machine-readable identities are in [images.json](../firmware/manifests/images.json).

## Address translation

| Format | File size | CODE range | OEM range | Accepted use |
|---|---:|---|---|---|
| Factory / CK_COND full SPI image | 70,144 (`0x11200`) | `0x01000..0x10FFF` | `0x11000..0x111FF` | Exact factory source or its CK_COND output; OEM unchanged. |
| Factory / CK_COND updater image | 67,072 (`0x10600`) | `0x00400..0x103FF` | `0x10400..0x105FF` | Exact updater readback or its CK_COND output; OEM unchanged. |
| JMS580 donor updater containers | 67,072 | Same updater offsets | Same updater offsets | Comparison only; no board compatibility inferred. |
| Truncated SPI prefix `ph8057-original.bin` | 65,536 | Only the first `0xF000` CODE bytes after the `0x1000` prefix | Absent | Rejected as a patch base or raw CPU image. |
| Factory tail capture | 4,608 (`0x1200`) | Completes full-image `0x10000..0x10FFF` | Includes full-image OEM | Reconstructs the full capture when appended to its exact prefix. |
| Explicit raw CPU CODE | 65,536 | `0x00000..0x0FFFF` | None | Analysis only with explicit raw-CPU intent; a recognized SPI prefix is still rejected. |

For CPU address `A`, the full-image file offset is `A + 0x1000`; an updater file offset is `A + 0x400`. CODE is 64 KiB in both complete formats. Donor scanning validates reset/interrupt-vector anchors at the updater CODE origin and reports CPU and file offsets separately.

## Factory and SMART Fixed identities

| Artifact | Bytes | SHA256 |
|---|---:|---|
| Full factory | 70,144 | `ef5ad9af3f3b290c565a4dc65933d539b7bb8b8051ac9bd45386932a77862c09` |
| CK_COND SPI image | 70,144 | `2aaece707763b5dab32c46cf10c17c88345d73b8635365a354dcffe8817b422b` |
| Original owner updater readback (`1.bin`) | 67,072 | `481e62548a3a7b9cf07e8552fa2e2a9d66a5f89d222a66301ad22982c8aca7c5` |
| CK_COND updater image | 67,072 | `f8406e8b83e9f97695ce4ae395a90b29e28d8210bc40c09087f3f6b43f33fd5b` |

These are **whole-file** hashes. In particular, `2aaece…` is not a CODE-only hash. The exact owner updater source has CODE/OEM equal to the full factory capture, and the CK_COND updater has CODE equal to the CK_COND SPI image, including its CRC trailer. Their wrappers and whole-file identities differ. Hardware observations identify the updater package; they do not establish that a 70,144-byte artifact was installed, nor substitute for post-flash readback.

The original prefix hash is `131bab19b558a25745c881c3c4193fd1f9fb541c0a6c89c7961bad31cecc60b2`; the tail hash is `083e5851cbdc17e0d641a33c8027d6a8e68d023995a03b6186fa134b7122e190`. The 512-byte factory OEM block hash is `9521e63007a1289846438195896ef2908a6ccd695c983f90b54fd501eb00e635`. These identify fragments of the same factory source.

## CRC convention and full SPI image

The stored CRC words are big-endian. The implementation reverses bytes within each four-byte input word, applies `zlib.crc32`, complements the result, then reverses its 32 bits. [image.py](../tools/patching/ckcond/image.py) cross-checks this against a bitwise formulation with polynomial `0x04C11DB7` and initial value `0xFFFFFFFF`. CRC inputs must be four-byte aligned.

The full capture begins with metadata magic `5A C3 69 E1`. Its header occupies `0xE00..0xFFF`; the protected CODE trailer begins at CPU `0xFFEC`.

| Field | CRC input, Python slices | Stored field |
|---|---|---|
| Header | `image[0xE00:0xFFC]` | `0xFFC..0xFFF` |
| Metadata | `image[0xE00:0x1000] + image[0:0x1FC]` | `0x1FC..0x1FF` |
| CODE | `image[0x1000:0x10FF8]` | `0x10FF8..0x10FFB` |
| Full | `image[0xE00:0x1000] + image[0x1000:0x10FFC]` | `0x10FFC..0x10FFF` |
| Full-CRC mirror | Equal to stored full CRC | `0x00C..0x00F` |

The header CRC is `698135A8` for both full SPI images. Other expected CRCs are recorded in `images.json` and generated manifests.

## Owner updater format

The updater wrapper starts with `01 00 15 2D 05 80 03 03 05 05`; metadata magic is at `0x200`. The wrapper, metadata and CODE have separate positions from the full SPI image:

| Field | CRC input, Python slices | Stored field |
|---|---|---|
| Wrapper/header | `image[0:0x1FC]` | `0x1FC..0x1FF` |
| Metadata | `image[0:0x200] + image[0x200:0x3FC]` | `0x3FC..0x3FF` |
| CODE | `image[0x400:0x103F8]` | `0x103F8..0x103FB` |
| Full | `image[0:0x200] + image[0x400:0x103FC]` | `0x103FC..0x103FF` |
| Full-CRC mirror | Equal to stored full CRC | `0x20C..0x20F` |

The exact original owner readback has a zero metadata CRC at `0x3FC`; that exception is accepted only with the pinned original SHA256. The CK_COND output populates the field and must pass every CRC check. Its first `0x200` bytes and all OEM bytes are preserved. The [updater builder](../firmware/ph8057-device/modified/build_from_1bin.py) consumes the exact [CK_COND patch records](../firmware/ph8057-device/modified/ckcond_patch_records.json).

## Build invariants

The build command selects the format from its exact input identity: the full SPI source SHA256 or the updater source SHA256 above. Both require matching original hook bytes, equal-length patches, empty expected caves, no overlap and no patch crossing CPU `0xFFEC`. Generation changes only declared CODE positions and required CRC/mirror fields. All 512 OEM bytes remain unchanged.

The CK_COND patch is applied directly to unmodified factory bytes. Generated manifests record guarded records, actual changed-byte ranges, sizes, hashes, CRCs and OEM equality; guarded-range lengths can exceed actual changed-byte counts where replacement bytes equal their old values.

Output preflight protects immutable inputs from output/sidecar collisions and filesystem aliases. The public build command is the same for both formats:

```bash
python3 ph8057.py build ckcond --stock /private/factory.bin --out build/ckcond
```

It emits `PH8057_CKCOND_SPI.bin` or `PH8057_CKCOND_UPDATER.bin`, with
`ckcond_manifest.json` and `ckcond_patch_records.json`. Container formats do
not create different firmware variants: `ckcond` is the sole patched variant.

## Installation and hardware boundaries

Integrity checks establish reproducibility and format consistency. The owner
reported installing the updater package with JMicron Windows updater
1.19.16.48, followed by a power cycle, enumeration and successful SMART commands.
That tool identified JMS580 Series but displayed an unknown SPI flash type.
No post-flash readback or final NVRAM-option capture accompanies the observations.

The builder does not select a flash chip, write a device or establish recovery.
Physical flash capacity, loader/cave execution, SRAM ownership and stack/interrupt
behavior require configuration-specific evidence. The
[hardware coverage guide](../tests/hardware/QUALIFICATION_PLAN.md) preserves
those engineering requirements.
