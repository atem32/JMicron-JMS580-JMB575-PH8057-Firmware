# Firmware patches

## Scope and variants

All current builds use exact input hashes and guarded byte replacements. [Firmware layout](firmware-layout.md) lists whole-file identities and checksum rules; [testing](testing.md) gives build commands and separates offline results from hardware observations.

| Variant | Function | Actual byte changes versus full factory | Status |
|---|---|---:|---|
| `ckcond-revised` | Command-owned ATA Return Descriptor plus abort invalidation | 2,607 | **OFFLINE VALIDATED**; corresponding 67,072-byte updater has limited **HARDWARE OBSERVED** SMART success. |
| `udma-trace` | Transparent completion observation points | 27 | **OFFLINE VALIDATED**; hardware **NOT TESTED**; residue unchanged. |
| `combined-revised-trace` | Revised CK_COND plus observation trampoline | 2,618 | **OFFLINE VALIDATED**; hardware **NOT TESTED**; no UDMA accounting repair. |
| CK_COND v8 | Reproducible predecessor used by the abort regression | 2,555 | Regression baseline only; contains the stale-snapshot defect below. |

The 67,072-byte revised updater and the 70,144-byte revised full image share CODE, but have different containers and SHA256 values. Successful updater use does not qualify installation of the full SPI artifact. All patch families remain experimental outside the stated checks. OEM settings are preserved; corrected OEM decoding is documented in the [register map](register-map.md).

## CK_COND and ATA Return Descriptor

### Original defect and current ownership model

Affected stock ATA PASS-THROUGH paths complete without the ATA output registers expected by SAT clients. SMART RETURN STATUS (`B0h/DAh`) and CHECK POWER MODE (`E5h`) therefore cannot reliably report SMART status or HDD standby. The stock vendor protocol-15 getter reads the **current** register bank and CDB EXTEND bit; it is not a saved result belonging to an earlier command.

The implementation in [core_patch.py](../tools/patching/ckcond/core_patch.py), [capture_wrappers.py](../tools/patching/ckcond/capture_wrappers.py) and [sense_patch.py](../tools/patching/ckcond/sense_patch.py) associates the descriptor with the serialized BOT command:

| Boundary | CPU address | Implemented behavior |
|---|---|---|
| BOT admission | `7C40` | Invalidates active context and the selected LUN's obsolete descriptor; REQUEST SENSE preserves a pending descriptor. |
| SAT normalization | `229E` | Records SAT12/SAT16 opcode, accepted protocol, LUN, tag equality, CK_COND, EXTEND and ATA command after native normalization. |
| Common launch | `8CA3` | Invalidates the preceding unpublished attempt; accepts only known return PCs, taskfile pointers, protocol classes and ownership. |
| Capture | Separate hooks below | Saves family-specific status/error and taskfile bytes, checking command and selected port before and after the snapshot. |
| CSW finalization | `94F9`, hook `9503` | Publishes only when saved ATA outcome, native status and pending sense agree. Leaves residue unchanged. |
| REQUEST SENSE | `C320` | Uses a matching per-LUN saved descriptor, native key/ASC/ASCQ mapping and native allocation-length clamp; otherwise uses native fallback. |

The capture sources are intentionally distinct:

| Family / hook | Status and error source | Additional condition |
|---|---|---|
| Non-data / `9837` | Completed taskfile `R6:R7 + 0Dh/+0Eh`, written at `9824..9836` | Does not reread a later live B9 value. |
| PIO-in / `970D` | XDATA `4B31/4B32` | `6346.bit5` transport error invalidates the result before native `82B8`; a matching numeric sense selector alone cannot authorize ATA attachment. |
| PIO-out / `B37B` | SFR `B9` and XDATA `7097` | Preserves native `B3C4` accounting call. |
| Main DMA / `735F`; alternate DMA / `9EB2` | SFR `B9` and XDATA `7097` | Preserves the displaced native status-test instructions. |

Descriptor slots are at XDATA `4D00..4DFF`, active state at `4E00..4E1F`, with unpublished-valid byte `4E07`. These are explicit, unqualified SRAM allocations. The implementation has one global active command, not a UAS tag table. Software checks and interrupt masking do not prove exclusive SRAM ownership or an atomic hardware taskfile snapshot.

Native sense selector `28h` is an internal pending-sense value, not a SCSI sense key or descriptor length. A good ATA result with CK_COND=1 legitimately yields CHECK CONDITION with an ATA Return Descriptor; BOT CSW failure status in that case is not evidence of ATA failure. Native ATA error mapping is retained. Finalization rejects BSY/DRQ snapshots and leaves phase-error handling to stock firmware.

### Revised abort invalidation

v8 captures at `735F` **before** Data-Out executes `7377 → AEF4 → CBE3`. CBE3 first waits for `5052.bit0`, then for `A3.bit7` to clear. Its helper `E140` returns carry set when `9F.bit2` is clear. Both native carry-set exits returned without clearing v8's `4E07=A5`:

