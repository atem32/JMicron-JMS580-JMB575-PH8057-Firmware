# PH8057 firmware: JMS580 / JMB575

SMART firmware repair, reproducible builds and tests for the **PH8057 enclosure
controller**, using a **JMicron JMS580 USB-to-SATA bridge** and a **JMB575
one-to-five SATA port multiplier**. The tested transport is **USB Bulk-Only
Transport (BOT)**; the completed stress tests cover two attached HDDs.

<img src="assets/images/ph8057.jpg" alt="PH8057 USB-to-SATA enclosure controller board" width="560">

*Owner-supplied product photograph from an Ozon listing;
[image attribution](NOTICE.md#image-attribution).*

## Why the SMART patch exists

The factory firmware returns incomplete ATA result registers on affected
ATA PASS-THROUGH commands. This prevents reliable **SMART RETURN STATUS** and
**CHECK POWER MODE** responses, including the power-state check used by
standby-aware monitoring. CK_COND supplies a valid ATA Return Descriptor and
keeps the result associated with the command that produced it. The HDD's
standby timer remains a separate drive setting.

### A word from the carbon-based owner 🥩

> The carbon-based lifeform behind this project has absolutely no idea what half of these registers are doing. He just wanted proper SMART data and a sensible HDD standby setup. He got what he came for. The AI can argue with the silicon about the rest. 😄
>
> And yes, this paragraph was also written by AI. The human was too lazy to write even his own disclaimer. 🤖

## Firmware

| Firmware | Purpose |
|---|---|
| **Factory / Original** | Unmodified factory firmware; the exact source for reproducible builds. |
| **SMART Fixed / CK_COND** | The `ckcond` patch: correct ATA Return Descriptors, SMART RETURN STATUS and CHECK POWER MODE support, command/result ownership and invalid-result clearing on abort. |

CK_COND preserves native handling of other commands, USB BOT accounting and all
OEM bytes. Its implementation and instruction-level checks are documented in
[patches](docs/patches.md).

The **70,144-byte SPI image** and **67,072-byte updater image** are two container
formats of the same firmware patch. They have matching CODE and different
wrappers and whole-file hashes. [Firmware layout](docs/firmware-layout.md) and
[the manifest](firmware/manifests/images.json) identify the exact inputs and
outputs. Vendor-derived BINs are not distributed.

## Build SMART Fixed

Use Python 3.11 or newer. The single build command accepts either exact factory
format and selects the matching output format:

```bash
python3 ph8057.py build ckcond \
  --stock /absolute/path/factory.bin \
  --out build/ckcond
```

| Input format | Generated firmware |
|---|---|
| Full SPI capture, 70,144 bytes | `build/ckcond/PH8057_CKCOND_SPI.bin` |
| Updater readback, 67,072 bytes | `build/ckcond/PH8057_CKCOND_UPDATER.bin` |

The builder checks the input SHA256, original instruction bytes, patch bounds,
overlap, CRCs and OEM equality. It also writes `ckcond_manifest.json` and
`ckcond_patch_records.json`. Building only creates local files; it does not
flash a device. See [format and installation boundaries](docs/firmware-layout.md).

## Port CK_COND to your own firmware

Have a different JMS580 firmware image? The existing builder accepts only the
exact PH8057 factory captures. For a different build, an AI assistant or
engineer must identify its container, locate equivalent BOT/SAT/ATA hooks,
relocate the patch and verify target-specific checksums, memory use and behavior.
**Do not apply the published patch records at matching numeric offsets.**

Follow the [AI-assisted CK_COND porting guide](docs/porting-ckcond.md) for
required inputs, step-by-step mapping, tests and a reusable AI task prompt.

## Three successful hardware tests

The following results were supplied by the device owner for two WD5000AAKX
HDDs on the PH8057 in BOT mode.

| Test | Dates | Work completed | Result |
|---|---|---|---|
| **1 — 24h I/O stress** | 3–4 November 2026 | 24.008 h; 1,593 fio passes; 6.838812672 TB written and the same amount read, approximately 6.219864 TiB each. | **PASS** — zero fio errors, target kernel errors or recorded CSW phase/residue anomalies. |
| **2 — SCSI/SAT protocol** | 4 November 2026 | `protocol-idle`; 308 commands; 102 expected negative-command rejections. | **PASS** — zero host timeouts, failures of expected-success commands or recorded CSW anomalies. |
| **3 — 24h combined stress** | 5–6 November 2026 | 24.015 h; 199 fio cycles; 595 verified fio phases; 520,828 SCSI/SAT commands; 201,114 expected negative-command rejections. | **PASS for the tested dual-HDD BOT workload** — zero fio errors, host timeouts, failures of expected-success commands, target kernel errors, recorded CSW anomalies or monitor warnings. |

The combined run's manual SMART baseline/end checks found no change in
attributes 5, 197, 198 or 199 on either HDD. Exact counts, byte conversions,
manual SMART values and evidence scope are in [testing](docs/testing.md#hardware-evidence).
These workloads do not qualify all five ports, UASP/NCQ or hot-swap, and do not
resolve the specific WRITE DMA EXT residue defect.

## Run the qualification suite

The actual hardware test suite is in [tests/hardware](tests/hardware/README.md).
It provides I/O stress, SCSI/SAT protocol tests and combined stress with fio
verification, SMART comparison, USB/SCSI/kernel monitoring and device guards.

**Writing modes destroy disk data. Use only disposable disks and physically
disconnect production disks from the bridge.** Start with a read-only preflight,
using the actual target paths and their exact ATA serials:

```bash
sudo python3 tests/hardware/ph8057_qualify.py \
  --devices /dev/disk/by-path/YOUR_DISK_1 /dev/disk/by-path/YOUR_DISK_2 \
  --expected-serials YOUR_ATA_SERIAL_1 YOUR_ATA_SERIAL_2 \
  --preflight
```

The [suite instructions](tests/hardware/README.md) give dependencies and the
three run commands. Destructive modes require an interactive `ERASE-…` token
derived from the verified target serials. The suite rejects mounted or
partitioned devices, filesystem/RAID/LVM use, unexpected bridge members and
identity or routing changes. The `rand64k` window is **512–768 MiB**.

## Offline tests

Public checks, including the hardware suite's regression tests, use no real
disks or firmware writer. Install Python 3.11+ and `cc` or `gcc` for the
bundled decoder comparison, then run:

```bash
python3 run_tests.py --out build/public-validation
```

[Testing](docs/testing.md#run-the-offline-suite) also documents checks against
locally held factory images. Missing proprietary inputs are reported as explicit
skips.

## Known issues

| Area | Current state |
|---|---|
| **UDMA / BOT CSW residue** | A WRITE DMA EXT transaction transferred 512 USB bytes but reported CSW residue = 512. No accounting fix is implemented. |
| **UASP / NCQ** | Not implemented or developed into a safe patch in this project. Multi-command ownership and recovery require further work. |
| **Hot-swap** | Not fixed. HDD removal has caused USB disconnect/re-enumeration. |

[Known issues](docs/known-issues.md) links the exact evidence, native execution
paths and technical requirements for further work.

## Engineering references

| Location | Content |
|---|---|
| [Architecture](docs/architecture.md) | USB BOT, SATA port mapping, 8051 memory and command lifecycle |
| [Firmware layout](docs/firmware-layout.md) | Container offsets, input/output identities and CRC rules |
| [Register map](docs/register-map.md), [machine-readable atlas](research/oem/registers.json) | Complete OEM coverage, registers, instruction evidence and confidence |
| [Patches](docs/patches.md) | CK_COND implementation, native UDMA/SCSI/BOT findings and unsafe-accounting counterexamples |
| [Testing](docs/testing.md), [hardware suite](tests/hardware/README.md) | Offline reproduction, hardware results and run instructions |
| [Hardware coverage](tests/hardware/QUALIFICATION_PLAN.md) | Acceptance criteria for extending the tested configuration |
| [Porting CK_COND](docs/porting-ckcond.md) | Instructions and AI task prompt for adapting the fix to another firmware image |
| [References](docs/references.md) | Primary specifications and related controller research |

`tools/` contains analysis, the 8051 emulator and the firmware builder.
`tests/` contains regression, integration and hardware qualification code.
`firmware/` holds image identities and guarded patch records; `research/`
holds the register atlas and bounded source evidence.

Project contributions use the scoped [MIT license](LICENSE). Vendor BINs and
proprietary Windows flashers are not distributed. Authorship, third-party
copyright boundaries and responsibility are in [NOTICE](NOTICE.md).
