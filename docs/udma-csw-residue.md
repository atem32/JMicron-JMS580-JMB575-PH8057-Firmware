# PH8057 UDMA Data-Out: CSW residue audit

Date: 2026-11-02. Scope: local firmware files, supplied historical evidence, and explicitly modeled 8051 execution. No USB, SATA, block-device, SPI, or hot-plug operations were performed.

## Result

The original firmware preserves the CBW transfer length in `IRAM 55h..58h` on the successful ATA PASS-THROUGH UDMA Data-Out path, then emits that unchanged value as the CSW residue. A new staged execution of the original instructions, beginning with the actual CBW fields and continuing through SAT decoding, SATA taskfile programming, completion handling, and CSW assembly, reproduces the supplied 512-byte residue exactly. This is a stronger reproduction than starting with a manually selected completion state.

The earlier `70C0..70C3 == 0` residue-clearing prototype is rejected. Contextual instruction evidence supports a hardware arithmetic/compare interface as a much stronger explanation of these registers than an always-live UDMA byte counter. A new native failure-path regression also demonstrates that the prototype can clear residue after the original USB wait has returned its inactive/abort indication.

**There is no qualified firmware correction for UDMA byte accounting in this deliverable.** The supplied candidate is a transparent observation trampoline named `PH8057_UDMA_TRACE_ONLY_DO_NOT_FLASH.bin`. It retains the known residue defect. Its purpose is to make the original completion entry and exit inspectable without inventing a persistent RAM allocation or an MMIO counter. The revised CK_COND component separately corrects consumption of a stale ATA capture after the native wait aborts; that correction does not establish a processed-byte count.

## Evidence and provenance

The complete stock image has 70,144 bytes and SHA256:

`ef5ad9af3f3b290c565a4dc65933d539b7bb8b8051ac9bd45386932a77862c09`

Its 8051 CODE occupies full-image offsets `0x01000..0x10FFF`. Every CPU address in this report therefore maps to a full-image file offset by adding `0x1000`. The final OEM/NVRAM area is `0x11000..0x111FF`.

The original experimental CK_COND v8 image has SHA256:

`4b7ac3e5bd124d8e44281e9aa79b7b65f7b62c54410ffd1abd8af4a586d74e11`

The revised CK_COND image used for additional compatibility checks has SHA256:

`2aaece707763b5dab32c46cf10c17c88345d73b8635365a354dcffe8817b422b`

Three kinds of evidence must remain distinct:

| Source | What it establishes | Limit |
|---|---|---|
| Archived v11.3 `stock_v11_3_test/probe.json` | SG_IO reports status 0, requested 512 bytes, residue 512 for the specified ATA command | It stops after this result and contains no raw USB CSW. Its `actual_bytes=0` field is calculated from residue; it is not a USB observation. The recorded write-payload hash differs from the saved original-sector hash. |
| Later user-provided USB/BOT excerpt, also repeated in the supplied reassessment report | A matching CBW/CSW tag, 512 successful USB Data-Out bytes, CSW status 0 and residue 512 | A complete usbmon capture was not supplied in these inputs. The accompanying matching readback and lack of errors are user-provided observations. A same-data write/readback alone does not prove physical media rewriting. |
| New offline native replay | The original instructions can produce exactly that CSW under the declared peripheral samples | It does not measure the hardware, transfer payloads, model interrupt timing, or validate a flash image on the controller. |

The later raw excerpt is:

```text
CBW  55534243fa0d00000002000000011085170600000001001000000001403500
CSW  55534253fa0d00000002000000
Data-Out completion: length=512, usb_status=0
```

The strict local decoder reports:

| Field | Value |
|---|---:|
| CBW length / CSW length | 31 / 13 bytes |
| Matching command tag | `0x00000DFA` |
| CBW transfer length | 512 |
| Direction / LUN | Data-Out / 1 |
| CDB | ATA PASS-THROUGH(16), `85h` |
| SAT protocol / EXTEND | 11 / 1 |
| CK_COND / T_DIR | 0 / 0 |
| BYT_BLOK / T_LENGTH | 1 / 2 |
| ATA command / sector-count register | WRITE DMA EXT `35h` / 1 |
| USB completed bytes | 512 |
| CSW status / residue | 0 / 512 |
| Device's implied processed-byte claim | 0 |

