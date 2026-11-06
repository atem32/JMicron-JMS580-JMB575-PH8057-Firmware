# Testing and hardware evidence

## Evidence labels

| Label | Meaning |
|---|---|
| **OFFLINE VALIDATED** | Executed source/build/protocol checks or 8051 instructions passed for their declared inputs and fixtures. No physical peripheral behavior follows automatically. |
| **HARDWARE OBSERVED** | A specified transaction or workload was reported on physical equipment. Record the source, configuration and missing evidence. |
| **HARDWARE QUALIFIED** | A defined configuration and test scope have complete, attributable evidence and stated acceptance criteria. This is never implied by enumeration, a hash match or a single successful command. |
| **NOT TESTED** | The specified path, artifact or configuration has no applicable executed test. |

Firmware instructions, injected MMIO values, host-language reference contracts and owner-provided observations are distinct evidence. The current two-disk workload summaries are **HARDWARE OBSERVED**; they do not establish general hardware qualification for every artifact, port or failure path.

## Run the current offline suite

Use Python 3.11 or newer. A C compiler is needed for the bundled decoder comparison. Public tests require no vendor BIN, historical archive, disk access or flashing tool:

```bash
python3 run_tests.py --out build/public-validation
```

Enable exact-image checks with locally held source files. The full SPI image and updater readback are separate inputs with different hashes ([layout](firmware-layout.md)):

```bash
python3 run_tests.py \
  --stock /private/complete-factory.bin \
  --device-stock /private/1.bin \
  --out build/full-validation
```

Optional donor comparison takes the directory containing the identified donor updater files:

```bash
python3 run_tests.py \
  --stock /private/complete-factory.bin \
  --device-stock /private/1.bin \
  --donors /private/jms580-donors \
  --out build/donor-validation
```

Without an input, corresponding checks are explicitly skipped. A skipped firmware-dependent method is not a successful firmware test. `--donors` requires `--stock`; donor signatures establish related code, not flash compatibility.

`summary.json` reports `PASS_OFFLINE`, `PASS_WITH_EXPLICIT_SKIPS` or `FAIL`, plus group results, reported/skipped unittest methods, input/source hashes and hardware-operation scope. Group logs, `ckcond/ckcond_suite_results.json`, `native_oem.json` and `udma_native/udma_audit_results.json` contain the detailed executed results; native disassembly is generated locally. These outputs are reproducible build artifacts, not committed historical scorecards. Assertion-disabled runs are rejected, inherited `PYTHONOPTIMIZE` is removed for child tests, and empty test discovery fails.

### Retained verification coverage

| Component | Checks | Boundary |
|---|---|---|
| [8051 emulator](../tools/emulator/mcs51.py) and [tests](../tools/emulator/tests/) | Arithmetic/flags, defined MUL/DIV inputs, decimal adjust, register banks, direct/indirect/bit addressing, stack, jump wrapping, MOVX, dual DPTR and pinned external decoder comparison. | No cycle-accurate controller or autonomous peripheral model. |
| [OEM decoder](../tools/analysis/oem.py), [native execution](../tools/analysis/native_oem.py) | Complete OEM coverage/redaction, signatures, string bounds, stateful flags, USB setup fields, power/timer pages, F8 copies/retries/sticky mismatch and MMIO instruction effects. | Native paths use declared register samples and selected peripheral/wait fixtures; physical register meaning remains separately classified. |
| [CK_COND tests](../tools/patching/ckcond/tests/) | SAT12/SAT16 normalization and natural dispatch, status/error mapping against native AA9F, descriptor ownership, allocation-length truncation, sense lifetime, capture families, native abort exits, preservation of ATA-error/non-CK policy. | Lower asynchronous scheduler, real SRAM ownership, interrupt timing and peripheral snapshot coherence are unqualified. |
| [UDMA tests](../tools/patching/udma/tests/test_udma.py) | CBW→taskfile→exact CSW replay, abort and unsafe-prototype counterexample, trace/state/MMIO equivalence, Data-In residual masks, 32-bit boundaries, BOT framing and qualified-count rejection contracts. | Staged execution supplies explicit peripheral samples; it does not execute real partial Data-Out processing. |
| [Integration](../tests/integration/) | Source/output hashes, CRCs, container origins, exact patch records, overlap/trailer limits, OEM preservation, combined compatibility, updater reproduction, output-alias protection and runner guards. | Hashes and CRCs do not certify installation or physical recovery. |

