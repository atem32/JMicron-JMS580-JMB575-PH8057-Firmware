# Independent audit and remediation report

Date: 2026-11-02. Target: the supplied PH8057/JMS580+JMB575 firmware and research packages. This report records implementation changes, their evidence and their limits. The original inputs remain unchanged. No hardware command, disk write, SPI operation, new hot-plug experiment or publication occurred.

## Engineering outcome

The audit produced a real instruction-level CK_COND correction, a new reproducible candidate, corrected emulator/analysis tools, an updated OEM atlas and regressions that expose earlier defects. It also disproved the earlier UDMA accounting prototype on a native abort path. A residue-changing UDMA image is withheld because the available evidence does not establish a reliable per-command processed-byte quantity. The supplied UDMA and combined variants are explicitly observation-only for accounting.

The outcome is therefore more than a documentation rewrite, and it is narrower than hardware qualification. The key firmware identities are:

| Artifact | SHA256 |
|---|---|
| Immutable full factory |`ef5ad9af3f3b290c565a4dc65933d539b7bb8b8051ac9bd45386932a77862c09`|
| Immutable original v8 |`4b7ac3e5bd124d8e44281e9aa79b7b65f7b62c54410ffd1abd8af4a586d74e11`|
| Revised CK_COND |`2aaece707763b5dab32c46cf10c17c88345d73b8635365a354dcffe8817b422b`|
| UDMA trace only |`a4bf69164548003a26efebcb3f5fd6e59d0dfc3321eeda2ffb97d6e36ba63712`|
| Revised CK + trace |`825660ce89e77f9fe827d0a34f7c527d155e1726795d093671c9aff38a844163`|

Every modified full image is **DO NOT FLASH**. Public output contains builders, tests and manifests; vendor-derived full images are private research artifacts.

## Inputs, completeness and independent method

The repository attachment has SHA256 `0766e3a6b43c642365b5ed001d6d992847e865af54a2ab1dedbe6117318c52e0`; the complete handover attachment has SHA256 `f3b3148c740947cbbf0ceedad5a9b9bf51b8741f375764d3b828e5bce8747985`. Both were recursively unpacked, including nested ZIP and TAR.GZ files. The result contains 79 archive occurrences, 48 distinct archive hashes, 945 extracted file entries and 413 unique payload hashes. Content-addressed extraction reproduces the same payload set. The supplied checksum lists contribute 808 matching entries and inspected JSON manifests 439 matching entries; these are overlapping integrity records.

The full factory image is 70144 bytes, with CODE at 1000..10FFF and OEM at 11000..111FF. The 65536-byte historical `ph8057-original.bin` is exactly the SPI prefix of that full image; adding the supplied 4608-byte tail reconstructs the full capture. The nine donor containers are 67072 bytes, with a different 400h CODE origin and 10400h OEM origin. Three obsolete 65536-byte lab IMG payloads are also present. These are not complete flash images and are not promoted to candidates.

Original source claims were treated as hypotheses. The audit checked actual bytes and instruction boundaries, compared the decoder with independent MIT source, exercised ISA semantics, ran native paths with explicit RAM/MMIO fixtures, introduced counterexamples and reran historical expectations unchanged. Source/offset scans are labeled as candidate references rather than complete control-flow graphs. Unknown indirect paths, hardware effects and asynchronous scheduling remain explicit limits.

The historical 33816 count was audited independently. It is a sum of heterogeneous reported units, while identity-only instrumentation counted 44211 executed assertion/check guards. Most tests execute real 8051 instructions, but supply synthetic state and sometimes host-copy/peripheral stubs. Their expected formulas often derive from the same code. They establish conditional software behavior and reproducibility, not 33816 independent features or physical tests.

## FIXED — execution and tooling defects

### EMU-001: ambiguous 64 KiB file loading

**What and why.** The old loader accepted a 65536-byte input as raw CPU CODE, even though the project uses exactly that size for a truncated SPI prefix. Disassembly and execution could therefore start 1000h bytes before the real CODE origin.

**Correction.** `tools/emulator/mcs51.py:load_code` recognizes the complete PH8057 layout and requires explicit raw-CPU intent for 64 KiB inputs; a recognized SPI prefix is rejected even under that explicit mode. `tools/analysis/firmware_inspect.py` separately identifies full, donor, truncated and unknown containers.

