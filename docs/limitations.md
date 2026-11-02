# Known limits, UASP and hot-swap

## UASP — NOT IMPLEMENTED

OEM E7.6 gates a UAS descriptor path at 44C4, but code at 6F57 and 46ED clears the live flag under additional conditions. Advertising a descriptor is not an implementation of command-tag ownership, concurrent completion, task management or multi-LUN routing. The current CK_COND design explicitly assumes serialized BOT and one active command context.

The external [9500/ds500u3-jms567-uas](https://github.com/9500/ds500u3-jms567-uas) project was inspected at commit `743529e7a29febf501cc187b96f3691905ed3245`, including its README, firmware-analysis notes, test log and LICENSE. Author9500 licenses the repository's authored scripts/docs under MIT and explicitly excludes its vendor-derived firmware from that grant. No external UAS patch was copied into PH8057.

That project is a JMS567 plus JMB575 experiment on a different enclosure. Its recorded progression includes multi-LUN disk aliasing after initial UAS enablement, a subsequent port-mapping fix, per-disk NCQ success, and a later cross-disk concurrency hang. Those are useful counterexamples to flag-only enablement, not JMS580 qualification. Its observed limits also do not prove that JMB575 silicon lacks FIS switching: the [manufacturer's product brief](https://www.jmicron.com/file/download/1058/JMB575.pdf) explicitly describes command-based and FIS-based switching. Board firmware, bridge scheduling and actual controller capabilities must be distinguished.

A PH8057 UASP implementation would require a tag-indexed command/ATA-result store, stable LUN-to-port mapping for all exposed drives, including the fifth bay if supported and enumerated, task management for abort/reset, per-port and per-tag errors, sense association across concurrent commands, NCQ scheduling and completion ownership, queue flushing, endpoint/stream handling, and verified recovery. CK_COND's current global active state and UDMA's unresolved accounting cannot simply be reused under parallel UAS. These changes are outside this release.

## Hot-swap — NOT IMPLEMENTED

The verified discovery loop compacts successfully detected ports into a LUN list at 459C. Native GET_MAX_LUN and CBW admission consume that mapping. Rebuilding a compact list after removal can change which disk appears behind an existing LUN. A safe stable-slot design needs a persistent port-to-LUN identity, explicitly absent LUN behavior, cache/IDENTIFY/SMART invalidation, queued-request cancellation, and per-port recovery rather than global ambiguity.

SCSI behavior would need to distinguish absent media, not-ready transitions and unit-attention events for changed configuration. REQUEST SENSE must return the error belonging to the affected LUN and command generation. Reconnection cannot inherit a previous disk's descriptor, capacity or cached sense. A blanket suppression of reset/re-enumeration is therefore not a justified patch.

The supplied historical reports describe complete USB disconnect/re-enumeration during removal, including three recorded disconnect observations and a separate reset/timeout observation. This audit preserves that evidence but does not independently measure the power rail, reset line, PHY or link. Possible causes include enclosure power behavior, bridge reset, link faults and firmware detach/recovery policy; no single cause is established by the instruction snippets alone.

No hot-swap implementation or new hot-plug experiment was performed. If a future project reopens that scope, it needs externally synchronized power/reset/link/host traces to distinguish those causes before changing event handling. The current qualification plan does not ask the reader to remove drives while active.

## Firmware qualification boundaries

| Unknown | Why it matters | Smallest useful new evidence |
|---|---|---|
| SRAM ownership and aliasing of 4D00..4DFF/4E00..4E1F | CK state could collide with an ISR, DMA engine or untraced function | Approved memory map or command/interrupt lifetime traces establishing exclusive use |
|6300 register-window ownership and atomicity | Double-checking software port state does not prove a coherent ATA taskfile snapshot | Correlated command/LUN/port snapshots at each capture family |
| Code-cave/loader behavior and flash recovery | File zeros and valid CRCs do not guarantee executable storage or rollback | Independent loader/SPI/recovery qualification before modified code executes |
| Stack/interrupt headroom | Revised abort leaf adds5 bytes; trace call adds2, for 7 cumulative bytes on the combined abort path before ISR nesting | Worst-case stack watermark and interrupt preemption measurements |
| UDMA processed-byte quantity | Residue requires H−P, including partial/error/recovery | Stable, command-owned count or documented completion event with exact accounting semantics |
| Native abort/reset scheduler | Conditional finalizer replay does not prove real post-reset CSW emission | Trace from reset/abort trigger through canceled or emitted CSW and later command admission |
| Optional F8 controller windows | Software retry semantics are known but their intended physical policy is not | Window operation contract, idempotence and completion/error evidence |
| Full SCSI data plane | Shared-state regressions do not execute real media transfers | Later controlled disposable-media comparisons after firmware prerequisites are established |

The reference accounting contract rejects unqualified/stale counts and abort/reset/timeout updates. It is a design constraint and regression oracle, not an implemented transport fix. Tests that run to an instruction limit model a pending loop, not real elapsed timeout. The executor provides no cycle-accurate timing or autonomous peripheral activity.

The issue registry in `research/findings/` and the final audit report use **FIXED**, **PARTIALLY FIXED**, **NOT REPRODUCED** and **BLOCKED BY HARDWARE EVIDENCE**. These issue states are separate from the evidence-status vocabulary in README.
