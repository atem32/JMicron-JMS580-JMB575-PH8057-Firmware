# Validation methodology and reproducibility

## What a pass means

A pass means that a specified assertion held for an executed program under its declared inputs. It does not prove all possible firmware paths, physical peripheral semantics, interrupt timing, DMA, SRAM ownership, safe SPI installation or media integrity. The public runner records omitted private-firmware tests as skips and rejects an empty unittest discovery. Assertion-disabled execution is rejected.

Three evidence levels remain separate:

1. **Supplied artifacts and observations.** Exact original bytes, archive lineage, historical command/log records and the owner's raw BOT excerpt.
2. **Native instruction execution.** The original or generated 8051 instructions run in a corrected executor. Tests supply memory/peripheral state, explicit hooks or an explicit arithmetic model; those assumptions are recorded.
3. **Reference contracts and parser tests.** Host-language tests check protocol framing, arithmetic preconditions, data bounds and rejection policies. They do not certify that hardware produces the modeled inputs.

The replayed output CSW is a newly generated offline result, not a recovered USB capture. The recorded SG_IO `actual_bytes` field can be derived from residue and is not an independent transport observation. See the evidence table in [UDMA accounting](udma-csw-residue.md).

## Corrected execution foundation

`tools/emulator/mcs51.py` is the single current decoder/executor. Its tests include exhaustive ADD/ADDC/SUBB operand/carry combinations, all 65536 MUL pairs, all 65280 defined DIV pairs, 20000 decimal-adjust cases, register banks, bit operations, direct/indirect RAM distinctions, stack behavior, MOVX addressing, jump wrapping and dual-DPTR fixture behavior. These are ISA combinations, not firmware integration cases.

The independent MIT emu8051 decoder comparison covers 20480 opcode/operand/PC samples, including page and 64 KiB wrap boundaries. It compares instruction lengths and normalized operands/targets for defined instructions; the external decoder's A5-as-NOP spelling is not accepted as a semantic model. The current common suite has 27 unittest methods. Four earlier regressions fail against the supplied old emulator and pass after corrections; the later conditional-SFR-read regression likewise fails on all five affected old branch opcodes.

The executor now refuses ambiguous 64 KiB images, invalid FixtureBus ranges and undefined DIV-by-zero continuation; traces record the executing PC; branch conditions avoid spurious reads. The native UDMA fixtures use explicit RAM/MMIO boundaries and reject unsupported access. OEM and some legacy fixtures instead supply a flat synthetic 64 KiB memory image; their register values and selected callee substitutions are declared test premises, not a fail-closed peripheral model. A register read supplied by a callback is a premise, not an independent silicon measurement.

## Current firmware tests

| Family | Measured scope | Remaining boundary |
|---|---|---|
| Native OEM |19790 bounded checks across initialization, signatures, flags, strings, power/timer pages, auxiliary fields and F8 copies/faults | Selected peripheral control/wait helpers and supplied register values remain fixtures |
| OEM portable regressions |512-row/32-bit coverage, state transitions, redaction, setup fields, retry behavior and bounds | Host models are cross-checked against native paths when stock is supplied |
| CK sense map |65536 status/error combinations against nativeAA9F | Exhaustive over those two bytes only |
| CK legacy sense/lifecycle |3245 scenarios | Synthetic ownership, allocation length, pending sense, state/reset loops |
| CK SAT12 |207 normalization/control scenarios | Device behavior is not exercised |
| CK integrated legacy |310 scenarios plus 10 later recorded port-ownership cases | Direct branch fixtures retain explicit premises |
| New CK abort leaf |128 ABI cases, both hook sites, carry paths, register banks, DPS and IE states | ISR scheduling and real stack maximum unmodeled |
| New native dispatch |112 paired stock/revised scenarios, or 224 individual runs; 32 invalid-direction pairs; 128 ordinary-SCSI shared-state pairs | Non-data asynchronous scheduler and full media transfer remain bounded out |
| New abort/error policy |12 scenarios across stock/v8/revised, 36 executions | Scheduled finalizer is executed conditionally, not a claim of physical post-reset CSW delivery |
| Native UDMA compatibility |24 scenarios across stock, original v8 and revised CK, each with/without trace: 72 pairs, 144 executions | Explicit MMIO samples and arithmetic model; no autonomous payload movement |
| Actual combined image |Executable bytes and 24 native scenarios compared with the revised+trace reference overlay | CRCs and bounded state tested; hardware unqualified |
| BOT/reference accounting |Strict CBW/CSW parser, tag/length/direction/status bounds, qualified H−P contract, partial/error/reset/timeout rejection | No real processed-byte register is asserted |
| Source/build/extraction |Exact source SHA, guarded ranges, overlap/trailer/CRC, file aliases, provenance and malicious/invalid archive cases | Provenance validation is not a general Python sandbox |

