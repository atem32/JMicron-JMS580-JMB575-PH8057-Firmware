# Earliest general, PIOv2 and PIOv3 lab reproduction

The three supplied 65536-byte lab images now reproduce exactly from the available
historical material. These are obsolete incomplete SPI-prefix experiments with
synthetic tests. They are not current firmware candidates or hardware validation.

Run `python3 tools/history/replay_labs.py /private/audit_input --out build/early-labs` from the repository root. The extended `replay_early.py` runner includes
this family automatically. All archived execution requires the adjacent reviewed
history manifest; originals are copied to temporary directories and never edited.

| Supplied family | Newly replayed original cases | Rebuilt image SHA256 |
|---|---:|---|
| General CK_COND | 14 | `22d4ef8f7adaa679c2b11b0e634a84c0888d65104044269b9bd32aefe3bc3e53` |
| PIO completion v2 | 12, plus the same 14 general cases during import | `0a9bc1e1c9ab90a8ad19e9d9f2df271549e5f6d509db62daf0b00dd4be70ba8f` |
| PIO Data-In v3 | 15 wrapper cases with the new dependency adapter | `94b093ab7293bfe3f94587e8a4a4cbdd1692fc17e99663b72c5ee3529831c35f` |

There are 41 distinct available original cases and 55 printed pass events because
the general cases execute twice. No original expectation was changed.

## Missing dependency and recovered evidence

The supplied PIOv3 source calls `runpy.run_path` on
`PH8057_general_ckcond_lab_v3_restricted.py`. That source is absent. Its original
invocation reproducibly raises `FileNotFoundError` before executing a PIO case or
writing an image. The unmodified failure is retained in
`pio_v3_original_missing_dependency.log`.

The five copies of the full handover report contain filenames, hashes, assembly
excerpts and recorded output, but not the complete missing Python source. A
read-only search of the extracted evidence found no matching filename or recorded
source SHA256, including Markdown fenced bodies and common newline variants.
The source's recorded identity is 11275 bytes and SHA256
`0c836343efeec7810e1d662b2b8727eb17cfeb4d51f229c590c1d8061ba77d48`.

Appendix A3 does preserve the exact original common-builder test log: 1724 bytes,
SHA256 `656b94494d6d37a06edb97e28056b63465a4e21258e8d51afb1b441e3b95969d`.
It is recovered verbatim as `restricted_common_RECORDED_NOT_REEXECUTED.log`.
Its 15 historical pass lines are retained as recorded evidence. The missing
source's original common-builder tests have **not** been reexecuted.

The newly written adapter exposes only `asm`, loaded from the hash-verified
supplied PIOv3 image at file range `0xF300..0xF479` (CPU `0xE300..0xE479`,
378 bytes). The unchanged supplied PIOv3 script then builds and tests its own
wrapper. The adapter is explicitly labeled as new code, contains no image payload,
and never claims the missing original source's identity.

Combining those common bytes and the supplied common hook bytes with the verified
stock prefix reconstructs the old restricted-only image: 65536 bytes, 372 actual
byte changes, SHA256
`0a351e85149027ea63f16694cca15de594065396ea7a4759a08179411d8463ee`.
That exact digest matches the historical report. This is a new binary
reconstruction, not a supplied standalone file or recovered original Python
source. All image reconstruction occurs in temporary memory/storage; output
contains logs and metadata, not copied firmware payloads.

## Validation boundaries

The replay tests only the historical scripts' own limited models. It does not
establish live register freshness, per-LUN ownership, DMA behavior, USB/SATA
timing, SPI integrity or safety to flash. Current corrected CK_COND and UDMA work
remain separate. Eighteen portable history integration tests pass, including five
new checks for adapter input hashes, source-presence refusal, unreviewed-input
rejection before execution, prefix validation and verbatim log recovery. The
extended early-history runner passes all 14 groups.
