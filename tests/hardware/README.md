# PH8057 hardware qualification suite

The PH8057 qualification suite provides I/O, SCSI/SAT and combined stress.
[Completed physical results](../../docs/testing.md#hardware-evidence) describe
the measured workloads. The tool runs directly on Linux with access to the test
bridge and its disposable HDDs; its offline unit/regression tests need no disks.

| Mode | Workload | Disk writes |
|---|---|---|
| `io` | fio writes followed by data verification; device, kernel and USB monitoring | **Destructive** |
| `protocol-idle` | One bounded SCSI/SAT probe round, including negative commands | No fio or SCSI Data-Out |
| `protocol-load` | fio verification while SCSI/SAT and SMART checks run | **Destructive** |

`diagnose` and `benchmark` are additional bounded I/O tools in the same suite;
`--help` lists their options. All writing modes require the same target guards
and interactive confirmation.

## Requirements

Run on the Linux host or VM that directly sees the USB-passthrough disks.
The reference setup is OpenMediaVault 8 / Debian 13. Required tools include
Python 3.11+, Linux fio 3.x, `sg_raw`, `smartctl`, `lsblk`, `wipefs` and
`journalctl`. On Debian/OMV:

```bash
sudo apt-get install python3 fio sg3-utils smartmontools sdparm usbutils util-linux
```

Linux usbmon/debugfs access is needed for USB sampling. The sampler tries to
load `usbmon` and mount debugfs if necessary. Kernel logs must be readable.
A normal run reports unavailable monitoring rather than silently treating it
as clean evidence.

**Use disposable disks only. Writing modes erase the selected regions, and the
optional full-surface pass includes the whole disk. Physically disconnect all
production disks from this bridge.** An intentionally excluded disposable disk
receives no fio writes, but a firmware routing fault could still affect it.

The suite requires two or three explicit test disks on the same `152d:a562`
bridge, distinct ATA serials and stable `/dev/disk/by-path` mappings. Each disk
must be a writable whole disk with capacity **at least 40 GiB and less than
3,000,000,000,000 bytes**, with no partition/child device, filesystem signature,
mount, swap, RAID or LVM/device-mapper use. Every populated bridge LUN must be
accounted for.

## Identify targets and run preflight

Read the actual ATA identities before selecting disks; do not rely on a
remembered `/dev/sdX` name or a USB enclosure serial:

```bash
lsblk -d -o NAME,SIZE,MODEL,TRAN
sudo smartctl -d sat -i /dev/YOUR_FIRST_DISK
sudo smartctl -d sat -i /dev/YOUR_SECOND_DISK
```

Use the corresponding `/dev/disk/by-path/...` links and the exact
`Serial Number` values in the commands below. The placeholders are deliberate;
replace them only after identifying your disposable disks.

```bash
sudo python3 tests/hardware/ph8057_qualify.py \
  --devices /dev/disk/by-path/YOUR_DISK_1 /dev/disk/by-path/YOUR_DISK_2 \
  --expected-serials YOUR_ATA_SERIAL_1 YOUR_ATA_SERIAL_2 \
  --preflight
```

`--preflight` audits identity and device state without writing disk blocks.
It is a real hardware inspection, not an offline simulation. Repeating the
checks at run time protects against changes after preflight.

## Run the three workload profiles

Run from the repository root in an interactive terminal, for example inside
`tmux`. Results go to a new directory on the system filesystem. Each example
uses a distinct output name; choose a fresh name if it already exists.

### 1. 24h sequential I/O stress

```bash
sudo python3 tests/hardware/ph8057_qualify.py \
  --devices /dev/disk/by-path/YOUR_DISK_1 /dev/disk/by-path/YOUR_DISK_2 \
  --expected-serials YOUR_ATA_SERIAL_1 YOUR_ATA_SERIAL_2 \
  --run --mode io --hours 24 --window-gib 2 \
  --no-full-surface --sequential-only --seq-qd 1 \
  --idle-check-minutes 0 --output-dir /root/ph8057-io-test
```

This profile rotates through sequential 2 GiB windows, writes with fio and
verifies the same data using CRC32C. It performs no active protocol/SMART
polling during fio; SMART snapshots bracket the workload. Omitting
`--sequential-only` enables the random phases described below.

### 2. SCSI/SAT protocol test

```bash
sudo python3 tests/hardware/ph8057_qualify.py \
  --devices /dev/disk/by-path/YOUR_DISK_1 /dev/disk/by-path/YOUR_DISK_2 \
  --expected-serials YOUR_ATA_SERIAL_1 YOUR_ATA_SERIAL_2 \
  --run --mode protocol-idle --fuzz-count 128 --sg-timeout 45 \
  --output-dir /root/ph8057-protocol-test
```

With two targets, the 26 fixed cases plus 128 bounded mutations per target
produce **308 commands**. This is a finite run; do not pass `--hours`.
Negative probes use an allowlist of read-only/no-data commands, limited
allocations, bounded READ(10) addresses and fixed safe ATA command registers.
They are issued with `sg_raw --readonly` and no Data-Out payload.

### 3. 24h combined I/O + protocol stress

```bash
sudo python3 tests/hardware/ph8057_qualify.py \
  --devices /dev/disk/by-path/YOUR_DISK_1 /dev/disk/by-path/YOUR_DISK_2 \
  --expected-serials YOUR_ATA_SERIAL_1 YOUR_ATA_SERIAL_2 \
  --run --mode protocol-load --hours 24 --window-gib 2 \
  --fuzz-count 128 --protocol-interval 30 --smart-interval 60 \
  --sg-timeout 45 --usbmon-interval 3600 \
  --output-dir /root/ph8057-combined-test
```

This mode runs sequential and random fio phases alongside SCSI/SAT/SMART
monitoring. It has no full-surface pass. The protocol probe round is serialized;
queue depth in fio does not establish SATA NCQ or parallel hardware command
execution through BOT.

### Confirmation and abort behavior

Before any writing mode, the suite displays the verified models, ATA serials,
LUNs, stable paths and bridge. It asks for an `ERASE-…` token derived from those
serials. A matching token must be entered through an interactive terminal;
piped input or an unconfirmed invocation is refused before fio starts.

Guards run throughout the test. Unexpected partitions, mounted descendants,
RAID/LVM use, serial/size changes, USB re-enumeration, changed LUN membership or
path rebinding stop the workload. Command and fio-phase timeouts, fio verify
failures and fatal monitor findings trigger abort logic. Keep all these checks
enabled.

The optional `--excluded-device` and `--excluded-serial` pair accounts for one
additional disposable bridge disk when testing two targets. It does not permit
a production disk to remain connected. Three active targets are also supported;
provide three paths and three exact serials. The published stress results
cover two active HDDs.

## I/O regions and duration

| Phase | Region | Verification |
|---|---|---|
| Sequential `seq1m` | Moving windows from 2 GiB; the last available window is shortened at the disk boundary | 1 MiB blocks, CRC32C; QD1/4/8/16 rotation unless `--seq-qd` is fixed |
| Random `rand64k` | **512–768 MiB**; offset 512 MiB, length 256 MiB | 64 KiB blocks, CRC32C, QD8 |
| Random `rand4k` | 1 GiB to 1 GiB + 64 MiB | 4 KiB blocks, SHA256, QD16 |
| Optional full surface (`io`) | Full MiB-aligned range starting at LBA0, followed by the aligned 4 KiB tail | Write/read verification with explicit uncovered-tail reporting |

The random-64 KiB phase never includes LBA0. `io` performs a full-surface pass
unless `--no-full-surface` is supplied. The examples above omit that pass.
The default `--duration-basis total` counts from the start of the workload;
an in-progress bounded phase can finish after the deadline. With a full-surface
pass, `--duration-basis after-surface` starts the stress clock after that pass,
so total runtime is longer. `--idle-check-minutes` adds an idle interval in
`io` mode before a standby-aware power check; it defaults to 35 minutes and is
set to zero in the 24h sequential example.

## Results and SMART comparison

Each run writes `manifest.json`, `summary.json`, generated fio job files,
fio verification output, per-phase byte totals, protocol records, SMART
snapshots/deltas, kernel logs and sampled usbmon captures. A sibling `.tar.gz`
packages the result directory. Keep unredacted results private because they
contain drive serials and host/device details.

SMART text (`-A` and `-x` tables) and JSON are parsed by ATA attribute ID. All
available attributes and raw annotations are retained. Baseline and final
captures are matched by **ATA serial**, with attributes 5, 197, 198 and 199
required for a complete comparison. Missing fields, mismatched/duplicate
serials, failed acquisitions and `smartctl` exit bits are recorded; absent
values are never replaced with zero. Incomplete SMART evidence prevents a
clean completion result.

The report distinguishes:

- verified logical bytes from system I/O activity and unique-LBA coverage;
- expected negative-command rejections from failures of expected-success commands;
- SMART parse completeness, acquisition status and health/counter changes;
- sampled CSW status/residue findings from complete USB capture coverage.

`COMPLETE_WITHOUT_DETECTED_ERROR` is the clean completion result. Warning,
protocol-finding and aborted results require review and return a nonzero exit
status. Read `summary.json` and the associated records rather than treating
elapsed time or the existence of an archive as a pass.

USB captures are bounded samples. The CSW checker detects invalid/phase status
and residue greater than the requested length; it does not identify every
semantic accounting error. It therefore cannot clear the known
[WRITE DMA EXT residue issue](../../docs/patches.md#udma-data-out-and-csw-residue).

## Offline development tests

These commands use fixtures and mocks only:

```bash
python3 -m unittest discover -s tests/hardware/tests -v
python3 run_tests.py --out build/public-validation
```

| Source | Role |
|---|---|
| [ph8057_qualify.py](ph8057_qualify.py) | CLI, target guards, fio workloads, monitors and reports |
| [scsi_protocol.py](scsi_protocol.py) | Bounded read-only SCSI/SAT cases and command classification |
| [usbmon_trace.py](usbmon_trace.py) | Size/time-bounded USB capture and BOT decoding |
| [smart.py](smart.py) | SMART parsing, acquisition diagnostics and attribute comparison |
| [tests](tests/) | Offline regressions and anonymized SMART fixtures |
| [inspect_ahdi_readonly.py](inspect_ahdi_readonly.py) | Optional read-only sector-zero partition inspection |

See [hardware coverage](QUALIFICATION_PLAN.md) for the criteria governing
additional ports, command paths, full-surface claims and targeted UDMA work.
