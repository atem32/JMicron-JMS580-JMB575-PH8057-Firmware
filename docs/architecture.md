# Architecture and command ownership

The owner identifies the PH8057 as a **five-bay enclosure**, with a JMS580 bridge upstream of a JMB575 port multiplier. Four HDDs were present in the supplied OMV enumeration; the fifth bay's drive discovery, LUN routing, and actual operation remain unverified by this project. JMicron's [JMS580 product brief](https://www.jmicron.com/file/download/1053/JMS580.pdf) describes the USB-to-SATA bridge; its [JMB575 brief](https://www.jmicron.com/file/download/1058/JMB575.pdf) describes a one-to-five SATA port multiplier supporting command/FIS switching. Those generic capabilities do not prove a particular PH8057 firmware feature is enabled or correct.

## Address spaces

The 8051 CPU executes 64 KiB CODE. Direct addresses below80h select lower IRAM; direct addresses80h and above select SFRs. Indirect `@R0/@R1` access can address upper IDATA. Bit addresses are a separate namespace. XDATA contains firmware RAM and memory-mapped peripherals, which the offline executor requires fixtures to distinguish. The board's actual RAM ownership and peripheral side effects are not inferred from zero-filled file regions.

The dual-DPTR fixture uses SFR 86.bit 0 to select the physical82/83 or 84/85 pair for DPTR instructions. Direct instructions still address the named SFR. This matches the supplied code's exercised ABI; it is explicitly an execution fixture, not a complete JMicron CPU manual. There is no autonomous DMA, timer, USB PHY, SATA PHY or interrupt-delivery model.

## Serialized BOT ownership

The native CBW parser at `7BF4..7C47` reads the transfer length, direction and LUN from `7988..798D`. The command tag remains at `7984..7987` for the CK admission hook and later CSW copy through `9503 → 800A`. It initializes software residue in IRAM 55..58. The physical port is obtained from the firmware's current LUN mapping, not by assuming LUN equals SATA port. Native SAT parsing and BOT dispatch choose taskfile and data paths, and common launch code programs the 6300 register window. The scheduled completion handler and finalizer later produce sense and CSW.

CK_COND preserves this serialization model. It stages one active command at 4E00 and per-LUN pending descriptors at 4D00. The design tracks LUN, tag equality, command/protocol, port ownership and result validity. It does not establish a general UAS tag table. Before arming each new launch it invalidates the preceding unpublished attempt, and REQUEST SENSE consumes only a matching saved descriptor. These software guards improve attribution but cannot by themselves prove SRAM exclusivity or coherent peripheral-bank reads.

The revised abort helper clears only 4E07 after a native CBE3 carry-set return. It preserves the original status, residue and retry branches. The UDMA observation helper adds one nested call frame but no persistent state. Its post-completion PC sees the native carry, so it is useful for the new bounded abort regression. The trace call frame remains live while the revised abort leaf executes, so their extra stack use can total seven bytes before interrupt nesting. Both helpers remain unqualified for physical stack/interrupt timing.

## Port discovery and LUN mapping

Original code at 04DA..064B scans candidate ports. On the inspected successful-port branch at 05B6..05CF, the current port458C is appended at 459C+4595 and 4595 is incremented. C75C..C788 copies mapping information into per-LUN hardware-facing locations starting at 7A06. D1F4 derives a maximum LUN from the detected count, bounded to the implementation's representable range. D896 returns the mapped port in R7; instructions at 7C43..7C47 then store it at 417F, the selected port context.

This is a compact discovery list. For an illustrative map `[1,2,3,4]`, removing port2 and rebuilding a compact list `[1,3,4]` would change the device behind LUN1. That example explains why stable hot-swap needs explicit slot identity; it is not a new physical experiment or a guarantee about a particular tray numbering.

GET_MAX_LUN uses the correct decoded setup-field representation: wValue atIRAM1A/1B, wIndex at 1C/1D and wLength at 1E/1F, high byte first internally. D970 recognizes the request and C702 applies further validation. USB wire words are little-endian; the internal arrangement is different. The corrected asymmetric tests expose the historical field-name swap.

Event code0709..073D compares459B with 4595 under further guards involving4592 and 4180, and can set bit 06 plus 4590. The exact temporal meaning of 459B is not proven; it must not be described as a previous-drive-count register merely from that comparison. At 27FB..2820, a pending event with F3.0 clear can schedule4161=3; an interrupt-side path near8FFD has related behavior. These observations explain software re-enumeration candidates but do not isolate the cause of a full electrical USB disconnect.

## Data paths and unresolved hardware contracts

For the supplied protocol11 Data-Out command, native dispatch reachesC789, programs SATA length at 6318..631B, and later reaches7308→AEF4→CBE3. The software residue is not decremented on this branch. The Data-In branch instead copies a masked SFR residual quantity, and PIO paths use the 70B*/70C* arithmetic interface. Register use in one of these contexts does not establish equivalence in another.

The new UDMA replay stages real instructions across these boundaries with explicit fixture values. It is not a complete boot-to-host scheduler simulation. After native completion schedules94F9, tests may execute that finalizer conditionally; an outer reset scheduler could cancel it on real hardware. The complete behavior of abort, bus reset and timeout must be measured before claiming any device-level transport correction.

See [UDMA accounting](udma-csw-residue.md), [CK_COND](smart-ckcond-fix.md), [OEM](oem-reference.md) and [limitations](limitations.md) for the instruction evidence and qualification boundaries.