| Wait | Native exit | Carry-clear retry | Revised hook |
|---|---|---|---|
| `5052.bit0` | `CBF6: JNC CBE3; CBF8: RET` | `CBE3` | `CBF6..CBF8`: `50 EB 22 → 02 FD 00` |
| `A3.bit7` | `CC04: JNC CBF9; CC06: RET` | `CBF9` | `CC04..CC06`: `50 F3 22 → 02 FD 08` |

AEF4 preserves the carry. Its caller can schedule `94F9` without branching on that carry; if finalization runs, v8 can publish the pre-abort snapshot. The outer reset scheduler might cancel that finalizer on hardware, so the regression deliberately tests a **conditional finalizer**, not observed post-reset CSW emission.

[abort_guard.py](../tools/patching/ckcond/abort_guard.py) places dispatchers at `FD00..FD07` and `FD08..FD0F`. Carry clear follows the original retry; carry set tail-jumps to `FD20..FD3E`, which clears **only `4E07`**. The leaf saves IE, A, DPS and physical DPTR0, masks CPU interrupts for the write, and restores IE last. It preserves carry/AC/OV, register-bank selection, B, all Rn, physical DPTR1 and the original caller's return address. Its five saved stack bytes introduce no additional nested call.

Relative to v8, the five records span 53 CODE bytes, of which 52 change; 16 CRC/mirror changes make **68 actual byte differences**. Exact records are generated from source and checked against the [revised record file](../firmware/ph8057-device/modified/ckcond_revised_patch_records.json). CPU addresses translate using the selected container's CODE offset.

The native regression in [test_native_paths.py](../tools/patching/ckcond/tests/test_native_paths.py) executes the original launch/completion/wait/finalizer instructions across both abort exits, CK_COND clear/set and ATA success/ERR/DF. In the 512-byte good-ATA, CK_COND=1 abort fixture:

| Conditional result | v8 | Revised |
|---|---:|---:|
| Unpublished validity / published descriptor marker | `A5 / A5` | `00 / 00` |
| Pending sense selector | `28h` | `00h` |
| CSW status if finalization runs | 1 | 0, preserving stock policy |
| Residue | 512 | 512 |

The revision repairs stale descriptor publication. It neither certifies stock's conditional GOOD status after abort nor changes UDMA accounting. Normal error/sense policy, retries and residue are preserved.

### Physical scope

