# SMART / CK_COND: independent audit and revised candidate

In these reports, native sense code `0x28` is the firmware's internal pending-sense selector (including IRAM `3B` in the exercised path). It is not itself a SCSI sense-key value, an ASC/ASCQ pair, or a descriptor length.

## Verdict

The original CK_COND v8 image was reproduced byte for byte and its original
offline suites were rerun. Its main ATA descriptor construction and deferred
sense paths passed those bounded tests. An additional native control-flow test
identified a real association error: v8 could publish an ATA result captured
**before** the native USB Data-Out wait subsequently returned through its
inactive/abort exit. A separate revised candidate now invalidates that
unpublished result on both native abort exits.

The correction is instruction-tested and reproducible. Neither original v8 nor
the revised candidate has been executed on the physical PH8057. Both remain
**EXPERIMENTAL — DO NOT FLASH**. This revision does not fix UDMA residue and does
not qualify the factory reset/recovery scheduler.

## Inputs and identities

| Image | Length | SHA256 |
| --- | ---: | --- |
| Complete factory capture | 70,144 | `ef5ad9af3f3b290c565a4dc65933d539b7bb8b8051ac9bd45386932a77862c09` |
| Original CK_COND v8 | 70,144 | `4b7ac3e5bd124d8e44281e9aa79b7b65f7b62c54410ffd1abd8af4a586d74e11` |
| CK_COND revised | 70,144 | `2aaece707763b5dab32c46cf10c17c88345d73b8635365a354dcffe8817b422b` |

The old 65,536-byte `ph8057-original.bin` is an incomplete SPI prefix, not the
complete CPU CODE image. The builder accepts only the complete, exact factory
capture. In that capture CPU CODE addresses map to file offsets by adding
`0x1000`. OEM occupies file `0x11000..0x111FF` and is preserved unchanged.

The revised image differs from stock in 2,607 actual byte positions. Original
v8 differs in 2,555. Revised differs from original v8 in 68 positions: 52 CODE
bytes and 16 CRC/mirror bytes. The patch specification covers 53 CODE bytes;
one replacement byte is zero where the code cave already contained zero.

The original image is retained separately. The correction is not a mutation of
the historical v8 artifact.

## Original defect addressed by v8

Stock ATA PASS-THROUGH handling can complete commands without supplying the
ATA Return Descriptor expected by host SAT software. A later vendor protocol
15 getter reads the current register bank and the current CDB EXTEND bit; it
is not a saved result belonging to a preceding command. Returning that live
bank from a subsequent REQUEST SENSE would risk reporting another command's
registers.

The preserved v8 design instead stages a command-owned snapshot:

1. Native BOT admission at CPU `7C40` invalidates the previous active context
   and the selected LUN's obsolete cached descriptor, except when the new
   command is REQUEST SENSE.
2. The native SAT parser reaches `229E` only after assembling the normalized
   taskfile and CK_COND state. The patch records opcode, original protocol,
   LUN, tag equality metadata, EXTEND and ATA command.
3. The common SATA launcher at `8CA3` accepts only explicitly audited return
   PCs, taskfile pointers, protocol classes and command ownership. Each launch
   invalidates the preceding attempt's unpublished result.
4. Non-data, PIO-in, PIO-out and both BOT DMA completion families have separate
   capture hooks. The capture code uses the accepted status/error source for
   that family and checks software ownership plus the selected port on both
   sides of the register snapshot.
5. Native CSW finalization at `94F9`, through the hook at `9503`, publishes the
   slot only when native status, pending sense and saved ATA outcome agree.
   CK_COND success becomes the native sense-code `0x28` path; native ATA error
   mapping remains intact. The four residue bytes `55..58` are not changed.
6. REQUEST SENSE at `C320` uses the matching per-LUN cached descriptor, the
   native key/ASC/ASCQ mapping, and the native allocation-length clamp. Invalid
   or mismatched saved state uses the native fallback.

These are claims about the inspected executable instructions. They do not
establish that the proposed SRAM allocation is exclusive, that `6300` always
belongs to the intended physical command, or that the entire system behaves
atomically during asynchronous peripheral activity.

## CK-001: capture published after a native USB-wait abort

### Failing control flow

