# Hardware coverage and acceptance

The [three completed tests](../../docs/testing.md#hardware-evidence) cover the
reported dual-HDD BOT workloads. The [qualification suite](README.md) runs I/O,
SCSI/SAT and combined stress. This document defines the additional evidence
needed to extend coverage to other command paths, ports and hardware contracts.

## Record the configuration

Record board/SPI identity, firmware container and SHA256, installed readback
when available, NVRAM settings, host/kernel/tool versions, USB mode, actual
port-to-LUN mapping and disk capacities. Keep original logs privately and use
anonymous disk labels in published extracts. SPI and updater containers have
different whole-file identities even when their CODE is equal.

For qualification beyond the tested configuration, establish independent
recovery for the exact SPI/loader, loaded/executable CODE caves and exclusive
use of `4D00..4DFF` / `4E00..4E1F` across commands, interrupts and recovery.
A region containing zero at one instant does not demonstrate exclusive SRAM
ownership. The observed updater's unknown SPI type leaves chip selection and
recovery unestablished; [firmware layout](../../docs/firmware-layout.md#installation-and-hardware-boundaries)
records the available evidence.

Measure stack watermark and interrupt interactions. CK_COND capture wrappers
save 17 context bytes; the abort leaf saves five bytes without a nested call.
Native frames and ISR nesting must be included in the physical stack budget.
CPU interrupt masking does not stop autonomous SATA/USB activity or prove a
coherent taskfile snapshot.

## CK_COND acceptance matrix

| Group | Cases | Acceptance evidence |
|---|---|---|
| Descriptor correctness | SAT12/SAT16, CK_COND clear/set; SMART RETURN STATUS, IDENTIFY and CHECK POWER MODE; ATA success/error | The descriptor belongs to the admitted command. EXTEND, ATA registers and native key/ASC/ASCQ match that outcome; informational CHECK CONDITION is distinguished from ATA failure. |
| Standby | Active/idle and a measured standby transition without an intervening wake-up command | Power-state response agrees with observed spindle state. Saved SZCT alone is insufficient. |
| Sense lifetime | Zero/short/full allocation lengths, repeated REQUEST SENSE, an intervening ordinary command, another LUN and reset | Correct truncation/fallback; no stale, cross-LUN or prior-command descriptor consumption. |
| Port ownership | Every actually exposed physical port/LUN and relevant populated configuration | Stable command/tag/LUN/port association before and after `6300` capture. Include the fifth bay only with discovery and test evidence. |
| Abort invalidation | Both CBE3 carry-set exits, CK_COND clear/set, ATA good/ERR/DF | `4E07` invalidates, native error/sense/retry policy remains, and actual scheduler cancellation or emitted CSW is recorded. |

The offline fixtures cover instruction behavior under declared samples. They do
not replace physical interrupt timing, peripheral coherence or complete port
coverage.

## UDMA accounting evidence

The known 512-byte WRITE DMA EXT discrepancy establishes the defect. A repair
needs a qualified **device-processed-byte** quantity and its ownership contract.
Correlate one command's tag, generation, LUN and selected port at these native
boundaries:

| Boundary | Required context |
|---|---|
| After CBW admission `7BF4..7C47` | CDB, requested length, direction, tag, LUN and a generation that changes across reset/reuse. |
| After Data-Out launch `C789..C7B5` / `8CA3..8CF7` | Programmed `6318..631B`, selected port and the operation establishing the candidate count's meaning. |
| Completion `735F` / before `7377` | ATA status/error, D2H marker and command owner. |
| Native USB wait exit `CBF8`, `CC06` or `CC07` | Carry, actual branch, candidate count and validity after abort. |
| Before CSW residue copy `9529` | Final IRAM `55h..58h`, native state/sense/status and outgoing CSW tag. |

For a candidate count, document address/event source, width, byte order, units,
latch/reset semantics, validity interval, safe read behavior and its relationship
to SATA processing. A new vendor SCSI getter can replace the register context
being investigated. Unknown MMIO must not be treated as passive RAM.
Observation requires a mechanism with established behavior; the repository
does not provide an on-device logger.

Acceptance covers 512-byte and multiblock completion, genuine partial Data-Out,
zero/invalid lengths, ATA errors before/after data acceptance, stall, reset,
abort, timeout and tag reuse, with CK_COND clear/set where relevant. Distinguish
USB-received bytes from device-processed bytes. Compute bounded `H−P` only from
a qualified quantity belonging to that command generation, preserving transport
status and sense independently. Zero arithmetic output or ATA-good status does
not establish `P=H`.

Compare Factory and CK_COND under the same observations. Use raw CSW records and
independent payload comparisons. SG_IO-derived `requested−resid` is not a USB
byte measurement, and same-data readback alone does not prove a physical rewrite.
The [native instruction chain and counterexamples](../../docs/patches.md#udma-data-out-and-csw-residue)
remain the regression baseline for any proposed repair.

## Workload records and coverage

Keep tool/source hashes, command arguments, generated fio configurations,
requested/actual duration, per-phase verified bytes, protocol classifications,
SMART acquisition status, kernel findings and USB sample coverage with each
run. Preserve identity/partition/mount/RAID/LVM guards and abort on device-state
changes. The random-64 KiB window is **512–768 MiB**; the random-4 KiB window
starts at 1 GiB and moving sequential windows start at 2 GiB.

The optional full-surface I/O pass deliberately includes LBA0 and requires the
same destructive confirmation. A full-surface claim additionally needs every
per-disk range and a completed write/read verification result, including the
aligned tail and any uncovered bytes. Cumulative transfer volume does not imply
unique-LBA coverage.

SMART comparisons must retain serial association, actual attributes and missing
or failed acquisitions. Report fio errors, host timeouts, expected negative
rejections, failures of expected-success commands, kernel target errors and
USB sampling separately. A routine workload with no sampled anomaly cannot
replace the targeted UDMA accounting test.

UASP, NCQ concurrency and hot-swap are outside this acceptance matrix. A separate
removal investigation would need synchronized power/reset/link and host traces
before changing firmware event policy. See [known issues](../../docs/known-issues.md).
