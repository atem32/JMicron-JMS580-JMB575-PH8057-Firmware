# PH8057 OEM reference — independently corrected

## Verdict and scope

The PH8057 OEM map is supported at the level of **specific instructions, data copies, branch conditions and protocol fields**. It is not a complete physical register specification for JMS580 or JMB575. The decoder, 512-row atlas and 32-bit flag table supplied with this project replace the successive historical tables. Unknown bytes remain unknown.

This audit corrected a wrong retry bound in the F8 transfer analysis, a swapped USB setup-field fixture in the v16 tests, and several gaps between zero-initialized/stubbed tests and the broader state transitions they were sometimes used to describe. It also separates public, redacted output from the private atlas containing the unit serial number. It did **not** identify a proven malfunction of the enabled stock OEM settings that can be safely repaired merely by changing an OEM flag. No OEM settings or optional functions were enabled.

The current canonical native suite executes **19,790 bounded checks** against original factory instructions. The historical v23–v29 and final audits were separately replayed without changing their expected values: all **33,816 reported check units** pass with the corrected common emulator. Their count is heterogeneous and overlapping; see the count audit below. None of these runs accesses a device.

### Exact image and address spaces

| Item | Value |
|---|---|
| Complete factory image size | `0x11200` / 70,144 bytes |
| Factory SHA256 | `ef5ad9af3f3b290c565a4dc65933d539b7bb8b8051ac9bd45386932a77862c09` |
| CODE file range | `0x01000–0x10FFF` |
| CODE CPU range | `0x0000–0xFFFF` |
| OEM file range | `0x11000–0x111FF` |
| OEM size | 512 bytes |
| OEM SHA256 | `9521e63007a1289846438195896ef2908a6ccd695c983f90b54fd501eb00e635` |
| Nonzero OEM bytes | 77 |
| Factory flag bytes | `E7=00`, `F2=38`, `F3=40`, `F8=00` |
| OEM timer input | `F4..F7=00000005`, big-endian |
| First-half boot staging | `XDATA 3900–39FF`, as used by the verified software parser |

An OEM offset, CPU address, IRAM bit address and XDATA/MMIO address are different namespaces. For example, OEM `E7` is a byte at file `0x110E7`; the operand `E7h` in an 8051 bit instruction names accumulator bit 7. `IRAM bit39h` means byte `27h`, bit 1. It is not XDATA `0039` or OEM offset `39`.

### Evidence categories

| Category | Meaning |
|---|---|
| `CONFIRMED` | A concrete supplied artifact or hardware observation is established; its scope must be stated. |
| `CODE-CONFIRMED` | Original instructions establish the stated software effect under the stated entry conditions. |
| `HYPOTHESIS` | A plausible interpretation requiring an additional contract, observation or specification. |
| `UNKNOWN` | No sufficient independent meaning is established. |
| `NOT USED IN VERIFIED PATH` | A specified slice does not consume the field individually; this is not a global non-use claim. |

All 512 offsets and all 32 option bits have explicit categories in the machine-readable tables. A zero byte, absence of a direct `MOV DPTR` reference, or a passing synthetic test does not establish that a location is reserved or safe scratch storage.

## Corrections established in this audit

### F8.7 retry behavior: twelve transfers, not ten

The earlier v27 and final OEM reports described the `77DA` copy/verify loop as permitting up to ten attempts. That is incorrect.

The entry sequence `77E2–77E8` clears `4BC4` and `4BC5` once. A mismatch at `7838–783D` sets `4BC4=1`. At `7851` the code executes `SETB C`, followed by `SUBB A,#0A` at `7852`; the branch tests whether the **old** counter is greater than ten. The transfer and comparison have already run before this test. With a persistent mismatch, the code therefore performs **12 copies**, exits with `4BC5=11`, and retains `4BC4=1`.

The mismatch latch is not cleared at the beginning of a retry. A failure on the first comparison followed by successful comparisons also performs 12 copies and retains the flag. Native instruction execution with an injected comparison-read fault proves the following software behavior:

| Assumed comparison results | Actual copies | Final `4BC5` | Final `4BC4` |
|---|---:|---:|---:|
| Success immediately | 1 | 1 | 0 |
| Failure on every comparison | 12 | 11 | 1 |
| First comparison fails, subsequent comparisons succeed | 12 | 11 | 1 |

The corrected `retry_77da_model()` matches the native loop and has a regression explicitly disproving the old ten-attempt claim. This is an analysis/model correction, not a firmware retry-policy repair.

The caller at `C4F9` invokes `77DA`, then unconditionally calls `71C4(R7=80)` at `C4FE`; it does not inspect `4BC4`. The helper `71C4(80)` writes controller registers in the `72xx` region without consuming that flag. The code establishes extra transfers and a retained diagnostic state; it does not establish the externally observable consequence, the intended retry policy, or whether those window accesses are idempotent. Stock `F8=00` does not enter this optional path. Changing the machine code without the window/controller contract would introduce an unsupported functional choice, so this release preserves it and documents the exact behavior.

### Stubbed call traces are not callee state-preservation proofs

The earlier F8 dispatcher tests replace `7616`, `77DA` and `71C4` with returning stubs. Their logged `R6` values correctly describe that fixture, but do not describe the real callee effects.

The new full native `C4D3` chain executes the actual `71C4`, `7616`, `77DA`, `800A` and `8026` instructions; only the explicit peripheral command/wait/control helpers remain stubbed. After `7616(02)`, `R6=1A`; after a successful `77DA(7300)` comparison, `R6=01`. The old return-only stubs instead leave `R6=00` or `73`. The real paths also leave the interrupt-enable bit set. `71C4` consumes `R7`, so this difference is not evidence of a functional bug in the factory code. It is a concrete reason to avoid promoting an old stub trace into a native ABI or interrupt-state guarantee.

### Stateful F2 effects

The old F2 enumeration starts with zeroed RAM. It proves the listed outputs for that initial state. The instruction slice is not a general assignment of all seven outputs from the flag byte.

| Output in `214A–2199` | Flag set | Flag clear |
|---|---|---|
| `44F3` from F2.3 | Write 1 | Write 0 |
| `487D` from F2.3 | Write 1 | Preserve prior value |
| `4583` from F2.4 | Write 1 | Preserve prior value |
| `4584` from F2.5 | Write 1 | Preserve prior value |
| `4588` from F2.2 | Write 1 | Preserve prior value |
| IRAM bit 39 from F2.6 | Set | Preserve prior bit |
| IRAM bit 3A from F2.7 | Set | Preserve prior bit |

Earlier code in `1F49` clears `4588`, bit 39 and bit 3A. The new tests exercise the whole initializer as well as the isolated slice with deliberately nonzero prior state. The corrected decoder exposes a state-transition model and does not mistake a clean boot fixture for arbitrary runtime overwrite behavior. Similarly, the E7.5 path at `3A2D` preserves `4575` when it does not publish a new event; it does not assign zero merely because the condition is false.

This does not prove a stock boot defect. It corrects the scope and implementation of the analysis model.

### USB setup fixture field order

The v16 GET_MAX_LUN harness named `IRAM 1C/1D` as wValue and `1A/1B` as wIndex. The names were reversed. The established internal representation is:

| USB setup field | Internal high byte | Internal low byte |
|---|---|---|
| wValue | `1A` | `1B` |
| wIndex | `1C` | `1D` |
| wLength | `1E` | `1F` |

USB wire words are little-endian; this table describes the firmware's decoded IRAM representation. The canonical `setup_iram()` implementation and asymmetric native tests fix the mapping. A GET_MAX_LUN request with wValue=1 and wIndex=0 passes the `D970` recognizer and is rejected by `C702`. A nonzero wIndex is rejected already by `D970`. The old tests checked the final rejection result for both fields, so the mistake was hidden by the symmetric requirement that both be zero.

### Public serial redaction

The earlier prose avoided printing the serial string while its 512-byte CSV and full OEM hex still exposed the individual bytes. Public decoder output now redacts the entire serial payload area `056–077`. The private atlas retains every original byte. Hashes and offset coverage are preserved in both versions. Public CI uses a clearly synthetic serial fixture.

## Whole-region layout and signature gates

The complete byte map is `oem_512_bytes.csv` / `oem_512_bytes.json`; all 512 rows are generated from the canonical metadata. The principal ranges are:

