# Known issues

## UDMA / BOT CSW residue

**Confirmed defect; no fix implemented.** A WRITE DMA EXT transaction requested
512 bytes, completed 512 USB Data-Out bytes with `usb_status=0`, and returned
CSW status 0 with residue 512. The
[wire excerpt](../research/usb/supplied_bot_excerpt.json),
[decoded evidence and native execution chain](patches.md#udma-data-out-and-csw-residue)
retain the exact command, addresses and regression.

The Data-Out path `7377 → AEF4 → CBE3` leaves software residue at
IRAM `55h..58h` unchanged; CSW construction at `9529..953A` copies that value.
A correct repair needs a stable, command-owned count of **device-processed
bytes**, with defined partial-transfer, error and recovery behavior. Merely
clearing residue after USB completion or reading zero from the unqualified
`70C0..70C3` arithmetic window is unsafe; executable counterexamples are
retained.

Zero anomalies in the three workload summaries do not resolve this targeted
pass-through defect. The observation alone also does not establish data
corruption or an identical problem on every ordinary SCSI WRITE path.

## UASP / NCQ

**Not implemented; no safe patch is supplied by this project.** OEM `E7.6`
gates a UAS descriptor path at `44C4`; native code at `6F57` and `46ED` can
clear the flag. Exposing descriptors does not establish a usable concurrent
command path. The current CK_COND state follows serialized BOT ownership.

A complete implementation requires tag/port ownership, independent completion
and result storage, task management, endpoint/stream handling and coordinated
abort, reset and queue flushing across JMS580 and JMB575. NCQ concurrency is
not established by ordinary BOT tests or the port multiplier's generic
FIS-switching capability. See [architecture](architecture.md#uasp-ncq-and-hot-swap-boundaries)
and the [related-controller research](references.md#related-controller-work)
for the concrete findings and cross-disk concurrency counterexample.

## Hot-swap

**Not fixed.** HDD removal has caused USB disconnect and re-enumeration,
affecting access to the enclosure's other drives. Discovery compacts the
LUN-to-port list, so removal can also change the disk behind a LUN.

The available instruction paths do not distinguish firmware detach policy
from a power, reset or link cause. Stable hot-swap needs established slot
identity, absent-LUN behavior, cache/sense invalidation and per-port recovery.
The exact discovery/event addresses are retained in
[architecture](architecture.md#port-discovery-and-lun-mapping).

For the boundaries of the completed tests and the evidence needed to extend
them, see [testing](testing.md#hardware-evidence) and
[hardware coverage](../tests/hardware/QUALIFICATION_PLAN.md).
