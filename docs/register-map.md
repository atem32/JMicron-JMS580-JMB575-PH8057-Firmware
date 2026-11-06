# Registers and OEM fields

[`research/oem/registers.json`](../research/oem/registers.json) is the canonical
machine-readable atlas. It covers every OEM byte by non-overlapping ranges,
all 32 option bits, and the MMIO, IRAM, SFR and XDATA locations established
by the retained OEM, command-accounting and patch analysis. Each entry records its purpose, read/write use,
instruction or source evidence, confidence and unresolved details. Instruction
excerpts include the exact image, CPU address, bytes and assembly.

The names describe this firmware's use of a location. They are **not JMicron
register specifications**. `CONFIRMED` applies to the stated software effect;
it does not establish a peripheral's complete physical contract.

| Confidence | Meaning |
|---|---|
| `CONFIRMED` | Exact instructions or generated patch layout establish the stated, scoped software fact. |
| `INFERRED` | Code consumers support the interpretation, but the hardware contract is undocumented. |
| `HYPOTHESIS` | An explicit model is consistent with selected checks; it cannot authorize a firmware change. |
| `UNKNOWN` | An individual meaning or required contract is not established. This never means unused or reserved. |

## Address namespaces and reproduction

CPU addresses name 8051 **CODE**, not XDATA registers or SPI file offsets.
For the full 70,144-byte factory image, CODE begins at file `0x1000`; the OEM
block is file `0x11000–0x111FF`. The 67,072-byte updater container instead has
CODE at `0x400` and OEM at `0x10400`. See [firmware layout](firmware-layout.md)
for exact identities and compatibility checks.

An IRAM bit address is also distinct from an IRAM byte address: bit `38h` is
byte `27h.bit0`. Direct SFR `AFh` and bit address `AFh` are different locations;
the latter names the interrupt-enable bit EA.

```sh
python3 ph8057.py oem --stock /private/PH8057_FACTORY_COMPLETE_READBACK_DO_NOT_FLASH.bin --out build/oem
```

This produces one decoded `oem_atlas.json` and a complete `register-map.md`
table with the columns **Address, Name / purpose, Read/write, Evidence,
Confidence, Unknowns**, followed by the exact instruction excerpts. These are
generated views of the canonical metadata; they are not committed copies of
the atlas. The public decoder redacts the full serial payload `OEM 056–077`.
The metadata itself contains no serial bytes. `--include-sensitive` is for
private analysis only.

`tools/analysis/oem.py` implements the decoder and bounded state models.
`tools/analysis/native_oem.py` executes the original instruction paths with
explicit RAM/MMIO fixtures. The OEM regression group checks atlas coverage,
evidence references, redaction and, when exact inputs are available, the
instruction excerpts against the factory image and generated CK_COND image.

## OEM loader and options

The initializer at `1F49` stages the first 256 OEM bytes at XDATA `3900–39FF`.
`JM` at OEM `FE–FF` gates the outer initializer; failure takes `9D1C`.
`HD` at `E0–E1` independently gates E7/F3 and the E7.5 action. `BC` at
`F0–F1` gates F2, F4–F7, F8 and FA–FC. Invalidating one inner signature does
not invalidate the other group.

| Field | Factory value | Established effect | Remaining limit |
|---|---:|---|---|
| E7 | `00` | USB power/DPOFUA/UAS descriptor gates; READ/WRITE(16) flag; event and register masks. | Descriptor claims do not qualify electrical power, FUA, UASP or 4Kn. |
| F2 | `38` | Timer enable, state-dependent `7058` controls and set-only software flags. | An inactive isolated slice can preserve old state. |
| F3 | `40` | Event/reporting paths, USB2 policy, TRIM capability and a no-PM NCQ enable gate. | Neither hot-swap nor multidisk NCQ is established by these bits. |
| F4–F7 | BE32 `5` | `(10 * max(180, value)) mod 2^32`; factory input becomes `1800`. | Oversized input can wrap; supported vendor range is undocumented. |
| F8 | `00` | Bit6 copies CODE `1A18–1B17` to `7500–75FF`; bit7 copies current staging `3900–39FF` to `7300–73FF` and compares. | Window ownership, idempotence and physical purpose are unknown. Bits0–5 have no individual dispatch in the inspected path. |
| F9 / FD | `0F` / `00` | Travel in the first-half block when F8.7 executes. | No independent decoder established. |
| FA | `32` | `39FA → 4174 → 7E18` after valid SET_ADDRESS. | No established time unit. |
| FB | `05` | `39FB → 4175 → 7086`; F3.2 can report its zero state. | Physical event meaning unknown. |
| FC | `00` | Only values `>20h` override `4AD6`; counter chain uses `4A18` and `7075`. | Tick source unknown; separate from SZCT. |

The MODE SENSE SZCT field uses 100 ms units: `1800` represents 180 seconds
on the SCSI wire. This does not establish the actual spindle-stop time.
Current and Saved share the runtime field; Default returns `18000`, and
Changeable returns `FFFFFFFF`. A RAM-backed Saved response does not prove
nonvolatile persistence.

Packed manufacturer, product and serial slots contain **ASCII**, with a
USB-style wire-length hint. The loader does not validate the `03` type bytes
at `00D`, `031` and `055`. The helper at `E1EB` computes
`((length - 2) & 0xFF) >> 1`; zero length skips that helper. The decoder reports
malformed lengths without reading beyond the supplied block. `3900` is also
reused as another controller buffer, so unrelated `39xx` reads do not prove
OEM consumers.