| OEM range | Established interpretation |
|---|---|
| `000–003` | Little-endian USB VID/PID; copied in the required internal order to `44EC–44EF`. |
| `004–005` | Independent OEM use unknown. Raw references to `3904` elsewhere are not automatically OEM references: `98B6` first loads another controller buffer into `3900`. |
| `006–007` | Copied to `44E6–44E7`; independent protocol meaning unassigned. |
| `008` | Serial source selection: value 5 sets `44E8=0`; 7 sets it to 1; other values use an available OEM serial and set it to 2. |
| `009`, `00B` | Individual meaning unknown. |
| `00A` | `0A` permits the custom SCSI INQUIRY copies. |
| `00C–02F` | Manufacturer packed ASCII storage and length hint; 32 payload bytes copied. |
| `030–053` | Product packed ASCII storage and length hint; 32 payload bytes copied. |
| `054–077` | Serial packed ASCII storage and length hint; 30 payload bytes copied. |
| `078–0C7` | Zero in stock; individual function unknown. |
| `0C8–0CF` | Eight-byte SCSI INQUIRY vendor field. |
| `0D0–0DF` | Sixteen-byte SCSI INQUIRY product field. |
| `0E0–0E1` | `HD` signature. |
| `0E2–0E6`, `0E8–0EF` | Individual meaning unknown. |
| `0E7` | E7 flags. |
| `0F0–0F1` | `BC` signature. |
| `0F2`, `0F3`, `0F8` | F2, F3, F8 flags. |
| `0F4–0F7` | Big-endian timer input. |
| `0F9`, `0FD` | No individual decoder established; may travel in the F8.7 block. |
| `0FA–0FC` | Three independently traced auxiliary fields described below. |
| `0FE–0FF` | `JM` signature. |
| `100–1FF` | Second half; stock all zero, role unknown. Not included in the verified F8 256-byte transfer. |

The **JM** signature is the outer initializer gate; a mismatch invokes the default-data handler at `9D1C`. **HD** independently gates the E7 and F3 copies plus the E7.5 action. **BC** gates F2, the timer transformation, F8, FA, FB and FC. A valid HD marker does not imply a valid BC group, and vice versa. These boundaries are tested through the original initializer with invalid markers, not inferred only from byte searches.

The string slots are not literal UTF-16LE string descriptors. They contain compact ASCII payloads and a USB-style wire-length hint. `E1EB` computes `((length−2) & 0xFF) >> 1`; the loader then performs its own terminator/copy logic. The bytes with value `03` at `00D`, `031`, `055` are not read or checked by this initializer. The atlas therefore labels that narrow fact `NOT USED IN VERIFIED PATH`, while leaving possible block/other consumers open. Malformed length hints are reported explicitly by the decoder, without an out-of-bounds host read.

## E7 — all eight bits

| Bit | Stock | Verified software effect and limit |
|---|---:|---|
| 0 | 0 | USB configuration power reporting at `454B–457F`: self-powered vs bus-powered attributes and MaxPower values. This does not switch electrical power rails. |
| 1 | 0 | Sets IRAM bit 38, consumed by special READ(16)/WRITE(16) handling. No general 4Kn or multisector-enable claim is made. |
| 2 | 0 | Cleared at `6F5D` before following local tests. Earlier/other consumers remain possible. |
| 3 | 0 | Enables `7085=2F`, `508F=01` at `D422`; physical mode unknown. |
| 4 | 0 | Advertises DPOFUA in MODE SENSE headers via `4BC8`. This does not validate FUA data durability. A later E7 branch can also clear the UAS gate. |
| 5 | 0 | Sets `4172`; a later path consults `7A04/7A05` and conditionally writes `4575=3`. Inactive path preserves old state. |
| 6 | 0 | Gates UAS descriptor construction at `44C4`. Cleared at `6F57` and `46ED`. UASP is not implemented or qualified by setting this flag. |
| 7 | 0 | At `D682`, `5082` bits 1/2 follow this flag; bit 3 is set in both branches. Cleanup at `5535`, `6631`, `7BED` clears bits 1/2 independently. |

Power-report byte values are exact CODE facts: with the internal speed-mode bit clear, stock self-powered reporting uses `bmAttributes=C0,bMaxPower=0F`, while bus-powered reporting uses `80,FA`; with that mode bit set, the respective MaxPower values are `01` and `70`. Applying the appropriate USB specification units is separate from measuring real consumption.

The E7.7 distinction was already corrected by historical v29, after v27/v28's broader “bits 1–3 init option” label. The canonical atlas preserves that correction and independently repeats exact-mask and cleanup execution. It is recorded as historical consolidation, not a newly discovered defect.

## F2 — all eight bits

| Bit | Stock | Verified software effect and limit |
|---|---:|---|
| 0 | 0 | No individual effect in `214A–2199`; global/indirect use not excluded. |
| 1 | 0 | Same bounded non-use result as bit 0. |
| 2 | 0 | Sets `4588`, with a prior explicit clear at `1F7C`; used by further state/event branches. |
| 3 | 1 | Assigns `44F3`, conditionally sets `487D`, and enables the timer transformation. |
| 4 | 1 | Sets `4583`; controls `7058.bit5` according to dispatcher state. |
| 5 | 1 | Sets `4584`; controls `7058.bit4` according to dispatcher state. |
| 6 | 0 | Sets IRAM bit 39. At `64B7`, a zero bit causes `7801 |=10`; a set bit preserves the register in that slice. With the preceding `7801=41`, results are `51` and `41`. |
| 7 | 0 | Sets IRAM bit 3A, byte 27.bit 2. Whole byte 27 is saved/restored through `B008`. No independent functional bit reader is proven. |

The `3F61` dispatcher has eight tested input states. Bits 4/5 of `7058` are not immutable copies of F2. For states 0/3/4/6, bit 4 follows F2.5; state 5 clears it; states1/2/7 preserve it. If F2.4 is enabled, bit 5 is set in states0/5/6 and cleared in 3/4; otherwise this specific control does not assign it. The related `702A` and four port-context bytes are checked as side effects.

## F3 — all eight bits

| Bit | Stock | Verified software effect and limit |
|---|---:|---|
| 0 | 0 | Affects event/topology paths, but is cleared at `6F62`. It is not a safe hot-swap toggle. |
| 1 | 0 | JM vendor-response indicators and a `7059.bit1` status path. Private protocol semantics remain incomplete. |
| 2 | 0 | If `7086==0`, arms `4176=4177=1`; the JM report path sets `3506.bit0` and clears `4177`. |
| 3 | 0 | No individual direct bit decoder established; full-byte/indirect use not excluded. |
| 4 | 0 | Filters one event subtype from `7993`: with high nibble0 and low2=0, clear bit 4 leads to `4BC9=2E,4AD8=1,4173=0`; set bit 4 skips it. Subtype1 is unaffected. |
| 5 | 0 | USB2-only software policy: state 6, `bcdUSB=0200`, and suppressed BOS response. Physical link behavior is not qualified. |
| 6 | 1 | TRIM/DSM capability gate with IDENTIFY word169/word105 and per-port status checks. Does not prove successful discard on a particular disk. |
| 7 | 0 | Additional NCQ enable in a no-Port-Multiplier branch, conditioned on IDENTIFY words75/76. It is not the sole global NCQ switch. |

## F8, F4–F7 and F9–FD

F8 bits 0–5 do not independently dispatch the verified `C4D3–C501` calls. Their global meaning remains unknown. Bit 6 selects the `CODE 1A18–1B17 -> XDATA 7500–75FF` copy via `7616(02)`. Bit 7 selects `XDATA 3900–39FF ->7300–73FF` via `77DA(7300)`, followed by comparison. The latter copies the current staging buffer, which must not be universally assumed immutable after parsing. Both windows have an unknown physical role; neither is identified as SPI merely from these accesses.

`F4–F7` are transformed by original 32-bit arithmetic:

`runtime = (10 × max(180, OEM_BE32)) modulo 2^32`.

The stock input 5 therefore becomes 1800 in both `44F4–44F7` and `4881–4884`. The MODE SENSE Power Condition page returns that runtime value for Current and Saved, `18000` for Default, and `FFFFFFFF` for Changeable. On the SCSI wire, SZCT uses 100 ms units: 1800 encodes180 seconds. This does not prove the actual hardware tick rate or spindle-stop time. Current and Saved sharing a RAM field also does not establish nonvolatile persistence.

A deliberately oversized OEM input can wrap the multiplication: `0x1999999A` yields4. The canonical decoder exposes `arithmetic_wraps`; it does not silently interpret this as a sensible timer setting or emit a modified OEM image. The supported OEM input range is not documented, and stock 5 does not approach overflow, so this observation is not reported as a proven stock malfunction.

MODE SELECT parsing stages the runtime value in `4BA0–4BA3`, with a later scheduled commit to `4881–4884`. Tests supply `70C0` responses explicitly. Values 1 and 2 lead to replacement values 288000 and 600 on the examined path. The observations are consistent with a compare/clamp command interface, but the silicon contract remains a hypothesis. They do not make `70C0–70C3` universally valid transfer counters.

