"""Builder guards, native SAT dispatch and CK_COND abort regressions.

Firmware tests execute the admitted native dispatcher (3804), not a fabricated
launch PC. MMIO readiness is supplied explicitly; this is still software-only.
"""
from test_config import STOCK_PATH, RESULTS, COMPONENT
import hashlib
import importlib
import json
import subprocess
import sys
import unittest

import capture_wrappers
from image import changed_ranges, ORIGINAL_V8_SHA


GUARD_PROBE = r'''
import importlib.util, json, sys
spec=importlib.util.spec_from_file_location("capture_under_test",sys.argv[1])
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
def base():
    code=bytearray(65536)
    for at,old,name,n in m.HOOKS: code[at:at+n]=bytes.fromhex(old)
    return code
out={}
for reason in ("hook","cave","duplicate_label"):
    try:
        if reason=="duplicate_label":
            obj=m.Bytes();obj.label("same");obj.label("same")
        else:
            code=base()
            if reason=="hook":code[m.HOOKS[0][0]]^=1
            else:code[m.SYMBOLS["capture_nondata"]]=0xFF
            m.build_patches(bytes(code))
        out[reason]="ACCEPTED_INVALID"
    except (ValueError,AssertionError):out[reason]="REJECTED"
print(json.dumps(out,sort_keys=True))
'''


def run_guard_probe(path):
    proc = subprocess.run([sys.executable, "-O", "-c", GUARD_PROBE, str(path)],
                          capture_output=True, text=True, check=True)
    return json.loads(proc.stdout)



class BuilderRegressionTests(unittest.TestCase):
    def test_expected_byte_and_duplicate_label_guards_survive_optimization(self):
        observed = run_guard_probe(COMPONENT / "capture_wrappers.py")
        self.assertEqual(observed, {"hook": "REJECTED", "cave": "REJECTED",
                                    "duplicate_label": "REJECTED"})

    def test_patch_generator_rejects_every_corrupted_hook_and_allocated_cave(self):
        template = bytearray(65536)
        for at, old, name, n in capture_wrappers.HOOKS:
            template[at:at+n] = bytes.fromhex(old)
        valid = capture_wrappers.build_patches(bytes(template))
        self.assertEqual(len(valid), 11)
        for at, old, name, n in capture_wrappers.HOOKS:
            for offset in range(n):
                damaged = bytearray(template)
                damaged[at+offset] ^= 1
                with self.assertRaises(ValueError, msg=f"{name}+{offset}"):
                    capture_wrappers.build_patches(bytes(damaged))
        for name, address in capture_wrappers.SYMBOLS.items():
            damaged = bytearray(template)
            damaged[address] = 0xA5
            with self.assertRaises(ValueError, msg=name):
                capture_wrappers.build_patches(bytes(damaged))

    def test_diff_rejects_size_mismatch(self):
        with self.assertRaises(ValueError):
            changed_ranges(b"\0", b"\0\0")


