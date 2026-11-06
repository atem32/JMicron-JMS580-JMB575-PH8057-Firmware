"""Canonical bounded OEM regression suite on exact PH8057 8051 instructions.

Every peripheral read is supplied synthetic memory. The dual-DPTR extension
is an explicit vendor model inferred from the firmware ABI, not a silicon
specification. Tests are offline; this module has no hardware I/O functions.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from mcs51 import CPU
from oem import (IMAGE_SIZE, STOCK_SHA256, build_atlas, decode_oem,
                 expected_7058, f2_slice_effect, retry_77da_model, setup_iram, timer_value, verify_atlas_evidence)


class DualDPTRCPU(CPU):
    """Explicit model for the two pointer ABI used at800A/8026.

    SFR82/83 follow SFR86.bit0;84/85 name pointer1. This is sufficient for
    verified helpers entered with SFR86=0. Other vendor SFR modes unsupported.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._dptr_pair = [0, 0]

    def _index(self):
        return super().read_direct(0x86) & 1

    def read_direct(self, address):
        address &= 255
        if address in (0x82, 0x83, 0x84, 0x85):
            index = self._index() if address in (0x82, 0x83) else 1
            return (self._dptr_pair[index] >> (0 if address in (0x82, 0x84) else 8)) & 255
        return super().read_direct(address)

    def write_direct(self, address, value):
        address, value = address & 255, value & 255
        if address in (0x82, 0x83, 0x84, 0x85):
            index = self._index() if address in (0x82, 0x83) else 1
            shift = 0 if address in (0x82, 0x84) else 8
            self._dptr_pair[index] = (self._dptr_pair[index] & ~(255 << shift)) | (value << shift)
        else:
            super().write_direct(address, value)


def make_cpu(code, memory=None, *, hooks=None, cls=DualDPTRCPU, fill=0):
    x = bytearray([fill]) * 65536
    for address, value in (memory or {}).items():
        if isinstance(value, (bytes, bytearray)):
            x[address:address + len(value)] = value
        else:
            x[address] = value
    return cls(code, xdata=x, hooks=hooks or {}), x


def execute(cpu, start, stops, steps=1000):
    cpu.run(start, stop=tuple(stops), max_steps=steps)
    if cpu.pc not in stops:
        raise AssertionError(("unexpected slice termination", start, cpu.pc))


def execute_function(cpu, start, steps=10000):
    sp = cpu.sp
    cpu.push_return(0)
    execute(cpu, start, (0,), steps)
    if cpu.sp != sp:
        raise AssertionError(("unbalanced physical stack", start, sp, cpu.sp))
    # Compiler helper424B removes its return via POP/JMP; call_depth is a
    # tracing heuristic and is deliberately not used as an architectural test.


def ret_stub(cpu):
    cpu.ret()