| Field | Stock | Verified chain | Limit |
|---|---:|---|---|
| F9 | `0F` | Included in the first-half block if F8.7 executes | Independent decoder unknown |
| FA | `32` | `39FA ->4174 ->7E18` after valid USB SET_ADDRESS; later readback branch | No proven time unit |
| FB | `05` | `39FB ->4175 ->7086`; F3.2 conditions event reporting on zero | Physical event meaning unknown |
| FC | `00` | Strictly greater than `20` overrides `4AD6`; copied to `4A18`; decremented if `7075>100` | Tick source unknown; separate from SZCT |
| FD | `00` | Included in first-half block if F8.7 executes | Independent decoder unknown |

The MMIO dependency table explicitly covers `7801`, `7058`, `5082`, `7085`, `7086`, `7E18`, `70B0–70B8`, `70C0–70C8`, `7075`, `7300–73FF`, and `7500–75FF`. Adjacent unknown registers are not assigned invented meanings.

## Second half and donor evidence

The stock second half (`100–1FF`) contains 256 zero bytes. One supplied BIWIN donor has 196 nonzero bytes there. That rules out the claim that this region is universally empty/reserved across the supplied JMS580 images, but it does not decode the donor's contents or prove that PH8057 executes an associated path.

The nine donor images use a different full-file layout: size `0x10600`, CODE at `0x0400`, OEM at `0x10400`. Their offsets cannot be transplanted into PH8057. Their shared constants `F9=0F,FA=32,FB=05,FC=00,FD=00` are correlations, not a register specification. Original and donor BIN files are private inputs, not redistributed in the public project.

## What the 33,816 historical units actually mean

All historical expected values were retained and passed when re-executed with the corrected canonical emulator. This confirms reproducibility of their conditional software results. It does not upgrade assumptions about MMIO, scheduling, interrupt delivery, DMA, electrical conditions, or persistent storage into hardware evidence.

The reports mix different counters. For example, v25 increments one scenario counter after a MODE SENSE case whose helper performs five boolean checks. Additional copy-ABI guards are also executed without incrementing that scenario counter. Identity-only AST instrumentation measured the following executed `assert` statements and boolean `check`/`ok`/`test_case` guards, excluding emulator internals:

| Historical suite | Reported units | Executed instrumented guards |
|---|---:|---:|
| v23 | 1,577 | 1,583 |
| v24 | 2,296 | 3,007 |
| v25 | 1,985 | 10,374 |
| v26 | 7,981 | 9,270 |
| v27 | 2,164 | 2,164 |
| v28 | 5,903 | 5,903 |
| v29 | 10,005 | 10,005 |
| final | 1,905 | 1,905 |
| **Total** | **33,816** | **44,211** |

Neither total is a coverage percentage. A coarse classification of the reported units is:

| Dominant proof method | Reported units |
|---|---:|
| Native instruction execution with supplied synthetic memory/register state | 28,635 |
| Native surrounding code with a host-side `800A` copy fixture | 2,624 |
| Native code with peripheral/callee return stubs | 2,316 |
| Static bytes, schema/bookkeeping, or raw-pattern scans | 241 |

There are real native instruction executions here, so dismissing all tests as pure Python tautologies would also be incorrect. However, the expected formulas were generally derived from the same reverse-engineered code, and the memory/peripheral values were supplied by the harness. A test that forces completion or a counter value cannot independently prove that real hardware generates it. Repetition across versions and multiple assertions on the same invocation further prevent treating the number as independent test coverage.

The new regressions address missed cases rather than merely enlarging the count: full initializer control flow, invalid signature groups, dirty prior state, native dual-DPTR copies, real callee clobbers, injected transient/persistent comparison failures, asymmetric USB setup fields, and public serial redaction.

## Reproduction and remaining limits

With a private copy of the exact stock image and the common emulator on the Python path:

```bash
PYTHONPATH=tools/emulator:tools/analysis python3 tools/analysis/oem.py \
  /path/to/PH8057_FACTORY_COMPLETE_READBACK_DO_NOT_FLASH.bin --out results/oem

PYTHONPATH=tools/emulator:tools/analysis python3 tools/analysis/native_oem.py \
  /path/to/PH8057_FACTORY_COMPLETE_READBACK_DO_NOT_FLASH.bin --out results/oem_native.json
```

The regular-file/size/hash gates prevent applying these exact-address conclusions to an unrelated image. Pure decoder tests use synthetic data and can run in public CI without proprietary firmware. Native tests require explicitly supplying the private image; a skip is recorded as a skip, not a pass.

The legacy replay wrappers retain original expected values and run temporary copies; v20 requires only a documented replacement of its historical hardcoded `/mnt/data` location. The original files remain unchanged. v15–v22 replay results, the 33,816 replay, native results and count audit have separate logs and provenance records.

No new hardware validation was performed. The unresolved physical meanings of private registers, peripheral timing, dual-DPTR silicon behavior outside the verified ABI, interrupt concurrency, complete boot execution, SPI persistence, and optional F8 controller-window behavior remain explicit limits. UASP and hot-swap remain **NOT IMPLEMENTED**. No inference in this atlas authorizes a flash operation or an OEM configuration change.

### Sources within the supplied evidence

Every CPU address above refers to the exact SHA256-identified factory CODE. The principal source artifacts are `FINAL_OEM_REPORT_2026-11-02.md`, the v23–v29 scripts and their original result JSON, the v16 hotplug audit, and the supplied factory/donor BINs. Fresh reproducibility evidence is the canonical `native_oem.json`, the legacy replay summaries, `count_audit.json`, and `classification.json`. Protocol field names should be read with the USB and SCSI primary references listed in the repository's references document; no external register map is assumed.


### Independent primary protocol references

The SZCT unit is independently supported by Seagate's [SCSI Commands Reference Manual, Rev. J, section 5.3.20, page 424](https://www.seagate.com/files/staticfiles/support/docs/manual/Interface%20manuals/100293068j.pdf): its standby_z timer field uses 100 ms units. This establishes the SCSI surface interpretation; it does not measure this bridge's physical timer.

The speed-dependent bMaxPower units are also documented by Infineon's [ModusToolbox USB Configurator user guide, 002-24357 Rev. Q, version-history entry 2.51, page 12](https://www.infineon.com/assets/row/public/documents/30/44/infineon-modustoolbox-usb-configurator-user-guide-usermanual-en.pdf): 2 mA at high speed and 8 mA at Gen X speed. The factory descriptor bytes are decoded using the corresponding speed; no actual current consumption is inferred.

## Appendix A — complete 512-byte atlas
Every row below is generated directly from the current `research/oem/oem_512_bytes.json`. Offsets and CPU addresses are hexadecimal. Unit-serial bytes remain redacted. A category describes the stated software effect only; an unknown individual meaning can coexist with a verified block copy. Offsets `000–0FF` participate in the conditional F8.7 copy of staging `3900–39FF`; offsets `100–1FF` are outside that verified copy.

### OEM 000–03F

