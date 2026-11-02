"""The supplied, rejected 64-byte prototype, retained only as a regression.

This module cannot write a file and does not present a releasable patch API.
It replays the old unsafe hypothesis in memory so tests can falsify it.
Do not import it into a production firmware builder.
"""
from __future__ import annotations

try:
    from .trace_patch import collect_patches, ORIGINAL, CODE_OFFSET, HOOK, CAVE
except ImportError:
    from trace_patch import collect_patches, ORIGINAL, CODE_OFFSET, HOOK, CAVE

HELPER_HEX = (
    "e4ff12aef4e559b46735201232e55ab4012d905052e030e0269050e2e07020"
    "e5a320e71b9070c0e07015a3e07011a3e0700da3e07009e4f558f557f556f55522"
)


def rejected_overlay_for_test(raw: bytes) -> bytes:
    collect_patches(raw)  # same exact source validation; no generic patching
    helper = bytes.fromhex(HELPER_HEX)
    start = CODE_OFFSET + CAVE
    if raw[start:start + len(helper)] != bytes(len(helper)):
        raise ValueError("Rejected prototype cave is not empty")
    out = bytearray(raw)
    out[CODE_OFFSET + HOOK:CODE_OFFSET + HOOK + 5] = bytes.fromhex("12e7000000")
    out[start:start + len(helper)] = helper
    return bytes(out)
