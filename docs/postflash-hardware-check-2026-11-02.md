# Limited physical verification after flashing the revised CK_COND image

**Date:** 2026-11-02 (owner-provided serial console output)

This is a **post-audit addendum**. Earlier reports in `docs/` correctly state that no modified image was installed during the independent offline audit; that statement does not cover the owner's subsequent physical test.

## Device and installation

- Enclosure: PH8057 using JMS580 plus JMB575, connected to an OMV host over USB.
- Update container: 67,072-byte, SMART-only revised CK_COND firmware, rebuilt from the owner's own 67,072-byte `1.bin`.
- Candidate SHA256: `f8406e8b83e9f97695ce4ae395a90b29e28d8210bc40c09087f3f6b43f33fd5b`.
- Reported updater: JMicron Windows 1.19.16.48; owner reports successful programming, power cycle, USB enumeration and drive discovery. The updater initially reported unknown SPI flash type; no readback of the installed firmware was supplied. Neither the exact NVRAM option state nor a second firmware dump after flashing was captured.
- OMV enumerated a Seagate 4 TB disk as `/dev/sdb` and three WD 500 GB disks as `/dev/sdc` through `/dev/sde`; this is enumeration, **not qualification of stable LUN behavior**.
- Physical SMART tests below were performed only on WD 500 GB `/dev/sdc`. Unique drive serial numbers are omitted from this public report.

## Read-only SMART STATUS

Command:

```bash
smartctl -d sat -r ioctl,2 -H /dev/sdc
```

Relevant response:

```text
SMART STATUS CHECK, ATA B0 / feature DA
SCSI status=2 (CHECK CONDITION)
Sense: 72 01 00 1D ... ATA Return Descriptor 09 0C
ATA output: ERR=00 SC=00 LM=4F LH=C2 STS=50
SMART overall-health self-assessment test result: PASSED
```

`CHECK CONDITION` is the **expected** response for successful CK_COND=1 when the ATA Return Descriptor is attached. The returned `4F/C2` registers indicate SMART STATUS good. The previous missing-register failure is absent in this transaction.

## Read-only CHECK POWER MODE

Command:

```bash
smartctl -d sat -r ioctl,2 -n standby,3 -i /dev/sdc
```

Relevant response:

```text
CHECK POWER MODE, ATA E5
SCSI status=2 (CHECK CONDITION)
Sense: 72 01 00 1D ... ATA Return Descriptor 09 0C
ATA output: ERR=00 SC=FF STS=50
Sector Count Register: ff
Power mode is: ACTIVE or IDLE
```

`SC=FF` indicates that the HDD was spinning, not a failure. The previous `incomplete response, ATA output registers missing` error is absent.

For `/dev/sdb`, `sdparm --save --set=STANDBY_Z=1,SZCT=18000` was accepted and `sdparm --page=po` returned `sav:18000`. This confirms the setting is reported as saved, not that a real 30-minute spin-down cycle has been physically measured.

## What this does and does not establish

**Observed:** controller USB enumeration following the update, ATA IDENTIFY and SMART attribute reads on the WD disk, valid CK_COND descriptor response for SMART STATUS, valid power-mode response for CHECK POWER MODE, all after the revised firmware was installed.

**Not established:** binary readback matching the expected hash; revision-specific controller behavior on all four LUNs; failed ATA commands; all SAT12/SAT16 variants; reentrant/interrupted command handling; UDMA CSW residue correction; firmware recovery; long-term stability; media integrity. The patch remains **experimental outside these bounded successes**.

No proprietary firmware bytes or unique device serial numbers are hosted in this public repository.