| OEM offset | BIN offset | Stock byte | Category | Effect / evidence boundary | CPU evidence |
|---|---|---|---|---|---|
| 000 | 11000 | 2D | CODE-CONFIRMED | USB VID, little-endian; reordered into 44EC/44ED | 1FBB,1FC3 |
| 001 | 11001 | 15 | CODE-CONFIRMED | USB VID, little-endian; reordered into 44EC/44ED | 1FBB,1FC3 |
| 002 | 11002 | 62 | CODE-CONFIRMED | USB PID, little-endian; reordered into 44EE/44EF | 1FCB,1FD3 |
| 003 | 11003 | A5 | CODE-CONFIRMED | USB PID, little-endian; reordered into 44EE/44EF | 1FCB,1FD3 |
| 004 | 11004 | 00 | UNKNOWN | No verified OEM boot consumer; 3904 comparison at 98E9 is a different staging-buffer context | 98E9 is not established OEM provenance |
| 005 | 11005 | 00 | UNKNOWN | No verified OEM boot consumer; 3904 comparison at 98E9 is a different staging-buffer context | 98E9 is not established OEM provenance |
| 006 | 11006 | 0A | CODE-CONFIRMED | Copied from 3906 to 44E6; physical/protocol meaning unassigned | 1FAB |
| 007 | 11007 | 0B | CODE-CONFIRMED | Copied from 3907 to 44E7; physical/protocol meaning unassigned | 1FB3 |
| 008 | 11008 | 03 | CODE-CONFIRMED | Serial source selector: 5 -> 44E8=0, 7 -> 44E8=1; otherwise nonempty OEM serial -> 44E8=2 | 2061-20E6 |
| 009 | 11009 | 01 | UNKNOWN | No individual OEM consumer established |  |
| 00A | 1100A | 0A | CODE-CONFIRMED | 0A enables custom SCSI INQUIRY vendor/product block copies | 20E6-210D |
| 00B | 1100B | 00 | UNKNOWN | No individual OEM consumer established |  |
| 00C | 1100C | 1A | CODE-CONFIRMED | Manufacturer packed-string wire-length hint; ASCII storage, not UTF-16LE | 1FDB-201E,E1EB |
| 00D | 1100D | 03 | NOT USED IN VERIFIED PATH | Value 03 resembles USB STRING type; this OEM loader does not read/validate it | 1FDB-201E |
| 00E | 1100E | 50 | CODE-CONFIRMED | Manufacturer ASCII storage; 32 bytes copied to 4511..4530 | 2011-201B |
| 00F | 1100F | 41 | CODE-CONFIRMED | Manufacturer ASCII storage; 32 bytes copied to 4511..4530 | 2011-201B |
| 010 | 11010 | 4E | CODE-CONFIRMED | Manufacturer ASCII storage; 32 bytes copied to 4511..4530 | 2011-201B |
| 011 | 11011 | 48 | CODE-CONFIRMED | Manufacturer ASCII storage; 32 bytes copied to 4511..4530 | 2011-201B |
| 012 | 11012 | 4F | CODE-CONFIRMED | Manufacturer ASCII storage; 32 bytes copied to 4511..4530 | 2011-201B |
| 013 | 11013 | 4E | CODE-CONFIRMED | Manufacturer ASCII storage; 32 bytes copied to 4511..4530 | 2011-201B |
| 014 | 11014 | 47 | CODE-CONFIRMED | Manufacturer ASCII storage; 32 bytes copied to 4511..4530 | 2011-201B |
| 015 | 11015 | 2D | CODE-CONFIRMED | Manufacturer ASCII storage; 32 bytes copied to 4511..4530 | 2011-201B |
| 016 | 11016 | 54 | CODE-CONFIRMED | Manufacturer ASCII storage; 32 bytes copied to 4511..4530 | 2011-201B |
| 017 | 11017 | 45 | CODE-CONFIRMED | Manufacturer ASCII storage; 32 bytes copied to 4511..4530 | 2011-201B |
| 018 | 11018 | 43 | CODE-CONFIRMED | Manufacturer ASCII storage; 32 bytes copied to 4511..4530 | 2011-201B |
| 019 | 11019 | 48 | CODE-CONFIRMED | Manufacturer ASCII storage; 32 bytes copied to 4511..4530 | 2011-201B |
| 01A | 1101A | 00 | CODE-CONFIRMED | Manufacturer ASCII storage; 32 bytes copied to 4511..4530 | 2011-201B |
| 01B | 1101B | 00 | CODE-CONFIRMED | Manufacturer ASCII storage; 32 bytes copied to 4511..4530 | 2011-201B |
| 01C | 1101C | 00 | CODE-CONFIRMED | Manufacturer ASCII storage; 32 bytes copied to 4511..4530 | 2011-201B |
| 01D | 1101D | 00 | CODE-CONFIRMED | Manufacturer ASCII storage; 32 bytes copied to 4511..4530 | 2011-201B |
| 01E | 1101E | 00 | CODE-CONFIRMED | Manufacturer ASCII storage; 32 bytes copied to 4511..4530 | 2011-201B |
| 01F | 1101F | 00 | CODE-CONFIRMED | Manufacturer ASCII storage; 32 bytes copied to 4511..4530 | 2011-201B |
| 020 | 11020 | 00 | CODE-CONFIRMED | Manufacturer ASCII storage; 32 bytes copied to 4511..4530 | 2011-201B |
| 021 | 11021 | 00 | CODE-CONFIRMED | Manufacturer ASCII storage; 32 bytes copied to 4511..4530 | 2011-201B |
| 022 | 11022 | 00 | CODE-CONFIRMED | Manufacturer ASCII storage; 32 bytes copied to 4511..4530 | 2011-201B |
| 023 | 11023 | 00 | CODE-CONFIRMED | Manufacturer ASCII storage; 32 bytes copied to 4511..4530 | 2011-201B |
| 024 | 11024 | 00 | CODE-CONFIRMED | Manufacturer ASCII storage; 32 bytes copied to 4511..4530 | 2011-201B |
| 025 | 11025 | 00 | CODE-CONFIRMED | Manufacturer ASCII storage; 32 bytes copied to 4511..4530 | 2011-201B |
| 026 | 11026 | 00 | CODE-CONFIRMED | Manufacturer ASCII storage; 32 bytes copied to 4511..4530 | 2011-201B |
| 027 | 11027 | 00 | CODE-CONFIRMED | Manufacturer ASCII storage; 32 bytes copied to 4511..4530 | 2011-201B |
| 028 | 11028 | 00 | CODE-CONFIRMED | Manufacturer ASCII storage; 32 bytes copied to 4511..4530 | 2011-201B |
| 029 | 11029 | 00 | CODE-CONFIRMED | Manufacturer ASCII storage; 32 bytes copied to 4511..4530 | 2011-201B |
| 02A | 1102A | 00 | CODE-CONFIRMED | Manufacturer ASCII storage; 32 bytes copied to 4511..4530 | 2011-201B |
| 02B | 1102B | 00 | CODE-CONFIRMED | Manufacturer ASCII storage; 32 bytes copied to 4511..4530 | 2011-201B |
| 02C | 1102C | 00 | CODE-CONFIRMED | Manufacturer ASCII storage; 32 bytes copied to 4511..4530 | 2011-201B |
| 02D | 1102D | 00 | CODE-CONFIRMED | Manufacturer ASCII storage; 32 bytes copied to 4511..4530 | 2011-201B |
| 02E | 1102E | 00 | UNKNOWN | String-slot tail outside verified 32-byte manufacturer copy |  |
| 02F | 1102F | 00 | UNKNOWN | String-slot tail outside verified 32-byte manufacturer copy |  |
| 030 | 11030 | 18 | CODE-CONFIRMED | Product packed-string wire-length hint; ASCII storage, not UTF-16LE | 201E-2061,E1EB |
| 031 | 11031 | 03 | NOT USED IN VERIFIED PATH | Value 03 resembles USB STRING type; this OEM loader does not read/validate it | 201E-2061 |
| 032 | 11032 | 55 | CODE-CONFIRMED | Product ASCII storage; 32 bytes copied to 4531..4550 | 2054-205E |
| 033 | 11033 | 53 | CODE-CONFIRMED | Product ASCII storage; 32 bytes copied to 4531..4550 | 2054-205E |
| 034 | 11034 | 42 | CODE-CONFIRMED | Product ASCII storage; 32 bytes copied to 4531..4550 | 2054-205E |
| 035 | 11035 | 33 | CODE-CONFIRMED | Product ASCII storage; 32 bytes copied to 4531..4550 | 2054-205E |
| 036 | 11036 | 2D | CODE-CONFIRMED | Product ASCII storage; 32 bytes copied to 4531..4550 | 2054-205E |
| 037 | 11037 | 53 | CODE-CONFIRMED | Product ASCII storage; 32 bytes copied to 4531..4550 | 2054-205E |
| 038 | 11038 | 41 | CODE-CONFIRMED | Product ASCII storage; 32 bytes copied to 4531..4550 | 2054-205E |
| 039 | 11039 | 54 | CODE-CONFIRMED | Product ASCII storage; 32 bytes copied to 4531..4550 | 2054-205E |
| 03A | 1103A | 41 | CODE-CONFIRMED | Product ASCII storage; 32 bytes copied to 4531..4550 | 2054-205E |
| 03B | 1103B | 58 | CODE-CONFIRMED | Product ASCII storage; 32 bytes copied to 4531..4550 | 2054-205E |
| 03C | 1103C | 35 | CODE-CONFIRMED | Product ASCII storage; 32 bytes copied to 4531..4550 | 2054-205E |
| 03D | 1103D | 00 | CODE-CONFIRMED | Product ASCII storage; 32 bytes copied to 4531..4550 | 2054-205E |
| 03E | 1103E | 00 | CODE-CONFIRMED | Product ASCII storage; 32 bytes copied to 4531..4550 | 2054-205E |
| 03F | 1103F | 00 | CODE-CONFIRMED | Product ASCII storage; 32 bytes copied to 4531..4550 | 2054-205E |

### OEM 040–07F

