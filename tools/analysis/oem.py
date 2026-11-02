"""Read-only, scoped PH8057 OEM decoder. No device access or firmware writes.

The metadata describes this exact PH8057 CODE layout. It is not a JMS580
register specification. UNKNOWN is deliberately different from unused.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

IMAGE_SIZE = 0x11200
CODE_BASE = 0x1000
OEM_BASE = 0x11000
OEM_SIZE = 512
STOCK_SHA256 = "ef5ad9af3f3b290c565a4dc65933d539b7bb8b8051ac9bd45386932a77862c09"
OEM_SHA256 = "9521e63007a1289846438195896ef2908a6ccd695c983f90b54fd501eb00e635"
CATEGORIES = {"CONFIRMED", "CODE-CONFIRMED", "HYPOTHESIS", "UNKNOWN", "NOT USED IN VERIFIED PATH"}

# Inclusive OEM ranges, effect, evidence category, aligned CPU entry points.
REGIONS = [
    (0x000, 0x001, "USB VID, little-endian; reordered into 44EC/44ED", "CODE-CONFIRMED", "1FBB,1FC3"),
    (0x002, 0x003, "USB PID, little-endian; reordered into 44EE/44EF", "CODE-CONFIRMED", "1FCB,1FD3"),
    (0x004, 0x005, "No verified OEM boot consumer; 3904 comparison at 98E9 is a different staging-buffer context", "UNKNOWN", "98E9 is not established OEM provenance"),
    (0x006, 0x006, "Copied from 3906 to 44E6; physical/protocol meaning unassigned", "CODE-CONFIRMED", "1FAB"),
    (0x007, 0x007, "Copied from 3907 to 44E7; physical/protocol meaning unassigned", "CODE-CONFIRMED", "1FB3"),
    (0x008, 0x008, "Serial source selector: 5 -> 44E8=0, 7 -> 44E8=1; otherwise nonempty OEM serial -> 44E8=2", "CODE-CONFIRMED", "2061-20E6"),
    (0x009, 0x009, "No individual OEM consumer established", "UNKNOWN", ""),
    (0x00A, 0x00A, "0A enables custom SCSI INQUIRY vendor/product block copies", "CODE-CONFIRMED", "20E6-210D"),
    (0x00B, 0x00B, "No individual OEM consumer established", "UNKNOWN", ""),
    (0x00C, 0x00C, "Manufacturer packed-string wire-length hint; ASCII storage, not UTF-16LE", "CODE-CONFIRMED", "1FDB-201E,E1EB"),
    (0x00D, 0x00D, "Value 03 resembles USB STRING type; this OEM loader does not read/validate it", "NOT USED IN VERIFIED PATH", "1FDB-201E"),
    (0x00E, 0x02D, "Manufacturer ASCII storage; 32 bytes copied to 4511..4530", "CODE-CONFIRMED", "2011-201B"),
    (0x02E, 0x02F, "String-slot tail outside verified 32-byte manufacturer copy", "UNKNOWN", ""),
    (0x030, 0x030, "Product packed-string wire-length hint; ASCII storage, not UTF-16LE", "CODE-CONFIRMED", "201E-2061,E1EB"),
    (0x031, 0x031, "Value 03 resembles USB STRING type; this OEM loader does not read/validate it", "NOT USED IN VERIFIED PATH", "201E-2061"),
    (0x032, 0x051, "Product ASCII storage; 32 bytes copied to 4531..4550", "CODE-CONFIRMED", "2054-205E"),
    (0x052, 0x053, "String-slot tail outside verified 32-byte product copy", "UNKNOWN", ""),
    (0x054, 0x054, "Serial wire-length hint; (length-2)/2 stored in 480A, later clamped to >=12", "CODE-CONFIRMED", "207C-20E6,E1EB"),
    (0x055, 0x055, "Value 03 resembles USB STRING type; this OEM loader does not read/validate it", "NOT USED IN VERIFIED PATH", "207C-20E6"),
    (0x056, 0x073, "Unit-specific serial ASCII storage; 30-byte copy to 4551,480D,48C5", "CODE-CONFIRMED", "20AD-20D1"),
    (0x074, 0x077, "Serial-slot tail outside verified 30-byte serial copy", "UNKNOWN", ""),
    (0x078, 0x0C7, "Zero in stock; individual role unknown; may participate in F8.7 block transfer", "UNKNOWN", "77DA-786E"),
    (0x0C8, 0x0CF, "SCSI INQUIRY vendor ASCII, gated by OEM[00A]==0A", "CODE-CONFIRMED", "20F3-20FD"),
    (0x0D0, 0x0DF, "SCSI INQUIRY product ASCII, gated by OEM[00A]==0A", "CODE-CONFIRMED", "2100-210A"),
    (0x0E0, 0x0E1, "HD signature gates E7/F3 copies and E7.5 initialization", "CODE-CONFIRMED", "210D-2136"),
    (0x0E2, 0x0E6, "Individual role unknown; do not call reserved", "UNKNOWN", ""),
    (0x0E7, 0x0E7, "E7 flags; see all eight bit records", "CODE-CONFIRMED", "2119,44C4,454B,6F4C"),
    (0x0E8, 0x0EF, "Individual role unknown; do not call reserved", "UNKNOWN", ""),
    (0x0F0, 0x0F1, "BC signature gates F2, timer, F8, FA, FB and FC; does NOT gate E7/F3", "CODE-CONFIRMED", "2136-222A"),
    (0x0F2, 0x0F2, "F2 flags; 487D/4583/4584 and IRAM flag updates have set-only paths", "CODE-CONFIRMED", "214A-2199"),
    (0x0F3, 0x0F3, "F3 flags; HD signature controls copy to 44F1", "CODE-CONFIRMED", "210D-2128"),
    (0x0F4, 0x0F7, "Big-endian OEM timer input; 10*max(180,value) modulo 2^32 ->44F4 and4881", "CODE-CONFIRMED", "2199-2200"),
    (0x0F8, 0x0F8, "F8 dispatch flags; BC-gated copy to4589; transfers require separate execution", "CODE-CONFIRMED", "2200,C4D3-C501"),
    (0x0F9, 0x0F9, "No individual decoder established; included in F8.7 staging block", "UNKNOWN", "77DA-786E"),
    (0x0FA, 0x0FA, "39FA ->4174 ->7E18 in USB SET_ADDRESS path; units unknown", "CODE-CONFIRMED", "2208,6232,279B"),
    (0x0FB, 0x0FB, "39FB ->4175 ->7086; F3.2 may report zero-state event; units unknown", "CODE-CONFIRMED", "2210,385A,7321,9CC6"),
    (0x0FC, 0x0FC, "Strictly >0x20 overrides4AD6; 028C copies4A18; counter decremented if7075>100", "CODE-CONFIRMED", "2218,028C,003E"),
    (0x0FD, 0x0FD, "No individual decoder established; included in F8.7 staging block", "UNKNOWN", "77DA-786E"),
    (0x0FE, 0x0FF, "JM signature gates OEM initializer; invalid takes default-data handler9D1C", "CODE-CONFIRMED", "1F87-1F9B,2227"),
    (0x100, 0x1FF, "Second OEM half: zero in this stock image; not transferred by verified256-byte paths; role unknown", "UNKNOWN", "1F49,77DA"),
]

# Each physical interpretation is scoped separately from the CODE effect.
BIT_FIELDS = {
    "E7": [
        ("CODE-CONFIRMED", "USB configuration power reporting: 0 self-powered,1 bus-powered; does not switch power rails", "454B-457F"),
        ("CODE-CONFIRMED", "Sets IRAM bit38 enabling special READ/WRITE(16) path; no 4Kn inference", "6F4C-6F56,5015"),
        ("CODE-CONFIRMED", "Cleared at6F5D before same-path checks; physical purpose unknown", "6F57-6F82"),
        ("CODE-CONFIRMED", "Enables writes7085=2F and508F=01; silicon semantics unknown", "D422-D435"),
        ("CODE-CONFIRMED", "Advertises DPOFUA in MODE SENSE header; does not prove FUA execution", "364E-367E,379E,37C8,6F7C"),
        ("CODE-CONFIRMED", "Sets4172; 3A2D consults7A04/7A05 and conditionally writes4575=3", "2129-2136,3A2D"),
        ("CODE-CONFIRMED", "UAS descriptor gate; cleared at6F57 and46ED; UASP NOT IMPLEMENTED", "44C4,6F57,46ED"),
        ("CODE-CONFIRMED", "5082 bits1/2 follow flag atD682; bit3 set in BOTH cases; independent cleanup clears bits1/2", "D682,5535,6631,7BED"),
    ],
    "F2": [
        ("NOT USED IN VERIFIED PATH", "No change in214A-2199 outputs; global/indirect consumers not excluded", "214A-2199"),
        ("NOT USED IN VERIFIED PATH", "No change in214A-2199 outputs; global/indirect consumers not excluded", "214A-2199"),
        ("CODE-CONFIRMED", "Sets4588=1; clear occurs earlier1F7C-1F80, not the F2 slice", "2172-217F,1F7C,875A"),
        ("CODE-CONFIRMED", "Assigns44F3 from flag; enabled sets487D=1 and transforms timer; disabled preserves487D here", "214A-2160,2199-2200,6B04"),
        ("CODE-CONFIRMED", "Sets4583=1 when enabled, otherwise preserves; state-dependent7058.bit5 effects", "217F-218C,3F61"),
        ("CODE-CONFIRMED", "Sets4584=1 when enabled, otherwise preserves; state-dependent7058.bit4 effects", "218C-2199,3F61"),
        ("CODE-CONFIRMED", "Sets IRAM bit39; initializer clears earlier; at64B7 false ORs7801 with10, true preserves", "1F78,2169-2172,64B7"),
        ("CODE-CONFIRMED", "Sets IRAM bit3A (=byte27.bit2); whole byte saved/restored viaB008; independent functional reader unknown", "1F7A,2160-2169,81DC,832F"),
    ],
    "F3": [
        ("CODE-CONFIRMED", "Event/topology paths; cleared by6F62; NOT a qualified hot-swap switch", "2804,6F62,8FD9"),
        ("CODE-CONFIRMED", "JM vendor response indicators;7059.bit1 status path; private protocol unknown", "272E,2D52,9CE1"),
        ("CODE-CONFIRMED", "If7086==0 arms4176/4177; JM report sets3506.bit0 and clears4177", "7321,9CC6,2210,385A"),
        ("UNKNOWN", "No individual direct decoder established; whole-byte and indirect consumers remain possible", "44F1 direct occurrence survey only"),
        ("CODE-CONFIRMED", "Filters7993 high-nibble0 low2=0 event: off writes4BC9=2E,4AD8=1,4173=0; on skips", "5216-527B"),
        ("CODE-CONFIRMED", "USB2-only policy paths: state6, bcdUSB0200 and suppressed BOS; link operation untested", "32E1,DD28,B6AE"),
        ("CODE-CONFIRMED", "TRIM/DSM capability gate requires IDENTIFY and per-port capability; command success unproven", "16C2,1177,C98E"),
        ("CODE-CONFIRMED", "Additional NCQ enable in no-port-multiplier branch with IDENTIFY words75/76; not global NCQ control", "154E-156F"),
    ],
    "F8": [
        *[("NOT USED IN VERIFIED PATH", "No individual dispatch inC4D3-C501; value may be carried in F8.7 block", "C4D3-C501") for _ in range(6)],
        ("CODE-CONFIRMED", "71C4(04),7616(02),71C4(40): CODE1A18..1B17 ->XDATA7500..75FF; peripheral meaning unknown", "C4D3,7616,8026"),
        ("CODE-CONFIRMED", "71C4(08),77DA(7300),71C4(80): staging3900..39FF ->7300..73FF with compare; up to12 copies, sticky mismatch", "C4E9,77DA-786E,800A"),
    ],
}

MMIO = [
    ("7801", "F2.6", "64B7 ORs bit4 only if IRAM bit39 is zero; usual preceding write is41", "Physical bit meaning unknown"),
    ("7058", "F2.4,F2.5", "Dispatcher3F61 controls bits5/4 by state", "Not a globally fixed register value"),
    ("5082", "E7.7", "D682 sets bit3 always and assigns bits1/2; cleanup clears1/2", "Peripheral meaning unknown"),
    ("7085,508F", "E7.3", "D422 conditional writes2F and01", "Peripheral meaning unknown"),
    ("7086", "FB,F3.2", "385A copies4175;7321 tests zero and arms event", "No time unit or hotplug interpretation proven"),
    ("7E18", "FA", "6232 writes4174 after validated SET_ADDRESS;279B reads when415E enabled", "Raw value, not established milliseconds"),
    ("70B0-70B3", "F2.3,F4-F7,MODE SELECT", "9185 path submits runtime4881 four bytes throughB409", "Byte-transfer relation confirmed; peripheral timebase unknown"),
    ("70B4-70B5,70B7", "UNKNOWN", "No OEM-specific meaning established", "Do not interpolate adjacent-register meanings"),
    ("70B6", "MODE SELECT", "9711/B409 path uses command/mode value2", "Context-dependent command interface"),
    ("70B8", "MODE SELECT", "9185 path writes64", "Physical meaning unknown"),
    ("70C0", "MODE SELECT", "9711 interprets synthetic result1/2 with alternate SZCT values", "NOT a universally valid byte-count register"),
    ("70C1-70C7", "UNKNOWN", "No universal OEM role established", "UDMA counter roles require separate context and hardware evidence"),
    ("70C8", "MODE SELECT", "Related completion/status path", "Physical bit semantics not proven"),
    ("7075", "FC", "003E: threshold>100 decrements4A18, increments4A9B, clears7075", "Tick source and unit unknown"),
    ("7300-73FF", "F8.7", "256-byte staging copy and comparison", "Not proven SPI/NVRAM storage"),
    ("7500-75FF", "F8.6", "256-byte CODE table copy", "Peripheral table function unknown"),
]


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

    Unlike historical zero-memory projections, this accepts a prior state and
    preserves values when the actual instructions do not write the location.
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
    representation uses high-byte/low-byte pairs1A:B,1C:D,1E:F. Historical v16
    interchanged the named wValue and wIndex fixtures; both-zero cases hid it.
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
        secret = 0x056 <= off <= 0x077 and not include_sensitive
        atlas.append({"oem_offset": f"{off:03X}", "file_offset": f"{OEM_BASE + off:05X}",
                      "stock_byte": "REDACTED" if secret else f"{o[off]:02X}",
                      "category": category, "effect": effect, "cpu_evidence": cpu,
                      "boot_stage_xdata": f"{0x3900 + off:04X}" if off < 256 else "NO VERIFIED BOOT-STAGING MAPPING",
                      "included_in_F8_bit7_copy": off < 256,
                      "global_unused_claim": False})
    return atlas


def write_outputs(raw: bytes, directory: Path, *, include_sensitive=False, source_path=None) -> None:
    names = ("oem_decoded.json", "oem_512_bytes.json", "oem_512_bytes.csv", "oem_32_bits.csv", "mmio_dependencies.json")
    # This decoder stays dependency-free. Validate all destinations before
    # writing any table, including hard links and symlinks to the input BIN.
    for name in names:
        path = directory / name
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError("OEM outputs must be regular files, not links or devices")
        if source_path is not None:
            source = Path(source_path)
            if path.resolve() == source.resolve() or (path.exists() and path.samefile(source)):
                raise ValueError("OEM output aliases the immutable source file")
    directory.mkdir(parents=True, exist_ok=True)
    decoded = decode_oem(raw, include_sensitive=include_sensitive)
    atlas = build_atlas(raw, include_sensitive=include_sensitive)
    (directory / "oem_decoded.json").write_text(json.dumps(decoded, indent=2) + "\n")
    (directory / "oem_512_bytes.json").write_text(json.dumps(atlas, indent=2) + "\n")
    with (directory / "oem_512_bytes.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(atlas[0]))
        writer.writeheader()
        writer.writerows(atlas)
    bits = [{"field": field, **row} for field, value in decoded["flags"].items() for row in value["bits"]]
    with (directory / "oem_32_bits.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(bits[0]))
        writer.writeheader()
        writer.writerows(bits)
    dependencies = [{"address": a, "source": s, "code_effect": e, "limitation": l} for a, s, e, l in MMIO]
    (directory / "mmio_dependencies.json").write_text(json.dumps(dependencies, indent=2) + "\n")


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
    print("Wrote 512 OEM rows and 32 bit records; no hardware access")


if __name__ == "__main__":
    main()
