# Manual hardware qualification plan — no executable device tests

No real command, disk write, SPI write or hot-plug operation is part of the automated suite. This document identifies the evidence needed after a separate hardware/recovery plan exists. Every candidate remains **DO NOT FLASH**. It is not an instruction to begin flashing merely because an offline test passed.

## Prerequisites before modified code

Establish a complete, independently recoverable factory image and the real flash/loader layout. Demonstrate a recovery method appropriate to this exact board and SPI part; a tool named for JMS578 is not evidence for JMS580. Establish whether proposed CODE caves are actually loaded/executable and whether 4D00..4DFF and 4E00..4E1F are exclusively available across boot, normal operation, interrupts and recovery. A readback of zero at one instant is insufficient.

Qualify stack and interrupt headroom: revised CK abort adds five temporary bytes; the trace call adds two that can remain live through the same abort path, giving seven cumulative bytes before ISR nesting. Record maximum stack use, interrupt enable/restore behavior and potential nested handlers. The offline executor does not schedule interrupts autonomously.

## Smallest useful UDMA accounting experiment

The supplied 512-byte WRITE DMA EXT result is accepted as the owner's hardware observation. The missing evidence is not another ordinary successful write alone. It is the attribution and semantics of a **processed-byte** quantity.

An approved debugger, controller documentation or separately qualified instrumentation must correlate one command's tag, generation, LUN and physical port across admission, launch, ATA completion, USB-wait exit and CSW. At minimum, obtain requested length, programmed 6318..631B length, ATA status/error/D2H marker, native wait carry and branch, final 55..58 residue and matching CSW tag. For any proposed counter, document address, width, byte order, unit, initialization, validity interval, latching and reset behavior.

The trace image exposes CPU E700 before the original completion call and E705 after it. It creates no logging transport and no persistent buffer. A fresh vendor SCSI getter after the transaction may replace the command context and is not automatically a valid way to sample the original counter. Reads must be known safe; unknown MMIO may be clear-on-read or select a different function.

Acceptance requires one full transfer plus controlled partial and failure cases. Use a qualified USB/SATA fault-injection arrangement or disposable test media, not valuable data. A genuine partial case must distinguish bytes accepted by USB from bytes processed by the device. The proposed algorithm must produce H−P only when P is stable and belongs to that generation, and must not manufacture GOOD/residue=0 after ATA failure, stall, reset, abort or timeout. Status and sense must remain independent of byte-count arithmetic.

## Qualification matrix after prerequisites

| Group | Minimum cases | Required observation |
|---|---|---|
| CK_COND descriptors | SAT12 and SAT16; CK0/CK1; SMART STATUS, IDENTIFY, CHECK POWER MODE; ATA success/error | Matching command-owned descriptor, correct EXTEND fields, key/ASC/ASCQ and GOOD/CHECK CONDITION behavior |
| Sense lifetime | Allocation lengths 0, short, full; repeated REQUEST SENSE; intervening ordinary command; different LUN | No stale descriptor, no cross-LUN consumption, correct truncation and native fallback |
| Ownership | All four observed LUN mappings and corresponding ports | Tag/LUN/port correspondence before/after capture; coherent 6300 snapshot |
| Abort correction | Both CBE3 wait exits, CK clear/set, ATA good/error | Revised 4E07 invalidation; native error/sense retained; real scheduler either cancels or emits the correct finalizer result |
| UDMA accounting | Full 512 and multi-block, true partial, zero-length/invalid length, ATA failure before/after acceptance | Stable processed-byte contract, bounded residue, no success inferred from an unrelated 70C0 value |
| Transport recovery | Stall, abort, bus reset, timeout, repeated tag across generations | Invalidation and recovery before next command; no false GOOD/residue=0 or cached sense reuse |
| Compatibility | Factory, revised CK, trace-only, revised CK+trace under identical observations | No new shared-state/MMIO divergence outside intended CK abort invalidation; trace variants retain accounting |
| Ordinary SCSI | Controlled READ/WRITE on disposable media only after earlier gates | Payload comparison, lengths/residue, sense and subsequent command behavior; not inferred from admission tests |

Hardware test records should preserve tool versions, command bytes, untouched host/USB traces, timestamp alignment, device/port mapping, raw CSW, readback method and payload hashes. Unit identifiers stay in the private record. Do not derive USB byte counts from SG_IO residue and then label them USB observations. A same-data readback alone does not prove that physical media were rewritten.

UASP and hot-swap are not part of this qualification scope. No drive removal/insertion is requested by this plan. If hot-swap is later explicitly authorized as a separate development task, electrical reset/power/link measurements must establish the cause of disconnect before firmware recovery policy is changed.