**Proof/test.** `test_reject_ambiguous_truncated_spi_as_cpu_code` fails on the supplied old loader and passes on the corrected one. `test_explicit_cpu_and_complete_image_layout` and the integration container tests cover the accepted alternatives. The prefix+tail equality is checked from the original files. This fix does not infer a flash capacity or donor compatibility.

### EMU-002: fixture initialization could wrap or resize memory

**What and why.** Negative or oversized FixtureBus initialization keys/ranges could index from the end of a bytearray or resize it through an out-of-range slice. That invalidated the claimed fixed 64 KiB model.

**Correction.** FixtureBus now validates RAM ranges, initial addresses and buffer extents before storing them. Invalid mappings fail instead of creating synthetic evidence outside the address space.

**Proof/test.** `test_bus_initialization_cannot_resize_or_wrap` fails on the old implementation and passes now. Existing native suites still pass. The fix validates the fixture; it does not assign unknown MMIO semantics.

### EMU-003: undefined DIV-by-zero results were treated as deterministic

**What and why.** After DIV AB with B=0, the old executor continued with convenient unchanged A/B values. The ISA does not define those result bytes, so later code could produce a falsely deterministic trace.

**Correction.** The executor reports the defined flag condition and raises an execution error instead of continuing through undefined results. Defined DIV behavior remains implemented and tested.

