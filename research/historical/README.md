# Historical evidence map

The private archive contains the two original ZIP attachments unchanged and the safely extracted content-addressed trees, including nested ZIP and TAR.GZ files. Each extraction directory is the first 16 hexadecimal digits of its archive SHA256. Repeated containers retain provenance references without requiring repeated identical expanded trees.

The inventory contains 79 archive occurrences, 48 unique archive hashes, 945 extracted file entries and 413 distinct file payload hashes. It records18,178,198 expanded bytes. All 808 entries in unique supplied checksum lists and 439 entries in inspected JSON hash manifests matched. These lists overlap; the counts describe integrity checks, not functional test coverage.

## Available versions, not an invented linear firmware chain

| Historical stage | Actual supplied material | Canonical treatment |
|---|---|---|
| Early general/v2/v3 labs | Three 65536-byte `.img` files, scripts, embedded toy-emulator tests and combined handover reports | Preserve obsolete incomplete-image experiments; explicit diffs and separate replay/reconstruction record |
| v3 restricted common wrapper | Mentioned source and restricted-only image hashes in a report; the original source file is missing | Binary-backed reconstruction is separately identified; absent original tests are not declared passed |
| v4 | Ownership audit and negative stale-result evidence | Preserved offline replay; current CK ownership tests supersede heuristic snapshot matching |
| v5 | Completion/error/descriptor/ownership audit scripts | Retained within v6 nine-group replay |
| v6 | Stock checkpoint, nine-group audit runner and mocked collector checks | Replayed with source identity; no hardware collector main |
| v7 | Full factory reconstruction, CRC/repacker and negative tests | Exact prefix+tail identity confirmed; current strict repacker consolidates behavior |
| v8 | Original full experimental BIN, source package and ten offline suites | Original reconstructed exactly; independent revised candidate fixes new abort association defect |
| v9/v9.1 | Hardware collector scripts and supplied stock captures | Preserved, not re-run against a device; no separate supplied offline test entry point |
| v10, v11, v11.1–v11.4 | Collector sources, offline tests and supplied logs/captures | Offline constants/parsers/mocks replayed; physical observations retain original provenance |
| v12 | Readback-corroboration scripts, sector captures, reports and offline tests | Preserved/replayed without new disk I/O; method and payload hashes remain distinct |
| v13 | DMA/port ownership probe, reports and offline tests | Replayed offline only |
| v14 | Vendor port-read probe, captures, later v8 ownership audit and offline tests | Ten later ownership cases retained in current CK suite |
| v15 | Static qualification audit | Replayed in a temporary source tree |
| v16–v19 | Hotplug/topology/event native analyses | Replayed offline; corrected setup fixture in current implementation; no new hot-plug test |
| v20 | Nine-donor comparison | Replayed with documented path-only adaptation; current comparison fixes container origin |
| v21 | OEM feature analysis/configurator self-test | Replayed in memory; no factory OEM change |
| v22 | JMS567 UAS comparison and local OEM-gate test | Replayed; external patch not adopted |
| v23–v29 | Successive OEM/code/protocol audits and machine tables | Original expectations preserved in historical replay; corrected decoder/native suite is current |
| Final handover audit / UDMA supplement | Additional 1905 reported units, counter reinterpretation and rejected prototype | Replayed with corrected emulator; new native abort counterexamples replace unsafe assumptions |

Some report titles use v2–v4 as revisions of an earlier handover while others use the same numbers for later lab stages. Files and hashes, not a guessed common version scale, establish identity. No new arbitrary vXX name was created.

The public package includes metadata and replay wrappers. Historical scripts, images, disk sectors, unredacted OEM data and device logs remain private. The reviewed replay manifest authorizes only exact supplied files, and temporary copies exclude bytecode caches. This is provenance control for reviewed offline scripts, not a general sandbox for arbitrary user-supplied Python.

Current tools reside under `tools/`; the historical scripts are not alternate supported implementations. A historical assertion that still passes does not restore an interpretation that later native tests disproved. Updated findings link the corrected code and regressions instead of editing the old evidence.

## Recovered early-lab execution

See [historical lab reproduction](../../docs/historical-labs.md). The general, PIOv2 and PIOv3 IMG builds match all three supplied hashes. The suite executes 41 distinct available original cases; 55 PASS events include a repeated 14-case import. The missing restricted common source remains unavailable. Its original 1724-byte log is recovered exactly from the report and marked RECORDED_NOT_REEXECUTED.