The main DMA handler captures ATA status at `735F`. For a successful Data-Out
ATA completion it subsequently executes `7377 -> AEF4 -> CBE3`. CBE3 waits for
`5052.bit0`, then for `A3.bit7` to clear. During either wait it calls E140.
E140 returns carry set when its observed `9F.bit2` condition is clear.

There are two native carry-set exits:

| Wait | Original instructions | Normal retry | Inactive/abort return |
| --- | --- | --- | --- |
| `5052.bit0` | `CBF6: JNC CBE3; CBF8: RET` | `CBE3` | `CBF8` |
| `A3.bit7` | `CC04: JNC CBF9; CC06: RET` | `CBF9` | `CC06` |

AEF4 preserves that carry through its remaining instructions. The main DMA
caller does not branch on it and can schedule `94F9`. This audit executes
that scheduled finalizer conditionally; it does not claim the outer reset
scheduler always permits a physical CSW to be sent after the event.

Original v8 had already set unpublished-valid byte `4E07=A5` before entering
the wait. Neither carry-set exit cleared it. If the finalizer ran, v8 could
commit that descriptor and synthesize sense `0x28` from a good ATA status,
despite the intervening abort of the native USB wait. The same stale
association occurred for captured ATA error results: the error itself
remained native, but v8 attached a result after the transport exit.

### Implemented correction

The revised candidate replaces each three-byte `JNC; RET` exit with a tail
jump. Carry clear follows exactly the original wait loop. Carry set enters
one small leaf that clears only `4E07`, then returns to the original caller.

| CPU range | File range | Replacement/function |
| --- | --- | --- |
| `CBF6..CBF8` | `0DBF6..0DBF8` | `50 EB 22 -> 02 FD 00` |
| `CC04..CC06` | `0DC04..0DC06` | `50 F3 22 -> 02 FD 08` |
| `FD00..FD07` | `10D00..10D07` | Carry dispatch; retry at `CBE3` or invalidate |
| `FD08..FD0F` | `10D08..10D0F` | Carry dispatch; retry at `CBF9` or invalidate |
| `FD20..FD3E` | `10D20..10D3E` | Preserve context, clear `4E07`, restore, return |

The leaf saves IE, A, DPS and physical DPTR0, masks CPU interrupts around the
single-byte invalidation, then restores them in reverse order with IE last.
It preserves carry, AC, OV, register-bank selection, B, all Rn registers,
physical DPTR1 and the native caller's return address. Its five extra saved
stack bytes are released before returning. It has no new nested call.

The generated source is `abort_guard.py`; the builder integrates it with all
original CK_COND hooks. Byte-for-byte patch records, CRCs, SHA256 and before/
after disassembly are supplied with the candidate manifests.

### Before/after evidence

`test_v8_pre_abort_snapshot_is_not_published_by_revised_candidate` executes
actual native launch and `7308 -> AEF4 -> CBE3 -> E140`, then conditionally
`94F9`, without substituting firmware functions. Both inactive exits reproduce
the original v8 failure. With ATA success and CK_COND set:

| Conditional result | Original v8 | Revised |
| --- | ---: | ---: |
| Unpublished valid after wait abort | `A5` | `00` |
| Published per-LUN descriptor marker | `A5` | `00` |
| Native pending sense code | `28` | `00` |
| CSW status if finalizer is run | `1` | `0`, unchanged stock policy |
| CSW residue in the 512-byte fixture | `512` | `512` |

**The conditional stock GOOD status is not repaired or certified.** The
revision prevents CK_COND from attaching a stale ATA result and creating
successful-ATA information for this aborted wait. Deciding whether the outer
recovery path should suppress CSW, report a phase error, or set other failure
state needs additional transport/scheduler evidence.

A separate matrix covers CK_COND clear/set and ATA success, ERR and DF at
both exits. The revised image preserves stock CSW and native sense policy,
including existing ATA failure status, while suppressing the stale descriptor.

## Tool and test remediation

The old capture generator used Python `assert` for original-hook checks,
zero-cave checks and duplicate label checks. Under `python -O` all three
checks vanished. The canonical generator now raises explicit exceptions;
the same subprocess regression accepts invalid inputs with the supplied
historical source and rejects them with the corrected source. This is an
API guard defect, not proof that the existing v8 BIN was malformed: the
historical top-level SHA/CRC checks provided additional protection.

