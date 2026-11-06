"""The supplied, rejected 64-byte prototype, retained only as a regression.

This module cannot write a file and does not present a releasable patch API.
It replays the old unsafe hypothesis in memory so tests can falsify it.
Do not import it into a production firmware builder.
"""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ckcond"))
from image import CODE_OFFSET, IMAGE_SIZE, STOCK_FULL_SHA, CKCOND_SHA, check_crc, sha

HOOK = 0x7377
CAVE = 0xE700
ORIGINAL = bytes.fromhex("e4 ff 12 ae f4")

HELPER_HEX = (
    "e4ff12aef4e559b46735201232e55ab4012d905052e030e0269050e2e07020"
    "e5a320e71b9070c0e07015a3e07011a3e0700da3e07009e4f558f557f556f55522"
)


def rejected_overlay_for_test(raw: bytes) -> bytes:
    if len(raw) != IMAGE_SIZE or sha(raw) not in (STOCK_FULL_SHA, CKCOND_SHA):
        raise ValueError("Counterexample requires an exact factory or CK_COND image")
    check_crc(raw)
    if raw[CODE_OFFSET + HOOK:CODE_OFFSET + HOOK + len(ORIGINAL)] != ORIGINAL:
        raise ValueError("Native completion instructions differ")
    if raw[CODE_OFFSET + 0x737C:CODE_OFFSET + 0x737E] != bytes.fromhex("8012"):
        raise ValueError("Native continuation differs")
    helper = bytes.fromhex(HELPER_HEX)
    start = CODE_OFFSET + CAVE
    if raw[start:start + len(helper)] != bytes(len(helper)):
        raise ValueError("Rejected prototype cave is not empty")
    out = bytearray(raw)
    out[CODE_OFFSET + HOOK:CODE_OFFSET + HOOK + 5] = bytes.fromhex("12e7000000")
    out[start:start + len(helper)] = helper
    return bytes(out)
