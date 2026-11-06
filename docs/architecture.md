# Architecture

PH8057 is a five-bay enclosure with a JMS580 USB-to-SATA bridge upstream of a JMB575 one-to-five SATA port multiplier. The tested transport is **USB Bulk-Only Transport (BOT)**. The product briefs describe generic bridge and command/FIS-switching capabilities; they do not establish which features this firmware implements. See [primary references](references.md).

The owner reported four disks enumerating after the November 2 update. The November 3–6 sustained tests used **two WD5000AAKX HDDs**. Enumeration, successful I/O on two disks and qualification of every physical port are different observations. Exact results and firmware-identity limits are in [testing](testing.md#hardware-evidence).

## 8051 address spaces

| Space | Meaning in this project |
|---|---|
| CODE | 64 KiB instruction/address space. CPU addresses in disassembly refer to this space. |
| IRAM / IDATA | Direct addresses below `80h` select lower internal RAM; indirect `@R0/@R1` accesses can select upper IDATA. |
| SFR | Direct addresses `80h..FFh` select special-function registers, not upper IDATA. Bit addresses are a separate namespace. |
| XDATA | External data space containing firmware state and memory-mapped peripherals. `MOVX` accesses require an explicit RAM/MMIO interpretation in tests. |

The exercised dual-DPTR ABI uses SFR `86h.bit0` to select physical pointer pairs `82h/83h` or `84h/85h` for DPTR instructions. Direct instructions still address the named SFR. This is an execution fixture supported by the exercised code, not a complete JMicron CPU specification. The emulator has no autonomous DMA, timer, interrupt delivery, USB PHY or SATA PHY.

CPU address and container offset differ: add `1000h` for the full SPI capture or `0400h` for an updater container. [Firmware layout](firmware-layout.md) defines the accepted formats and integrity fields; the [register map](register-map.md) separates observed instruction effects from inferred hardware meanings.

## Serialized command ownership

Native BOT admission at `7BF4..7C47` reads tag, length, direction and LUN from the CBW window. It initializes software residue at IRAM `55h..58h`: `55h` is the most-significant byte and `58h` the least-significant byte. The incoming little-endian length at XDATA `7988h..798Bh` is copied to `58h,57h,56h,55h`; CSW construction reverses that internal order back to wire little-endian.

SAT decoding selects a normalized taskfile and launch path. The common launcher `8CA3` programs the `6300h` register window. A scheduled completion handler later supplies ATA status/error, followed by sense and CSW finalization at `94F9`. The tag at `7984h..7987h` is copied through `9503 → 800A`. The complete UDMA path is documented in [patches](patches.md#udma-data-out-and-csw-residue).

The CK_COND implementation retains one active command and per-LUN pending sense:

| State | Address / role | Constraint |
|---|---|---|
| Active command | XDATA `4E00h..4E1Fh` | One global owner; stores LUN, protocol, command, EXTEND, tag equality, launch type/port and ATA result. |
| Unpublished result validity | `4E07h`; valid marker `A5h` | Cleared before another launch and on either revised USB-wait abort exit. |
| Pending descriptors | XDATA `4D00h..4DFFh`, 16-byte slots | Valid marker, native sense selector and 14-byte ATA Return Descriptor; slot capacity does not prove that 16 physical disks are supported. |

Admission invalidates the previous active context and the selected LUN's old descriptor, except for REQUEST SENSE. Capture checks software ownership and selected port before and after reading registers. Finalization publishes only an eligible result; REQUEST SENSE consumes a matching saved descriptor with native allocation-length clamping. A CBW tag is equality metadata, **not a command-generation counter**. Interrupt masking serializes CPU instructions but does not establish coherent autonomous hardware access or exclusive SRAM ownership. These assumptions prohibit treating the current state as a concurrent UAS command table.

The existing CK wrappers save 17 context bytes. The revised abort leaf adds five temporary bytes on its path; the trace trampoline adds a two-byte call frame that can remain live during that leaf. Seven is the combined **increment over the corresponding v8 abort path**, not total stack usage. Native frames and interrupt nesting still require measurement.

## Port discovery and LUN mapping

The firmware builds a compact list of discovered ports; LUN must not be assumed equal to physical SATA port or tray number.

| Native code | Observed operation |
|---|---|
| `04DA..064B`, successful branch `05B6..05CF` | Appends current port `458C` at `459C + 4595`, then increments detected count `4595`. |
| `C75C..C788` | Copies the discovered port at `459C + LUN` to the hardware-facing slot `7A06 + 8 × LUN` (`C774..C784` computes the stride). |
| `D1F4` | Derives a bounded maximum LUN from the detected count. |
| `D896`, then `7C43..7C47` | Resolves the current LUN to a port in R7 and stores selected context at `417F`. |
| `D970 → C702` | Recognizes and validates GET_MAX_LUN. Internally wValue is IRAM `1A/1B`, wIndex `1C/1D`, wLength `1E/1F`, high byte first; USB wire words are little-endian. |

For example, compacting `[1,2,3,4]` into `[1,3,4]` after removal would change the drive behind LUN 1. This is a mapping consequence, not an additional hardware test. Stable hot-swap would need persistent slot identity, absent-LUN behavior, cache/sense invalidation and per-port recovery.

Event code `0709..073D` compares `459B` with `4595`, also consulting `4592` and `4180`, and can set bit `06h` plus `4590`. The temporal meaning of `459B` is unknown; calling it a previous-drive count is unsupported. At `27FB..2820`, a pending event with `F3.0` clear can schedule `4161=3`; `8FFD` has related interrupt-side behavior. These instructions do not distinguish firmware detach policy from a power, reset or link cause for the reported USB disconnects.

## UASP, NCQ and hot-swap boundaries

OEM `E7.6` gates a UAS descriptor path at `44C4`; code at `6F57` and `46ED` can clear the live flag. Descriptor exposure alone does not implement tag ownership, task management, streams, concurrent completion or multi-LUN error recovery. A UASP implementation would require a tag-indexed result store, stable routing, reset/abort handling, queue flushing and verified endpoint/completion ownership. NCQ scheduling across this JMS580/JMB575 combination is unproven.

The external JMS567/JMB575 experiment in [references](references.md#related-controller-work) demonstrates why these are separate obligations; it does not qualify JMS580. No UASP or hot-swap patch is supplied. [Known issues](known-issues.md) records the remaining contracts and the evidence needed to resolve them.