The owner reported installing updater package SHA256 `f8406e8b83e9f97695ce4ae395a90b29e28d8210bc40c09087f3f6b43f33fd5b`. On one WD disk, SMART RETURN STATUS returned `ERR=00, SC=00, LM=4F, LH=C2, STS=50`; CHECK POWER MODE returned `ERR=00, SC=FF, STS=50` with an ATA Return Descriptor. `SC=FF` demonstrates ACTIVE/IDLE in that transaction, not a measured standby transition. Both abort paths, full SAT12/SAT16/error coverage and interrupt/reentrant behavior remain unqualified physically. [Testing](testing.md#hardware-evidence) records provenance, later two-disk workloads and the missing readback.

## UDMA Data-Out and CSW residue

### Preserved wire evidence

The [owner-supplied BOT excerpt](../research/usb/supplied_bot_excerpt.json) contains:

```text
CBW  55534243fa0d00000002000000011085170600000001001000000001403500
CSW  55534253fa0d00000002000000
Data-Out completion reported: length=512, usb_status=0
```

The strict [decoder](../tools/patching/udma/bot_evidence.py) identifies tag `0x00000DFA`, LUN 1, a 512-byte Data-Out request and ATA PASS-THROUGH(16): protocol 11, EXTEND=1, CK_COND=0, T_DIR=0, BYT_BLOK=1, T_LENGTH=2, WRITE DMA EXT `35h`, sector count 1. The matching CSW has status = 0 and residue = 512, implying zero processed bytes despite the separately reported 512 successful USB bytes.

A complete raw usbmon capture is unavailable in this repository. The older SG_IO observation also reported residue = 512, but its `actual_bytes=0` was calculated from requested length minus residue. It is not an independent USB measurement. Matching readback/no-error observations came from the owner; a same-data readback alone does not prove physical media rewriting.

BOT Data-Out residue means host-requested bytes **minus device-processed bytes**; phase-error residue is ignored. USB completion, ATA-good status and processed-byte accounting must remain distinct ([BOT specification](references.md)). No data corruption or identical defect in every ordinary SCSI WRITE path is established by this observation.

### Native command chain

All addresses refer to CODE in the exact full factory image.

| Stage | CPU addresses | Evidence |
|---|---|---|
| CBW | `7BF4..7C47` | Copies little-endian `7988..798B` into IRAM `58,57,56,55`; programs `5040..5043`, direction bit `12h` and mapped port context `417F`. |
| SAT16 | `222B`, table after `22A4`, `23E5`, `247A..248F` | Protocol 11 selects state `59h=67h`; taskfile is copied to `4B24..4B38`. |
| SAT length | `7D61`, `A203` | Derives request quantity at `4C16..4C19`; arithmetic-interface behavior is an explicit fixture premise. |
| BOT dispatch | Table after `380D`, `385A` | State `67h` takes the DMA path; the supplied Data-Out mapping selects `C789`. |
| SATA launch | `C789..C7B5`, `8CA3..8CF7` | Programs length `6318..631B`, taskfile `6300..630B`, command `6302=35h`, port `6312`, command-FIS marker `6313`. No `70B6` operation establishes a UDMA count here. |
| Completion | `7308..73A8` | Requires completion conditions and D2H marker `6313=34h`; `735F` tests `(B9 & E1h)==40h`, which excludes BSY/DF/ERR but does not test DRQ. |
| State-specific accounting | `7367..7375` | Only state `59h=64h` clears `55h..58h` directly. |
| UDMA completion | `7377..737B → AEF4..AF3F` | State `67h` runs `CLR A; MOV R7,A; LCALL AEF4`. Data-In copies SFR `AC..AF`, masking `AF` with `3Fh`; Data-Out branches to `AF25 → CBE3` without updating residue. |
| USB wait | `CBE3..CC08` | Waits on `5052.bit0` and `A3.bit7`, handles `50E2`, returns carry clear at `CC07` or carry set through either `E140` abort exit. |
| CSW | `94F9..9564`, residue copy `9529..953A` | Copies tag `7984..7987`; serializes `58,57,56,55` at CSW offsets 8..11; derives status from `5Ah`, or phase error for state `0Dh`. |

The original-instruction replay in [test_udma.py](../tools/patching/udma/tests/test_udma.py) reaches the exact supplied CSW with residue = 512 unchanged from admission. No firmware-function substitutions are used in that staged chain; LUN tables, peripheral samples and arithmetic-interface behavior are declared fixtures. The executor does not move real payloads or run the complete asynchronous scheduler.

### Why the rejected clearing prototype is unsafe

`70B0..70BD` and `70C0..70C5` are consistent with an arithmetic/compare interface, not a demonstrated always-live UDMA byte counter. Native timer code `9711..977A` compares bounds 600/288000; PIO code `C7C5 → D1D7 → B3C4` supports chunk subtraction such as `512−128−384=0` and `512−255−256=1`; `A203 → E0CA` converts sectors to bytes. The [atlas](register-map.md) retains operation hypotheses and exact references. A result zero has no UDMA meaning without an operation and ownership contract establishing it.

The previous helper called AEF4, then cleared residue when later USB flags looked ready and `70C0..70C3` read zero. The negative regression [unsafe_prototype_fixture.py](../tools/patching/udma/unsafe_prototype_fixture.py) demonstrates:

1. `5052` first reads 0; `E140` sees `9F.bit2=0`, so CBE3 exits at `CBF8` with carry set.
2. AEF4 returns with carry intact; the helper ignores it.
3. A later `5052=1` and unqualified result zero satisfy the helper, which erases residue = 512 after the abort.

This is an instruction-level counterexample under stated sample timing. The unsafe helper is retained only as an in-memory negative fixture and has no supported image builder.

A correct repair needs a stable processed-byte quantity `P` attributable to the active command: source address/event, width, byte order, units, lifetime, latch/reset behavior and partial/error semantics. It must compute bounded `H−P` while preserving transport status and sense independently. [accounting_contract.py](../tools/patching/udma/accounting_contract.py) rejects unqualified/stale counts and reset, abort, timeout, stall or phase-error updates; it is a regression contract, not an implemented firmware repair.

### Observation-only trampoline

[trace_patch.py](../tools/patching/udma/trace_patch.py) makes exactly these CODE edits:

| CPU range | Replacement |
|---|---|
| `7377..737B` | `E4 FF 12 AE F4 → 12 E7 00 00 00` |
| `E700..E707` | Zero cave → `E4 FF 12 AE F4 00 00 22` |

The original jump at `737C..737D` remains. Observation PCs are `E700` before completion and `E705` after it. The helper adds no MMIO reads, persistent RAM, residue/status/sense writes or on-device logging channel; it adds a two-byte nested call frame. Observing those PCs on hardware would require a separately qualified debugger or mechanism.

Offline compatibility compares live IRAM, SFRs, both DPTR banks, fixture XDATA and MMIO events for each base with/without trace. It covers full/partial Data-In, successful and failed ATA results, pending/stall/abort paths, phase errors, CK_COND settings and the actual combined image. The trace preserves revised abort invalidation, including the seven-byte combined stack increment described in [architecture](architecture.md).

**The trace and combined variants retain the known UDMA residue defect.** No `udma-fix` artifact exists, and zero anomalies in later sampled usbmon monitoring do not change this result.
