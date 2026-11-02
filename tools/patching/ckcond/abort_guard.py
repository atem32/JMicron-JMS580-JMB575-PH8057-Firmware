"""Invalidate an unpublished ATA snapshot when the native USB wait aborts.

This fixes a CK_COND association error only. Native residue, sense, status,
reset scheduling, and data-transfer accounting remain unchanged. The observed
abort meaning is the native E140/CBE3 control flow, not a hardware timeout model.
"""
from asm51 import Asm

SYMBOLS = {"abort_wait_first": 0xFD00, "abort_wait_endpoint": 0xFD08,
           "invalidate_aborted_snapshot": 0xFD20}
HOOKS = ((0xCBF6, "50eb22", "abort_wait_first", 0xCBE3),
         (0xCC04, "50f322", "abort_wait_endpoint", 0xCBF9))


def build_bodies():
    result = []
    for _, _, symbol, retry in HOOKS:
        asm = Asm(SYMBOLS[symbol])
        # Recreate original JNC retry. Both original exits retain the CBE3
        # caller's return address; these are tail jumps, not added calls.
        asm.emit(0x40, 0x03)  # JC over LJMP retry
        asm.jump(retry)
        asm.jump(SYMBOLS["invalidate_aborted_snapshot"])
        result.append((asm.origin, asm.resolve()))
    asm = Asm(SYMBOLS["invalidate_aborted_snapshot"])
    # Five saved bytes; no nested calls. This leaf changes no arithmetic flag.
    # Preserve IE and disable CPU interrupts only around the single-byte
    # invalidation. This does not claim to stop autonomous peripheral engines.
    asm.hex("C0 A8 C2 AF C0 E0 C0 86 75 86 00 C0 82 C0 83")
    asm.hex("90 4E 07 E4 F0")
    asm.hex("D0 83 D0 82 D0 86 D0 E0 D0 A8 22")
    result.append((asm.origin, asm.resolve()))
    return result


def build_patches(stock_code):
    if len(stock_code) != 65536:
        raise ValueError("Expected the complete 64-KiB CPU CODE region")
    patches = []
    for at, expected, symbol, _ in HOOKS:
        old = bytes.fromhex(expected)
        if stock_code[at:at+len(old)] != old:
            raise ValueError(f"Unexpected original CBE3 exit at CPU {at:04X}")
        target = SYMBOLS[symbol]
        patches.append({"cpu": at, "old": old.hex(),
                        "new": bytes((0x02, target >> 8, target & 255)).hex()})
    for at, body in build_bodies():
        if at+len(body) > 0xFFEC or stock_code[at:at+len(body)] != bytes(len(body)):
            raise ValueError(f"Abort-guard code cave unavailable at CPU {at:04X}")
        patches.append({"cpu": at, "old": bytes(len(body)).hex(), "new": body.hex()})
    return patches