The BOT specification defines meaningful Data-Out residue as host-requested bytes minus bytes processed by the device. USB transfer completion is therefore insufficient by itself to manufacture the processed-byte quantity. For a phase-error CSW, the residue is ignored. The evidence decoder follows these distinctions and never rewrites a CSW or overrides SG_IO results. See [USB Mass Storage Class Bulk-Only Transport 1.0](https://www.usb.org/sites/default/files/usbmassbulk_10.pdf), sections 2.2, 5.2, and 6.7.3.

## Reconstructed native data flow

`build/udma_native_disassembly.txt` contains the relevant original instruction listings. `build/udma_audit_results.json` records the exact guards, stages, observations, and fixture assumptions.

| Stage | CPU addresses | Native behavior |
|---|---|---|
| CBW fields | `7BF4..7C47` | Copies little-endian `7988..798B` to `58,57,56,55`; programs `5040..5043`; derives direction bit `12h`; maps the selected LUN to `417F` and initializes command state. |
| ATA PASS-THROUGH(16) decoding | `222B`, table after `22A4`, `23E5`, `247A..248F` | The supplied protocol-11 CDB selects `59h=67h`; request taskfile bytes are copied to `4B24..4B38`. |
| Requested length decoding | `7D61`, `A203` | Derives the requested SAT quantity in `4C16..4C19`. The model of the arithmetic interface is explicit here. |
| BOT dispatch | Table after `380D`, then `385A` | State `67h` takes the DMA branch. With the declared mapping and count, Data-Out selects `C789`. |
| Data-Out / SATA programming | `C789..C7B5`, `8CA3..8CF7` | Programs the transfer length at `6318..631B`, copies the taskfile to `6300..630B`, sets command byte `6302=35h`, port `6312`, and a command FIS marker at `6313`. This launch path does not initialize or update the `70B6` arithmetic interface. |
| Completion | `7308..73A8` | Waits for its completion conditions and D2H marker `6313=34h`; the branch at `735F` tests `(B9 & E1h)==40h`. That mask excludes BSY/DF/ERR but does not test DRQ. |
| Special native state | `7367..7375` | Only `59h=64h` clears `55h..58h` directly. |
| UDMA branch | `7377..737B` | Executes `CLR A; MOV R7,A; LCALL AEF4` for state `67h`. |
| Direction-dependent accounting | `AEF4..AF3F` | Data-In copies SFR `AC..AF` to residue with an `AF & 3Fh` mask. Data-Out takes `AF25`, calls `CBE3`, and does not update residue. |
| USB wait | `CBE3..CC08` | Tests `5052.bit0`, handles `50E2`, waits for `A3.bit7` to clear, and returns carry clear at `CC07`; `E140` can instead terminate the wait with carry set. |
| CSW | `94F9..9564` | Copies the tag from `7984..7987`; serializes `58,57,56,55` to CSW offsets 8..11; emits ordinary status from `5Ah`, or phase-error status for state `0Dh`. |

For the supplied CBW, the new native replay records CBW residue 512, state `67h`, SAT length 512, programmed SATA length 512, handler `7308`, and finally the exact CSW above. The complete chain uses the original instructions and **zero firmware-function stubs**. LUN-table contents, peripheral samples, and the arithmetic behavior remain declared fixture inputs.

The defect is scoped to this pass-through accounting path. These observations do not establish the same defect for every normal SCSI WRITE command, and do not establish data corruption.

## Why `70B6` / `70C0..70C3` cannot authorize a residue repair

The earlier reassessment was correct to reject an unqualified counter, but its bank-selector explanation was too definite. The code supplies a more useful contextual explanation:

1. The firmware writes multi-byte quantities to `70B0..70B5` and `70B8..70BD`.
2. It sends operation-like values through `70B6` and, for some operations, waits on `70B7.bit0` in `DF9B`.
3. Several operations produce values at `70C0..70C5` that are consumed outside USB data accounting.

The explicit competing model used in the new tests is:

| Command written to `70B6` | Modeled operation | Native context supporting the inference |
|---|---|---|
| `C0h` | Clear operand inputs while retaining prior result | Initializations before operand loads |
| `10h` | Copy prior result into operand A | `D1D7` before subtracting another PIO chunk |
| `00h` | A + B | `C7C5` initializes accumulated residue from H + 0 |
| `01h` | A − B | `D1D7` subtracts the chunk length in `6318..631B` |
| `02h` | Compare: 0 equal, 1 greater, 2 smaller | `9711..977A` compares a timer quantity against 600 and 288000 |
| `04h` | Shift operand A left by B | `A203 -> E0CA` converts sector counts to byte quantities |

This model is consistent with ten native timer boundary cases: values below 600 become 600, in-range values are preserved, and values above 288000 become 288000. It also reproduces five PIO accounting chains, including `512−128−384=0`, `512−0−256=256`, and `512−255−256=1`, with the native result copied by `B3C4` into `55h..58h`.

Those are consistency checks on an explicit peripheral hypothesis. They are not a substitute for register documentation or hardware measurement. They do establish why a zero observed in `70C0` cannot be assigned UDMA-counter meaning merely because a different PIO path copies it into residue.

The literal command-02/read-result sequence occurs at CPU `2B97`, `7710`, `7726`, `973A`, `9760`, `9A91`, and `B2DE`. These are verified signature sites, not a claim that a byte scan has recovered a complete control-flow graph.

All nine supplied JMS580 donors contain the two relevant residue-dispatch and Data-In SFR-copy signatures. Their updater containers are 67,072 bytes: CODE is at file `0x00400..0x103FF` and OEM data begins at `0x10400`. The audit verifies reset/interrupt-vector anchors at that CODE origin and reports separate CPU and full-file offsets. The earlier scan of the first 65,536 file bytes had a 1,024-byte origin error when treated as CPU CODE; its matched file signatures did not establish those CPU addresses. The corrected comparison supports common lineage of the logic. It does not qualify a donor image for this hardware or prove every surrounding path identical.

## New falsification of the earlier prototype

The previous prototype replaces the `7377` path and, after calling `AEF4`, checks state, direction, `5Ah`, USB flags, and whether `70C0..70C3` are all zero. It then clears residue. Its earlier negative tests stubbed `AEF4` in several error scenarios, omitting the original wait that needed examination.

The new regression executes `AEF4`, `CBE3`, and `E140` natively:

1. The first read of `5052` returns 0.
2. `E140` reads `9F.bit2=0`, returns carry set, and `CBE3` exits at `CBF8`.
3. `AEF4` returns with that carry intact.
4. The old helper ignores this return indication. Its subsequent `5052` read returns 1 and its unqualified arithmetic-result reads return zero.
5. The old helper clears the 512-byte residue.

| Image and CK_COND | Earlier rejected prototype | Transparent trace candidate |
|---|---|---|
| Stock, CK=0 or CK=1 | Conditional CSW residue 0 | Conditional CSW residue 512 |
| Original v8, CK=0 | Conditional CSW residue 0 | Conditional CSW residue 512 |
| Original v8, CK=1 | Conditional CSW status 1, sense `28h`, residue 0 | Conditional CSW status 1, sense `28h`, residue 512 |

This proves that the prototype does not reject the native wait's carry-set exit. It does not claim that this exact sample timing has occurred on physical hardware. The ordinary caller also schedules the finalizer after that exit; the external recovery scheduler is not modeled, so the table deliberately says **conditional CSW**.

The original-v8 row also illustrates why a failed CSW cannot be used as a synonym for ATA failure: CK_COND can produce an informational sense result after an otherwise good ATA status. The revised CK_COND abort guard invalidates that stale completion capture before its finalizer can consume it. The underlying native transport/recovery status and the UDMA residue are otherwise preserved.

## Trace candidate: exact scope and integrity

| CPU range | Full-image range | Replacement |
|---|---|---|
| `7377..737B` | `08377..0837B` | `12 E7 00 00 00` |
| `E700..E707` | `0F700..0F707` | `E4 FF 12 AE F4 00 00 22` |

The original `SJMP 7390` at `737C..737D` is preserved. The helper executes the displaced three instructions and returns. The stable observation boundaries are `E700` before completion and `E705` after completion. The Python harness records the CPU state at these boundaries without changing firmware registers or invoking a replacement function.

There are no additional MMIO reads, no persistent RAM allocation, and no writes to status, residue, sense, or command-ownership data. The nested helper call requires two additional transient stack bytes while inside `AEF4`; real stack headroom and timing remain unqualified. The candidate by itself provides no persistent on-device logging channel. A separately qualified debugger would be needed to observe those points on hardware.

The integrity-aware builder updates the required existing checksum fields. The output has 70,144 bytes, preserves all 512 OEM bytes, and has SHA256:

`a4bf69164548003a26efebcb3f5fd6e59d0dfc3321eeda2ffb97d6e36ba63712`

The manifest records 27 changed bytes. Actual changed full-image ranges, half-open, are `0x0000C..0x00010`, `0x001FC..0x00200`, `0x08377..0x0837C`, `0x0F700..0x0F705`, `0x0F707..0x0F708`, and `0x10FF8..0x11000`. The unchanged zero observation NOP bytes at `0F705..0F706` are included in the reserved helper range but are naturally absent from the byte-difference list. Valid checksums do not certify hardware execution or recovery.

## Tests and compatibility

The audit runs 24 scenario definitions against stock, original v8, and revised CK_COND, each paired with its trace overlay: 72 paired comparisons and 144 native executions. Returned-path comparisons include live IRAM below the restored stack pointer, all modeled SFRs including both DPTR banks, the complete fixture memory, and the MMIO event sequence. This tests interactions through state and sense, not just non-overlapping patch offsets.

Cases include full 512/4096-byte requests, CK_COND clear/set, ATA ABRT/device-fault/busy status, missing D2H/completion signals, pending/short USB conditions, endpoint stall/busy conditions, inactive/abort exits, late termination, prior failure status, Data-In controls, a nonzero Data-In residue, native state-64 behavior, phase error, and an arbitrary nonzero arithmetic result.

Separate tests exercise 32-bit residue boundaries through `FFFFFFFFh`, the Data-In `3FFFFFFFh` mask, malformed CBW/CSW records, tag mismatches, out-of-range residue, partial or failed USB completions, and the old prototype's failure. A future-accounting contract explicitly rejects unqualified counts, stale command epochs, reset, abort, timeout, stall, and phase-error updates. Full, partial, zero-length, and maximum-length arithmetic is tested only after an explicit qualified-count premise.

These tests deliberately distinguish native instruction behavior from model premises. A perpetual wait reaching the interpreter's instruction limit proves that the selected flags do not complete that handler. It is not a simulation of an actual hardware timer. Reset/timeout epoch tests cover the accounting contract; they do not certify a controller reset implementation.

The plain test run has 19 test methods. Without privately supplied firmware, the nine evidence-decoder, donor-layout, and accounting-contract methods run while the ten native-firmware methods explicitly skip. Supplying the exact stock and original-v8 files enables all methods.

## Exact blocker and the evidence needed to remove it

A real residue correction needs a stable quantity P attributable to the active CBW, representing bytes processed by the device. The implementation must know its address or event source, width, byte order, unit, validity interval, latch/reset behavior, interaction with the SATA engine, and behavior on partial transfers and recovery. Neither `70C0==0`, an all-zero uninitialized fixture, a successful host URB, nor an ATA-good snapshot alone establishes that contract for every outcome.

The minimal useful observation would correlate one command's CBW tag, LUN/physical port, and generation through these boundaries:

| Observation point | Required context |
|---|---|
| After CBW admission | Requested length, CDB, tag, direction, LUN, and a generation that changes across reset/reuse |
| After Data-Out launch | Programmed `6318..631B`, initial candidate counter state, and the operations that establish its meaning |
| `7377` / trace `E700` | ATA completion marker/status/error and the selected command owner |
| Native wait exit / trace `E705` | Carry, the actual USB wait branch, candidate count, and whether the snapshot remains valid after abort |
| Before `9529` | Final residue/state/sense and the CSW tag being emitted |

A register specification or a separately qualified observation mechanism must establish which reads are safe and which memory is owned. Issuing a fresh vendor SCSI read after the transaction may replace the very register context under investigation. The trace candidate intentionally does not solve that observability problem by claiming unused-looking XDATA is safe RAM.

Required qualification cases are a full transfer, a true partial transfer, an ATA error before and after consuming data, a stall, abort/reset/timeout recovery, repeated tags across command generations, and CK_COND clear/set. A corrected implementation would compute H−P with bounded arithmetic and preserve transport/sense decisions independently. Until this evidence exists, the release decision is to retain the measured defect transparently and withhold a residue-changing image.

## Reproduction

The top-level runner supplies all import paths and reconstructs original v8 and revised CK from the exact stock image:

```bash
python3 run_tests.py --stock /absolute/path/complete-factory.bin --out build/full-validation
python3 ph8057.py build udma-trace --stock /absolute/path/complete-factory.bin --out build/candidates
python3 ph8057.py build combined-revised-trace --stock /absolute/path/complete-factory.bin --out build/candidates
```

For the focused native report, the standalone entry point is `tools/patching/udma/run_audit.py`, with explicit `--stock`, `--v8`, `--revised-ckcond` and `--out` arguments; `--donors` is optional. The report's `udma_native_disassembly.txt` is generated locally and retained in the private audit results. Public release includes bounded summaries rather than full vendor instruction listings.

There is no firmware download, device writer, flash uploader, automatic publication or hardware test in this component. The unsafe old helper exists only as a negative in-memory fixture.