| OEM offset | BIN offset | Stock byte | Category | Effect / evidence boundary | CPU evidence |
|---|---|---|---|---|---|
| 040 | 11040 | 00 | CODE-CONFIRMED | Product ASCII storage; 32 bytes copied to 4531..4550 | 2054-205E |
| 041 | 11041 | 00 | CODE-CONFIRMED | Product ASCII storage; 32 bytes copied to 4531..4550 | 2054-205E |
| 042 | 11042 | 00 | CODE-CONFIRMED | Product ASCII storage; 32 bytes copied to 4531..4550 | 2054-205E |
| 043 | 11043 | 00 | CODE-CONFIRMED | Product ASCII storage; 32 bytes copied to 4531..4550 | 2054-205E |
| 044 | 11044 | 00 | CODE-CONFIRMED | Product ASCII storage; 32 bytes copied to 4531..4550 | 2054-205E |
| 045 | 11045 | 00 | CODE-CONFIRMED | Product ASCII storage; 32 bytes copied to 4531..4550 | 2054-205E |
| 046 | 11046 | 00 | CODE-CONFIRMED | Product ASCII storage; 32 bytes copied to 4531..4550 | 2054-205E |
| 047 | 11047 | 00 | CODE-CONFIRMED | Product ASCII storage; 32 bytes copied to 4531..4550 | 2054-205E |
| 048 | 11048 | 00 | CODE-CONFIRMED | Product ASCII storage; 32 bytes copied to 4531..4550 | 2054-205E |
| 049 | 11049 | 00 | CODE-CONFIRMED | Product ASCII storage; 32 bytes copied to 4531..4550 | 2054-205E |
| 04A | 1104A | 00 | CODE-CONFIRMED | Product ASCII storage; 32 bytes copied to 4531..4550 | 2054-205E |
| 04B | 1104B | 00 | CODE-CONFIRMED | Product ASCII storage; 32 bytes copied to 4531..4550 | 2054-205E |
| 04C | 1104C | 00 | CODE-CONFIRMED | Product ASCII storage; 32 bytes copied to 4531..4550 | 2054-205E |
| 04D | 1104D | 00 | CODE-CONFIRMED | Product ASCII storage; 32 bytes copied to 4531..4550 | 2054-205E |
| 04E | 1104E | 00 | CODE-CONFIRMED | Product ASCII storage; 32 bytes copied to 4531..4550 | 2054-205E |
| 04F | 1104F | 00 | CODE-CONFIRMED | Product ASCII storage; 32 bytes copied to 4531..4550 | 2054-205E |
| 050 | 11050 | 00 | CODE-CONFIRMED | Product ASCII storage; 32 bytes copied to 4531..4550 | 2054-205E |
| 051 | 11051 | 00 | CODE-CONFIRMED | Product ASCII storage; 32 bytes copied to 4531..4550 | 2054-205E |
| 052 | 11052 | 00 | UNKNOWN | String-slot tail outside verified 32-byte product copy |  |
| 053 | 11053 | 00 | UNKNOWN | String-slot tail outside verified 32-byte product copy |  |
| 054 | 11054 | 1C | CODE-CONFIRMED | Serial wire-length hint; (length-2)/2 stored in 480A, later clamped to >=12 | 207C-20E6,E1EB |
| 055 | 11055 | 03 | NOT USED IN VERIFIED PATH | Value 03 resembles USB STRING type; this OEM loader does not read/validate it | 207C-20E6 |
| 056 | 11056 | REDACTED | CODE-CONFIRMED | Unit-specific serial ASCII storage; 30-byte copy to 4551,480D,48C5 | 20AD-20D1 |
| 057 | 11057 | REDACTED | CODE-CONFIRMED | Unit-specific serial ASCII storage; 30-byte copy to 4551,480D,48C5 | 20AD-20D1 |
| 058 | 11058 | REDACTED | CODE-CONFIRMED | Unit-specific serial ASCII storage; 30-byte copy to 4551,480D,48C5 | 20AD-20D1 |
| 059 | 11059 | REDACTED | CODE-CONFIRMED | Unit-specific serial ASCII storage; 30-byte copy to 4551,480D,48C5 | 20AD-20D1 |
| 05A | 1105A | REDACTED | CODE-CONFIRMED | Unit-specific serial ASCII storage; 30-byte copy to 4551,480D,48C5 | 20AD-20D1 |
| 05B | 1105B | REDACTED | CODE-CONFIRMED | Unit-specific serial ASCII storage; 30-byte copy to 4551,480D,48C5 | 20AD-20D1 |
| 05C | 1105C | REDACTED | CODE-CONFIRMED | Unit-specific serial ASCII storage; 30-byte copy to 4551,480D,48C5 | 20AD-20D1 |
| 05D | 1105D | REDACTED | CODE-CONFIRMED | Unit-specific serial ASCII storage; 30-byte copy to 4551,480D,48C5 | 20AD-20D1 |
| 05E | 1105E | REDACTED | CODE-CONFIRMED | Unit-specific serial ASCII storage; 30-byte copy to 4551,480D,48C5 | 20AD-20D1 |
| 05F | 1105F | REDACTED | CODE-CONFIRMED | Unit-specific serial ASCII storage; 30-byte copy to 4551,480D,48C5 | 20AD-20D1 |
| 060 | 11060 | REDACTED | CODE-CONFIRMED | Unit-specific serial ASCII storage; 30-byte copy to 4551,480D,48C5 | 20AD-20D1 |
| 061 | 11061 | REDACTED | CODE-CONFIRMED | Unit-specific serial ASCII storage; 30-byte copy to 4551,480D,48C5 | 20AD-20D1 |
| 062 | 11062 | REDACTED | CODE-CONFIRMED | Unit-specific serial ASCII storage; 30-byte copy to 4551,480D,48C5 | 20AD-20D1 |
| 063 | 11063 | REDACTED | CODE-CONFIRMED | Unit-specific serial ASCII storage; 30-byte copy to 4551,480D,48C5 | 20AD-20D1 |
| 064 | 11064 | REDACTED | CODE-CONFIRMED | Unit-specific serial ASCII storage; 30-byte copy to 4551,480D,48C5 | 20AD-20D1 |
| 065 | 11065 | REDACTED | CODE-CONFIRMED | Unit-specific serial ASCII storage; 30-byte copy to 4551,480D,48C5 | 20AD-20D1 |
| 066 | 11066 | REDACTED | CODE-CONFIRMED | Unit-specific serial ASCII storage; 30-byte copy to 4551,480D,48C5 | 20AD-20D1 |
| 067 | 11067 | REDACTED | CODE-CONFIRMED | Unit-specific serial ASCII storage; 30-byte copy to 4551,480D,48C5 | 20AD-20D1 |
| 068 | 11068 | REDACTED | CODE-CONFIRMED | Unit-specific serial ASCII storage; 30-byte copy to 4551,480D,48C5 | 20AD-20D1 |
| 069 | 11069 | REDACTED | CODE-CONFIRMED | Unit-specific serial ASCII storage; 30-byte copy to 4551,480D,48C5 | 20AD-20D1 |
| 06A | 1106A | REDACTED | CODE-CONFIRMED | Unit-specific serial ASCII storage; 30-byte copy to 4551,480D,48C5 | 20AD-20D1 |
| 06B | 1106B | REDACTED | CODE-CONFIRMED | Unit-specific serial ASCII storage; 30-byte copy to 4551,480D,48C5 | 20AD-20D1 |
| 06C | 1106C | REDACTED | CODE-CONFIRMED | Unit-specific serial ASCII storage; 30-byte copy to 4551,480D,48C5 | 20AD-20D1 |
| 06D | 1106D | REDACTED | CODE-CONFIRMED | Unit-specific serial ASCII storage; 30-byte copy to 4551,480D,48C5 | 20AD-20D1 |
| 06E | 1106E | REDACTED | CODE-CONFIRMED | Unit-specific serial ASCII storage; 30-byte copy to 4551,480D,48C5 | 20AD-20D1 |
| 06F | 1106F | REDACTED | CODE-CONFIRMED | Unit-specific serial ASCII storage; 30-byte copy to 4551,480D,48C5 | 20AD-20D1 |
| 070 | 11070 | REDACTED | CODE-CONFIRMED | Unit-specific serial ASCII storage; 30-byte copy to 4551,480D,48C5 | 20AD-20D1 |
| 071 | 11071 | REDACTED | CODE-CONFIRMED | Unit-specific serial ASCII storage; 30-byte copy to 4551,480D,48C5 | 20AD-20D1 |
| 072 | 11072 | REDACTED | CODE-CONFIRMED | Unit-specific serial ASCII storage; 30-byte copy to 4551,480D,48C5 | 20AD-20D1 |
| 073 | 11073 | REDACTED | CODE-CONFIRMED | Unit-specific serial ASCII storage; 30-byte copy to 4551,480D,48C5 | 20AD-20D1 |
| 074 | 11074 | REDACTED | UNKNOWN | Serial-slot tail outside verified 30-byte serial copy |  |
| 075 | 11075 | REDACTED | UNKNOWN | Serial-slot tail outside verified 30-byte serial copy |  |
| 076 | 11076 | REDACTED | UNKNOWN | Serial-slot tail outside verified 30-byte serial copy |  |
| 077 | 11077 | REDACTED | UNKNOWN | Serial-slot tail outside verified 30-byte serial copy |  |
| 078 | 11078 | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 079 | 11079 | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 07A | 1107A | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 07B | 1107B | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 07C | 1107C | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 07D | 1107D | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 07E | 1107E | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 07F | 1107F | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |

