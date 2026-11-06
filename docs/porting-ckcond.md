# Porting SMART / CK_COND to another firmware

**Audience:** AI coding agents and engineers working with an **original, legally obtained firmware dump** from their own JMS580-based USB-to-SATA device.

**Objective:** reproduce the *behavior* of this project's SMART/CK_COND repair on a different firmware build. Do not copy binary patches blindly. This repository contains **one** maintained patched variant, `ckcond`, and its exact-image builder; it is not a universal JMS580 firmware patcher.

The repair makes ATA PASS-THROUGH commands return the correct command-owned ATA Return Descriptor, especially for SMART RETURN STATUS (`B0h/DAh`) and CHECK POWER MODE (`E5h`). It also prevents an unpublished ATA result from being exposed after the native USB-wait abort paths. The HDD's standby timer is configured separately.

A successful port requires both semantic equivalence and a correctly packaged image for the **specific target device**. A matching chip model, file size, USB VID/PID or superficially similar disassembly is insufficient.

## 1. Inputs an AI agent needs

Before modifying anything, obtain and identify:

- **The target's original firmware** read from that exact device or supplied as its exact OEM update file; its length and SHA256. Keep the original immutable.
- **Hardware identity:** bridge/controller marking, any SATA port multiplier, board revision, USB VID/PID, number of exposed LUNs, BOT/UASP mode, flash-chip identity (if known), and firmware/update-tool version.
- **Evidence of how the target boots and is packaged:** full SPI dump versus updater container, metadata, checksums, CODE and OEM offsets, any encryption/signature, and a *known recovery method*. Do not infer flash capacity from file length.
- **Optional but helpful:** stock-versus-stock dumps from related devices, USB/SCSI traces of SMART STATUS and CHECK POWER MODE, the target's original updater, relevant disassembly, and a read-only device enumeration.
- **Test environment:** disposable HDDs, host OS, tools and an independent way to restore the factory firmware. Do not use production disks for destructive qualification.

If only an unknown, truncated or encrypted file is available, finish identification first. If required code or recovery information is missing, produce a specific blocker report rather than claiming a flashable port.

Do not publish vendor firmware, proprietary flash utilities, serial numbers or private dumps in this public repository.

### Firmware readback and update over USB (no external SPI programmer)

**An external SPI programmer was not required for the PH8057 work recorded here.**
The bridge exposes vendor-specific firmware access over USB, but this is *device/firmware-dependent* and is not a universal JMS580 recovery guarantee.

**Linux — complete PH8057 firmware acquisition used in this project:**

The reference's complete **70,144-byte** factory image **was acquired through Linux over USB**, in two stages; it was not obtained using an external SPI flasher.

