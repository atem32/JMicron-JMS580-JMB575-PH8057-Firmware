# Hardware qualification plan

This plan specifies missing evidence and acceptance criteria. The automated suite remains offline. Existing owner observations and the completed two-disk workloads are in [testing](../../docs/testing.md#hardware-evidence); they do not need to be relabeled as unperformed work.

## Establish the test configuration

Record board/SPI identity, firmware container and SHA256, actual installed readback when available, NVRAM settings, host/kernel/tool versions, USB mode, physical port-to-LUN mapping and test-disk capacity. A 67,072-byte updater package and a 70,144-byte full SPI artifact require separate identities. Preserve original logs privately and remove serials/device identities from published extracts.

Before extending modified-code qualification, establish independent recovery for this exact SPI/loader, verify that proposed CODE caves are loaded/executable and establish exclusive use of `4D00..4DFF`/`4E00..4E1F` across commands, interrupts and recovery. A region containing zero at one instant is insufficient. The reported updater's unknown SPI type leaves chip selection and recovery unresolved.

Measure stack watermark and interrupt interactions, including existing 17-byte CK context saves, native frames and ISR nesting. The revised abort leaf adds five saved bytes; the trace call contributes another two that can coexist with it. Seven is a path increment, not a total stack budget. Interrupt masking does not stop autonomous SATA/USB activity.

## CK_COND acceptance matrix

| Group | Cases | Required evidence |
|---|---|---|
| Descriptor correctness | SAT12/SAT16, CK_COND clear/set; SMART STATUS, IDENTIFY, CHECK POWER MODE; ATA success/error | Descriptor belongs to the admitted command; EXTEND, ATA registers and native key/ASC/ASCQ are correct. Informational CHECK CONDITION is distinguished from ATA failure. |
| Standby | Active/idle and an actual standby transition, with a method that does not wake the disk before the measurement | Correct power-state response and observed spindle state; saved SZCT alone is insufficient. |
| Sense lifetime | Allocation lengths 0/short/full; repeated REQUEST SENSE; intervening ordinary command; another LUN; reset | No stale descriptor, correct truncation/fallback, no cross-LUN or prior-generation consumption. |
| Ownership | Record every exposed physical port/LUN; include the fifth bay only with actual discovery and test evidence | Stable command/tag/LUN/port association before and after `6300` capture. A synthetic four-slot map is not physical port qualification. |
| Revised abort guard | Both CBE3 carry-set exits; CK_COND clear/set; ATA good/ERR/DF | `4E07` invalidates; native error/sense/retry policy remains; actual scheduler cancellation or emitted CSW is recorded. |

## Minimal UDMA accounting evidence

The known 512-byte WRITE DMA EXT discrepancy already establishes the issue. A repair needs the meaning and ownership of a **processed-byte** quantity, not another ordinary successful USB transfer alone.

A documented peripheral contract or separately qualified observation mechanism must correlate one command's tag, generation, LUN and port at these boundaries:

| Boundary | Required context |
|---|---|
| After CBW admission | CDB, requested length, direction, tag, LUN and generation that changes across reset/reuse. |
| After Data-Out launch | Programmed `6318..631B`, selected port, candidate quantity's initialization and operations establishing its meaning. |
| `7377` / trace `E700` | ATA status/error, D2H marker and command owner. |
| Native wait exit / trace `E705` | Carry and actual wait branch; candidate quantity and its validity after abort. |
| Before `9529` | Final `55h..58h`, native state/sense/status and outgoing CSW tag. |

For a candidate quantity document address/event source, width, byte order, units, latch/reset semantics, validity interval, safe read behavior and relation to SATA processing. A fresh vendor SCSI getter may replace the register context being investigated. Unknown MMIO must not be treated as passive RAM. The trace candidate creates observation PCs, no persistent log or transport.

Acceptance covers full 512-byte/multi-block, genuine partial Data-Out, zero/invalid length, ATA errors before/after data acceptance, stall, reset, abort, timeout and tag reuse, each with CK_COND clear/set where applicable. Distinguish USB-received bytes from device-processed bytes. Compute bounded `H−P` only from a qualified quantity belonging to that generation, and preserve status/sense independently. A zero arithmetic result or ATA-good snapshot does not establish `P=H`.

Compare factory, revised CK, trace-only and revised+trace under identical observations. Trace variants should preserve their base's status/sense/residue and MMIO behavior; their compatibility is not an accounting fix. Use actual raw CSW and independent payload comparisons. SG_IO-derived `requested−resid` is not a USB byte measurement, and same-data readback alone does not prove a physical rewrite.

## Workload reproduction and coverage

The original `ph8057_qualify.py` and complete run archives are absent from Git. Add a verified original before claiming exact reproduction of the November workloads; retain its source/configuration hashes, tool versions, requested/actual durations, command/cycle counts, ranges and error definitions. Do not substitute a newly invented harness for the measured one.

The owner-reported AHDI incident was a harness safety stop. Reproduction of the corrected workload must preserve the partition guard and the `rand64k` range at **512–768 MiB**, with every other destructive-I/O range explicitly recorded from the verified source. An unexpected partition must remain a stop condition. No executable disk-writing commands are provided here.

Separate repeated-window I/O volume from full-surface coverage. A full-surface claim needs exact LBA ranges and a completed write/read verification result for every disk. The automatic SMART baseline/end parser must be repaired and checked against recovered original records; manual equality of attributes 5/197/198/199 is separate evidence. Preserve fio errors, host timeouts, expected negative rejections, unexpected successes, kernel target errors and the scope of USB sampling as distinct counters.

No UASP, NCQ-concurrency or hot-swap test is included in this scope. Investigating removal-related disconnects would require separate synchronized electrical power/reset/link and host traces before changing firmware event policy. See the [issue register](../../docs/known-issues.md).