### OEM 080–0BF

| OEM offset | BIN offset | Stock byte | Category | Effect / evidence boundary | CPU evidence |
|---|---|---|---|---|---|
| 080 | 11080 | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 081 | 11081 | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 082 | 11082 | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 083 | 11083 | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 084 | 11084 | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 085 | 11085 | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 086 | 11086 | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 087 | 11087 | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 088 | 11088 | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 089 | 11089 | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 08A | 1108A | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 08B | 1108B | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 08C | 1108C | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 08D | 1108D | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 08E | 1108E | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 08F | 1108F | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 090 | 11090 | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 091 | 11091 | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 092 | 11092 | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 093 | 11093 | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 094 | 11094 | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 095 | 11095 | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 096 | 11096 | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 097 | 11097 | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 098 | 11098 | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 099 | 11099 | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 09A | 1109A | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 09B | 1109B | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 09C | 1109C | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 09D | 1109D | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 09E | 1109E | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 09F | 1109F | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 0A0 | 110A0 | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 0A1 | 110A1 | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 0A2 | 110A2 | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 0A3 | 110A3 | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 0A4 | 110A4 | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 0A5 | 110A5 | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 0A6 | 110A6 | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 0A7 | 110A7 | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 0A8 | 110A8 | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 0A9 | 110A9 | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 0AA | 110AA | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 0AB | 110AB | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 0AC | 110AC | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 0AD | 110AD | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 0AE | 110AE | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 0AF | 110AF | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 0B0 | 110B0 | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 0B1 | 110B1 | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 0B2 | 110B2 | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 0B3 | 110B3 | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 0B4 | 110B4 | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 0B5 | 110B5 | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 0B6 | 110B6 | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 0B7 | 110B7 | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 0B8 | 110B8 | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 0B9 | 110B9 | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 0BA | 110BA | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 0BB | 110BB | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 0BC | 110BC | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 0BD | 110BD | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 0BE | 110BE | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 0BF | 110BF | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |

### OEM 0C0–0FF

| OEM offset | BIN offset | Stock byte | Category | Effect / evidence boundary | CPU evidence |
|---|---|---|---|---|---|
| 0C0 | 110C0 | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 0C1 | 110C1 | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 0C2 | 110C2 | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 0C3 | 110C3 | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 0C4 | 110C4 | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 0C5 | 110C5 | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 0C6 | 110C6 | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 0C7 | 110C7 | 00 | UNKNOWN | Zero in stock; individual role unknown; may participate in F8.7 block transfer | 77DA-786E |
| 0C8 | 110C8 | 50 | CODE-CONFIRMED | SCSI INQUIRY vendor ASCII, gated by OEM[00A]==0A | 20F3-20FD |
| 0C9 | 110C9 | 48 | CODE-CONFIRMED | SCSI INQUIRY vendor ASCII, gated by OEM[00A]==0A | 20F3-20FD |
| 0CA | 110CA | 44 | CODE-CONFIRMED | SCSI INQUIRY vendor ASCII, gated by OEM[00A]==0A | 20F3-20FD |
| 0CB | 110CB | 4B | CODE-CONFIRMED | SCSI INQUIRY vendor ASCII, gated by OEM[00A]==0A | 20F3-20FD |
| 0CC | 110CC | 20 | CODE-CONFIRMED | SCSI INQUIRY vendor ASCII, gated by OEM[00A]==0A | 20F3-20FD |
| 0CD | 110CD | 20 | CODE-CONFIRMED | SCSI INQUIRY vendor ASCII, gated by OEM[00A]==0A | 20F3-20FD |
| 0CE | 110CE | 20 | CODE-CONFIRMED | SCSI INQUIRY vendor ASCII, gated by OEM[00A]==0A | 20F3-20FD |
| 0CF | 110CF | 20 | CODE-CONFIRMED | SCSI INQUIRY vendor ASCII, gated by OEM[00A]==0A | 20F3-20FD |
| 0D0 | 110D0 | 50 | CODE-CONFIRMED | SCSI INQUIRY product ASCII, gated by OEM[00A]==0A | 2100-210A |
| 0D1 | 110D1 | 48 | CODE-CONFIRMED | SCSI INQUIRY product ASCII, gated by OEM[00A]==0A | 2100-210A |
| 0D2 | 110D2 | 38 | CODE-CONFIRMED | SCSI INQUIRY product ASCII, gated by OEM[00A]==0A | 2100-210A |
| 0D3 | 110D3 | 30 | CODE-CONFIRMED | SCSI INQUIRY product ASCII, gated by OEM[00A]==0A | 2100-210A |
| 0D4 | 110D4 | 35 | CODE-CONFIRMED | SCSI INQUIRY product ASCII, gated by OEM[00A]==0A | 2100-210A |
| 0D5 | 110D5 | 37 | CODE-CONFIRMED | SCSI INQUIRY product ASCII, gated by OEM[00A]==0A | 2100-210A |
| 0D6 | 110D6 | 00 | CODE-CONFIRMED | SCSI INQUIRY product ASCII, gated by OEM[00A]==0A | 2100-210A |
| 0D7 | 110D7 | 00 | CODE-CONFIRMED | SCSI INQUIRY product ASCII, gated by OEM[00A]==0A | 2100-210A |
| 0D8 | 110D8 | 00 | CODE-CONFIRMED | SCSI INQUIRY product ASCII, gated by OEM[00A]==0A | 2100-210A |
| 0D9 | 110D9 | 00 | CODE-CONFIRMED | SCSI INQUIRY product ASCII, gated by OEM[00A]==0A | 2100-210A |
| 0DA | 110DA | 00 | CODE-CONFIRMED | SCSI INQUIRY product ASCII, gated by OEM[00A]==0A | 2100-210A |
| 0DB | 110DB | 00 | CODE-CONFIRMED | SCSI INQUIRY product ASCII, gated by OEM[00A]==0A | 2100-210A |
| 0DC | 110DC | 00 | CODE-CONFIRMED | SCSI INQUIRY product ASCII, gated by OEM[00A]==0A | 2100-210A |
| 0DD | 110DD | 00 | CODE-CONFIRMED | SCSI INQUIRY product ASCII, gated by OEM[00A]==0A | 2100-210A |
| 0DE | 110DE | 00 | CODE-CONFIRMED | SCSI INQUIRY product ASCII, gated by OEM[00A]==0A | 2100-210A |
| 0DF | 110DF | 00 | CODE-CONFIRMED | SCSI INQUIRY product ASCII, gated by OEM[00A]==0A | 2100-210A |
| 0E0 | 110E0 | 48 | CODE-CONFIRMED | HD signature gates E7/F3 copies and E7.5 initialization | 210D-2136 |
| 0E1 | 110E1 | 44 | CODE-CONFIRMED | HD signature gates E7/F3 copies and E7.5 initialization | 210D-2136 |
| 0E2 | 110E2 | 00 | UNKNOWN | Individual role unknown; do not call reserved |  |
| 0E3 | 110E3 | 00 | UNKNOWN | Individual role unknown; do not call reserved |  |
| 0E4 | 110E4 | 00 | UNKNOWN | Individual role unknown; do not call reserved |  |
| 0E5 | 110E5 | 00 | UNKNOWN | Individual role unknown; do not call reserved |  |
| 0E6 | 110E6 | 00 | UNKNOWN | Individual role unknown; do not call reserved |  |
| 0E7 | 110E7 | 00 | CODE-CONFIRMED | E7 flags; see all eight bit records | 2119,44C4,454B,6F4C |
| 0E8 | 110E8 | 00 | UNKNOWN | Individual role unknown; do not call reserved |  |
| 0E9 | 110E9 | 00 | UNKNOWN | Individual role unknown; do not call reserved |  |
| 0EA | 110EA | 00 | UNKNOWN | Individual role unknown; do not call reserved |  |
| 0EB | 110EB | 00 | UNKNOWN | Individual role unknown; do not call reserved |  |
| 0EC | 110EC | 00 | UNKNOWN | Individual role unknown; do not call reserved |  |
| 0ED | 110ED | 00 | UNKNOWN | Individual role unknown; do not call reserved |  |
| 0EE | 110EE | 00 | UNKNOWN | Individual role unknown; do not call reserved |  |
| 0EF | 110EF | 00 | UNKNOWN | Individual role unknown; do not call reserved |  |
| 0F0 | 110F0 | 42 | CODE-CONFIRMED | BC signature gates F2, timer, F8, FA, FB and FC; does NOT gate E7/F3 | 2136-222A |
| 0F1 | 110F1 | 43 | CODE-CONFIRMED | BC signature gates F2, timer, F8, FA, FB and FC; does NOT gate E7/F3 | 2136-222A |
| 0F2 | 110F2 | 38 | CODE-CONFIRMED | F2 flags; 487D/4583/4584 and IRAM flag updates have set-only paths | 214A-2199 |
| 0F3 | 110F3 | 40 | CODE-CONFIRMED | F3 flags; HD signature controls copy to 44F1 | 210D-2128 |
| 0F4 | 110F4 | 00 | CODE-CONFIRMED | Big-endian OEM timer input; 10*max(180,value) modulo 2^32 ->44F4 and4881 | 2199-2200 |
| 0F5 | 110F5 | 00 | CODE-CONFIRMED | Big-endian OEM timer input; 10*max(180,value) modulo 2^32 ->44F4 and4881 | 2199-2200 |
| 0F6 | 110F6 | 00 | CODE-CONFIRMED | Big-endian OEM timer input; 10*max(180,value) modulo 2^32 ->44F4 and4881 | 2199-2200 |
| 0F7 | 110F7 | 05 | CODE-CONFIRMED | Big-endian OEM timer input; 10*max(180,value) modulo 2^32 ->44F4 and4881 | 2199-2200 |
| 0F8 | 110F8 | 00 | CODE-CONFIRMED | F8 dispatch flags; BC-gated copy to4589; transfers require separate execution | 2200,C4D3-C501 |
| 0F9 | 110F9 | 0F | UNKNOWN | No individual decoder established; included in F8.7 staging block | 77DA-786E |
| 0FA | 110FA | 32 | CODE-CONFIRMED | 39FA ->4174 ->7E18 in USB SET_ADDRESS path; units unknown | 2208,6232,279B |
| 0FB | 110FB | 05 | CODE-CONFIRMED | 39FB ->4175 ->7086; F3.2 may report zero-state event; units unknown | 2210,385A,7321,9CC6 |
| 0FC | 110FC | 00 | CODE-CONFIRMED | Strictly >0x20 overrides4AD6; 028C copies4A18; counter decremented if7075>100 | 2218,028C,003E |
| 0FD | 110FD | 00 | UNKNOWN | No individual decoder established; included in F8.7 staging block | 77DA-786E |
| 0FE | 110FE | 4A | CODE-CONFIRMED | JM signature gates OEM initializer; invalid takes default-data handler9D1C | 1F87-1F9B,2227 |
| 0FF | 110FF | 4D | CODE-CONFIRMED | JM signature gates OEM initializer; invalid takes default-data handler9D1C | 1F87-1F9B,2227 |

