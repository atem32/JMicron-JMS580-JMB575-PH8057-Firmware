# Firmware containers, offsets and integrity

## Identified source layouts

| Input | File size | CODE file range | OEM file range | Interpretation |
|---|---:|---|---|---|
| Complete PH8057 factory capture |70144 (`11200h`)|`01000..10FFF`|`11000..111FF`|Exact accepted patch base |
| Original v8 / new full candidates |70144|Same|Same, unchanged|Derived from that exact base |
| Historical `ph8057-original.bin` |65536|Only the firstF000h CODE bytes are present after the 1000h prefix|Absent|Truncated SPI prefix, **not raw CPU CODE** |
| Historical stock tail |4608 (`1200h`)|Completes file 10000..10FFF|Includes11000..111FF|Together with the prefix reconstructs the full supplied capture |
| Nine JMS580 donor update containers |67072 (`10600h`)|`00400..103FF`|`10400..105FF`|Different1024-byte wrapper; no hardware interchangeability implied |
| Explicit raw CPU CODE |65536|`00000..0FFFF`|None|Must be requested explicitly; recognized SPI prefix is rejected |

These are file layouts, not flash-capacity measurements. The prefix equality and tail reconstruction are checked against the supplied bytes. The primary identities are in `firmware/manifests/input_firmware.json`. There are 19 distinct `.bin` payload hashes in the input archives: nine donors, full factory, v8, factory prefix, factory tail, OEM block and five distinct saved512-byte sector payloads. A `.bin` extension alone does not identify firmware.

## PH8057 integrity fields

The full capture begins with metadata magic `5A C3 69 E1`. The header occupies the established E00..FFF region, CODE starts at 1000, and the CODE trailer begins atCPUFFEC. The canonical repacker rejects patches at or beyond that trailer. The CRC fields are:

| Field | Input bytes | Stored at |
|---|---|---|
| Header CRC |FileE00..FFB|FileFFC..FFF|
| Metadata CRC |HeaderE00..FFF concatenated with metadata000..1FB|File 1FC..1FF|
| CODE CRC |File 1000..10FF7|File 10FF8..10FFB|
| Full CRC |HeaderE00..FFF concatenated with CODE1000..10FFB|File 10FFC..10FFF|
| Full-CRC mirror |Must equal stored full CRC|File 00C..00F|

`tools/patching/ckcond/image.py` evaluates the captured CRC convention by two formulations: a word-byte transformation plus zlib, and a bitwise polynomial implementation. It checks the source, applies guarded equal-length edits, recalculates CODE/full/metadata fields, verifies the complete result and rejects every change outside the declared CODE/CRC positions. The header and all 512 OEM bytes remain unchanged.

CPU addresses in PH8057 maps become file offsets by adding1000h. Donor CPU addresses instead add400h. The corrected donor scanner reports both values and validates reset/interrupt-vector anchors. It does not disassemble wrapper bytes as CPU 0.

## Manifests and original preservation

Every candidate manifest records source/output SHA256, image length, exact guarded replacements, actual contiguous byte differences, OEM equality and CRC values. Guarded ranges may include unchanged zero bytes; therefore the sum of patch-range lengths is not the actual changed-byte count. CRC/mirror differences are separately present in the whole-image diff.

The builders accept only the exact full factory hash; they cannot operate on a donor, arbitrary dump or truncated prefix. The original v8 is a reproducibility target, not an in-place patch base for the combined build. Revised CK and trace edits are merged once from factory bytes so that expected-byte checks and overlap checks refer to one origin.

Both source aliases and sidecar-output aliases are checked before writing any output. Symlink/hardlink aliases to the input are rejected. Historical archives are extracted and replayed separately; raw evidence is not overwritten or silently normalized.

Valid CRCs do not establish the physical flash part, code-bank/cache behavior, safe code-cave execution or recovery. No bytewise patch check substitutes for those missing hardware contracts.