1. **Initial 64-KiB prefix:** [projectgus/jms567ctl](https://github.com/projectgus/jms567ctl) with the [`py3_sg.py` Linux SG_IO helper](https://github.com/9500/ds500u3-jms567-uas/blob/main/tools/py3_sg.py):

   ~~~bash
   python3 jms567ctl.py -d /dev/sdc read_flash ph8057-original.bin
   sha256sum ph8057-original.bin
   ~~~

   This standard read returns the first **65,536 bytes** (`0x00000..0x0FFFF`), SHA256 `131bab19b558a25745c881c3c4193fd1f9fb541c0a6c89c7961bad31cecc60b2`, **not** the entire PH8057 factory image.

2. **Missing tail:** the read-only, reference-device-specific Linux collector [`tools/analysis/read_stock_tail.py`](../tools/analysis/read_stock_tail.py) (preserved from the actual `PH8057_stock_probe_v6.py` acquisition tool) performed five more USB vendor-SCSI `SG_IO` reads with `DF/FA`:

   | Factory-image offset | Bytes received |
   |---|---:|
   | `0x10000` | 1,024 |
   | `0x10400` | 1,024 |
   | `0x10800` | 1,024 |
   | `0x10C00` | 1,024 |
   | `0x11000` | 512 |
   | **Total** | **4,608** |

   The collector also checked the first 1,024 bytes against the original prefix and queried cached flash information. All seven SG_IO reads reported SCSI GOOD, zero host/driver errors and zero residue. The final five payloads formed `ph8057-stock-10000-111ff.bin`, SHA256 `083e5851cbdc17e0d641a33c8027d6a8e68d023995a03b6186fa134b7122e190`.

   **Example using the preserved collector** (replace the node and *USB enclosure serial*, not the HDD ATA serial; requires an isolated, idle PH8057 and root privileges):

   ~~~bash
   python3 tools/analysis/read_stock_tail.py \
     --phase flash-tail \
     --device /dev/sdc \
     --usb-serial YOUR_ENCLOSURE_USB_SERIAL \
     --original ph8057-original.bin \
     --run \
     --output stock-tail-capture
   ~~~

   The tool enforces the reference USB VID:PID (`152d:a562`), the original prefix hash, unchanged device identity, no mounted/claimed bridge disks, a fixed read-only command allowlist, zero transfer residue, and no erase/write/reset. It saves a detailed `stock_probe.json` alongside the tail. This is **not a generic full-flash reader**: its target-specific assumptions must not be bypassed on another device.

3. **Reconstruct and verify the complete factory image** from the two files:

   ~~~bash
   cat ph8057-original.bin \
     stock-tail-capture/ph8057-stock-10000-111ff.bin \
     > PH8057_FACTORY_COMPLETE_READBACK.bin
   wc -c PH8057_FACTORY_COMPLETE_READBACK.bin
   sha256sum PH8057_FACTORY_COMPLETE_READBACK.bin
   ~~~

   Verified for this PH8057: size **70,144 bytes** (`0x11200`), SHA256 `ef5ad9af3f3b290c565a4dc65933d539b7bb8b8051ac9bd45386932a77862c09`. The reconstructed CODE/trailer CRCs and OEM configuration were checked. The last 512 bytes are the captured OEM block; **70,144 bytes describe the validated firmware image, not necessarily the flash chip's entire physical capacity**.

The Windows vendor tool separately produced the original **67,072-byte updater-format** readback (`1.bin`). It is not interchangeable with the Linux full-image layout; see [container layouts](firmware-layout.md) and [original updater readback](../firmware/ph8057-device/original/README.md).

**Windows — firmware installation used in this project:**

- Tool: **JMicron FwUpdateTool version 1.19.16.48**, using the appropriate **67,072-byte updater-format CK_COND image** over USB.
- The owner reported a successful update, power cycle, USB enumeration, and the expected SMART RETURN STATUS and CHECK POWER MODE results. No external SPI flasher was used.
- The utility reported an **unknown SPI flash type** and no independently verified post-flash dump was captured. A successful software update does not prove that recovery from a bad flash will be possible over USB.

**For another device:** first identify the original firmware and compatible transport/container format. Acquire and preserve its factory backup, verify actual read length and hashes, and establish a credible recovery procedure. Prefer read-only firmware acquisition first; do not treat the reference Windows writer or Linux reader as automatically compatible with another JMS580 board. Neither third-party tool nor vendor flashing binary is bundled with this project.

## 2. Decide which case applies

| Target input | Required approach |
|---|---|
| **Exact reference factory image** with the pinned size and SHA256 | **No port needed.** Use the normal `ph8057.py build ckcond` command. |
| Same verified 64-KiB **CODE** but a different header/wrapper | Validate its device identity, OEM data, layout, loader and checksum scheme independently. Adapt container handling only if equivalence is proven. Do **not** treat identical CODE as proof of hardware compatibility. |
| Similar JMS580/8051 firmware with differing CODE | **Semantic port:** identify corresponding native functions and control flow, relocate patch logic and prove every new hook/precondition. |
| Different bridge/CPU, fundamentally different command scheduler, signed/encrypted image without an authorized build path | The current patch cannot be transplanted mechanically. Stop and specify what would have to be redesigned or obtained. |

The reference images in this repository have these **specific**, not universal, layouts:

| Reference container | Size | 8051 CODE | OEM block | CPU-to-file offset |
|---|---:|---|---|---|
| PH8057 full SPI image | 70,144 bytes (`0x11200`) | `0x1000..0x10FFF` | `0x11000..0x111FF` | CPU address + `0x1000` |
| PH8057 updater image | 67,072 bytes (`0x10600`) | `0x0400..0x103FF` | `0x10400..0x105FF` | CPU address + `0x0400` |

**These offsets only apply after this exact format has been established.** A 65,536-byte partial SPI prefix is **not** a raw 8051 CODE image. Consult [firmware layout](firmware-layout.md) and [image identities](../firmware/manifests/images.json).

The stock verification in `ph8057.py` / `tools/patching/ckcond/image.py` deliberately rejects other hashes. **Do not replace the reference SHA256 constant with the target SHA256 to bypass that guard.** Build a separate target-specific parser, porting manifest and source validator with equally strict checks.

## 3. Reference implementation: what to study

| File | Role |
|---|---|
| [docs/patches.md](patches.md) | Command ownership, SAT/ATA semantics, all native hook families and abort invalidation |
| [docs/architecture.md](architecture.md) | BOT admission, LUN/port mapping, 8051 memory spaces and command lifecycle |
| [docs/register-map.md](register-map.md), [research/oem/registers.json](../research/oem/registers.json) | Known and inferred OEM/MMIO/IRAM/XDATA fields, with evidence levels |
| [tools/patching/ckcond/core_patch.py](../tools/patching/ckcond/core_patch.py) | Command admission, launch ownership, ATA snapshot and finalization |
| [tools/patching/ckcond/capture_wrappers.py](../tools/patching/ckcond/capture_wrappers.py) | Hooks for different completion/data families |
| [tools/patching/ckcond/sense_patch.py](../tools/patching/ckcond/sense_patch.py) | Sense selection and ATA Return Descriptor composition |
| [tools/patching/ckcond/abort_guard.py](../tools/patching/ckcond/abort_guard.py) | Native USB-wait abort invalidation |
| [tools/patching/ckcond/asm51.py](../tools/patching/ckcond/asm51.py) | 8051 patch assembly |
| [tools/patching/ckcond/image.py](../tools/patching/ckcond/image.py) | Original-image verification, guarded patch application and CRC |
| [firmware/ph8057-device/modified/ckcond_patch_records.json](../firmware/ph8057-device/modified/ckcond_patch_records.json) | Exact **reference-image-only** CPU byte replacements |
| [tools/patching/ckcond/tests/](../tools/patching/ckcond/tests/) | Native instruction and command/abort regressions |
| [tests/hardware/](../tests/hardware/README.md) | Read-only preflight, SCSI/SAT probes and destructive qualification on disposable HDDs |

The 8051 emulator is at [tools/emulator/mcs51.py](../tools/emulator/mcs51.py). Its peripheral states are explicit fixtures, **not** a complete JMS580 hardware model.

## 4. Locate equivalent functions in the target, not just byte sequences

Start by comparing clean CPU CODE regions and identifying reset/interrupt vectors, branch/call targets, reachable routines and the native SAT/BOT state machine. Disassemble the **target**. For each reference hook below, record the function's *behavior*, incoming/outgoing state, instructions displaced by a patch, and evidence for its target equivalent.

| Reference CPU PC | Function to locate in the target | Required evidence |
|---|---|---|
| `7C40` | BOT command admission | LUN, CBW tag/CDB, command generation and pending REQUEST SENSE policy |
| `229E` | SAT12/SAT16 normalization | ATA protocol, command, CK_COND, EXTEND, selected LUN and normalized taskfile |
| `8CA3` | Shared SATA/taskfile launch | Caller provenance, physical port selection and current-command ownership |
| `9837` | Non-data ATA completion | Completed taskfile status/error source and original post-completion flow |
| `970D` | PIO Data-In completion | `4B31/4B32`-equivalent ATA result and transport-error conditions |
| `B37B` | PIO Data-Out completion | ATA status/error and original byte-accounting call |
| `735F` / `9EB2` | DMA completion paths | Completed ATA result, valid/abort conditions, displaced flags and calls |
| `94F9` / hook `9503` | BOT CSW finalization | Native status, sense, tag, residue and publication ordering |
| `C320` | REQUEST SENSE | Per-LUN descriptor lifetime, allocation-length clamp and fallback |
| `CBE3`, exits `CBF6` / `CC04` | USB Data-Out wait / abort | Carry-set abort exits, carry-clear retry targets and later finalizer reachability |

**All PCs and RAM/MMIO addresses in this guide are reference-firmware addresses.** In a different firmware, a similar opcode sequence may implement a different function. Require native control-flow and data-flow evidence for each mapping; record `NOT FOUND` or `UNKNOWN` when appropriate.

Important reference state to trace (not universal memory allocations):

- CBW tag around `7984..7987` and transfer length around `7988..798B`; normalized CDB around `798F`.
- SATA taskfile/launch around `6300..630B`, command at `6302`, physical port at `6312`, command completion/status context.
- ATA completion status/error from the **appropriate** source for each path (e.g. `B9`/`7097` versus `4B31`/`4B32`); do not substitute a later live register read for a completed command's snapshot.
- Original CK_COND slot storage at XDATA `4D00..4DFF`; global active context at `4E00..4E1F`; unpublished-valid marker `4E07`.
- Internal native sense selector `28h` is **not** itself the SCSI sense key, ASC/ASCQ or descriptor length.
- The reference assumes **serialized BOT ownership**. It does not provide a UASP/NCQ command-tag scheduler.

Map target OEM flags separately, and preserve the target's original OEM/board configuration unless changing an identified field is explicitly required and validated. Do not enable UASP, NCQ or hot-swap as part of this port.

## 5. Design and build the target-specific port

1. **Preserve the original:** create a read-only copy, record `SHA256`, length, byte ranges, metadata, complete readback provenance, and the exact target device. Never patch the only factory backup.
2. **Confirm container integrity:** locate CODE start/end, OEM/NVRAM, reserved trailer, CRC/checksum fields, any mirrored fields, loader metadata and signatures. Determine the target's checksum algorithm rather than copying reference offsets. If vendor signing/encryption prevents a valid authorized build, stop.
3. **Create a semantic crosswalk:** one row per hook and memory location, with reference CPU PC, target CPU PC, evidence (instruction/call graph), expected original bytes, replaced instruction behavior, and confidence. Unknown mappings must block release.
4. **Reassess RAM and stack:** verify unused or exclusively owned XDATA/IRAM for per-LUN saved results and active-command state, ISR overlap, stack depth, DPTR bank selection, SFR clobbers and nested interrupts. A region full of zero bytes in a dump does not prove it is spare RAM.
5. **Reallocate CODE and hooks:** find real executable space in the target, verify loader coverage, branch reachability and ownership, then relocate assembly symbols and jumps. The reference `E300`/`E500`/`FD00` caves, `4D00`/`4E00` RAM and `0xFFEC` trailer boundary are not automatically free on another build.
6. **Preserve original semantics:** execute displaced instructions; preserve flags, carry, selected register bank, physical DPTR banks, saved registers, return PCs and original error paths. Handle both relevant abort exits so a stale unpublished ATA result cannot be published.
7. **Generate guarded patch records** from the *target's* original bytes: `cpu`, `old`, `new`, evidence and any relocated symbols. Require equal old/new span where applying in-place hooks, strict non-overlap, explicit cave checks and no writes into protected sections.
8. **Repackage and verify:** recompute target-format checksums and mirrors; verify wrapper, metadata, OEM and other untouched bytes independently. Generate a full before/after diff with exact CPU and file offsets.
9. **Do not change unrelated functions.** In particular, CK_COND does **not** fix the separately documented UDMA Data-Out / CSW residue defect; the port must not claim or attempt such a fix.

The reference CRC scheme is documented in [firmware-layout.md](firmware-layout.md), but **do not assume that another vendor build uses it**. Keep each target's original image, build script, patch manifest and result hashes separate from the canonical PH8057 reference. A new port is a distinct target-specific deliverable, not a new variant in this project's main CLI.

Example target-specific manifest structure (illustrative; **not** valid patch data):

~~~json
{
  "target": "exact board + firmware revision",
  "original_sha256": "SHA256_OF_TARGET_ORIGINAL",
  "container": {
    "size": "MEASURED_LENGTH",
    "code_file_offset": "DISCOVERED_OFFSET",
    "oem_file_offset": "DISCOVERED_OFFSET_OR_UNKNOWN"
  },
  "hooks": [
    {
      "function": "BOT command admission",
      "reference_cpu": "0x7C40",
      "target_cpu": "VERIFIED_TARGET_PC",
      "evidence": "INSTRUCTION_AND_CALL_GRAPH_REFERENCE",
      "expected_old_bytes": "VERIFIED_TARGET_BYTES",
      "replacement_bytes": "TARGET_SPECIFIC_ASSEMBLY"
    }
  ],
  "status": "ANALYSIS_ONLY_UNTIL_VERIFIED"
}
~~~

## 6. Required behavioral regressions

Build independent fixtures for **target-native instructions** rather than only unit-testing a high-level rewritten model:

- SAT12/SAT16 normalization, CK_COND off/on, EXTEND, LUN, port, command tag, and command lifetime.
- SMART RETURN STATUS and CHECK POWER MODE: correct ATA status/error and sector-count/register fields. Include actual active/idle versus standby states when physically measured.
- Valid ATA result with CK_COND=1: appropriate informational CHECK CONDITION with an ATA Return Descriptor; preserve genuine ATA-error/transport-error distinctions.
- Non-data, PIO-in, PIO-out, DMA-in/out, short/malformed/unsupported CDBs, normal SCSI READ/WRITE and native fallback.
- REQUEST SENSE: correct owner, per-LUN association, length 0/short/full, repeated requests and intervening commands.
- Both native USB-wait abort exits, including a *conditional later finalizer*: no stale descriptor; original wait/retry/error behavior retained.
- Reset, command-generation/tag reuse, LUN changes, invalid ATA status (including BSY/DRQ), recovery and failed transfers.
- Byte-for-byte untouched OEM/wrapper regions, deterministic output hashes, independent CRC verification, allowed changes only, and no patch overlap or trailer modification.
- Emulated stack/register/memory invariants with explicit peripheral fixtures, including interrupt-related limitations. Passing simulation is **OFFLINE VALIDATED**, not hardware proof.

Reference tests may inspire these cases, but passing them with **reference** firmware does not test the new image. Run a target-native regression with the original target image and the patched target image under matching fixtures. Report executed tests and skips separately.

## 7. Hardware acceptance and release gates

Do not flash solely because byte patches apply and CRCs match. Before any installation, establish independently recoverable factory firmware, exact board/SPI compatibility, and a workable restoration path.

After a separately authorized installation with an appropriate recovery plan, establish the installed image identity when feasible, then progress from read-only checks to riskier qualification:

1. Stable USB enumeration, all expected LUNs and port mapping; original SCSI READ, INQUIRY, capacity and sense behavior.
2. Targeted read-only SMART STATUS and CHECK POWER MODE with decoded ATA Return Descriptors; test actual standby without waking a disk first if that claim matters.
3. SAT12/SAT16, CK_COND off/on, ATA success/failure, REQUEST SENSE lifetime and cross-LUN association.
4. Reset, USB-wait abort, power-cycle and recovery paths with controlled evidence.
5. Only on **disposable disks**, use the [hardware qualification suite](../tests/hardware/README.md): preflight, protocol-idle, verified I/O and combined stress. The current suite has explicit size/device guards and is not a universal five-bay test.
6. Compare SMART health before/after and preserve fio verification results, SCSI host timeouts, unexpected successes, kernel errors and the scope of USB monitoring.

The original PH8057's successful two-disk BOT stress tests are **not** evidence that the newly ported image was tested. Likewise, zero sampled USB anomalies do not prove that the known `WRITE DMA EXT` residue discrepancy has disappeared.

## 8. Required output from the AI agent

Deliver a *reviewable, target-specific* engineering package:

1. **Identification:** device identity, original hashes/sizes, exact layout and container/integrity interpretation.
2. **Crosswalk:** every relocated hook and memory object; original instruction evidence, calling/branch contracts, confirmed assumptions and blockers.
3. **Source-only builder:** target-specific assembly, guarded old/new records, format-specific checksums and reproducible output. Do not redistribute the vendor-derived BIN.
4. **Diff and manifests:** full changed ranges, protected-region equality, before/after SHA256, independent integrity checks.
5. **Tests:** executed/skipped list, exact fixtures, stock-versus-patched native behavior, remaining hardware qualification gates.
6. **Decision:** `READY FOR CONTROLLED HARDWARE TEST` only when all prerequisites are proven; otherwise `BLOCKED` with precise missing evidence. Never imply general safety from an offline PASS.

### Copy/paste task for an AI assistant

> I own a USB-to-SATA device and have supplied its **original firmware** plus hardware identification. Use this repository's `docs/porting-ckcond.md` as the porting specification and `tools/patching/ckcond/` as a **semantic reference**, not a byte patch template. First identify my firmware's CPU CODE, file wrapper, checksum/signature rules and control flow. Compare it with the exact PH8057 reference; classify whether it is identical, container-only different, semantically similar or incompatible. Map every BOT/SAT/ATA/CSW/REQUEST SENSE/abort hook and RAM assumption with native instruction evidence. If feasible, produce a **separate** guarded, reproducible CK_COND port with target-specific tests and before/after diffs. Preserve the original image, OEM settings and native error/residue behavior. Do not change SHA constants merely to evade source checks. Do not run flashing or destructive tests. Report concrete blockers and uncertainty; do not claim successful porting without target-native validation. Provide source, manifest, test results and a clear release decision.