**Proof/test.** `test_divide_zero_is_not_a_deterministic_execution` is a before/after regression; `test_div_all_defined_inputs` covers 65280 defined pairs. The [Microchip ISA manual](https://www.microchip.com/content/dam/mchp/documents/OTH/ProductDocuments/UserGuides/doc4316.pdf) independently supports the distinction. This is an epistemic execution boundary, not a claim that physical hardware traps on DIV0.

### EMU-004: MMIO events recorded the next PC

**What and why.** Instruction dispatch advancedPC before a MOVX callback logged the event, so traces attributed a register access to the following instruction.

**Correction.** A scoped active-instruction PC is recorded while executing each instruction; read/write events use it and it is cleared even on exceptions.

**Proof/test.** `test_mmio_trace_records_executed_pc_not_next_pc` fails before and passes after. Native MMIO sequences were rerun with the corrected executor. The change improves source attribution, not physical timing accuracy.

### EMU-COND-001: unrelated SFR conditions were read eagerly

**What and why.** A dictionary selecting JC/JNC/JZ/JNZ/SJMP evaluated all its conditions. Even SJMP could read ACC/PSW through callbacks, and conditional branches read unrelated registers. Effectful callbacks could change modeled behavior.

**Correction.** Selected `if/elif` evaluation reads only the actual branch condition. `test_conditional_jumps_read_only_their_required_condition` fails for all five affected old opcodes and passes now. The common 27-method suite passes. Existing CK/UDMA fixtures do not attach effectful ACC/PSW callbacks, so no firmware bytes or previous candidate hashes change.

### CK-TOOL-001 and CK-TEST-001: optimization removed prerequisites and tests

**What and why.** Original-hook, zero-cave and duplicate-label checks in the old capture generator were Python assertions; `python -O` removed them. The historical runner could also execute assertion-based tests with their checks disabled.

**Correction.** Production builder checks use explicit exceptions. The canonical test configuration and runners reject optimized assertion-disabled execution and remove inherited PYTHONOPTIMIZE from child environments. The intentionally optimized negative guard probe remains isolated.

**Proof/test.** `test_expected_byte_and_duplicate_label_guards_survive_optimization` and `test_original_guard_bug_if_historical_source_is_supplied` run the same invalid cases against old and corrected generators. Old code accepts the invalid cases under -O; corrected code rejects them. Optimized suite entry points are also tested to reject execution. This does not prove that the already-supplied v8 BIN was malformed: its hash and original build remain exact.

### IO-001: result sidecars could overwrite source files

**What and why.** Protecting only a candidate BIN destination left JSON manifests and analysis outputs unchecked. A valid stock file named like the generated manifest, or a filesystem alias to it, could be overwritten after the builder read it. Disposable copies reproduced this failure in the initial unified, CK and UDMA builders.

**Correction.** `image.py:guard_outputs` preflights every destination, including sidecars, before any write and rejects symlink/hardlink aliases. The standalone CK/trace builders, unified CLI and UDMA audit use it. The OEM decoder/native audit have equivalent source protection. Both the unified runner and the standalone CK runner preflight existing result trees before starting any suite, rejecting linked log files or subdirectories even without historical replay. Test outputs are kept outside their immutable input trees.

**Proof/test.** `test_all_builder_sidecars_preserve_source_on_filename_collision`, `test_output_guard_rejects_direct_symlink_and_hardlink_source_aliases`, `test_unified_runner_refuses_log_alias_before_any_execution`, `test_ck_runner_refuses_log_alias_before_any_execution` and `test_oem_sidecar_cannot_overwrite_input` verify source bytes and absence of partial outputs. Before/after evidence uses disposable copies, never the original archive inputs.

### HIST-TOOL-001: historical execution lacked reviewed-source validation

**What and why.** A directory with the expected name could contain changed Python. Earlier replay wrappers recorded a script's hash after execution rather than requiring the reviewed hash beforehand. Copying ignored bytecode caches would add another unreviewed import route.

**Correction.** `tools/history/provenance.py` verifies selected source trees against a metadata-only reviewed manifest, rejecting missing, changed, extra or linked inputs before any archived subprocess. Replays strip bytecode caches, verify the canonical replacement emulator and require separate output trees. This is provenance control for reviewed offline entry points, not a general arbitrary-Python sandbox.

**Proof/test.** `test_modified_v8_entrypoint_rejected_before_any_archived_process` verifies rejection before `subprocess.run`. Other regressions cover same-size edits, missing/extra files, symlinks, sourceless bytecode and output-log aliases. The optional optimized legacy-guard witness independently requires the exact reviewed source SHA before executing it. Genuine original-v8 and v15–v22 replays pass after hardening; the unified replay covers the later groups too.

### HIST-TOOL-002: extraction inventory could alias an input archive

**What and why.** A ZIP named inventory.json in the output directory could be overwritten by the generated inventory; an existing inventory link could similarly target source data. A general extraction byte budget also needed separate treatment of compressed-file size and expanded payload.

**Correction.** The extractor preflights inventory/input aliases, rejects links/traversal/special members, separates compressed and expanded budgets, preserves conflicting existing files by failing, and bounds nesting. Tests explicitly require the correct expanded-budget failure so ZIP header overhead cannot accidentally satisfy that test.

**Proof/test.** `test_inventory_output_cannot_overwrite_a_source_archive`, `test_inventory_link_cannot_modify_original_or_escape_output`, `test_conflicting_existing_evidence_is_not_overwritten` and the expansion/traversal tests pass. The real two-archive extraction reproduces the original payload hashes.

## FIXED — OEM analysis, decoder and tests

The canonical files are `tools/analysis/oem.py`, `tools/analysis/native_oem.py`, `tests/regression/test_oem.py` and generated `research/oem/` tables. Every 512-byte row and every option bit has an explicit evidence category. No factory setting was changed.

### OEM-01: F8.7 attempt count and retained mismatch

The prior analysis missed `SETB C` before `SUBB A,#0A` and the use of the old counter after a copy. `77E2..77E8` clears the mismatch flag once, while `7838..783D` sets it and later successful comparisons do not clear it. Persistent failure, and first-failure-then-success, both execute 12 copies with 4BC5=11 and 4BC4=1. Immediate success executes one copy. The retry model and atlas now match those instructions. `test_F8_retry_ten_attempt_claim_counterexample`, `test_F8_mismatch_flag_is_sticky` and native injected-fault tests prove the correction. Intended physical retry policy remains blocked separately below.

### OEM-02: swapped USB setup fields

v16 named IRAM1C/1D as wValue and 1A/1B as wIndex. Both must be zero for a valid GET_MAX_LUN request, so final-rejection-only tests concealed the swap. The corrected `setup_iram()` maps wValue to 1A/1B and wIndex to 1C/1D, high byte first internally. Native asymmetric cases distinguish D970 recognition from C702 rejection. `test_setup_fields_regression_asymmetric_value_index` and `test_native_correct_setup_mapping` cover the error. USB wire endianness remains separately described.

### OEM-03: clean-RAM projections were mistaken for general state transitions

The F2 slice assigns 44F3 but only conditionally sets 487D, 4583, 4584, 4588 and IRAM bits 39/3A. Clear flags preserve some prior values in that slice; earlier initialization clears only certain fields. E7.5 can likewise preserve 4575. Corrected state-transition helpers accept prior state, while poisoned native fixtures and the full initializer test the actual lifetime. `test_F2_zero_memory_projection_is_not_state_transition` and `test_native_poisoned_F2_state` prove the distinction. This is not evidence of a factory boot defect with enabled stock settings.

### OEM-04: dispatcher stubs were overinterpreted as callee guarantees

Return-only replacements for 7616/77DA preserved R6 and interrupt state, unlike the original callees. The new native C4D3 chain executes the real copy helpers: 7616 returns R6=1A, successful 77DA returns R6=01, and the path leaves EA set. Peripheral command/wait helpers remain explicit stubs. `Audit.f8_transfers` records native clobbers, CODE copying and fault behavior. Since 71C4 consumesR7, the R6 difference alone is not a factory malfunction. The correction is to the test model, evidence scope and atlas.

### OEM-05: unit serial escaped through byte tables

Suppressing the serial string in prose did not remove its bytes from the old 512-row CSV/full hex. Redaction now occurs in canonical serialization: OEM056..077 is redacted by default in both decoded output and byte tables. Private output intentionally retains the original bytes. `test_serial_payload_is_redacted_by_default` checks the boundary, and package scanning checks actual factory/donor serial forms. Product-level identifiers remain available.

### OEM-06: the 33816 aggregate was misinterpreted

Reported counters mixed scenarios with assertion calls and repeated earlier paths. The unchanged replay passes 33816 reported units, but independent instrumentation finds 44211 guard evaluations. Classification distinguishes 28635 synthetic-memory native units, 2624 host-copy-fixture units, 2316 stubbed-peripheral/callee units and 241 static/bookkeeping units. The runner summary keys, documentation and public results now use the right terms. No expected result was changed to obtain PASS; assumptions are described rather than counted as hardware evidence.

Other decoder refinements preserve JM/HD/BC gating, packed ASCII versus UTF-16 distinctions, malformed-length bounds, the 100 ms SCSI SZCT interpretation, 32-bit timer wrapping and the unknown second half. The already-correct v29 E7.7/5082 interpretation is retained and credited under OEM-07, not relabeled as a new discovery.

## FIXED — CK_COND firmware and reachability tests

### CK-001: stale ATA result after native USB-wait abort

**Cause.** Original v8 captures ATA status at 735F before Data-Out callsAEF4→CBE3. During either wait, E140 can return carry set when its active condition is absent. Native CBE3 returns through CBF8 orCC06, and the caller does not branch on that carry. v8 leaves 4E07=A5. If scheduled 94F9 executes, it can publish the prior good snapshot and synthesize sense 28 after the intervening abort.

**Instruction correction.** Guarded three-byte replacements at CBF6 and CC04 jump to FD00 and FD08. Carry-clear paths return to CBE3/CBF9 exactly as before. Carry-set paths tail-jump to FD20..FD3E, which preserves IE/A/DPS/DPTR and clears only 4E07, then returns using the existing caller frame. It uses five temporary stack bytes and no new persistent RAM. Native status, sense mapping and residue are not rewritten.

**Proof.** The new test executes 7308→AEF4→CBE3→E140 and the conditional native finalizer without replacing those functions. Original v8 fails both abort cases; revised suppresses stale publication. `test_v8_pre_abort_snapshot_is_not_published_by_revised_candidate`, `test_abort_suppression_keeps_ata_error_and_non_ck_status_policy` and 128 helper ABI cases verify the intended effect and preservation.12 error/CK scenarios execute 36 candidate combinations.

**Result and limit.** The revised image is reproducible, OEM-identical and differs from v8 in 68 actual byte positions including integrity fields. This fixes the bounded association defect. It does not establish real reset scheduling, SRAM ownership, code-cave loading or physical CSW delivery after abort. It also does not fix UDMA residue.

### CK-VAL-001: launch fixtures did not prove natural CDB dispatch

The earlier integration helpers selected known launch PCs directly. Those tests remain useful but did not prove that host SAT12/16 requests naturally reach them. New tests execute actual CBW parsing, 4A97 SCSI dispatch and 3804 BOT/SAT dispatch.112 paired scenarios cover both CDB lengths, seven protocol classes, four supplied LUN maps and CK clear/set; 32 wrong-direction pairs preserve stock rejection.128 ordinary-SCSI cases compare admission/shared-sense behavior. This strengthens native reachability evidence without inventing a full asynchronous non-data scheduler or claiming complete READ/WRITE media validation.

## FIXED — UDMA analysis and unsafe research implementation

### UDMA-002 and UDMA-004: old helper could clear residue after abort

The old prototype relied on later USB-ready samples and 70C0..C3 being zero, while some negative tests replaced AEF4 with a stub. The new native sequence reads 5052=0, takes E140/CBE3's carry-set abort, then lets the old helper see a late 5052=1 and stale/unqualified 70C0=0. The helper incorrectly changes 512 to 0. Four native counterexamples cover stock/v8 and CK settings. Under v8 CK1, CSW failure can also be informational sense 28 rather than ATA ERROR, so a CSW-status shortcut is invalid.

The unsafe algorithm is removed from supported builders and retained solely in `unsafe_prototype_fixture.py` for negative regression. `test_rejected_prototype_zeros_residue_after_native_abort` fails its accounting claim; trace-only code preserves residue. New fixtures execute the original completion functions with zero firmware-function stubs and compare architectural/MMIO state. This remediates the unsafe implementation and false-assurance test path; the factory accounting defect itself remains blocked.

### UDMA-003: universal counter/bank-selector claims exceeded the evidence

Native timer and PIO paths use 70B0/70B8 as operand-like inputs, 70B6 as an operation interface and 70C0 as a result. Ten timer clamps and five PIO subtraction chains are consistent with an explicit arithmetic/compare model. UDMA launch C789 performs no 70B6 operation establishing an attributable count. The canonical fixture now labels this as a competing hypothesis and forbids using an unqualified zero to repair residue. `test_native_comparator_and_pio_arithmetic_are_consistent_hypotheses` verifies consistency, not silicon identity.

### UDMA-006: SG_IO-derived bytes were confused with USB observations

The archived v11.3 report's actual_bytes=0 is derived from 512 − resid 512. It stops after the write result and does not contain raw CSW. The later owner-supplied account reports 512 successful USB Data-Out bytes and includes raw CBW/CSW; the Data-Out observation is separately attributed and cannot be derived from CBW/CSW alone. Its matching readback claim remains separately attributed; a complete raw usbmon capture is absent. `bot_evidence.py` parses strict framing/tag/status/direction/residue and reports transported versus claimed-processed bytes distinctly. Tests reject malformed/mismatched records and avoid interpreting phase-error residue as meaningful.

### UDMA-007: donor file offsets were mistaken for CPU offsets

Scanningraw[: 65536] in 67072-byte update containers placed CPU 0 at the wrapper rather than 400h. The corrected scanner checks reset/interrupt anchors at 400h, scans the actual64 KiB CODE slice and reports CPU and file offsets separately. All nine donors pass. `test_container_offset_and_vector_anchors_are_explicit` catches the old origin mistake. Matching signatures establish related logic, not donor suitability or complete control-flow equivalence.

## PARTIALLY FIXED

**HIST-001 — missing v3 restricted-wrapper source.** The supplied v3 script imports a source file absent from all archive entries. A report contains its historical hash and the restricted-only IMG hash, but a hash cannot recreate source. The supplied v3 IMG contains the relevant restricted common bytecode, allowing an explicitly labeled binary-backed dependency adapter and reconstruction of the restricted-only image. The original missing-dependency failure is preserved. The three supplied general/v2/v3 images rebuild byte for byte. The replay executes 41 distinct available original cases (55 PASS events because the 14 general cases execute twice). The original common-builder log is also recovered verbatim from the report: 1724 bytes, SHA256 `656b94494d6d37a06edb97e28056b63465a4e21258e8d51afb1b441e3b95969d`. Its 15 recorded PASS lines are preserved evidence, not newly executed tests. Executable tests belonging to the absent source remain unavailable. `tools/history/replay_labs.py` and [historical lab reproduction](historical-labs.md) record the distinction. Current canonical CK builders supersede the obsolete algorithm.

**UDMA-005 — abort association versus native recovery policy.** Revised CK fixes its stale-snapshot publication, but the surrounding firmware's physical abort/reset scheduling and its decision to emit or cancel a CSW are unqualified. Tests preserve native state instead of inventing a success or error policy. A conditional native finalizer result is not presented as an observed device response during reset.

## NOT REPRODUCED / previously corrected claims

- The original v8 was not found to have a malformed binary container or an unreproducible patch set. Its exact hash, original suites and checksum relationships reproduce. The newly found abort defect is behavioral and separate.
- A malfunction of the enabled factory OEM settings was not established. Optional F8 behavior and oversized timer wrapping are accurately modeled, but their supported input/physical contracts are insufficient to justify an OEM firmware-policy change.
- E7.7's unconditional 5082.bit 3 and independent cleanup were already corrected in v29. The current atlas preserves that correction and independently exercises 1280 mask and 768 cleanup cases; no new defect is claimed there.
- A universal UDMA counter role for 70C0..C3, a proven bank-selector role for 70B6, and the claim that a zero/unused-looking region is safe scratch RAM are not established. The current tools no longer promote these assumptions to facts.
- No new full USB disconnect cause was proven. Existing hotplug observations remain supplied evidence; code-level event paths alone do not distinguish power/reset/PHY from firmware policy.

## BLOCKED BY HARDWARE EVIDENCE

**UDMA-001 — actual residue correction.** The original CBW→SAT→SATA launch→completion→CSW instructions reproduce the exact supplied CSW. IRAM 55..58 starts at 512, the UDMA Data-Out branch never updates it, and 94F9 serializes it unchanged. The causal accounting omission is therefore localized. What is missing is an attributable, stable quantity P of bytes processed, including partial transfer and ATA/USB failure behavior. USB completion, ATA-good status and a stale arithmetic result cannot independently provide it. The BOT specification's H−P requirement is documented in the primary [USB BOT source](https://www.usb.org/sites/default/files/usbmassbulk_10.pdf). The reference contract rejects unqualified/stale counts; no residue-changing BIN is issued.

**OEM-HW-01 — optional F8 policy.** Software demonstrates repeated copies and retained mismatch, but does not establish the 7300/7500 window operation contract, idempotence or intended recovery. Stock F8=0 disables the path. The caller ignores 4BC4 before its next controller command. A blind latch/retry patch would select unsupported behavior. The minimum missing evidence is the controller-window contract or qualified traces of immediate success, transient/persistent mismatch and completion/reset behavior.

**HW-QUAL-001 — modified-firmware qualification.** Exclusive SRAM, coherent 6300 taskfile capture, actual code loading/caves, worst-case stack/IRQ usage, safe SPI recovery and real scheduler behavior remain unverified. The combined abort path can need seven additional bytes for the new leaf plus trace call, before ISR nesting. No synthetic pass replaces those gates. UASP and stable hot-swap are intentionally not implemented.

## Regression, compatibility and delivery

The public runner executes portable tests and reports private-input skips. With exact stock it builds the original and revised variants temporarily, runs native OEM/CK/UDMA and actual combined-image tests, and records source hashes. With reviewed history it adds the original suites and count audit. The new UDMA matrix has 24 scenario definitions across three bases and their trace overlays: 72 pairs/144 native executions. The original 33816 expectations remain unchanged. The full new logs retain failures/counterexamples as well as passing corrections.

Compatibility includes live IRAM/SFR/XDATA, sense/status/residue and bus events, not just disjoint file addresses. Revised CK and the observation helper are compatible within those fixtures. The combined image uses 34 guarded records and has 2618 actual byte changes versus stock, with all 512 OEM bytes unchanged. Complete physical READ/WRITE data transfer and UDMA partial/error accounting are not declared qualified.

The public package contains current sources, English documentation, tests, workflow, scoped licenses/notices, redacted atlas and manifests. The complete private archive contains both original ZIPs, every extracted source/evidence file, historical logs/images, new implementations, tests/results and candidate BINs. Public packaging excludes full vendor firmware, unit serials, raw sector payloads and unredacted logs. The GitHub workflow is prepared but not remotely executed or published.

The twelve direct answers are in `docs/final-status.md`; exact byte changes and CRCs are in `docs/firmware-validation-report.md` and candidate manifests. The manual qualification plan lists the minimal additional observations without executing or supplying an automatic dangerous test. Every identified fixable current implementation issue has a correction and regression; the remaining gaps name the exact unavailable evidence instead of claiming a ready solution.
