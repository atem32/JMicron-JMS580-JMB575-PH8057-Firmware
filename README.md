# PH8057 firmware: JMS580 / JMB575

Reverse engineering, reproducible patch builders and offline tests for one
captured PH8057 firmware. The five-bay enclosure uses a **JMicron JMS580
USB-to-SATA bridge** and a **JMB575 SATA port multiplier**. The tested transport
is **USB Bulk-Only Transport (BOT)**; sustained tests cover two attached HDDs.

<img src="assets/images/ph8057.jpg" alt="PH8057 USB-to-SATA enclosure controller board" width="560">

*Owner-supplied product photograph from an Ozon listing;
[image attribution](NOTICE.md#image-attribution).*

## AIM

Make **SMART STATUS** and **CHECK POWER MODE** return usable ATA registers, so
standby-aware monitoring can determine whether a HDD is asleep and skip further
queries. The factory firmware's incomplete ATA Return Descriptor prevented this.
The standby timer itself is a separate drive setting, not a feature added by the
patch.

The owner observed successful SMART STATUS and CHECK POWER MODE responses on one
physical HDD after installing the revised CK_COND updater package. Later I/O and
protocol-load tests exercised two WD5000AAKX drives. These observations have
different scopes: they do not qualify every command, abort path or SATA port.

### A word from the carbon-based owner 🥩

> The carbon-based lifeform behind this project has absolutely no idea what half of these registers are doing. He just wanted proper SMART data and a sensible HDD standby setup. He got what he came for. The AI can argue with the silicon about the rest. 😄
>
> And yes, this paragraph was also written by AI. The human was too lazy to write even his own disclaimer. 🤖

## Current status

| Component | Result | Evidence and boundary |
|---|---|---|
| Revised CK_COND / SMART | Builds ATA Return Descriptors and invalidates unpublished snapshots on both native USB-wait abort exits | **OFFLINE VALIDATED**; two command responses on one HDD are **HARDWARE OBSERVED**. Abort handling, SRAM ownership and interrupt timing remain unqualified. |
| OEM decoder and register atlas | Corrected flag semantics, F8.7 retries, sticky mismatch, state preservation and USB setup-field mapping | **OFFLINE VALIDATED** against exact firmware instructions; undocumented hardware semantics remain explicitly uncertain. |
| UDMA Data-Out / CSW residue | Known `WRITE DMA EXT` transaction transferred 512 USB bytes but reported residue 512 | **HARDWARE OBSERVED** excerpt and offline reproduction. **No validated residue repair.** |
| UDMA observation candidate | Adds observation PCs while preserving native accounting | **OFFLINE VALIDATED**; **NOT TESTED** on hardware. It is neither a residue fix nor an autonomous logger. |
| Revised CK_COND + observation | Composes both changes from the exact factory image | **OFFLINE VALIDATED**; **NOT TESTED** on hardware. |
| UASP, NCQ and hot-swap | No implementation or qualification in this project | Changing an OEM bit does not establish safe multi-command operation. Disk removal has caused USB disconnects. |

The full SPI image and the updater package are **different artifacts**, even
when their CODE regions match. The observed installation used the 67,072-byte
package; no post-flash readback is available. Exact identities, layouts and CRCs
are recorded in [firmware layout](docs/firmware-layout.md) and
[image manifest](firmware/manifests/images.json).

## Hardware results through 6 November 2026

The following is the owner's supplied summary. Original long-run archives and
the qualification script are not present in this repository.

| Run | Scope | Result |
|---|---|---|
| 3–4 November: I/O | 24.008 h; two HDDs; 6.839 TB written and 6.839 TB read in total | No fio or target kernel errors reported. |
| 4 November: protocol-idle | 308 SCSI/SAT commands | No host timeouts or unexpected successes; 102 expected negative-command rejections. |
| 4 November: protocol-load | 3.751 h; 81,773 SCSI commands | **ABORTED — TEST-HARNESS SAFETY** after Linux detected false AHDI partitions in the test region. |
| 5–6 November: protocol-load v7.1 | 24.015 h; 520,828 SCSI commands | No fio errors, host timeouts, unexpected successes, target kernel errors or monitor warnings reported; AHDI partitions did not recur. |

The final run's manual SMART checks found no change in attributes 5, 197, 198 or
199 on either HDD. The automatic SMART delta parser remained incomplete.
No CSW phase/residue anomalies were recorded by the sampling monitor, which does
**not** resolve the targeted UDMA residue defect. See
[testing and evidence](docs/testing.md) for exact counts, bytes, provenance and
limits. There is no whole-firmware **HARDWARE QUALIFIED** claim.

## Reproduce

Requirements: Python 3.11 or newer, its standard library, and `cc` or `gcc` for
the bundled decoder comparison. Public checks do not need vendor firmware:

```bash
python3 run_tests.py --out build/public-validation
```

Firmware-dependent checks are explicitly skipped when their inputs are absent.
With the exact local full factory capture:

```bash
python3 ph8057.py inspect /absolute/path/complete-factory.bin
python3 run_tests.py --stock /absolute/path/complete-factory.bin --out build/full-validation
python3 ph8057.py oem --stock /absolute/path/complete-factory.bin --out build/oem
python3 ph8057.py build ckcond-revised --stock /absolute/path/complete-factory.bin --out build/candidates
```

The accepted full capture is 70,144 bytes, SHA256
`ef5ad9af3f3b290c565a4dc65933d539b7bb8b8051ac9bd45386932a77862c09`.
Other current build choices are `udma-trace` and `combined-revised-trace`.
Superseded v8 exists only as a differential regression baseline.

Builders enforce source identity, expected bytes, code-cave boundaries, patch
overlap, checksums and unchanged OEM data. The source-only
[device package builder](firmware/ph8057-device/README.md) separately accepts the
exact 67,072-byte input. No tool here establishes safe flashing or recovery.
See [patches](docs/patches.md) for patch records and
[testing](docs/testing.md) for commands, skipped checks and fixture assumptions.

## Engineering references

| Location | Canonical content |
|---|---|
| [Architecture](docs/architecture.md) | USB BOT, SATA port mapping, 8051 memory and command lifecycle |
| [Firmware layout](docs/firmware-layout.md) | CPU addresses versus file offsets, container identities and CRCs |
| [Register map](docs/register-map.md), [machine-readable atlas](research/oem/registers.json) | OEM fields, MMIO, IRAM/XDATA, instruction evidence and confidence |
| [Patches](docs/patches.md) | CK_COND implementation, rejected UDMA approach and observation-only variant |
| [Testing](docs/testing.md), [hardware qualification plan](tests/hardware/QUALIFICATION_PLAN.md) | Reproduction, evidence levels and remaining qualification work |
| [Known issues](docs/known-issues.md) | Severity, evidence, impact and next action for unresolved problems |
| [References](docs/references.md) | Primary specifications and related projects |

`tools/` contains analysis, the 8051 emulator and patch builders; `tests/`
contains regression, integration and hardware test documentation.
`firmware/` contains manifests and the device-specific builder.
`research/` contains the canonical atlas and bounded source evidence.

Project contributions use the scoped [MIT license](LICENSE). Vendor BINs and
proprietary Windows flashers are not distributed. Authorship, third-party
copyright boundaries and responsibility are in [NOTICE](NOTICE.md).
