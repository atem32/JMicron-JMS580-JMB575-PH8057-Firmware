# Firmware validation report

Date: 2026-11-02. All modified images are **EXPERIMENTAL — DO NOT FLASH**. No candidate was installed or executed on PH8057 hardware in this task. The factory hardware observations were supplied by the owner and remain separate from this offline work.

## Compared images

Every full image below has 70144 bytes. OEM file 11000..111FF is identical across all variants.

| Image | SHA256 | Actual changed bytes vs stock | Verdict |
|---|---|---:|---|
| Factory complete |`ef5ad9af3f3b290c565a4dc65933d539b7bb8b8051ac9bd45386932a77862c09`|0|Immutable base; known UDMA accounting defect |
| Original CK_COND v8 |`4b7ac3e5bd124d8e44281e9aa79b7b65f7b62c54410ffd1abd8af4a586d74e11`|2555|Exact reconstruction; newly exposed abort-snapshot defect |
| Revised CK_COND |`2aaece707763b5dab32c46cf10c17c88345d73b8635365a354dcffe8817b422b`|2607|Instruction-level abort invalidation fixed; hardware unqualified |
| Factory + UDMA trace |`a4bf69164548003a26efebcb3f5fd6e59d0dfc3321eeda2ffb97d6e36ba63712`|27|Observation only; residue 512 intentionally retained |
| Revised CK + UDMA trace |`825660ce89e77f9fe827d0a34f7c527d155e1726795d093671c9aff38a844163`|2618|Combined bounded behavior verified; no UDMA accounting repair |

There is no qualified **stock+UDMA fix** or **CK+UDMA fix** image. The requested four-way concept is evaluated using the available trace-only variant, explicitly labeled, and extended to original v8 and revised CK. A name or green test cannot turn an unqualified accounting algorithm into a release fix.

## Exact new CODE edits

The original v8 remains unchanged. Relative to v8, the revised patch adds these guarded ranges:

| CPU range, inclusive | Full-image range, inclusive | Before → after |
|---|---|---|
|CBF6..CBF8|0DBF6..0DBF8|`50 EB 22` → `02 FD 00`|
|CC04..CC06|0DC04..0DC06|`50 F3 22` → `02 FD 08`|
|FD00..FD07|10D00..10D07|Zero cave → `40 03 02 CB E3 02 FD 20`|
|FD08..FD0F|10D08..10D0F|Zero cave → `40 03 02 CB F9 02 FD 20`|
|FD20..FD3E|10D20..10D3E|Zero cave → context-preserving validity-clear leaf below |

```text
C0 A8 C2 AF C0 E0 C0 86 75 86 00 C0 82 C0 83
90 4E 07 E4 F0
D0 83 D0 82 D0 86 D0 E0 D0 A8 22
```

The conditional trampolines preserve the original retry branches on carry clear. Carry set enters the leaf, which saves IE, disables EA, saves A/DPS/current physical DPTR0, clears 4E07, restores the saved state and returns using the original caller frame. It introduces five temporary saved bytes and no new nested call. New patch ranges cover 53 CODE bytes, of which 52 actually differ; the zero DPTR-select immediate was already zero. Along with 16 changed CRC/mirror bytes, v8→revised has 68 actual byte differences.

The UDMA observation edits, relative to factory or revised CK, are:

| CPU range | File range | Before → after |
|---|---|---|
|7377..737B|08377..0837B|`E4 FF 12 AE F4` → `12 E7 00 00 00`|
|E700..E707|0F700..0F707|Zero cave → `E4 FF 12 AE F4 00 00 22`|

The original 737C branch is preserved. E700 and E705 are the pre/post-completion observation PCs. The helper makes no additional MMIO read, allocates no persistent RAM, and does not assign residue/status/sense. Its extra call frame uses two bytes. In the combined abort path that frame coexists with the five-byte CK leaf frame: seven additional bytes before interrupt nesting relative to original v8 on the corresponding abort path, or two additional bytes relative to revised CK alone.

The revised candidate has 32 guarded CODE records; combined has 34. The combined image has 82 actual contiguous diff ranges versus stock. Full original-v8 edits, cave lengths, CPU/file offsets and every before/after byte are in `firmware/manifests/*_manifest.json`; the concise table above only lists the new audit corrections and observation helper.