### OEM 100–13F

| OEM offset | BIN offset | Stock byte | Category | Effect / evidence boundary | CPU evidence |
|---|---|---|---|---|---|
| 100 | 11100 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 101 | 11101 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 102 | 11102 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 103 | 11103 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 104 | 11104 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 105 | 11105 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 106 | 11106 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 107 | 11107 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 108 | 11108 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 109 | 11109 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 10A | 1110A | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 10B | 1110B | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 10C | 1110C | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 10D | 1110D | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 10E | 1110E | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 10F | 1110F | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 110 | 11110 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 111 | 11111 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 112 | 11112 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 113 | 11113 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 114 | 11114 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 115 | 11115 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 116 | 11116 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 117 | 11117 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 118 | 11118 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 119 | 11119 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 11A | 1111A | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 11B | 1111B | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 11C | 1111C | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 11D | 1111D | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 11E | 1111E | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 11F | 1111F | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 120 | 11120 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 121 | 11121 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 122 | 11122 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 123 | 11123 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 124 | 11124 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 125 | 11125 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 126 | 11126 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 127 | 11127 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 128 | 11128 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 129 | 11129 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 12A | 1112A | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 12B | 1112B | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 12C | 1112C | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 12D | 1112D | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 12E | 1112E | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 12F | 1112F | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 130 | 11130 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 131 | 11131 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 132 | 11132 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 133 | 11133 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 134 | 11134 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 135 | 11135 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 136 | 11136 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 137 | 11137 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 138 | 11138 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 139 | 11139 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 13A | 1113A | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 13B | 1113B | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 13C | 1113C | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 13D | 1113D | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 13E | 1113E | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 13F | 1113F | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |

### OEM 140–17F

| OEM offset | BIN offset | Stock byte | Category | Effect / evidence boundary | CPU evidence |
|---|---|---|---|---|---|
| 140 | 11140 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 141 | 11141 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 142 | 11142 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 143 | 11143 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 144 | 11144 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 145 | 11145 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 146 | 11146 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 147 | 11147 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 148 | 11148 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 149 | 11149 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 14A | 1114A | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 14B | 1114B | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 14C | 1114C | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 14D | 1114D | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 14E | 1114E | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 14F | 1114F | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 150 | 11150 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 151 | 11151 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 152 | 11152 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 153 | 11153 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 154 | 11154 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 155 | 11155 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 156 | 11156 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 157 | 11157 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 158 | 11158 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 159 | 11159 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 15A | 1115A | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 15B | 1115B | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 15C | 1115C | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 15D | 1115D | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 15E | 1115E | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 15F | 1115F | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 160 | 11160 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 161 | 11161 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 162 | 11162 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 163 | 11163 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 164 | 11164 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 165 | 11165 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 166 | 11166 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 167 | 11167 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 168 | 11168 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 169 | 11169 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 16A | 1116A | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 16B | 1116B | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 16C | 1116C | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 16D | 1116D | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 16E | 1116E | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 16F | 1116F | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 170 | 11170 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 171 | 11171 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 172 | 11172 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 173 | 11173 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 174 | 11174 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 175 | 11175 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 176 | 11176 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 177 | 11177 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 178 | 11178 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 179 | 11179 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 17A | 1117A | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 17B | 1117B | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 17C | 1117C | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 17D | 1117D | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 17E | 1117E | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 17F | 1117F | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |

### OEM 180–1BF

| OEM offset | BIN offset | Stock byte | Category | Effect / evidence boundary | CPU evidence |
|---|---|---|---|---|---|
| 180 | 11180 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 181 | 11181 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 182 | 11182 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 183 | 11183 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 184 | 11184 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 185 | 11185 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 186 | 11186 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 187 | 11187 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 188 | 11188 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 189 | 11189 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 18A | 1118A | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 18B | 1118B | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 18C | 1118C | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 18D | 1118D | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 18E | 1118E | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 18F | 1118F | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 190 | 11190 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 191 | 11191 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 192 | 11192 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 193 | 11193 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 194 | 11194 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 195 | 11195 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 196 | 11196 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 197 | 11197 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 198 | 11198 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 199 | 11199 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 19A | 1119A | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 19B | 1119B | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 19C | 1119C | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 19D | 1119D | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 19E | 1119E | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 19F | 1119F | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1A0 | 111A0 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1A1 | 111A1 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1A2 | 111A2 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1A3 | 111A3 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1A4 | 111A4 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1A5 | 111A5 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1A6 | 111A6 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1A7 | 111A7 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1A8 | 111A8 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1A9 | 111A9 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1AA | 111AA | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1AB | 111AB | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1AC | 111AC | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1AD | 111AD | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1AE | 111AE | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1AF | 111AF | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1B0 | 111B0 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1B1 | 111B1 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1B2 | 111B2 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1B3 | 111B3 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1B4 | 111B4 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1B5 | 111B5 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1B6 | 111B6 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1B7 | 111B7 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1B8 | 111B8 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1B9 | 111B9 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1BA | 111BA | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1BB | 111BB | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1BC | 111BC | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1BD | 111BD | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1BE | 111BE | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1BF | 111BF | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |

### OEM 1C0–1FF

| OEM offset | BIN offset | Stock byte | Category | Effect / evidence boundary | CPU evidence |
|---|---|---|---|---|---|
| 1C0 | 111C0 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1C1 | 111C1 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1C2 | 111C2 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1C3 | 111C3 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1C4 | 111C4 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1C5 | 111C5 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1C6 | 111C6 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1C7 | 111C7 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1C8 | 111C8 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1C9 | 111C9 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1CA | 111CA | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1CB | 111CB | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1CC | 111CC | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1CD | 111CD | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1CE | 111CE | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1CF | 111CF | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1D0 | 111D0 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1D1 | 111D1 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1D2 | 111D2 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1D3 | 111D3 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1D4 | 111D4 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1D5 | 111D5 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1D6 | 111D6 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1D7 | 111D7 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1D8 | 111D8 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1D9 | 111D9 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1DA | 111DA | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1DB | 111DB | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1DC | 111DC | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1DD | 111DD | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1DE | 111DE | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1DF | 111DF | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1E0 | 111E0 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1E1 | 111E1 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1E2 | 111E2 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1E3 | 111E3 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1E4 | 111E4 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1E5 | 111E5 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1E6 | 111E6 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1E7 | 111E7 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1E8 | 111E8 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1E9 | 111E9 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1EA | 111EA | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1EB | 111EB | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1EC | 111EC | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1ED | 111ED | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1EE | 111EE | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1EF | 111EF | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1F0 | 111F0 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1F1 | 111F1 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1F2 | 111F2 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1F3 | 111F3 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1F4 | 111F4 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1F5 | 111F5 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1F6 | 111F6 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1F7 | 111F7 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1F8 | 111F8 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1F9 | 111F9 | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1FA | 111FA | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1FB | 111FB | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1FC | 111FC | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1FD | 111FD | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1FE | 111FE | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |
| 1FF | 111FF | 00 | UNKNOWN | Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown | 1F49,77DA |