The emulator rejects ambiguous 64 KiB input layouts and invalid fixture ranges instead of wrapping/resizing memory. DIV-by-zero stops after setting the defined flags because A/B results are undefined; this does not claim that silicon traps. MMIO events record the executing instruction PC, and conditional branches read only their required SFR condition. These behaviors have direct regressions in [test_memory_and_control.py](../tools/emulator/tests/test_memory_and_control.py).

Current tests retain the unique counterexamples and acceptance contracts. Overlapping assertions, firmware executions and scenario definitions are not added together as a hardware-validation score. An interpreter instruction limit demonstrates a pending modeled loop, not elapsed hardware timeout. Ordinary SCSI admission/shared-sense checks do not by themselves verify a sector transfer.

CI runs the public offline entry point on its configured Python versions. Exact proprietary inputs remain local; missing private-input groups must remain visible in CI results. The [workflow](../.github/workflows/offline.yml) defines the actual check, and generated logs are the record of each execution.

## Reproduce candidate builds

Run from the repository root. Builders never open a device:

```bash
python3 ph8057.py inspect /private/complete-factory.bin
python3 ph8057.py build ckcond-revised --stock /private/complete-factory.bin --out build/candidates
python3 ph8057.py build udma-trace --stock /private/complete-factory.bin --out build/candidates
python3 ph8057.py build combined-revised-trace --stock /private/complete-factory.bin --out build/candidates
```

The v8 predecessor is built internally for the stale-snapshot regression; it is not a current deployment choice. Current full-image builds emit a BIN and a manifest with exact guarded records, actual differences, hashes, CRCs and OEM equality.

For the separate owner updater package:

```bash
mkdir -p build/device
python3 firmware/ph8057-device/modified/build_from_1bin.py \
  --stock /private/1.bin \
  --output build/device/PH8057_SMART_CKCOND_REVISED_67072_EXPERIMENTAL.bin
python3 firmware/ph8057-device/modified/verify_device_build.py \
  --candidate build/device/PH8057_SMART_CKCOND_REVISED_67072_EXPERIMENTAL.bin \
  --stock /private/1.bin
```

The updater verifier's byte-for-byte rebuild is a comparison of local files. It is **not post-flash readback**. [Patch semantics](patches.md) and [known issues](known-issues.md) describe the remaining installation/operation limits.

## Hardware evidence

### Firmware identity and available records

The November 2 observations came from owner-supplied terminal output. The November 3–6 results below are the owner's supplied summary, incorporated on **2026-11-06**. Original fio JSON, complete usbmon captures, kernel logs, raw SMART baseline/end files and run archives for those later tests are **not present in this repository**. The figures cannot be independently reconstructed from the public tree.

The reported installed artifact is the **67,072-byte SMART-only revised updater**, rebuilt from the exact owner `1.bin`:

`f8406e8b83e9f97695ce4ae395a90b29e28d8210bc40c09087f3f6b43f33fd5b`

The owner reported successful programming with JMicron Windows updater **1.19.16.48**, power cycling, USB enumeration and disk discovery. The tool recognized JMS580 Series but displayed an unknown SPI flash type. No post-flash firmware readback or captured final NVRAM option state is supplied. Later workload summaries concern the same reported PH8057/BOT setup, but omit per-run binary readback/hash attestations. Their results must not be reassigned to the distinct 70,144-byte full-image hash or to trace variants.

### November 2: bounded SMART and power-mode observations

Four disks were enumerated: one Seagate 4 TB and three WD 500 GB HDDs. The following transactions ran only on one WD disk; enumeration is not a per-LUN qualification result.

| Transaction | Reported response | Interpretation |
|---|---|---|
| `smartctl -d sat -r ioctl,2 -H /dev/sdc`; ATA `B0h`, feature `DAh` | SCSI status = 2, sense `72 01 00 1D`, descriptor `09 0C`; `ERR=00 SC=00 LM=4F LH=C2 STS=50`; SMART overall PASSED. | Expected CK_COND CHECK CONDITION and valid SMART-good registers. The previous missing-register error is absent in this transaction. |
| `smartctl -d sat -r ioctl,2 -n standby,3 -i /dev/sdc`; ATA `E5h` | Same descriptor framing; `ERR=00 SC=FF STS=50`; ACTIVE or IDLE. | Valid power-mode result for a spinning drive; this does not measure a standby transition. |
| Saved power-condition setting on the Seagate | `STANDBY_Z=1`, `SZCT=18000`, subsequent page read reports `sav:18000`. | Setting reported as saved. Standard SZCT units are 100 ms, so 18000 corresponds to 30 minutes; a real timed spin-down was not measured in this record. |

