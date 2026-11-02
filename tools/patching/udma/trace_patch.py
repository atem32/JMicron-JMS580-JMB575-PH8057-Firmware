"""Minimal, offline-only UDMA observation trampoline. THIS IS NOT A FIX.

It neither reads an assumed counter nor changes residue, sense, or status.
The two stable observation PCs are useful with the supplied native-instruction
harness (or a separately qualified debugger). They are not a hardware logging
channel. No XDATA allocation or on-device reader is invented.
"""
from __future__ import annotations

import hashlib

STOCK_SHA256 = "ef5ad9af3f3b290c565a4dc65933d539b7bb8b8051ac9bd45386932a77862c09"
V8_SHA256 = "4b7ac3e5bd124d8e44281e9aa79b7b65f7b62c54410ffd1abd8af4a586d74e11"
REVISED_CKCOND_SHA256 = "2aaece707763b5dab32c46cf10c17c88345d73b8635365a354dcffe8817b422b"
SIZE = 0x11200
CODE_OFFSET = 0x1000
HOOK = 0x7377
CAVE = 0xE700
PRE_COMPLETION = CAVE
POST_COMPLETION = CAVE + 5
ORIGINAL = bytes.fromhex("e4 ff 12 ae f4")
REPLACEMENT = bytes.fromhex("12 e7 00 00 00")
# Original three instructions (five bytes), two observation NOPs, RET.
HELPER = ORIGINAL + bytes.fromhex("00 00 22")


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def require(value, reason):
    if not value:
        raise ValueError(reason)


def collect_patches(raw: bytes) -> list[dict]:
    """Return two exact guarded CODE edits, for an integrity-aware repacker."""
    require(len(raw) == SIZE, "A complete 70,144-byte image is required")
    require(sha256(raw) in (STOCK_SHA256, V8_SHA256, REVISED_CKCOND_SHA256),
            "Unsupported source image hash")
    require(raw[CODE_OFFSET + HOOK:CODE_OFFSET + HOOK + 5] == ORIGINAL,
            "Completion hook does not contain the exact expected instructions")
    require(raw[CODE_OFFSET + CAVE:CODE_OFFSET + CAVE + len(HELPER)] == bytes(len(HELPER)),
            "Diagnostic code cave is occupied")
    require(raw[CODE_OFFSET + 0x737C:CODE_OFFSET + 0x737E] == bytes.fromhex("80 12"),
            "Original continuation branch differs")
    return [
        {"cpu": f"0x{HOOK:04X}", "old": ORIGINAL.hex(), "new": REPLACEMENT.hex()},
        {"cpu": f"0x{CAVE:04X}", "old": bytes(len(HELPER)).hex(), "new": HELPER.hex()},
    ]


def overlay_for_emulation(raw: bytes) -> bytes:
    """In-memory overlay only. CRCs intentionally remain those of the base.

    Do not serialize this return value as a hardware-ready image. The artifact
    builder uses the common integrity-aware repacker separately.
    """
    out = bytearray(raw)
    for item in collect_patches(raw):
        at = CODE_OFFSET + int(item["cpu"], 16)
        new = bytes.fromhex(item["new"])
        out[at:at + len(new)] = new
    require(out[0x11000:] == raw[0x11000:], "OEM configuration changed")
    return bytes(out)


def manifest(raw: bytes) -> dict:
    return {
        "classification": "UDMA_TRACE_ONLY_DO_NOT_FLASH__NOT_A_RESIDUE_FIX",
        "source_sha256": sha256(raw),
        "patches": collect_patches(raw),
        "observation_points": {
            "before_original_completion": f"0x{PRE_COMPLETION:04X}",
            "after_original_completion": f"0x{POST_COMPLETION:04X}",
        },
        "new_persistent_ram_bytes": 0,
        "new_mmio_reads": 0,
        "additional_nested_stack_bytes": 2,
        "known_effect": "Retains original accounting, including the known 512-byte residue defect",
        "not_qualified": [
            "Real execution of the code cave and added stack depth",
            "Timing, interrupts, reset races, and physical controller behavior",
            "A debugger, trace port, or persistent device-side observation channel",
            "A real Data-Out processed-byte source",
        ],
    }
