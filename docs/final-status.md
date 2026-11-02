# Final status — direct answers

Date: 2026-11-02. This status describes the completed offline audit, remediation and prepared release. No hardware commands, SPI write, new hot-plug test or GitHub publication was performed.

## 1. What errors were found in the earlier OEM analysis?

The F8.7 loop was described as at most ten attempts; native execution proves twelve copies after a mismatch and a sticky failure latch. The v16 setup fixture swapped wValue/wIndex. Zero-initialized F2/E7 tests were too narrow to establish overwrite semantics for conditionally preserved state. Return-only F8 callee stubs concealed real register/EA changes. Public byte tables could disclose a serial suppressed in prose. The 33816 total mixed and overlapped different check units. E7.7/5082 was already corrected in v29; that correction was credited, retained and independently revalidated.

## 2. Were all identified fixable OEM issues corrected in code, tables and tests?

Yes. The current decoder, state-transition helpers, native tests, public/private serialization and generated 512-byte/32-bit tables incorporate the identified corrections. The native OEM suite passes 19790 bounded checks. Unknown hardware meanings remain explicitly UNKNOWN/HYPOTHESIS, not reserved. No proven defect in an enabled factory OEM setting justified changing that setting. The optional F8 retry policy is blocked by an unknown controller-window contract rather than silently patched.

## 3. Was original CK_COND v8 correct?

Not completely. Its original hash and historical suites reproduce, but a new native regression shows that it can publish a previously captured good ATA snapshot after either native USB-wait abort exit, if the scheduled finalizer executes. This is a specific control-state defect, not a claim that every v8 path fails or that a physical device was observed running v8.

## 4. What was fixed, and was a new candidate created?

Yes. The revised image adds guarded CBF6/CC04 hooks and FD00/FD08/FD20 code to clear only unpublished validity byte 4E07 on carry-set exits while preserving native retries and error policy. It differs from v8 in 68 actual bytes including CRC/mirror updates. SHA256 is `2aaece707763b5dab32c46cf10c17c88345d73b8635365a354dcffe8817b422b`. Original v8 is preserved byte for byte.

## 5. Was CSW residue 512 fixed?

No qualified firmware fix was established. The native root cause is localized: UDMA Data-Out leaves the CBW length in 55..58, and the CSW path emits it. The previous counter-based prototype is demonstrably unsafe and has been removed from release builders. A safe correction requires a trustworthy processed-byte source with command ownership and error/partial semantics. The supplied UDMA image is trace-only and deliberately retains residue 512.

## 6. Were partial and erroneous transfers verified?

Their bounded software behavior and rejection contracts were tested, including native ATA errors, waiting/stall flags, abort exits, Data-In partial residuals, phase errors and reset/timeout generation checks. That does not qualify real partial Data-Out processing or physical recovery. The missing count and scheduler contracts are explicit. No test forces an unqualified count to become a successful accounting result.

## 7. Are CK_COND and UDMA changes compatible?

Revised CK and the **UDMA observation helper** are compatible within the executed scope. Tests compare live architecture state, sense/status/residue and MMIO events across 72 paired scenarios, plus actual combined-image tests. There is no implemented UDMA accounting fix whose hardware compatibility could be certified.

## 8. Is there one combined candidate?

Yes: `PH8057_CKCOND_REVISED_UDMA_TRACE_ONLY_DO_NOT_FLASH.bin`, SHA256 `825660ce89e77f9fe827d0a34f7c527d155e1726795d093671c9aff38a844163`. It combines the CK abort correction with transparent UDMA observation. It is not a combined SMART+residue fix. Its OEM is unchanged; physical safety remains unqualified.

## 9. Were all historical tests preserved in the unified suite?

All supplied historical files are preserved unchanged in the private archive, and the unified runner replays the reviewed available offline entry points. The 33816 units retain their original expectations and pass with the corrected emulator. Original v8 and earlier standalone suites are retained separately from current tests. There are real gaps: no standalone v9 offline suite is supplied, and v3's original restricted-wrapper source is missing. Its supplied binary permits a labeled reconstruction and wrapper replay: 41 distinct available early cases execute, and all three supplied lab images reproduce exactly. The missing common source's original output log is recovered verbatim, but its 15 executable test cases cannot be claimed as re-run. Obsolete algorithms are not current implementations.

## 10. Is the public GitHub project ready?

The source project, English documentation, scoped licenses/notices, manifests, corrected tools, current tests and offline GitHub Actions workflow are prepared. Vendor BINs, disk-sector payloads, unredacted logs and unit serials are excluded. The source package is ready for review and a separately authorized upload. It has not been published; its Actions workflow has only been exercised through the equivalent local entry point, not on GitHub.

## 11. What remains unproven and why?

The essential open evidence is physical SRAM ownership/aliasing, coherent 6300 completion snapshots, executable code caves/loader behavior, worst-case stack/interrupt timing, safe recovery, native abort/reset scheduler behavior and a command-owned processed-byte quantity for UDMA. Optional F8 peripheral semantics are unknown. Complete READ/WRITE media behavior, UASP and stable hot-swap are not established by bounded code fixtures. Donor redistribution rights and acquisition chains outside the supplied archives are not proven. The missing v3 source cannot be recovered merely by naming its recorded hash.

## 12. What minimum hardware tests are needed for qualification?

First establish independent recovery, CODE loading, exclusive SRAM and stack/IRQ headroom. Then correlate command tag/generation/LUN/port and taskfile snapshots through each CK capture family and both abort exits. For UDMA, establish a safe stable processed-byte contract at completion, then test one full transfer, a genuine partial transfer, ATA errors before/after acceptance, stall, reset/abort/timeout and tag reuse, with CK clear/set. Finally compare ordinary SCSI data on disposable media after prerequisites. Detailed observations and acceptance criteria are in the manual qualification plan. No automatic disk-write/SPI script or hot-plug experiment is included.