class Audit:
    def __init__(self, raw):
        if len(raw) != IMAGE_SIZE or hashlib.sha256(raw).hexdigest() != STOCK_SHA256:
            raise ValueError("Exact factory image required for native OEM audit")
        self.raw = raw
        self.code = raw[0x1000:0x11000]
        self.oem = raw[0x11000:]
        self.counts = Counter()
        self.evidence = {}

    def check(self, value, name, detail=None):
        if not value:
            raise AssertionError((name, detail))
        self.counts[name] += 1

    def f2(self):
        # Exercise both initialized and nonzero prior state.
        for value in range(256):
            for prior_value in (0, 1, 0xA5):
                prior = {"44F3": prior_value, "487D": prior_value,
                         "4583": prior_value, "4584": prior_value,
                         "4588": prior_value, "IRAM.bit39": int(bool(prior_value)),
                         "IRAM.bit3A": int(bool(prior_value))}
                c, x = make_cpu(self.code, {int(k, 16): v for k, v in prior.items() if not k.startswith("IRAM")})
                x[0x39F2] = value
                c.write_bit(0x39, prior["IRAM.bit39"])
                c.write_bit(0x3A, prior["IRAM.bit3A"])
                c.dptr = 0x39F1
                execute(c, 0x214A, (0x2199,), 80)
                got = {k: x[int(k, 16)] for k in prior if not k.startswith("IRAM")}
                got.update({"IRAM.bit39": c.read_bit(0x39), "IRAM.bit3A": c.read_bit(0x3A)})
                self.check(got == f2_slice_effect(value, prior), "F2_stateful_loader", (value, prior_value, got))
        for flags in range(256):
            for initial in (0, 0x30, 0xCF, 0xFF):
                c, x = make_cpu(self.code, {0x7801: initial})
                c.write_bit(0x39, bool(flags & 0x40))
                c.dptr = 0x7801
                execute(c, 0x64B7, (0x64BE,), 15)
                self.check(x[0x7801] == (initial if flags & 0x40 else initial | 0x10),
                           "F2_bit6_7801", (flags, initial))
        for state in range(8):
            for bit4 in (0, 1):
                for bit5 in (0, 1):
                    for old in (0, 0x30, 0xCF, 0xFF):
                        c, x = make_cpu(self.code, {0x4583: bit4, 0x4584: bit5, 0x7058: old,
                                                   0x702A: 0xAB, 0x7618: 0xFF, 0x7638: 0xFF,
                                                   0x7658: 0xFF, 0x7678: 0xFF})
                        c.set_r(7, state)
                        execute_function(c, 0x3F61, 150)
                        active = state in (0, 3, 4, 5, 6)
                        self.check(x[0x7058] == expected_7058(state, bit4, bit5, old),
                                   "F2_7058_dispatch", (state, bit4, bit5, old))
                        self.check(x[0x702A] == (0xA0 if active else 0xAB) and
                                   all(x[a] == (0xFE if active else 0xFF) for a in (0x7618, 0x7638, 0x7658, 0x7678)),
                                   "F2_7058_port_side_effects", (state, bit4, bit5, old))
        for value in range(256):
            c, x = make_cpu(self.code)
            c.iram[0x27] = value
            execute_function(c, 0x81B9, 200)
            self.check(x[0xB008] == value and x[0xB000:0xB002] == b"JM", "IRAM27_context_save", value)
            c, x = make_cpu(self.code, {0xB000: b"JM", 0xB008: value})
            c.iram[0x27] = value ^ 255
            execute(c, 0x8300, (0x8331,), 100)
            self.check(c.iram[0x27] == value, "IRAM27_context_restore", value)
        self.evidence["F2_stateful_correction"] = {
            "counterexample": "F2=00, prior487D=4583=4584=4588=A5, IRAM39/3A=1: only44F3 becomes0 in214A-2199",
            "scope": "set-only behavior is not a proven boot defect; earlier initializer clears some fields"}

    def initializer(self):
        # Execute the COMPLETE software initializer from1F49, with two
        # peripheral fetch/wait callbacks supplied. The OEM readback itself
        # is a fixture at3900; this is not a simulated SPI controller.
        for fill in (0, 0xA5):
            for flag in (0, 1, 0x38, 0x40, 0x80, 0xFF):
                o = bytearray(self.oem[:256]); o[0xF2] = flag
                c, x = make_cpu(self.code, {0x3900: o}, fill=fill,
                                hooks={0xB37F: ret_stub, 0x80F5: ret_stub})
                c.iram[0x27] = 255
                execute_function(c, 0x1F49, 6000)
                self.check(x[0x44EC:0x44F0] == bytes.fromhex("152da562") and x[0x44E6:0x44E8] == o[6:8],
                           "whole_initializer_identifiers", fill)
                self.check(x[0x44F0] == o[0xE7] and x[0x44F1] == o[0xF3] and
                           c.read_bit(0x39) == bool(flag & 0x40) and c.read_bit(0x3A) == bool(flag & 0x80),
                           "whole_initializer_flag_defaults", (fill, flag))
                self.check(x[0x4588] == int(bool(flag & 4)) and x[0x4AD6] == 0x20,
                           "whole_initializer_explicit_defaults", (fill, flag))
                if flag & 8:
                    self.check(x[0x44F4:0x44F8] == x[0x4881:0x4885] == (1800).to_bytes(4, "big"),
                               "whole_initializer_native_timer", (fill, flag))
                self.check(x[0x4511:0x4531] == o[0x0E:0x2E] and x[0x4531:0x4551] == o[0x32:0x52],
                           "whole_initializer_native_strings", fill)
                self.check(x[0x44F9:0x4501] == o[0xC8:0xD0] and x[0x4501:0x4511] == o[0xD0:0xE0],
                           "whole_initializer_native_inquiry", fill)
        for marker, addresses in (("JM", (0xFE, 0xFF)), ("HD", (0xE0, 0xE1)), ("BC", (0xF0, 0xF1))):
            for address in addresses:
                o = bytearray(self.oem[:256]); o[address] ^= 255
                c, x = make_cpu(self.code, {0x3900: o, 0x44F0: 0xAA, 0x4589: 0xAA, 0x4174: 0xAA},
                                hooks={0xB37F: ret_stub, 0x80F5: ret_stub})
                execute_function(c, 0x1F49, 6000)
                if marker == "JM":
                    self.check(0x9D1C in c.trace, "JM_invalid_takes_default_handler", address)
                elif marker == "HD":
                    self.check(x[0x44F0] == 0xAA and x[0x44F1] == 1 and x[0x44F3] == 1 and x[0x4174] == o[0xFA],
                               "HD_signature_scope", address)
                else:
                    self.check(x[0x44F0] == 0 and x[0x44F1] == 0x40 and x[0x4589] == 0xAA and x[0x4174] == 0xAA,
                               "BC_signature_scope", address)
        # The packed USB type-byte is not validated by the OEM loader.
        for address in (0x0D, 0x31, 0x55):
            o = bytearray(self.oem[:256]); o[address] = 0xFF
            c, x = make_cpu(self.code, {0x3900: o}, hooks={0xB37F: ret_stub, 0x80F5: ret_stub})
            execute_function(c, 0x1F49, 6000)
            self.check(x[0x4511:0x4531] == o[0x0E:0x2E] and x[0x4531:0x4551] == o[0x32:0x52] and
                       x[0x4551:0x456F] == o[0x56:0x74], "string_type_not_validated", address)
        for selector in range(256):
            for length in (0, 0x1C):
                o = bytearray(self.oem[:256]); o[8] = selector; o[0x54] = length
                c, x = make_cpu(self.code, {0x3900: o, 0x44E8: 0xA5})
                execute(c, 0x2061, (0x20E6,), 3000)
                expected = 0 if selector == 5 else 1 if selector == 7 else 2 if length else 0xA5
                self.check(x[0x44E8] == expected, "serial_source_selector", (selector, length))

    def timer_and_mode_pages(self):
        values = list(range(701)) + [1800, 18000, 65536, 0x19999999, 0x1999999A, 0xFFFFFFFE, 0xFFFFFFFF]
        for value in values:
            c, x = make_cpu(self.code, {0x44F3: 1, 0x39F4: value.to_bytes(4, "big")})
            execute(c, 0x2199, (0x2200,), 800)
            expected = timer_value(value)["runtime_szct"]
            self.check(int.from_bytes(x[0x44F4:0x44F8], "big") == expected and
                       x[0x44F4:0x44F8] == x[0x4881:0x4885], "timer_native_dual_dptr", value)
        for value in (0, 5, 1800, 0xFFFFFFFF):
            c, x = make_cpu(self.code, {0x44F3: 0, 0x39F4: value.to_bytes(4, "big"),
                                       0x44F4: b"\xA5" * 4, 0x4881: b"\x5A" * 4})
            execute(c, 0x2199, (0x2200,), 20)
            self.check(x[0x44F4:0x44F8] == b"\xA5" * 4 and x[0x4881:0x4885] == b"\x5A" * 4,
                       "timer_disabled_preserves_state", value)
        for value in (0, 1, 599, 600, 1800, 18000, 288000, 0x01020304, 0xFFFFFFFF):
            for enabled in (0, 1, 2, 255):
                for page_control in (0, 0x40, 0x80, 0xC0):
                    c, x = make_cpu(self.code, {0x4BCB: b"\x35\x08", 0x487D: enabled,
                                               0x4881: value.to_bytes(4, "big")})
                    c.set_r(6, 0x4B); c.set_r(7, 0xCB); c.set_r(5, page_control)
                    execute_function(c, 0x6B04, 1200)
                    expected = 0xFFFFFFFF if page_control == 0x40 else 18000 if page_control == 0x80 else value
                    flag = 1 if page_control in (0x40, 0x80) else enabled & 1
                    self.check(x[0x3508:0x350A] == b"\x9A\x26" and x[0x350B] == flag and
                               int.from_bytes(x[0x3510:0x3514], "big") == expected and
                               x[0x4BCB:0x4BCD] == b"\x35\x30", "mode_sense_native_page", (value, enabled, page_control))
        for value in (0, 1, 600, 1800, 18000, 288000, 0x01020304, 0xFFFFFFFF):
            for flag in (0, 1, 2, 3, 0x10, 0x11, 0x0F):
                c, x = self.select_page(value, flag)
                accepted = flag & 0x0E == 0
                self.check(c.pc == (0x35D1 if accepted else 0x360B), "mode_select_flags", (value, flag))
                if accepted:
                    self.check(x[0x4B9F] == flag & 1 and int.from_bytes(x[0x4BA0:0x4BA4], "big") == value and
                               x[0x70B6] == 2, "mode_select_stage", (value, flag))
        for status, expected in ((0, 1800), (1, 288000), (2, 600), (3, 1800), (255, 1800)):
            c, x = self.select_page(1800, 1, status=status)
            self.check(c.pc == 0x35D1 and int.from_bytes(x[0x4BA0:0x4BA4], "big") == expected,
                       "mode_select_synthetic_70C0", status)
        for kind, values in (("length", (0, 0x25, 0x27, 255)), ("available", (0, 0x27)), ("page2", (1, 3, 255))):
            for value in values:
                c, x = self.select_page(1800, 1, **{kind: value})
                self.check(c.pc == (0x3607 if kind == "available" else 0x360B), "mode_select_reject_malformed", (kind, value))
        for value in (0, 600, 1800, 6000, 18000, 0xFFFFFFFF):
            for flag in (0, 1):
                c, x = make_cpu(self.code, {0x4BA0: value.to_bytes(4, "big"), 0x4B9F: flag,
                                           0x44F4: b"\xA5" * 4})
                execute(c, 0x7493, (0x74A8,), 200)
                self.check(x[0x4881:0x4885] == value.to_bytes(4, "big") and x[0x487D] == flag and
                           x[0x44F4:0x44F8] == b"\xA5" * 4, "mode_select_commit", (value, flag))
        self.evidence["timer"] = {"conversion": "10*max(180,OEM_be32) modulo2^32", "stock_szct": 1800,
                                   "wire_seconds": 180, "default_wire_szct": 18000,
                                   "physical_spindle_timer": "UNKNOWN", "copy800A": "native instructions, dual-DPTR model"}

    def select_page(self, value, flag, *, status=0, length=0x26, available=0x28, page2=0):
        page = bytearray(40)
        page[0:4] = bytes((0x1A, length, page2, flag))
        page[8:12] = value.to_bytes(4, "big")
        c, x = make_cpu(self.code, {0x4BAB: b"\x36\x00", 0x4BC8: available.to_bytes(2, "big"),
                                   0x3600: page, 0x70C0: status, 0x44F4: b"\xC3" * 4})
        c.iram[0x5E] = 1
        execute(c, 0x356C, (0x35D1, 0x360B, 0x3607), 1200)
        return c, x

    def flags_and_descriptors(self):
        for e7 in range(256):
            for f3 in (0, 1, 0x40, 0xFF):
                c, x = make_cpu(self.code, {0x44F0: e7, 0x44F1: f3})
                execute(c, 0x6F4C, (0x6F82,), 70)
                self.check(x[0x44F0] == e7 & 0xBB and x[0x44F1] == f3 & 0xFE and
                           c.read_bit(0x38) == bool(e7 & 2), "E7_F3_unconditional_masks", (e7, f3))
            for mode in (0, 1):
                c, x = make_cpu(self.code, {0x44F0: e7})
                c.write_bit(0x0E, mode)
                execute(c, 0x454B, (0x457F,), 60)
                self.check(x[0x4057] == (0x80 if e7 & 1 else 0xC0) and
                           x[0x4058] == ((0x70 if e7 & 1 else 1) if mode else (0xFA if e7 & 1 else 0x0F)),
                           "E7_power_descriptor", (e7, mode))
            for wp in (0, 1):
                c, x = make_cpu(self.code, {0x44F0: e7, 0x44E1: wp})
                execute(c, 0x364E, (0x367E,), 50)
                expected = (0x10 if e7 & 0x10 else 0) | (0x80 if wp else 0)
                self.check(x[0x4BC8] == expected, "E7_DPOFUA_WP", (e7, wp))
            for old in (0, 6, 8, 0xA5, 255):
                c, x = make_cpu(self.code, {0x44F0: e7, 0x5082: old})
                execute_function(c, 0xD682, 30)
                expected = old | 0x0E if e7 & 0x80 else (old & 0xF9) | 8
                self.check(x[0x5082] == expected, "E7_5082_exact_masks", (e7, old))
        for start in (0x5535, 0x6631, 0x7BED):
            for old in range(256):
                c, x = make_cpu(self.code, {0x5082: old})
                execute(c, start, (start + 7,), 8)
                self.check(x[0x5082] == old & 0xF9, "5082_cleanup", (start, old))
        for flag in (0, 1):
            for old in (0, 0x55, 255):
                c, x = make_cpu(self.code, {0x44F0: flag << 3, 0x7085: old, 0x508F: old})
                execute(c, 0xD422, (0xD435,), 30)
                self.check((x[0x7085], x[0x508F]) == ((0x2F, 1) if flag else (old, old)), "E7_7085_508F", (flag, old))
        for enable in (0, 1):
            for r4 in (0, 1):
                for r5 in (0, 1):
                    c, x = make_cpu(self.code, {0x4172: enable, 0x7A04: r4, 0x7A05: r5, 0x4575: 0xA5})
                    execute(c, 0x3A2D, (0x3A45,), 40)
                    # No event preserves old4575; the inactive path does not write zero.
                    expected = 3 if enable and (r4 or r5) else 0xA5
                    self.check(x[0x4575] == expected, "E7_bit5_preserves_inactive_state", (enable, r4, r5))
        for f3 in range(256):
            for retries in (0, 9, 10, 255):
                c, x = make_cpu(self.code, {0x44F1: f3, 0x4160: retries})
                execute(c, 0x32E1, (0x32F3, 0x32F9), 30)
                self.check(c.pc == (0x32F3 if f3 & 0x20 or retries >= 10 else 0x32F9),
                           "F3_USB2_state", (f3, retries))
            c, x = make_cpu(self.code, {0x44F1: f3, 0x4052: 0xA5, 0x4053: 0xA5})
            execute_function(c, 0xDD28, 40)
            self.check(tuple(x[0x4052:0x4054]) == ((0, 2) if f3 & 0x20 else (0xA5, 0xA5)), "F3_bcdUSB", f3)
            for index in (0, 1):
                c, x = make_cpu(self.code, {0x44F1: f3})
                c.iram[0x1A] = 15; c.iram[0x1C] = index
                execute_function(c, 0xB6AE, 130)
                enabled = not f3 & 0x20 and index == 0
                got = tuple(c.iram[0x4B:0x50])
                self.check(got == (0x1D, 0x74, 0, 0x2A, 0) if enabled else c.iram[0x4F] == 255,
                           "F3_BOS_gate", (f3, index, got))

    def trim_ncq(self):
        for flag in (0, 1):
            for capable in (0, 1):
                for pages in range(256):
                    c, x = make_cpu(self.code, {0x44F1: flag << 6, 0x3B52: capable,
                                               0x3AD2: pages, 0x4A17: 0xA9})
                    execute(c, 0x16C2, (0x170F,), 100)
                    expected = min(64, pages or 16) if flag and capable else 0xA9
                    self.check(x[0x416C] == flag * capable and x[0x4A17] == expected,
                               "F3_TRIM_IDENTIFY", (flag, capable, pages))
        for flag in (0, 1):
            for mode in (0, 1):
                for port in range(16):
                    for single in (0, 1):
                        for portbit in (0, 1):
                            c, x = make_cpu(self.code, {0x44F1: flag << 6, 0x4592: mode,
                                                       0x416C: single, 0x4181 + 0x36 * port: 2 * portbit})
                            c.set_r(7, port)
                            execute_function(c, 0xC98E, 100)
                            self.check(c.cy == flag * (portbit if mode else single),
                                       "F3_TRIM_port_query", (flag, mode, port, single, portbit))
                for capable in (0, 1):
                    for depth in range(32):
                        c, x = make_cpu(self.code, {0x44F1: flag << 7, 0x4592: mode,
                                                   0x3A99: capable, 0x3A96: depth})
                        execute(c, 0x154E, (0x156F,), 60)
                        self.check(c.read_bit(0x2D) == bool(flag and not mode and capable and depth >= 15),
                                   "F3_NCQ_gate", (flag, mode, capable, depth))

    def auxiliary(self):
        # Distinguish decoded wValue and wIndex with asymmetric setup words.
        for value, index, expected_recognized, expected_handled in (
            (0, 0, True, True), (1, 0, True, False), (0, 1, False, False),
            (0x100, 0, True, False), (0, 0x100, False, False), (0x1200, 0x0034, False, False)):
            c, x = make_cpu(self.code)
            for address, byte in setup_iram(0xA1, 0xFE, value, index, 1).items():
                c.iram[address] = byte
            c.iram[0x4D] = 0; c.iram[0x4E] = 1; c.iram[0x4F] = 0xEE; c.iram[0x5D] = 3
            execute_function(c, 0xD970, 50)
            recognized = bool(c.cy)
            if recognized:
                execute_function(c, 0xC702, 50)
            handled = recognized and c.iram[0x4F] != 255
            self.check((recognized, handled) == (expected_recognized, expected_handled),
                       "GET_MAX_LUN_correct_setup_field_mapping", (value, index, recognized, handled))
        self.evidence["setup_mapping_correction"] = {
            "IRAM": "1A:B=wValue high:low;1C:D=wIndex high:low;1E:F=wLength high:low",
            "counterexample": "GET_MAX_LUN wValue=1,wIndex=0 passesD970 recognizer but failsC702; wIndex=1 failsD970",
            "regression_scope": "Asymmetric fields distinguish recognizer rejection from handler rejection"}
        for value in range(256):
            for fc in (0, 31, 32, 33, 255):
                c, x = make_cpu(self.code, {0x39F8: value, 0x39FA: value ^ 255,
                                           0x39FB: value, 0x39FC: fc, 0x4AD6: 0x20})
                execute(c, 0x2200, (0x2226, 0x222A), 60)
                self.check((x[0x4589], x[0x4174], x[0x4175], x[0x4AD6]) ==
                           (value, value ^ 255, value, fc if fc > 32 else 32), "aux_loader", (value, fc))
            for start, stop, src, dst in ((0x6232, 0x623A, 0x4174, 0x7E18),
                                          (0x385A, 0x3862, 0x4175, 0x7086),
                                          (0x028C, 0x0294, 0x4AD6, 0x4A18)):
                c, x = make_cpu(self.code, {src: value, dst: value ^ 255})
                execute(c, start, (stop,), 20)
                self.check(x[dst] == value, "aux_downstream_copy", (src, dst, value))
        for count in (0, 1, 32, 33, 255):
            for counter in (0, 99, 100, 101, 255):
                c, x = make_cpu(self.code, {0x4A18: count, 0x7075: counter, 0x4A9B: 254})
                c.iram[0x29] = 1
                execute(c, 0x003E, (0x0061,), 60)
                expected = (max(0, count - 1), 0, 255) if counter > 100 else (count, counter, 254)
                self.check((x[0x4A18], x[0x7075], x[0x4A9B]) == expected, "FC_counter", (count, counter))
        for address in range(256):
            for fa in (0, 1, 50, 127, 255):
                c, x = make_cpu(self.code, {0x4174: fa, 0x7E18: 0xA5})
                c.iram[0x19] = 5; c.iram[0x1B] = address
                c.push_return(0)
                execute(c, 0x6222, (0, 0x6244), 100)
                accepted = address <= 127
                self.check((c.pc == 0) == accepted and x[0x7E18] == (fa if accepted else 0xA5),
                           "FA_SET_ADDRESS_range", (address, fa))
        for offset in (0x18, 0x19, 0x1A, 0x1C, 0x1D, 0x1E, 0x1F):
            for value in range(256):
                c, x = make_cpu(self.code, {0x4174: 50, 0x7E18: 0xA5})
                c.iram[0x19] = 5; c.iram[0x1B] = 22; c.iram[offset] = value
                accepted = value == (5 if offset == 0x19 else 0)
                c.push_return(0)
                execute(c, 0x6222, (0, 0x6244), 100)
                self.check((c.pc == 0) == accepted and x[0x7E18] == (50 if accepted else 0xA5),
                           "FA_SET_ADDRESS_invalid_fields", (offset, value))
        for f3 in range(256):
            for reg in (0, 1, 5, 255):
                c, x = make_cpu(self.code, {0x44F1: f3, 0x7086: reg, 0x4176: 0x55, 0x4177: 0xAB})
                execute(c, 0x7321, (0x7337,), 40)
                event = bool(f3 & 4) and reg == 0
                self.check((x[0x4176], x[0x4177]) == ((1, 1) if event else (0x55, 0xAB)),
                           "FB_F3_event_arm", (f3, reg))
            for pending in (0, 1, 128):
                c, x = make_cpu(self.code, {0x44F1: f3, 0x4177: pending, 0x3506: 0x30})
                execute(c, 0x9CC6, (0x9CE0,), 40)
                event = bool(f3 & 4) and pending != 0
                self.check((x[0x3506], x[0x4177]) == ((0x31, 0) if event else (0x30, pending)),
                           "FB_F3_event_report", (f3, pending))
            for eventreg in (0, 1, 2, 3):
                def status_stub(c):
                    c.cy = 0
                    c.ret()
                c, x = make_cpu(self.code, {0x44F1: f3, 0x7993: eventreg, 0x4BC9: 0xCC,
                                           0x4AD8: 0xA5, 0x4173: 0xBB}, hooks={0xE1F9: status_stub})
                c.push_return(0)
                execute(c, 0x5216, (0, 0x52CF), 150)
                expected = (0, 0, 0xA5, 0xBB) if eventreg == 0 and f3 & 0x10 else \
                    (0x52CF, 0x2E, 1, 0) if eventreg == 0 else \
                    (0x52CF, 0x34, 0xA5, 0xBB) if eventreg == 1 else (0x52CF, 0, 0xA5, 0xBB)
                self.check((c.pc, x[0x4BC9], x[0x4AD8], x[0x4173]) == expected,
                           "F3_event_filter", (f3, eventreg))

    def f8_transfers(self):
        for value in range(256):
            calls = []
            def hook(address):
                def call(c):
                    calls.append((address, c.r(6), c.r(7)))
                    c.ret()
                return call
            c, x = make_cpu(self.code, {0x4589: value}, hooks={a: hook(a) for a in (0x71C4, 0x7616, 0x77DA)})
            execute(c, 0xC4D3, (0xC501,), 70)
            expected = []
            if value & 0x40:
                expected += [(0x71C4, 0, 4), (0x7616, 0, 2), (0x71C4, 0, 0x40)]
            if value & 0x80:
                expected += [(0x71C4, 0, 8), (0x77DA, 0x73, 0), (0x71C4, 0x73, 0x80)]
            self.check(calls == expected, "F8_local_call_dispatch", value)
        # Historical dispatcher hooks deliberately preserve R6 and EA. This
        # separate end-to-end CODE test executes the real callees and shows
        # why their recorded tuple values were not actual callee ABI evidence.
        class CallRecorder(DualDPTRCPU):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.native_calls = []

            def step(self):
                if self.pc in (0x71C4, 0x7616, 0x77DA):
                    self.native_calls.append((self.pc, self.r(6), self.r(7)))
                return super().step()

        actual_sequences = {}
        for flags in (0, 0x40, 0x80, 0xC0):
            c, x = make_cpu(self.code, {0x4589: flags, 0x3900: bytes(range(256))}, cls=CallRecorder,
                            hooks={a: ret_stub for a in (0xB37F, 0x80F5, 0xE1A6, 0xE1AE)})
            execute_function(c, 0xC4D3, 30000)
            expected = []
            if flags & 0x40:
                expected += [(0x71C4, 0, 4), (0x7616, 0, 2), (0x71C4, 0x1A, 0x40)]
            if flags & 0x80:
                expected += [(0x71C4, 0x1A if flags & 0x40 else 0, 8),
                             (0x77DA, 0x73, 0), (0x71C4, 1, 0x80)]
            self.check(c.native_calls == expected and c.read_bit(0xAF) == bool(flags),
                       "F8_native_callee_clobbers", (flags, c.native_calls))
            actual_sequences[f"{flags:02X}"] = [{"cpu": f"{a:04X}", "R6": r6, "R7": r7} for a, r6, r7 in c.native_calls]
        self.evidence["F8_native_call_sequences"] = actual_sequences
        for selector, source, destination in ((1, 0x1B18, 0x7300), (2, 0x1A18, 0x7500)):
            c, x = make_cpu(self.code, hooks={0xE1A6: ret_stub, 0xE1AE: ret_stub})
            c.set_r(7, selector)
            execute_function(c, 0x7616, 10000)
            self.check(x[destination:destination + 256] == self.code[source:source + 256],
                       "F8_native_CODE_transfer", selector)
        retry_evidence = []
        for outcomes in ([False], [True], [True, False], [False, True]):
            c, x = self.retry_cpu(outcomes)
            expected = retry_77da_model(outcomes)
            got = {"copies": c.copies, "counter_4BC5": x[0x4BC5], "mismatch_4BC4": x[0x4BC4]}
            self.check(got == expected, "F8_fault_injection_retry", (outcomes, got, expected))
            self.check(x[0x7300:0x7400] == x[0x3900:0x3A00], "F8_final_copy_bytes", outcomes)
            retry_evidence.append({"assumed_compare_faults": outcomes, **got,
                                   "status": "synthetic fault injection; real peripheral unspecified"})
        self.evidence["77DA_retry"] = retry_evidence
        self.evidence["F8_dependencies"] = {"native_copy": "800A and8026 instruction loops",
                                             "stubbed": ["B37F controller command", "80F5 controller wait", "E1A6/E1AE peripheral control"],
                                             "window_semantics": "UNKNOWN; no SPI write claim"}

    def retry_cpu(self, outcomes):
        class FaultCPU(DualDPTRCPU):
            copies = 0

            def step(self):
                if self.pc == 0x7804:
                    self.copies += 1
                return super().step()

            def read_xdata(self, address):
                value = super().read_xdata(address)
                # At7826 MOVX performs the first compare read of the destination.
                # CPU.step advances PC to7827 before read_xdata is called.
                if self.pc == 0x7827 and address == 0x7300 and outcomes[min(self.copies - 1, len(outcomes) - 1)]:
                    return value ^ 1
                return value

        data = bytes((73 * i + 31) & 255 for i in range(256))
        c, x = make_cpu(self.code, {0x3900: data}, cls=FaultCPU,
                        hooks={a: ret_stub for a in (0xB37F, 0x80F5, 0xE1A6, 0xE1AE)})
        c.set_r(6, 0x73); c.set_r(7, 0)
        execute_function(c, 0x77DA, 200000)
        return c, x

    def run(self):
        for name in ("f2", "initializer", "timer_and_mode_pages", "flags_and_descriptors", "trim_ncq", "auxiliary", "f8_transfers"):
            getattr(self, name)()
        return {"factory_sha256": STOCK_SHA256, "counts": dict(self.counts),
                "passed": sum(self.counts.values()), "evidence": self.evidence,
                "qualification": "OFFLINE bounded original8051 CODE with synthetic RAM/MMIO; not hardware validation",
                "atlas_evidence": verify_atlas_evidence(self.raw)}


def audit_native(stock_path):
    return Audit(Path(stock_path).read_bytes()).run()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("image", type=Path)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    if not args.image.is_file():
        p.error("Input must be a regular local file")
    if args.out.is_symlink() or args.out.resolve() == args.image.resolve() or (args.out.exists() and args.out.samefile(args.image)):
        p.error("Native OEM output must not alias the immutable source image")
    result = audit_native(args.image)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print("PASS native OEM instruction and state regressions (offline fixtures)")


if __name__ == "__main__":
    main()