The UDMA matrix includes complete 512/4096-byte requests, CK clear/set, ATA ABRT/device-fault/busy states, missing D2H/completion, pending/short conditions, stall, inactive/late abort, previous failure, Data-In full/partial controls, phase error and arbitrary arithmetic-result values. Four native counterexamples reject the previous residue-clearing prototype. Ten timer-clamp and five PIO arithmetic chains demonstrate a consistent competing 70B*/70C* interpretation; those are explicitly hypothesis tests.

The common SCSI tests compare admission and shared state, not entire disk READ/WRITE data paths. True partial SATA/USB processing and physical stall/reset/timeout behavior are not qualified. A pending loop stopped at an interpreter limit is not a simulated real-time timeout.

## The historical 33816 total

All original expected values in v23–v29 and the final audit were retained. Reported units and independently instrumented guard counts are:

| Suite | Reported units | Executed guards |
|---|---:|---:|
|v23|1577|1583|
|v24|2296|3007|
|v25|1985|10374|
|v26|7981|9270|
|v27|2164|2164|
|v28|5903|5903|
|v29|10005|10005|
|final|1905|1905|
|Total|33816|44211|

The instrumentation wraps boolean conditions with identity and counts guards; it does not replace expected results. It excludes emulator-internal guards. Classification by dominant method gives 28635 units with synthetic-memory native execution, 2624 with a host copy fixture, 2316 with a peripheral/callee stub and 241 static/schema/raw-scan checks.

The tests are not all tautological host models: original instructions genuinely execute. They also are not 33816 independent physical validations. Counts overlap across versions and mix scenarios with individual assertions. Some expectations were derived from the same code being tested. The new tests address missing entry conditions and native paths instead of merely preserving a count.

## Historical replay

The extracted originals remain immutable. The current wrappers validate reviewed file size/SHA, require separate output trees, reject changed/missing/unlisted/symlinked source files and exclude bytecode caches from copies. They execute only reviewed offline entry points. The corrected canonical emulator replaces old copies where documented. v20's hardcoded source path is changed only in its temporary copy; expectations are unchanged.

Original v8's ten suites reconstruct its exact original hash. Earlier v4/v5/v6/v7 and v10–v14 test entry points, plus v15–v22 and v23–v29/final, are retained and replayed. The three earlier lab images rebuild exactly, with 41 distinct available original cases and 55 PASS events because one 14-case group repeats. The extended early runner has 14 groups. The missing restricted common source's 15-case output log is recovered byte for byte but explicitly not re-executed. [Historical lab reproduction](historical-labs.md) records the separate supplied/reconstructed identities. Missing original v3 restricted-wrapper source is an explicit historical gap; an adapter backed by supplied bytes does not become that original source or its absent tests. No v9 standalone offline suite is invented.

Raw old test files remain private evidence and are not offered as competing current tools. An unchanged old assertion may still pass within its narrow fixture even when its former broad interpretation is withdrawn.

## Running and reading results

```bash
python3 run_tests.py --out build/public-validation
python3 run_tests.py --stock /private/complete-factory.bin --out build/full-validation
python3 run_tests.py --stock /private/complete-factory.bin --history-root /private/audit_input --out build/history-validation
```

`summary.json` reports group status, unittest methods/skips where available, source hashes and zero hardware operations. Detailed CK, native OEM, UDMA and historical JSON/logs are separate; their counters are not added into a single qualification total. The public release carries sanitized result summaries. The private archive carries complete new logs plus every supplied original.

The local execution environment is Linux with Python 3.12 and an available C compiler. Source grammar was also checked for Python 3.11, but a separate local 3.11 interpreter was unavailable. The GitHub Actions workflow is prepared for 3.11/3.12, with pinned action commits and public-only tests. It has not run remotely because no GitHub publication occurred. The local entry point and fresh package contents are validated here.