## Integrity and reproducibility

| Variant | Header CRC | Metadata CRC | CODE CRC | Full CRC / mirror |
|---|---|---|---|---|
|Original v8|698135A8|19FF89C9|D042940A|C52EF5E7|
|Revised CK|698135A8|2426F5E2|46FFB024|FAA494BF|
|UDMA trace|698135A8|C8ABCF58|278995AD|95406CEB|
|Combined revised+trace|698135A8|A9A6EC9D|711625A8|4037893B|

Two CRC formulations agree. All builders require the exact stock SHA, reject modified hooks or occupied caves, reject overlap/trailer crossing and preserve the OEM. The combined builder applies both patch sets once to stock and updates integrity fields once. Its executable bytes equal revised CK plus the observation overlay. A separate reviewer rebuilt the combined image from its 34 manifest records and independently confirmed its hash, offsets, diff ranges and OEM equality.

## Behavioral comparison

| Scenario | Stock | Original v8 | Revised CK | Trace variants |
|---|---|---|---|---|
| Successful ATA, CK=0 | Native policy | Cached-result machinery preserves native status policy | Same bounded result | Same as respective base |
| Successful ATA, CK=1 | Missing/inadequate saved descriptor in affected paths | Corrected descriptor/sense path under accepted fixtures | Same normal result | Same as respective base |
| Native USB-wait abort after good ATA capture | Native handling; no patch slot | Can leave 4E07 valid and conditionally publish sense 28 | Clears 4E07, preventing that publication | Observation preserves each base's result |
| ATA ERROR | Native mapping | Native mapping retained, with owned descriptor where valid | Error/sense policy retained by abort fix | Same as respective base |
| Confirmed UDMA OUT512 fixture | GOOD/residue 512 | Residue 512; CK1 can change sense/CSW status | Residue 512; abort stale-sense suppression fixed | Residue 512 remains |
| Data-In full/partial fixture | Native masked SFR residue | Preserved | Preserved | Preserved |
| Partial/error/reset/timeout accounting | No universally established OUT processed count | No new accounting contract | No new accounting contract | Cannot be called repaired |
| Ordinary READ/WRITE admission and shared sense | Reference | Compared within bounded hooks | Compared within bounded hooks | Native state/event equivalence checked |

The 72 paired UDMA comparisons cover 24 scenario definitions across stock, original v8 and revised CK. The full-image combined test additionally executes 24 scenarios and matches its reference overlay. Live IRAM, modeled SFRs, dual DPTRs, fixture memory and MMIO events are compared on returned paths. This is stronger than a no-overlap check but remains conditional on the peripheral fixtures.

Hardware partial transfers, actual disk processing, real stalls/resets/timeouts, code-cave execution, SRAM ownership, atomic capture and ISR timing remain unqualified. The independent abort regression conditionally runs the scheduled finalizer; it does not assert that physical firmware necessarily emits a CSW during reset.

## Release disposition

Original v8 and all new BINs are private research artifacts. Public distribution contains the guarded builders and manifests, not vendor-derived images. The earlier unsafe UDMA residue-changing prototype has no release image builder and is retained only as a negative in-memory test.

No image is declared safe to flash. The remaining prerequisite evidence and smallest useful hardware matrix are specified in `tests/hardware/QUALIFICATION_PLAN.md`. A successful offline reconstruction is a prerequisite for review, not an installation authorization or hardware qualification.

## Post-audit owner hardware check (2026-11-02)

After completion of this offline report, the owner flashed the 67,072-byte updater-style package derived from revised CK_COND. The controller enumerated after a power cycle and produced a successful CK_COND ATA Return Descriptor for `SMART STATUS` and `CHECK POWER MODE` on one WD disk via OMV. See [`postflash-hardware-check-2026-11-02.md`](postflash-hardware-check-2026-11-02.md). This evidence validates only those two transactions; it does not amend the UDMA verdict or qualify abort/reset/LUN/data integrity. Earlier "no candidate installed" statements above refer solely to the pre-flash independent audit.