The second OEM half is all zero in this factory image. A supplied BIWIN donor
has 196 nonzero bytes there; this prevents a universal “reserved” claim but
does not establish a PH8057 consumer. Donor identities and their different
container layout remain in the [image manifest](../firmware/manifests/images.json).

### State preservation and retry behavior

At `214A–2199`, F2.3 assigns `44F3` to zero or one. Enabled bits only **set**
`487D`, `4583`, `4584`, `4588` and IRAM bits `39/3A`; disabled bits preserve
those locations in this slice. The earlier initializer explicitly clears
`4588` and bits `39/3A`. The E7.5 path similarly preserves `4575` when it does
not publish an event. Tests use nonzero prior state to distinguish preservation
from clearing.

E7.7 controls `5082.bits1/2`: enabled gives `old | 0Eh`, disabled gives
`(old & F9h) | 08h`. Bit3 is set in both cases. Separate paths at `5535`,
`6631` and `7BED` clear bits1/2 independently.

The F8.7 loop clears `4BC4/4BC5` once at `77E2–77E8`; mismatch sets `4BC4`
at `7838–783D`. `7851: SETB C` followed by `7852: SUBB A,#0Ah` tests the old
counter **after** a copy. The resulting bounded behavior is:

| Injected comparison results | Copies | Final `4BC5` | Final `4BC4` |
|---|---:|---:|---:|
| Immediate success | 1 | 1 | 0 |
| Persistent mismatch | 12 | 11 | 1 |
| First mismatch, then success | 12 | 11 | 1 |

The latch stays set across retries. The caller then invokes `71C4(R7=80h)`
without checking it. This describes the code; no firmware retry-policy change
is justified by these observations alone. Native `7616(02)` leaves `R6=1Ah`,
successful `77DA` leaves `R6=01h`, and enabled F8 chains leave EA set. Returning
stubs do not prove those ABI effects. Tests still stub the explicitly named
peripheral command/wait/control helpers `B37F`, `80F5`, `E1A6`, `E1AE`.

## Command accounting and patch state

| Address | Name / purpose | Read/write | Evidence | Confidence | Unknowns |
|---|---|---|---|---|---|
| XDATA `459C + LUN` | Compact LUN-to-port discovery list | R/W | `05B6–05CF`, `D896` | CONFIRMED | Physical tray numbering and stable hot-swap identity |
| MMIO `7A06 + 8*LUN` | Mapping copied to hardware-facing slots | W | `C774: MOV B,#08h; C778: MUL AB`, store at `C784` | CONFIRMED | Complete hardware routing contract |
| IRAM `55–58` | Software residue, big-endian (`55` MSB, `58` LSB) | R/W | `7BF4–7C04`, `9529–953A`, `B3C4` | CONFIRMED | Trustworthy processed-byte source for UDMA Data-Out |
| MMIO `6300–6313` | Taskfile, selected port and FIS-related fields | R/W | `8CA3–8CF6`, `7357`, generated capture code | CONFIRMED | Coherent, command-owned snapshot under autonomous activity |
| SFR `B9` / MMIO `7097` | Accepted DMA/PIO status and error | R | `735F`, `7386–738D` | CONFIRMED | Lifetime/coherence after abort or reset |
| MMIO `630F` / `630D` | PIO Setup E_Status/error staged in `4B31/32` | R | `96BD–96CC` | CONFIRMED | Timing of physical transfer completion |
| MMIO `70B0–70BD`, `70C0–70C9` | Operand, command and result uses in arithmetic-related paths | R/W by field | `C7C5`, `D1D7`, `B3C4`, `9711`, `91E1` | CONFIRMED | Full silicon operation semantics; none is a universal UDMA counter |
| SFR `AC–AF` | Data-In residual quantity; upper byte masked with `3Fh` | R | `AEFC–AF09` | CONFIRMED | Equivalent Data-Out interpretation |
| XDATA `4D00 + 16*LUN` | Generated pending ATA descriptor slots | R/W | `core_patch.py:capture_block`, `sense_patch.py` | CONFIRMED | Exclusive physical SRAM allocation |
| XDATA `4E00–4E1F` | Generated single active-command context | R/W | `core_patch.py`; `FD20–FD3E` clears `4E07` | CONFIRMED | Whole-system interrupt/DMA and concurrent ownership contract |

CBW and CSW use little-endian lengths on the wire: the parser copies
`7988..798B → 58,57,56,55`, and the CSW builder serializes `58,57,56,55`.
The UDMA Data-Out branch through `AEF4 → CBE3` does not decrement these
residue bytes. The separate Data-In and PIO paths do not justify clearing them.

The arithmetic fixture models `70B6` operations `C0/10/00/01/02/04` as input
clear, result-to-input copy, addition, subtraction, comparison and left shift.
This is explicitly a **HYPOTHESIS**. Native consumers also use other commands;
their full semantics are unknown. The timer path's reads of `70C9/C8` into
`4AF1/4AF2` after commands `05/06` do not establish a quotient, remainder or
physical time unit. [Patch documentation](patches.md) explains why these
observations cannot authorize a UDMA residue fix.

For USB SETUP, the decoded internal word order is `wValue=1A/1B`,
`wIndex=1C/1D`, `wLength=1E/1F`, high byte first. The `D970` recognizer and
`C702` handler reject asymmetric invalid fields at different stages; the
regressions preserve that distinction.

The dual-DPTR convention is an explicit execution model. CPU interrupt
masking does not freeze USB/SATA engines. Unknown ownership, timing and SRAM
contracts are recorded in the [hardware coverage guide](../tests/hardware/QUALIFICATION_PLAN.md).
