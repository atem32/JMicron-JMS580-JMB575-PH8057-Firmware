# Testing and hardware evidence

## Run the offline suite

Use Python 3.11 or newer and a C compiler (`cc` or `gcc`) for the bundled
decoder comparison. Public checks require no vendor firmware, disk access or
flashing tool:

```bash
python3 run_tests.py --out build/public-validation
```

The entry point includes firmware/emulator regressions and the hardware
qualification suite's offline tests. Enable exact-image checks with locally
held factory inputs:

```bash
python3 run_tests.py \
  --stock /private/complete-factory.bin \
  --device-stock /private/1.bin \
  --out build/full-validation
```

`--stock` identifies the 70,144-byte SPI capture; `--device-stock` identifies the
67,072-byte updater readback. Their hashes and layouts are in
[firmware layout](firmware-layout.md). Optional `--donors /private/jms580-donors`
adds comparison with the identified donor updater files and requires `--stock`.
Donor code similarity does not establish board compatibility.

Without an input, the corresponding checks are explicitly skipped.
`summary.json` reports `PASS_OFFLINE`, `PASS_WITH_EXPLICIT_SKIPS` or `FAIL`,
group results, executed/skipped unittest methods, input/source hashes and the
hardware-operation scope. Group logs and generated native disassembly record
the detailed results. Assertion-disabled runs are rejected, inherited
`PYTHONOPTIMIZE` is removed for child tests, and empty test discovery fails.

The hardware suite's isolated regression command is:

```bash
python3 -m unittest discover -s tests/hardware/tests -v
```

### Verification coverage

| Component | Checks | Scope |
|---|---|---|
| [8051 emulator](../tools/emulator/mcs51.py) and [tests](../tools/emulator/tests/) | Arithmetic/flags, defined MUL/DIV inputs, decimal adjust, register banks, direct/indirect/bit addressing, stack, jump wrapping, MOVX, dual DPTR and a pinned external decoder comparison. | Instruction execution with explicit fixtures; no cycle-accurate controller or autonomous peripheral model. |
| [OEM decoder](../tools/analysis/oem.py), [native execution](../tools/analysis/native_oem.py) | Complete OEM coverage/redaction, signatures, string bounds, stateful flags, USB setup fields, power/timer pages, F8 copies/retries/sticky mismatch and MMIO instruction effects. | Hardware meanings are classified separately from confirmed instruction effects. |
| [CK_COND tests](../tools/patching/ckcond/tests/) | SAT12/SAT16 normalization and dispatch, native status/error mapping, command/result ownership, descriptor truncation and lifetime, capture families, both native abort exits and preservation of ordinary-command policy. | Native instructions and declared peripheral samples; physical SRAM ownership and interrupt timing remain separate questions. |
| [UDMA tests](../tools/patching/udma/tests/test_udma.py) | CBW→taskfile→exact CSW replay, Data-In residual masks, abort behavior, unsafe-clearing counterexamples, 32-bit boundaries, BOT framing and processed-byte ownership contracts. | Preserves evidence for the known defect; no residue repair is implied. |
| [Integration](../tests/integration/) | SPI/updater source and output hashes, CRCs, guarded patch records, overlap/trailer limits, OEM preservation, byte-for-byte rebuild, output-alias protection and runner guards. | Reproducible local files; installation/readback is outside these tests. |
| [Hardware-suite regressions](../tests/hardware/tests/) | Device/serial/routing guards, destructive confirmation, fio verification and ranges, safe SCSI cases, USB monitoring, realistic SMART parsing and baseline/end comparison. | Mocks and temporary fixtures; no physical disk operations. |

The emulator rejects ambiguous 64 KiB input layouts and invalid fixture ranges.
DIV-by-zero stops after setting the defined flags because A/B are undefined;
this does not claim that silicon traps. MMIO events record the executing
instruction PC, and conditional branches read only their required SFR condition.
These behaviors have direct regressions in
[test_memory_and_control.py](../tools/emulator/tests/test_memory_and_control.py).
An interpreter instruction limit means a pending modeled loop, not elapsed
hardware timeout. Ordinary SCSI admission and shared-sense checks do not prove
a sector transfer.

The [CI workflow](../.github/workflows/offline.yml) runs public checks on its
configured Python versions and retains explicit private-input skips. A passing
offline check applies to its declared inputs and fixtures. A hardware PASS
applies to the equipment, workload and observed counters recorded below.

## Reproduce the firmware build

The same command accepts either exact factory container and emits the
corresponding CK_COND image:

```bash
python3 ph8057.py build ckcond --stock /private/factory.bin --out build/ckcond
```

It produces the BIN, `ckcond_manifest.json` and `ckcond_patch_records.json`,
including guarded replacements, actual differences, hashes, CRCs and OEM
comparison. The expected SPI/updater hashes are in
[the image manifest](../firmware/manifests/images.json). The
[updater verifier](../firmware/ph8057-device/modified/verify_device_build.py)
compares a supplied local image with a fresh rebuild; it never reads a device.