## Appendix B — all 32 option bits

This table is generated from `research/oem/oem_32_bits.csv`. See the main text for entry conditions, prior-state preservation and physical limitations.

| Field.bit | Stock | Category | Verified effect / boundary | CPU evidence |
|---|---:|---|---|---|
| E7.0 | 0 | CODE-CONFIRMED | USB configuration power reporting: 0 self-powered,1 bus-powered; does not switch power rails | 454B-457F |
| E7.1 | 0 | CODE-CONFIRMED | Sets IRAM bit38 enabling special READ/WRITE(16) path; no 4Kn inference | 6F4C-6F56,5015 |
| E7.2 | 0 | CODE-CONFIRMED | Cleared at6F5D before same-path checks; physical purpose unknown | 6F57-6F82 |
| E7.3 | 0 | CODE-CONFIRMED | Enables writes7085=2F and508F=01; silicon semantics unknown | D422-D435 |
| E7.4 | 0 | CODE-CONFIRMED | Advertises DPOFUA in MODE SENSE header; does not prove FUA execution | 364E-367E,379E,37C8,6F7C |
| E7.5 | 0 | CODE-CONFIRMED | Sets4172; 3A2D consults7A04/7A05 and conditionally writes4575=3 | 2129-2136,3A2D |
| E7.6 | 0 | CODE-CONFIRMED | UAS descriptor gate; cleared at6F57 and46ED; UASP NOT IMPLEMENTED | 44C4,6F57,46ED |
| E7.7 | 0 | CODE-CONFIRMED | 5082 bits1/2 follow flag atD682; bit3 set in BOTH cases; independent cleanup clears bits1/2 | D682,5535,6631,7BED |
| F2.0 | 0 | NOT USED IN VERIFIED PATH | No change in214A-2199 outputs; global/indirect consumers not excluded | 214A-2199 |
| F2.1 | 0 | NOT USED IN VERIFIED PATH | No change in214A-2199 outputs; global/indirect consumers not excluded | 214A-2199 |
| F2.2 | 0 | CODE-CONFIRMED | Sets4588=1; clear occurs earlier1F7C-1F80, not the F2 slice | 2172-217F,1F7C,875A |
| F2.3 | 1 | CODE-CONFIRMED | Assigns44F3 from flag; enabled sets487D=1 and transforms timer; disabled preserves487D here | 214A-2160,2199-2200,6B04 |
| F2.4 | 1 | CODE-CONFIRMED | Sets4583=1 when enabled, otherwise preserves; state-dependent7058.bit5 effects | 217F-218C,3F61 |
| F2.5 | 1 | CODE-CONFIRMED | Sets4584=1 when enabled, otherwise preserves; state-dependent7058.bit4 effects | 218C-2199,3F61 |
| F2.6 | 0 | CODE-CONFIRMED | Sets IRAM bit39; initializer clears earlier; at64B7 false ORs7801 with10, true preserves | 1F78,2169-2172,64B7 |
| F2.7 | 0 | CODE-CONFIRMED | Sets IRAM bit3A (=byte27.bit2); whole byte saved/restored viaB008; independent functional reader unknown | 1F7A,2160-2169,81DC,832F |
| F3.0 | 0 | CODE-CONFIRMED | Event/topology paths; cleared by6F62; NOT a qualified hot-swap switch | 2804,6F62,8FD9 |
| F3.1 | 0 | CODE-CONFIRMED | JM vendor response indicators;7059.bit1 status path; private protocol unknown | 272E,2D52,9CE1 |
| F3.2 | 0 | CODE-CONFIRMED | If7086==0 arms4176/4177; JM report sets3506.bit0 and clears4177 | 7321,9CC6,2210,385A |
| F3.3 | 0 | UNKNOWN | No individual direct decoder established; whole-byte and indirect consumers remain possible | 44F1 direct occurrence survey only |
| F3.4 | 0 | CODE-CONFIRMED | Filters7993 high-nibble0 low2=0 event: off writes4BC9=2E,4AD8=1,4173=0; on skips | 5216-527B |
| F3.5 | 0 | CODE-CONFIRMED | USB2-only policy paths: state6, bcdUSB0200 and suppressed BOS; link operation untested | 32E1,DD28,B6AE |
| F3.6 | 1 | CODE-CONFIRMED | TRIM/DSM capability gate requires IDENTIFY and per-port capability; command success unproven | 16C2,1177,C98E |
| F3.7 | 0 | CODE-CONFIRMED | Additional NCQ enable in no-port-multiplier branch with IDENTIFY words75/76; not global NCQ control | 154E-156F |
| F8.0 | 0 | NOT USED IN VERIFIED PATH | No individual dispatch inC4D3-C501; value may be carried in F8.7 block | C4D3-C501 |
| F8.1 | 0 | NOT USED IN VERIFIED PATH | No individual dispatch inC4D3-C501; value may be carried in F8.7 block | C4D3-C501 |
| F8.2 | 0 | NOT USED IN VERIFIED PATH | No individual dispatch inC4D3-C501; value may be carried in F8.7 block | C4D3-C501 |
| F8.3 | 0 | NOT USED IN VERIFIED PATH | No individual dispatch inC4D3-C501; value may be carried in F8.7 block | C4D3-C501 |
| F8.4 | 0 | NOT USED IN VERIFIED PATH | No individual dispatch inC4D3-C501; value may be carried in F8.7 block | C4D3-C501 |
| F8.5 | 0 | NOT USED IN VERIFIED PATH | No individual dispatch inC4D3-C501; value may be carried in F8.7 block | C4D3-C501 |
| F8.6 | 0 | CODE-CONFIRMED | 71C4(04),7616(02),71C4(40): CODE1A18..1B17 ->XDATA7500..75FF; peripheral meaning unknown | C4D3,7616,8026 |
| F8.7 | 0 | CODE-CONFIRMED | 71C4(08),77DA(7300),71C4(80): staging3900..39FF ->7300..73FF with compare; up to12 copies, sticky mismatch | C4E9,77DA-786E,800A |

## Appendix C — MMIO dependencies

These entries preserve the scoped claims in `research/oem/mmio_dependencies.json`. They are not a vendor register specification.

| Address | OEM / software source | Code effect | Unresolved meaning |
|---|---|---|---|
| 7801 | F2.6 | 64B7 ORs bit4 only if IRAM bit39 is zero; usual preceding write is41 | Physical bit meaning unknown |
| 7058 | F2.4,F2.5 | Dispatcher3F61 controls bits5/4 by state | Not a globally fixed register value |
| 5082 | E7.7 | D682 sets bit3 always and assigns bits1/2; cleanup clears1/2 | Peripheral meaning unknown |
| 7085,508F | E7.3 | D422 conditional writes2F and01 | Peripheral meaning unknown |
| 7086 | FB,F3.2 | 385A copies4175;7321 tests zero and arms event | No time unit or hotplug interpretation proven |
| 7E18 | FA | 6232 writes4174 after validated SET_ADDRESS;279B reads when415E enabled | Raw value, not established milliseconds |
| 70B0-70B3 | F2.3,F4-F7,MODE SELECT | 9185 path submits runtime4881 four bytes throughB409 | Byte-transfer relation confirmed; peripheral timebase unknown |
| 70B4-70B5,70B7 | UNKNOWN | No OEM-specific meaning established | Do not interpolate adjacent-register meanings |
| 70B6 | MODE SELECT | 9711/B409 path uses command/mode value2 | Context-dependent command interface |
| 70B8 | MODE SELECT | 9185 path writes64 | Physical meaning unknown |
| 70C0 | MODE SELECT | 9711 interprets synthetic result1/2 with alternate SZCT values | NOT a universally valid byte-count register |
| 70C1-70C7 | UNKNOWN | No universal OEM role established | UDMA counter roles require separate context and hardware evidence |
| 70C8 | MODE SELECT | Related completion/status path | Physical bit semantics not proven |
| 7075 | FC | 003E: threshold>100 decrements4A18, increments4A9B, clears7075 | Tick source and unit unknown |
| 7300-73FF | F8.7 | 256-byte staging copy and comparison | Not proven SPI/NVRAM storage |
| 7500-75FF | F8.6 | 256-byte CODE table copy | Peripheral table function unknown |
