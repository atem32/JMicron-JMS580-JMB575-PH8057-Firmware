"""Strict local BOT evidence decoder. No USB, SCSI, ioctl, or device access.

Host completion length and the device's processed-byte claim are kept separate.
The decoder never repairs a CSW or overrides a kernel residue value.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class CBW:
    tag: int
    transfer_length: int
    data_in: bool
    lun: int
    cdb_length: int
    cdb: bytes


@dataclass(frozen=True)
class CSW:
    tag: int
    residue: int
    status: int


def decode_cbw(raw: bytes) -> CBW:
    if len(raw) != 31 or raw[:4] != b"USBC":
        raise ValueError("CBW must have a USBC signature and exactly 31 bytes")
    if raw[12] & 0x7F or raw[13] & 0xF0 or not 1 <= raw[14] <= 16:
        raise ValueError("Reserved CBW flag/LUN bits or invalid command length")
    return CBW(int.from_bytes(raw[4:8], "little"), int.from_bytes(raw[8:12], "little"),
               bool(raw[12] & 0x80), raw[13], raw[14], raw[15:15 + raw[14]])


def decode_csw(raw: bytes) -> CSW:
    if len(raw) != 13 or raw[:4] != b"USBS":
        raise ValueError("CSW must have a USBS signature and exactly 13 bytes")
    if raw[12] > 2:
        raise ValueError("CSW status must be 0, 1, or 2")
    return CSW(int.from_bytes(raw[4:8], "little"), int.from_bytes(raw[8:12], "little"), raw[12])


def analyze_transaction(cbw_raw: bytes, csw_raw: bytes, completions: list[dict],
                        *, sg_io_resid: int | None = None) -> dict:
    cbw, csw = decode_cbw(cbw_raw), decode_csw(csw_raw)
    if cbw.tag != csw.tag:
        raise ValueError("CBW and CSW tags differ")
    if csw.status != 2 and csw.residue > cbw.transfer_length:
        raise ValueError("Meaningful CSW residue exceeds the requested transfer length")
    total = 0
    clean = True
    for completion in completions:
        if set(completion) != {"length", "usb_status"}:
            raise ValueError("Each completion requires exactly length and usb_status")
        if type(completion["length"]) is not int or completion["length"] < 0:
            raise ValueError("USB completion length must be nonnegative")
        if type(completion["usb_status"]) is not int:
            raise ValueError("USB completion status must be an integer")
        total += completion["length"]
        clean = clean and completion["usb_status"] == 0
    if total > cbw.transfer_length:
        raise ValueError("Completed data exceeds the CBW transfer length")
    if sg_io_resid is not None and (type(sg_io_resid) is not int or
                                   not 0 <= sg_io_resid <= cbw.transfer_length):
        raise ValueError("SG_IO residue is outside the requested bounds")
    sat = None
    if len(cbw.cdb) == 16 and cbw.cdb[0] == 0x85:
        cdb = cbw.cdb
        sat = {
            "protocol": (cdb[1] >> 1) & 0x0F,
            "extend": bool(cdb[1] & 1),
            "ck_cond": bool(cdb[2] & 0x20),
            "t_dir": bool(cdb[2] & 0x08),
            "byt_blok": bool(cdb[2] & 0x04),
            "t_length": cdb[2] & 3,
            "ata_command": f"0x{cdb[14]:02X}",
            "sector_count_register": (cdb[5] << 8) | cdb[6],
        }
    known_pattern = (sat is not None and sat["protocol"] == 11 and
                     sat["ata_command"] == "0x35" and not cbw.data_in and
                     cbw.transfer_length > 0 and clean and total == cbw.transfer_length and
                     csw.status == 0 and csw.residue == cbw.transfer_length)
    return {
        "tag": f"0x{cbw.tag:08X}", "lun": cbw.lun,
        "requested_bytes": cbw.transfer_length,
        "direction": "in" if cbw.data_in else "out",
        "usb_completed_bytes": total,
        "usb_completions_clean": clean,
        "csw_status": csw.status, "csw_residue_raw": csw.residue,
        "csw_residue_meaningful": csw.status != 2,
        "device_claimed_processed_bytes": (cbw.transfer_length - csw.residue
                                           if csw.status != 2 else None),
        "sg_io_residue_matches_csw": (sg_io_resid == csw.residue
                                      if sg_io_resid is not None else None),
        "sat": sat,
        "matches_reported_ph8057_udma_anomaly": known_pattern,
        "proof_limit": "USB bytes received are not an independent measurement of bytes processed by the device",
    }