## Hardware evidence

### Configuration and provenance

The three results below are the **device owner's supplied successful test
summaries**, incorporated on 6 November 2026. The setup used two
**WDC WD5000AAKX-001CA0 HDDs**, each 500,107,837,440 bytes, through
**PH8057 / JMS580 / JMB575**, **USB BOT (`usb-storage`) at 5 Gbit/s**, in
**OpenMediaVault 8 / Debian 13 under Proxmox USB passthrough**. Published disk
labels are anonymous.

The owner identifies the installed SMART Fixed package as the 67,072-byte
updater with SHA256
`f8406e8b83e9f97695ce4ae395a90b29e28d8210bc40c09087f3f6b43f33fd5b`.
The full SPI file has a different container/hash. The public repository includes
the qualification source and offline regressions; complete raw run archives,
unredacted device logs and per-run post-flash readbacks are not published here.
These summaries preserve the reported counters and scope.

### Test 1 — 24h I/O stress

**3–4 November 2026 — PASS.**

| Measurement | Result |
|---|---:|
| Duration | 24.008 hours |
| HDDs | 2 |
| Completed fio passes | 1,593 |
| fio errors | 0 |
| Target kernel errors | 0 |
| Recorded USB CSW phase/residue anomalies | 0 |

This was a sequential, CRC-verified workload with moving 2 GiB windows,
QD1 and no full-surface pass. The reported logical byte totals are:

| Across both HDDs | Bytes | TB (`10¹²` bytes) | TiB (`2⁴⁰` bytes) |
|---|---:|---:|---:|
| Written | 6,838,812,672,000 | 6.838812672 | 6.2198638916015625 |
| Read | 6,838,812,672,000 | 6.838812672 | 6.2198638916015625 |
| **Total logical I/O** | **13,677,625,344,000** | **13.677625344** | **12.439727783203125** |

Each HDD contributed 3,419,406,336,000 bytes in each direction. These are
cumulative verified fio bytes, not unique LBA coverage or measured USB traffic.

### Test 2 — SCSI/SAT protocol

**4 November 2026 — PASS.**

| Measurement | Result |
|---|---:|
| Mode | `protocol-idle` |
| SCSI/SAT protocol commands | 308 |
| Expected negative-command rejections | 102 |
| Host timeouts | 0 |
| Failures of commands expected to succeed | 0 |
| Recorded USB CSW anomalies | 0 |

The protocol workload uses bounded read-only/no-data probes and no fio writes.
Expected rejections of negative commands are counted separately from failures
of commands marked as expected to succeed.

### Test 3 — 24h combined I/O + protocol stress

**5–6 November 2026 — PASS for the tested dual-HDD BOT workload.**

| Measurement | Result |
|---|---:|
| Duration | 24.015 hours |
| HDDs | 2 |
| fio cycles | 199 |
| Verified fio phases | 595 |
| SCSI/SAT protocol commands | 520,828 |
| Expected negative-command rejections | 201,114 |
| fio errors | 0 |
| Host timeouts | 0 |
| Failures of commands expected to succeed | 0 |
| Target kernel errors | 0 |
| Recorded CSW phase/residue anomalies | 0 |
| Monitor warnings | 0 |

The workload combined sequential 1 MiB writes/verification with QD1/4/8/16,
256 MiB random-64 KiB windows at **512–768 MiB**, 64 MiB random-4 KiB windows
at 1 GiB, and concurrent SCSI/SAT/SMART checks. The cycle count includes the
final cycle's completed sequential phase: 198 three-phase cycles plus one
sequential phase give 595 verified phases. No exact transfer-byte total is
asserted without the per-phase byte records; cycle counts alone are not a
measurement.

The final SMART values were supplied as a **manual baseline/end comparison**:

| SMART attribute | HDD 1 | HDD 2 |
|---|---|---|
| 5 — Reallocated sectors | `0 → 0` | `0 → 0` |
| 197 — Current pending sectors | `0 → 0` | `0 → 0` |
| 198 — Offline uncorrectable | `0 → 0` | `0 → 0` |
| 199 — UDMA CRC errors | `231 → 231` | `28 → 28` |

### What these results establish

The two HDDs passed the stated I/O and protocol workloads, with no errors in the
reported categories. The results cover the verified fio regions and sampled
USB/kernel observations. They do not establish full-surface coverage, all five
physical ports, UASP/NCQ, hot-swap or every abort/error path.

The usbmon sampler checks framing/status and residue larger than the requested
length. A residue equal to a 512-byte request is within that numeric bound, so
zero sampled anomalies cannot resolve the separate
[WRITE DMA EXT residue defect](patches.md#udma-data-out-and-csw-residue).
That path needs a targeted processed-byte/accounting test.

Use the [hardware suite instructions](../tests/hardware/README.md) to run the
current tool. [Hardware coverage](../tests/hardware/QUALIFICATION_PLAN.md)
defines acceptance criteria for extending the tested configuration and for
investigating the remaining firmware contracts.