@unittest.skipUnless(STOCK_PATH.is_file(), "Requires user-supplied exact stock image")
class NativePathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t = importlib.import_module("test_integrated_patch")
        cls.stock_raw = STOCK_PATH.read_bytes()

    def native_setup(self, code, lun, opcode, protocol, ck, direction=None, ata=None):
        t = self.t
        c = t.new_cpu(code)
        # Explicit four-slot software map; no claim about physical tray order.
        for slot in range(4):
            c.xdata[0x459C+slot] = (slot+1) % 4
        if direction is None:
            direction = protocol in (4, 6, 10)
        if ata is None:
            ata = 0xE5 if protocol == 3 else (0x25 if direction else 0x35)
        t.admit(c, lun, opcode=opcode, wire=2*protocol, ck=ck, ata=ata)
        c.xdata[0x70B7] = 1  # readiness fixture for native arithmetic/MMIO wait
        c.xdata[0x7988:0x798C] = (0 if protocol == 3 else 512).to_bytes(4, "little")
        c.xdata[0x798C] = 0x80 if direction else 0
        flags = (0x20 if ck else 0) | (0x0E if direction else (6 if protocol != 3 else 0))
        if opcode == 0x85:
            c.xdata[0x7991] = flags
            c.xdata[0x799C] = 0
            c.xdata[0x7995] = 1
        else:
            c.xdata[0x798F:0x799F] = bytes((
                0xA1, 2*protocol, flags, 0, 1, 0x10, 0, 0, 0, ata, 0, 0, 0, 0, 0, 0))
        # Parse actual CBW flags/length after constructing the complete request.
        c.run(0x7BF4, stop={0x7C43})
        c.call(0x4A97)
        c.call(0x3804)  # native scheduled SAT parser, BOT state selection, launch
        return c

    def assert_native_state_equal(self, stock, patched):
        self.assertEqual(stock.iram[:128], patched.iram[:128])
        self.assertEqual(stock.sfr, patched.sfr)
        actual = bytearray(patched.xdata)
        actual[0x4D00:0x4E20] = stock.xdata[0x4D00:0x4E20]
        self.assertEqual(stock.xdata, actual)

    def test_actual_sat_dispatch_and_bot_launch_both_cdb_lengths(self):
        records = []
        expected = {4: (0xC7C2, 2, 0x96A7), 5: (0xC8F0, 3, 0xB339),
                    6: (0xB2A5, 4, 0x7308), 7: (0xC7AA, 4, 0x7308),
                    10: (0xB2A5, 4, 0x7308), 11: (0xC7AA, 4, 0x7308)}
        for opcode in (0x85, 0xA1):
            for protocol in (3, 4, 5, 6, 7, 10, 11):
                for lun in range(4):
                    for ck in (False, True):
                        stock = self.native_setup(self.t.STOCK, lun, opcode, protocol, ck)
                        patched = self.native_setup(self.t.PATCHED, lun, opcode, protocol, ck)
                        self.assert_native_state_equal(stock, patched)
                        self.assertIn(0x229E, patched.trace)
                        self.assertEqual(patched.xdata[0x4E00], 0xA5)
                        if protocol == 3:
                            # Non-data is deferred via D7B5; do not invent an
                            # asynchronous firmware scheduler transition here.
                            self.assertEqual(patched.xdata[0x4159:0x415B], bytes.fromhex("cd31"))
                            self.assertEqual(patched.xdata[0x4E06], 0)
                        else:
                            launch_pc, kind, completion = expected[protocol]
                            self.assertIn(launch_pc, patched.trace)
                            self.assertEqual(patched.xdata[0x4E06], 0x5A)
                            self.assertEqual(patched.xdata[0x4E09], kind)
                            self.assertEqual(int.from_bytes(patched.iram[0x32:0x34], "big"), completion)
                        self.assertFalse(any(e[0] == "hook" for e in patched.events))
                        records.append({"opcode": opcode, "protocol": protocol, "lun": lun, "ck": ck})
        (RESULTS / "native_dispatch_coverage.json").write_text(json.dumps({
            "status": "PASS", "scenarios": len(records),
            "entry": "7BF4 -> 4A97 -> 3804 -> actual 222B and BOT launch",
            "mmio_fixture": {"70B7": 1}, "code_stubs": 0,
            "limitations": ["No USB/SATA engine or asynchronous scheduler", "Four synthetic map slots"],
        }, indent=2) + "\n")

    def test_non_sat_admission_and_sense_updates_preserve_native_state(self):
        # Exercising ordinary command admission and common sense update hooks
        # does not claim full-sector READ/WRITE data-transfer validation.
        for opcode in (0x00, 0x12, 0x25, 0x28, 0x2A, 0x35, 0x88, 0x8A):
            for lun in range(4):
                for pending in (0, 2, 0x28, 0x29):
                    pair = []
                    for code in (self.t.STOCK, self.t.PATCHED):
                        c = self.t.new_cpu(code)
                        c.xdata[0x4D00:0x4E20] = bytes([0xA5]) * 0x120
                        self.t.admit(c, lun, opcode=opcode, wire=0, ck=False)
                        c.set_r(7, pending)
                        c.call(0xD8AC)
                        pair.append(c)
                    self.assert_native_state_equal(*pair)
                    self.assertEqual(pair[1].xdata[0x4D00+16*lun], 0)
                    self.assertNotEqual(pair[1].xdata[0x4E00], 0xA5)

    def test_native_dispatch_wrong_direction_retains_stock_rejection(self):
        # SAT PIO/UDMA transfer-direction checks execute before a launch.
        for protocol in (4, 5, 10, 11):
            for opcode in (0x85, 0xA1):
                for lun in range(4):
                    pair = []
                    for code in (self.t.STOCK, self.t.PATCHED):
                        c = self.native_setup(code, lun, opcode, protocol, True,
                                              direction=protocol not in (4, 10))
                        pair.append(c)
                    self.assert_native_state_equal(*pair)
                    self.assertEqual(pair[1].iram[0x3A+lun], 2)
                    self.assertEqual(pair[1].xdata[0x4E06], 0)

    def test_exact_original_candidate_hash_and_all_changed_offsets(self):
        from build_ckcond import build
        candidate = build(self.stock_raw, variant="v8")[0]
        self.assertEqual(hashlib.sha256(candidate).hexdigest(), ORIGINAL_V8_SHA)
        changed = changed_ranges(self.stock_raw, candidate)
        self.assertEqual(sum(len(bytes.fromhex(r["new"])) for r in changed), 2555)
        self.assertTrue(all(int(r["end_exclusive"], 16) <= 0x11000 for r in changed))
        self.assertEqual(candidate[0x11000:], self.stock_raw[0x11000:])

    def test_v8_pre_abort_snapshot_is_not_published_by_revised_candidate(self):
        """Original v8 fails this command-association requirement at both exits."""
        from build_ckcond import build
        original = build(self.stock_raw, variant="v8")[0][0x1000:0x11000]
        revised = build(self.stock_raw, variant="revised")[0][0x1000:0x11000]
        records = []
        for exit_name, usb_ready, endpoint_busy, original_return in (
            ("waiting_for_5052", 0, 0, 0xCBF8),
            ("waiting_for_A3", 1, 0x80, 0xCC06),
        ):
            pair = []
            for label, code in (("original_v8", original), ("revised", revised)):
                c = self.native_setup(code, 1, 0x85, 11, True)
                bank = self.t.result_bank(c, 1, status=0x50)
                c.write_bit(0x02, 1)
                c.write_bit(0x21, 1)
                c.write_direct(0x9F, 0)  # E140's explicit inactive/abort fixture
                c.write_direct(0xA3, endpoint_busy)
                c.xdata[0x5052] = usb_ready
                c.xdata[0x50E2] = 0
                c.call(0x7308)
                unpublished = c.xdata[0x4E07]
                self.assertIn(0xE140, c.trace)
                self.assertEqual(c.cy, 1)
                self.assertEqual(int.from_bytes(c.iram[0x32:0x34], "big"), 0x94F9)
                self.assertEqual(c.xdata[0x4D10], 0)
                if label == "original_v8":
                    self.assertIn(original_return, c.trace)
                # Conditional continuation: real reset recovery is not modeled.
                self.t.finalize(c)
                pair.append(c)
                records.append({"exit": exit_name, "candidate": label,
                                "unpublished_valid_after_abort": unpublished,
                                "published_per_lun_valid": c.xdata[0x4D10],
                                "csw_status": c.xdata[0x400C],
                                "residue": int.from_bytes(c.xdata[0x4008:0x400C], "little"),
                                "pending_sense": c.iram[0x3B],
                                "max_sp": c.max_sp})
            old, new = pair
            self.assertEqual(old.xdata[0x4D10], 0xA5)  # actual failing v8 witness
            self.assertEqual(old.iram[0x3B], 0x28)
            self.assertEqual(new.xdata[0x4D10], 0)
            self.assertEqual(new.iram[0x3B], 0)
            self.assertEqual(new.xdata[0x4E07], 0)
            self.assertEqual(old.xdata[0x4008:0x400C], new.xdata[0x4008:0x400C])
            self.assertFalse(any(event[0] == "hook" for event in new.events))
        (RESULTS / "ckcond_abort_regression.json").write_text(json.dumps({
            "status": "PASS: original v8 defect reproduced; revised candidate prevents publication",
            "scope": "Native 7308 -> AEF4 -> CBE3 -> E140, then conditional 94F9",
            "results": records,
            "not_fixed": ["Stock conditional GOOD status on USB-wait abort",
                          "UDMA residue accounting", "Unknown external reset scheduler"],
        }, indent=2) + "\n")

    def test_abort_suppression_keeps_ata_error_and_non_ck_status_policy(self):
        from build_ckcond import build
        original = build(self.stock_raw, variant="v8")[0][0x1000:0x11000]
        records = []
        for usb_ready, endpoint_busy in ((0, 0), (1, 0x80)):
            for ck in (False, True):
                for status, error in ((0x50, 0), (0x51, 4), (0x70, 0)):
                    cases = []
                    for label, code in (("stock", self.t.STOCK),
                                        ("original_v8", original),
                                        ("revised", self.t.PATCHED)):
                        c = self.native_setup(code, 1, 0x85, 11, ck)
                        self.t.result_bank(c, 1, status=status, error=error)
                        c.write_bit(0x02, 1)
                        c.write_bit(0x21, 1)
                        c.write_direct(0x9F, 0)
                        c.write_direct(0xA3, endpoint_busy)
                        c.xdata[0x5052] = usb_ready
                        c.xdata[0x50E2] = 0
                        c.call(0x7308)
                        self.t.finalize(c)
                        cases.append(c)
                        records.append({"candidate": label, "usb_ready": usb_ready,
                                        "ck": ck, "ata_status": status, "ata_error": error,
                                        "csw_status": c.xdata[0x400C], "sense": c.iram[0x3B],
                                        "descriptor_valid": c.xdata[0x4D10]})
                    stock, old, revised = cases
                    self.assertEqual(revised.xdata[0x4D10], 0)
                    self.assertEqual(revised.xdata[0x4004:0x400D], stock.xdata[0x4004:0x400D])
                    self.assertEqual(revised.iram[0x3B], stock.iram[0x3B])
                    if ck or status != 0x50:
                        self.assertEqual(old.xdata[0x4D10], 0xA5)
                    if status != 0x50:
                        self.assertEqual(revised.xdata[0x400C], 1)
                        self.assertNotEqual(revised.iram[0x3B], 0)
        (RESULTS / "abort_status_preservation.json").write_text(json.dumps({
            "status": "PASS", "scenarios": len(records), "results": records,
            "interpretation": "Revised candidate preserves stock CSW/native sense and does not attach an ATA descriptor after native USB-wait abort",
        }, indent=2) + "\n")

    def test_abort_helper_matches_original_wait_abi_all_register_banks(self):
        from build_ckcond import build
        original = build(self.stock_raw, variant="v8")[0][0x1000:0x11000]
        revised = self.t.PATCHED
        cases = 0
        for entry, retry in ((0xCBF6, 0xCBE3), (0xCC04, 0xCBF9)):
            for carry in (0, 1):
                for bank in range(4):
                    for dps in (0, 1, 0xFE, 0xFF):
                        for interrupts in (0, 1):
                            cpus = []
                            for code in (original, revised):
                                c = self.t.new_cpu(code)
                                c.sp = 0x90
                                c.a = 0xA6
                                c.psw = 0x44 | (bank << 3) | (carry << 7)
                                c.b = 0x79
                                c.write_direct(0xA8, 0x25 | (interrupts << 7))
                                for reg in range(8):
                                    c.set_r(reg, 0x31 + 7*reg)
                                for address, value in ((0x82, 0xA4), (0x83, 0x39),
                                                       (0x84, 0x65), (0x85, 0x27),
                                                       (0x86, dps)):
                                    c.write_direct(address, value)
                                c.xdata[0x4E07] = 0xA5
                                if carry:
                                    c.call(entry)
                                else:
                                    c.run(entry, stop={retry})
                                cpus.append(c)
                            old, new = cpus
                            self.assertEqual(old.iram[:128], new.iram[:128])
                            self.assertEqual(old.sfr, new.sfr)
                            self.assertEqual(old.sp, new.sp)
                            expected = bytearray(old.xdata)
                            if carry:
                                expected[0x4E07] = 0
                            self.assertEqual(new.xdata, expected)
                            self.assertEqual(new.max_sp-old.max_sp, 5 if carry else 0)
                            cases += 1
        (RESULTS / "abort_helper_abi.json").write_text(json.dumps({
            "status": "PASS", "cases": cases, "additional_stack_bytes_on_abort": 5,
            "preserved": ["All native IRAM below stack", "SFRs and both physical DPTRs", "DPS", "IE", "A/B/PSW", "Current register bank", "Carry and retry target"],
            "only_data_change_on_carry_set": "XDATA 4E07 = 0",
            "interrupts": "IE state tested; asynchronous ISR execution not modeled",
        }, indent=2) + "\n")


if __name__ == "__main__":
    unittest.main(verbosity=2)