ATA IDENTIFY and SMART attribute reads also succeeded. The records do not exercise failed ATA commands, all SAT12/SAT16 combinations, either abort exit, every LUN or reentrant/interrupt behavior.

### November 3–6: two-disk BOT workloads

All runs below used **two WD5000AAKX HDDs through PH8057/JMS580/JMB575 in USB BOT mode**. Zero errors refer only to the reported categories and monitoring scope.

| Run | Duration | Completed work | Reported result |
|---|---:|---|---|
| **Test 1 — I/O, November 3–4** | 24.008 h | 1,593 successful fio phases. | Completed; fio errors = 0, kernel target errors = 0, monitored CSW phase/residue anomalies = 0. Automated SMART delta was not produced. |
| **Protocol-idle, November 4** | Not supplied | 308 SCSI/SAT commands; 102 rejected negative-test commands. | Host timeouts = 0; unexpected-success failures = 0. |
| **Test 2 — protocol-load, November 4** | 3.751 h | 31 complete cycles, 95 successful fio phases, 81,773 SCSI commands. | **ABORTED — TEST-HARNESS SAFETY**. fio errors = 0, host timeouts = 0 before the stop. |
| **Test 3 — protocol-load v7.1, November 5–6** | 24.015 h | 199 complete cycles, 595 successful fio phases, 520,828 SCSI commands; 201,114 expected negative-command failures. | Completed; fio errors = 0, host timeouts = 0, unexpected-success failures = 0, kernel target errors = 0, monitored CSW phase/residue anomalies = 0, monitor warnings = 0. No AHDI partitions appeared. |

Test 1's reported logical transfer volume is exact:

| Scope | Written bytes | Read bytes |
|---|---:|---:|
| Each HDD | 3,419,406,336,000 | 3,419,406,336,000 |
| Both HDDs | 6,838,812,672,000 | 6,838,812,672,000 |

That is **6.838812672 TB written plus 6.838812672 TB read** across both disks, or 13.677625344 TB combined, using decimal TB. Transfer byte totals for Tests 2 and 3 were not supplied and are not extrapolated from cycles or elapsed time.

Test 2 stopped when the script's partition guard detected false Linux AHDI partitions on `/dev/sdc`. The owner's diagnosis links this to a test region including the start of the disk, with no recorded USB-controller failure. The subsequent harness moved `rand64k` to **512–768 MiB** and retained the partition guard. The aborted run is neither PASS nor evidence of firmware FAILURE.

After Test 3, the owner manually compared SMART baseline/end values:

| Attribute | HDD A | HDD B |
|---|---|---|
| 5 — Reallocated sectors | `0 → 0` | `0 → 0` |
| 197 — Current pending sectors | `0 → 0` | `0 → 0` |
| 198 — Offline uncorrectable | `0 → 0` | `0 → 0` |
| 199 — UDMA CRC errors | `231 → 231` | `28 → 28` |

HDD A/B are anonymous labels for the two reported counter pairs. **The automatic SMART delta remained incomplete because of a parser defect.** Manual equality does not mean that parser was fixed.

### Limits and reproducibility of the hardware runs

- Sampled usbmon monitoring finding zero anomalies does not rerun, disprove or fix the specific WRITE DMA EXT residue = 512 defect preserved in [patches](patches.md#udma-data-out-and-csw-residue).
- Two drives passed the reported workloads. There is no qualification of all five ports, stable hot-swap, UASP/NCQ concurrency or every LUN-to-port mapping.
- Cumulative terabytes do not prove complete LBA coverage. No completed full-surface verification record is supplied.
- The original hardware harness `ph8057_qualify.py` is absent from this Git tree. Reproduction of those exact hardware runs requires adding its verified original source and associated configuration/logs; no replacement implementation is invented here.
- The remaining observations and acceptance criteria are in the [hardware qualification plan](../tests/hardware/QUALIFICATION_PLAN.md). The repository's automated suite performs offline work only.
