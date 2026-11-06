"""Read-only, scoped PH8057 OEM decoder. No device access or firmware writes.

The metadata describes this exact PH8057 CODE layout. It is not a JMS580
register specification. UNKNOWN is deliberately different from unused.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

IMAGE_SIZE = 0x11200
CODE_BASE = 0x1000
OEM_BASE = 0x11000
OEM_SIZE = 512
STOCK_SHA256 = "ef5ad9af3f3b290c565a4dc65933d539b7bb8b8051ac9bd45386932a77862c09"
OEM_SHA256 = "9521e63007a1289846438195896ef2908a6ccd695c983f90b54fd501eb00e635"
CATEGORIES = {"CONFIRMED", "INFERRED", "HYPOTHESIS", "UNKNOWN"}
ATLAS_PATH = Path(__file__).resolve().parents[2] / "research/oem/registers.json"
REGISTER_ATLAS = json.loads(ATLAS_PATH.read_text())

# One metadata source; these tuple views preserve the decoder's public API.
REGIONS = [(row["start"], row["end"], row["purpose"], row["confidence"], row["cpu_paths"])
           for row in REGISTER_ATLAS["oem_regions"]]
BIT_FIELDS = {
    field: [(row["confidence"], row["purpose"], row["cpu_paths"])
            for row in REGISTER_ATLAS["oem_bits"] if row["field"] == field]
    for field in ("E7", "F2", "F3", "F8")
}


def validate_atlas_metadata():
    """Validate namespace coverage, confidence and evidence references."""
    if REGISTER_ATLAS["schema_version"] != 1:
        raise ValueError("Unsupported register-atlas schema")
    coverage = [0] * OEM_SIZE
    for row in REGISTER_ATLAS["oem_regions"]:
        if not 0 <= row["start"] <= row["end"] < OEM_SIZE:
            raise ValueError("OEM range outside the 512-byte block")
        for offset in range(row["start"], row["end"] + 1):
            coverage[offset] += 1
    if coverage != [1] * OEM_SIZE:
        raise ValueError("OEM ranges must cover every byte exactly once")
    for field in BIT_FIELDS:
        bits = [row["bit"] for row in REGISTER_ATLAS["oem_bits"] if row["field"] == field]
        if bits != list(range(8)):
            raise ValueError("Every option byte must define bits 0 through 7 once")
    if len(REGISTER_ATLAS["oem_bits"]) != 32:
        raise ValueError("Unexpected OEM option byte")
    for group in ("oem_regions", "oem_bits", "registers"):
        for row in REGISTER_ATLAS[group]:
            if row["confidence"] not in CATEGORIES:
                raise ValueError("Unknown confidence category")
            if not all(row.get(key) for key in ("address", "purpose", "read_write", "unknowns")):
                raise ValueError("Incomplete atlas entry")
            if any(ref not in REGISTER_ATLAS["evidence"] for ref in row["evidence"]):
                raise ValueError("Missing instruction evidence")
            if row["confidence"] == "CONFIRMED" and not row["evidence"] and not row.get("reference"):
                raise ValueError("Confirmed entry has no instruction or source reference")
    return True


def verify_atlas_evidence(raw):
    """Check cited instruction bytes and decoding against an exact local image.

    This checks static evidence, not instruction reachability or physical MMIO
    behavior. Native path regressions establish the bounded data-flow claims.
    """
    from mcs51 import decode
    digest = hashlib.sha256(raw).hexdigest()
    identities = REGISTER_ATLAS["images"]
    matches = [name for name, item in identities.items()
               if digest == item["sha256"] and len(raw) == item["size"]]
    if len(matches) != 1:
        raise ValueError("Atlas evidence requires an exact declared firmware image")
    name = matches[0]
    offset = int(identities[name]["code_offset"], 16)
    code = raw[offset:offset + 65536]
    checked = 0
    for item in REGISTER_ATLAS["evidence"].values():
        if item["image"] != name:
            continue
        for address, expected, assembly in item["instructions"]:
            pc = int(address, 16)
            expected = bytes.fromhex(expected)
            instruction = decode(code, pc)
            if instruction.raw != expected or f"{instruction.mnemonic} {instruction.operands}".rstrip() != assembly:
                raise ValueError(f"Atlas instruction differs at CPU {pc:04X}")
            checked += 1
    return {"image": name, "sha256": digest, "instructions_checked": checked}


def extract_oem(raw: bytes) -> bytes:
    if len(raw) == OEM_SIZE:
        return bytes(raw)
    if len(raw) != IMAGE_SIZE:
        raise ValueError("Expected 512-byte OEM block or exact-size 0x11200 PH8057 image")
    return bytes(raw[OEM_BASE:OEM_BASE + OEM_SIZE])


def timer_value(value: int) -> dict:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 0xFFFFFFFF:
        raise ValueError("OEM timer must be an unsigned 32-bit integer")
    product = 10 * max(180, value)
    return {"input_be32": value, "runtime_szct": product & 0xFFFFFFFF,
            "scsi_seconds": (product & 0xFFFFFFFF) / 10,
            "arithmetic_wraps": product > 0xFFFFFFFF,
            "hardware_spindle_time": "UNKNOWN"}


def f2_slice_effect(value: int, prior: dict | None = None) -> dict:
    """Exact state transition at214A-2199, including set-only outputs.

    A prior state distinguishes preserved values from explicit zero writes.
    Values remain unchanged when the actual instructions do not write them.
    """
    if not 0 <= value <= 255:
        raise ValueError("F2 must fit one byte")
    out = {"44F3": 0, "487D": 0, "4583": 0, "4584": 0, "4588": 0,
           "IRAM.bit39": 0, "IRAM.bit3A": 0}
    out.update(prior or {})
    out["44F3"] = int(bool(value & 8))
    for mask, target in [(8, "487D"), (16, "4583"), (32, "4584"),
                         (4, "4588"), (64, "IRAM.bit39"), (128, "IRAM.bit3A")]:
        if value & mask:
            out[target] = 1
    return out


def expected_7058(state: int, f2_bit4: bool, f2_bit5: bool, initial: int) -> int:
    out = initial
    if state in (0, 3, 4, 6):
        out = (out & ~0x10) | (0x10 if f2_bit5 else 0)
    if state == 5:
        out &= ~0x10
    if f2_bit4:
        if state in (0, 5, 6):
            out |= 0x20
        elif state in (3, 4):
            out &= ~0x20
    return out


def retry_77da_model(mismatches: list[bool]) -> dict:
    """Exact bounded software loop; inputs are assumed compare outcomes only.

    The mismatch latch is cleared once on entry, not once per attempt. This
    model cannot establish actual hardware write completion or retry safety.
    """
    if not mismatches:
        raise ValueError("At least one comparison outcome is required")
    count = latch = attempts = 0
    while True:
        failure = mismatches[min(attempts, len(mismatches) - 1)]
        attempts += 1
        if failure:
            latch = 1
        if count > 10:
            break
        count += 1
        if not latch:
            break
    return {"copies": attempts, "counter_4BC5": count, "mismatch_4BC4": latch}


def setup_iram(bm_request_type: int, request: int, value: int, index: int, length: int) -> dict[int, int]:
    """USB setup fields in the firmware's internal big-endian IRAM layout.

    USB wire wValue/wIndex/wLength are little-endian. This decoded internal
    representation uses high-byte/low-byte pairs 1A:B, 1C:D, 1E:F. Asymmetric
    value/index tests are needed because both-zero fixtures cannot distinguish them.
    """
    if not (0 <= bm_request_type < 256 and 0 <= request < 256):
        raise ValueError("Request header fields must fit one byte")
    if any(not isinstance(v, int) or not 0 <= v <= 65535 for v in (value, index, length)):
        raise ValueError("USB setup word fields must fit sixteen bits")
    return {0x18: bm_request_type, 0x19: request,
            0x1A: value >> 8, 0x1B: value & 255,
            0x1C: index >> 8, 0x1D: index & 255,
            0x1E: length >> 8, 0x1F: length & 255}


def packed_string(oem: bytes, offset: int, capacity: int, sensitive: bool) -> dict:
    length = oem[offset]
    # The caller skips E1EB for a zero length; do not report its unreachable
    # underflow result as a 127-character request.
    char_slots = ((length - 2) & 255) >> 1 if length else None
    payload = oem[offset + 2:offset + 2 + capacity]
    valid = length == 0 or (2 <= length <= 2 + 2 * capacity and not length & 1)
    result = {"offset": f"{offset:03X}", "wire_length_hint": length,
              "type_byte": oem[offset + 1], "type_checked_by_loader": False,
              "computed_char_slots": char_slots, "loader_requested_by_length": bool(length),
              "copied_ascii_capacity": capacity,
              "well_formed_length": valid,
              "text": "[REDACTED]" if sensitive else payload.split(b"\0", 1)[0].decode("ascii", "backslashreplace")}
    return result


def decode_oem(raw: bytes, *, include_sensitive: bool = False) -> dict:
    o = extract_oem(raw)
    jm = o[0xFE:0x100] == b"JM"
    hd = o[0xE0:0xE2] == b"HD"
    bc = o[0xF0:0xF2] == b"BC"
    return {
        "scope": "PH8057 layout only; CODE facts are not silicon qualification",
        "image_sha256": hashlib.sha256(raw).hexdigest() if len(raw) == IMAGE_SIZE else None,
        "exact_stock_image": len(raw) == IMAGE_SIZE and hashlib.sha256(raw).hexdigest() == STOCK_SHA256,
        "oem_sha256": hashlib.sha256(o).hexdigest(),
        "signatures": {"JM": jm, "HD": hd, "BC": bc},
        "signature_scopes": {"JM": "outer initializer gate", "HD": "E7/F3 and E7.5", "BC": "F2,F4-F7,F8,FA,FB,FC"},
        "active_groups": {"base_OEM": jm, "E7_F3": jm and hd, "F2_timer_aux": jm and bc},
        "usb_vid": f"{int.from_bytes(o[0:2], 'little'):04X}",
        "usb_pid": f"{int.from_bytes(o[2:4], 'little'):04X}",
        "manufacturer": packed_string(o, 0x0C, 32, False),
        "product": packed_string(o, 0x30, 32, False),
        "serial": packed_string(o, 0x54, 30, not include_sensitive),
        "serial_source_selector": {"raw": o[8], "44E8": 0 if o[8] == 5 else 1 if o[8] == 7 else 2 if o[0x54] else "unchanged in this branch"},
        "scsi_inquiry_marker_present": o[0x0A] == 0x0A,
        "scsi_inquiry_enabled": jm and o[0x0A] == 0x0A,
        "scsi_vendor": o[0xC8:0xD0].decode("ascii", "backslashreplace"),
        "scsi_product": o[0xD0:0xE0].decode("ascii", "backslashreplace"),
        "flags": {field: {"raw": o[int(field, 16)], "bits": [
            {"bit": b, "value": (o[int(field, 16)] >> b) & 1,
             "category": entry[0], "effect": entry[1], "cpu": entry[2]}
            for b, entry in enumerate(rows)]} for field, rows in BIT_FIELDS.items()},
        "timer": timer_value(int.from_bytes(o[0xF4:0xF8], "big")),
        "timer_enabled_in_oem": bool(o[0xF2] & 8),
        "timer_conversion_reached_in_initializer": jm and bc and bool(o[0xF2] & 8),
        "auxiliary": {f"{v:02X}": o[v] for v in range(0xF9, 0xFE)},
        "fc_override": o[0xFC] if o[0xFC] > 0x20 else None,
        "second_half_nonzero_bytes": sum(bool(v) for v in o[0x100:]),
        "second_half_category": "UNKNOWN",
    }


def build_atlas(raw: bytes, *, include_sensitive: bool = False) -> list[dict]:
    o = extract_oem(raw)
    atlas = []
    for off in range(512):
        region = [r for r in REGIONS if r[0] <= off <= r[1]]
        if len(region) != 1:
            raise AssertionError(f"OEM region coverage {off:03X}: {len(region)}")
        _, _, effect, category, cpu = region[0]
        metadata = next(row for row in REGISTER_ATLAS["oem_regions"]
                        if row["start"] <= off <= row["end"])
        secret = 0x056 <= off <= 0x077 and not include_sensitive
        atlas.append({"oem_offset": f"{off:03X}", "file_offset": f"{OEM_BASE + off:05X}",
                      "stock_byte": "REDACTED" if secret else f"{o[off]:02X}",
                      "category": category, "effect": effect, "cpu_evidence": cpu,
                      "read_write": metadata["read_write"], "evidence": metadata["evidence"],
                      "unknowns": metadata["unknowns"],
                      "boot_stage_xdata": f"{0x3900 + off:04X}" if off < 256 else "NO VERIFIED BOOT-STAGING MAPPING",
                      "included_in_F8_bit7_copy": off < 256,
                      "global_unused_claim": False})
    return atlas


def register_map_markdown():
    """Render the complete six-column table from the canonical metadata."""
    def cell(value):
        return str(value).replace("|", "\\|").replace("\n", " ")

    lines = ["# PH8057 register and OEM atlas", "", REGISTER_ATLAS["scope"], "",
             "Generated from `research/oem/registers.json`. CPU addresses name CODE;",
             "the full SPI file offset is CPU + `0x1000`. Confidence describes the",
             "stated software fact, not hardware qualification.", ""]
    groups = [("OEM byte ranges", REGISTER_ATLAS["oem_regions"]),
              ("OEM flag bits", REGISTER_ATLAS["oem_bits"])]
    for space in REGISTER_ATLAS["address_namespaces"]:
        rows = [row for row in REGISTER_ATLAS["registers"] if row["space"] == space]
        if rows:
            groups.append((space, rows))
    for title, rows in groups:
        lines += [f"## {title}", "", "| Address | Name / purpose | Read/write | Evidence | Confidence | Unknowns |",
                  "|---|---|---|---|---|---|"]
        for row in rows:
            references = ", ".join(f"[{ref}](#{ref.lower()})" for ref in row["evidence"])
            if row.get("reference"):
                references += ("; " if references else "") + f"`{row['reference']}`"
            if not references:
                references = "No individual consumer established"
            lines.append("| " + " | ".join(cell(value) for value in
                         (row["address"], row["purpose"], row["read_write"], references,
                          row["confidence"], row["unknowns"])) + " |")
        lines.append("")
    lines += ["## Instruction evidence", "",
              "Excerpts retain exact image identity, CPU address, bytes and assembly.",
              "A byte match checks the excerpt; it does not prove whole-program reachability.", ""]
    for name, item in REGISTER_ATLAS["evidence"].items():
        lines += [f"### {name}", "", f"Image: `{item['image']}`. Reference: `{item.get('reference', 'see atlas entry')}`.", ""]
        if item.get("scope"):
            lines += [item["scope"], ""]
        lines += ["```text", *[f"{address}: {raw:<20} {assembly}"
                                for address, raw, assembly in item["instructions"]], "```", ""]
    return "\n".join(lines)


def write_outputs(raw: bytes, directory: Path, *, include_sensitive=False, source_path=None) -> None:
    names = ("oem_atlas.json", "register-map.md")
    directory = Path(directory)
    # Validate every destination before writing either view.
    if directory.is_symlink():
        raise ValueError("OEM output directory must not be a symbolic link")
    for name in names:
        path = directory / name
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError("OEM outputs must be regular files, not links or devices")
        if source_path is not None:
            source = Path(source_path)
            if path.resolve() == source.resolve() or (path.exists() and path.samefile(source)):
                raise ValueError("OEM output aliases the immutable source file")
    validate_atlas_metadata()
    decoded = decode_oem(raw, include_sensitive=include_sensitive)
    atlas = build_atlas(raw, include_sensitive=include_sensitive)
    output = {"schema_version": 1, "metadata": "research/oem/registers.json",
              "metadata_sha256": hashlib.sha256(ATLAS_PATH.read_bytes()).hexdigest(),
              "decoded": decoded, "oem_bytes": atlas}
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "oem_atlas.json").write_text(json.dumps(output, indent=2) + "\n")
    (directory / "register-map.md").write_text(register_map_markdown())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--include-sensitive", action="store_true", help="Private outputs only: include serial payload")
    args = parser.parse_args()
    if not args.image.is_file():
        parser.error("Input must be a regular local file")
    raw = args.image.read_bytes()
    if len(raw) != IMAGE_SIZE or hashlib.sha256(raw).hexdigest() != STOCK_SHA256:
        parser.error("Native OEM atlas applies only to the exact factory image")
    write_outputs(raw, args.out, include_sensitive=args.include_sensitive, source_path=args.image)
    print("Wrote oem_atlas.json and register-map.md; no hardware access")


if __name__ == "__main__":
    main()