Historical suites also contain ordinary assertions. The canonical test
configuration refuses assertion-disabled execution, and its runner removes
inherited `PYTHONOPTIMIZE` for child tests. The deliberately optimized
generator-guard subprocess is isolated from the assertion-based suites.

The original direct-launch fixtures remain useful but cannot prove that a
given host CDB naturally reaches the selected launch site. New tests execute
native CBW parsing, native SCSI dispatch and native `3804` BOT dispatch. They
confirm 112 paired stock/revised scenarios over both SAT CDB lengths, seven
protocol classes, four explicitly supplied LUN-map slots and CK_COND clear/
set. Non-data's asynchronous lower-state scheduling remains a stated boundary.

## Regression coverage and interpretation

The canonical CK suite retains the original assertion contracts, including:

- 65,536 status/error combinations comparing the generated pure ATA sense map
  with native AA9F execution. This is exhaustive over two input bytes, not
  exhaustive firmware or hardware validation.
- 3,245 sense/lifecycle fixture scenarios: mapping, allocation truncation,
  per-LUN ownership, invalidation, reset loops, pending-sense changes and DPS.
- 207 native SAT12 normalization/control-validation scenarios.
- 310 integrated fixture scenarios for begin, launch, capture, finalization,
  sense, ATA errors, CK_COND clear/set and synthetic LUN routing.
- Native terminal branches, timeout paths, PIO transport errors, nonzero
  residue, main/alternate DMA completion, subsequent chunk invalidation and
  the later ten-case recorded port-ownership replay.
- Original code/image integrity, source-hash enforcement, patch overlap,
  expected bytes, CRCs, and replay of the captured stock E5 register bytes.

The independent additions include the abort regressions above, 128 leaf-ABI
cases, 112 paired full native dispatch scenarios, 32 direction-rejection
scenarios and 128 ordinary-SCSI admission/sense-hook comparisons. Ordinary
READ/WRITE admission and common state are covered; no complete physical
sector transfer or media-integrity guarantee follows from these fixtures.

No test executes SG_IO, sends USB packets, writes SPI, or opens a disk.
The native-code tests supply XDATA/SFR values explicitly. They do not model
autonomous DMA, interrupt timing, PHY behavior, power loss or controller RAM
aliasing. Historical test counts are retained by category rather than added
together into a misleading hardware qualification number.

## Compatibility with the UDMA research candidate

The UDMA observation-only trampoline uses `7377` and `E700..E707`; it does not
overlap the revised abort guard at `CBF6`, `CC04`, `FD00`, `FD08`, `FD20`.
More importantly, staged native tests compare live IRAM/SFR/XDATA and MMIO
events for revised CK alone and revised CK plus the observation trampoline.
The trace preserves the correction's carry-set invalidation and normal
CK_COND sense behavior. Its added two-byte call frame remains live while the
abort leaf saves five bytes: the combined path can therefore use seven
additional stack bytes before interrupt nesting.

There is **no proven UDMA residue fix** in this compatibility statement.
The combined candidate is CK_COND revised plus UDMA research instrumentation,
and still reports the known 512-byte residue in the confirmed transfer fixture.

## Reproduction

Use the exact user-owned stock capture; vendor firmware is not bundled with
the public project. From the CK component directory:

```sh
python3 build_ckcond.py --stock /path/to/complete-factory.bin --out /path/to/output --variant v8
python3 build_ckcond.py --stock /path/to/complete-factory.bin --out /path/to/output --variant revised
python3 run_tests.py --stock /path/to/complete-factory.bin --out /path/to/results
```

The optional `--legacy-capture-generator` test argument can point to the
historical `capture_wrappers.py` in the internal archive to reproduce the
optimized-guard failure. Without a stock image the public test run reports
`PASS_PUBLIC_SYNTHETIC_ONLY` and explicitly lists skipped firmware suites.

## Remaining qualification gates

The minimal missing evidence is specific: demonstrate exclusive unaliased
SRAM for `4D00..4DFF`/`4E00..4E1F`; qualify code-cave loading/execution and
SPI recovery; measure worst-case stack/interrupt behavior; establish atomic
completion-bank provenance across actual ports and protocols; and observe
real reset/abort scheduling through CSW or command cancellation. Only after
those gates should modified firmware face controlled hardware commands.
The supplied tooling performs none of these hardware operations automatically.
