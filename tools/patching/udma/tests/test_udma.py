"""Native failure paths, BOT evidence and accounting bounds."""
import json
import os
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[1]))
from accounting_contract import ProcessedBytes, future_residue_decision
from audit import (load_sources, RAW_CBW, RAW_CSW, hardware_excerpt, static_checks,
                   completion_matrix, arithmetic_native_checks,
                   rejected_prototype_counterexamples, DEFAULT_STOCK, DEFAULT_V8)
from bot_evidence import analyze_transaction, decode_cbw, decode_csw
from fixtures import completion_case, make_bus
from trace_patch import (collect_patches, overlay_for_emulation, ORIGINAL, HELPER,
                         STOCK_SHA256, V8_SHA256, sha256)
from unsafe_prototype_fixture import rejected_overlay_for_test
from run_audit import donor_record


@unittest.skipUnless(os.environ.get("PH8057_STOCK") or
                     (DEFAULT_STOCK.is_file() and DEFAULT_V8.is_file()),
                     "Native firmware tests require PH8057_STOCK and PH8057_V8; no stock firmware is redistributed")
class UDMAAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stock, cls.v8 = load_sources()

    def test_source_identity_and_exact_code_guards(self):
        self.assertEqual(sha256(self.stock), STOCK_SHA256)
        self.assertEqual(sha256(self.v8), V8_SHA256)
        result = static_checks(self.stock)
        self.assertEqual(result["command02_then_result_read_sites"],
                         ["0x2B97", "0x7710", "0x7726", "0x973A", "0x9760", "0x9A91", "0xB2DE"])

    def test_trace_builder_rejects_wrong_input_and_occupied_cave(self):
        for mutated in (self.stock[:0x10000], self.stock[0x1000:0x11000],
                        self.stock + b"\0", b"\0" * len(self.stock)):
            with self.subTest(size=len(mutated)):
                with self.assertRaises(ValueError):
                    collect_patches(mutated)
        # A byte mutation is rejected before it can authorize arbitrary code.
        for offset in (0, 0x8377, 0xF700, 0x11000):
            altered = bytearray(self.stock)
            altered[offset] ^= 1
            with self.assertRaises(ValueError):
                collect_patches(bytes(altered))
        with self.assertRaises(ValueError):
            collect_patches(rejected_overlay_for_test(self.stock))

    def test_trace_patch_has_no_counter_access_or_persistent_memory(self):
        patches = collect_patches(self.stock)
        self.assertEqual([p["cpu"] for p in patches], ["0x7377", "0xE700"])
        self.assertEqual(HELPER, ORIGINAL + bytes.fromhex("000022"))
        patched = overlay_for_emulation(self.stock)
        allowed = set(range(0x8377, 0x837C)) | set(range(0xF700, 0xF708))
        changes = {i for i, (a, b) in enumerate(zip(self.stock, patched)) if a != b}
        self.assertLessEqual(changes, allowed)
        self.assertEqual(self.stock[0x11000:], patched[0x11000:])

    def test_four_way_native_matrix_preserves_architectural_and_bus_state(self):
        rows = completion_matrix(self.stock, self.v8)
        self.assertEqual(len(rows), 48)
        self.assertTrue(all(row["trace_variant_equivalent"] for row in rows))

    def test_original_cbw_to_taskfile_to_exact_csw(self):
        result, cpu = completion_case(self.stock)
        self.assertEqual(result["csw"]["hex"], RAW_CSW.hex())
        self.assertEqual(result["stages"]["cbw_parser_residue"], 512)
        self.assertEqual(result["stages"]["sat_state"], 0x67)
        self.assertEqual(result["stages"]["sata_programmed_bytes_6318"], 512)
        self.assertEqual(cpu.xdata.memory[0x6302], 0x35)
        self.assertEqual(result["stages"]["new_70B6_operations_during_launch"], 0)
        self.assertTrue(all(pc in cpu.trace for pc in (0x7BF4, 0x222B, 0x248C, 0x380B,
                                                       0xC789, 0x8CA3, 0x7308, 0x7377,
                                                       0xAEF4, 0xCBE3, 0x94F9)))
        self.assertEqual(cpu.hooks, {})

    def test_unsigned32_residue_boundaries_native(self):
        for value in (0, 1, 255, 256, 511, 512, 513, 65535, 65536,
                      0xFFFFFF, 0x1000000, 0x3FFFFFFF, 0x40000000, 0xFFFFFFFF):
            for base in (self.stock, self.v8):
                for trace in (False, True):
                    with self.subTest(value=value, trace=trace):
                        raw = overlay_for_emulation(base) if trace else base
                        result, _ = completion_case(raw, length=value, stage=False)
                        self.assertEqual(result["residue_before_finalizer"], value)
                        self.assertEqual(result["csw"]["residue"], value)

    def test_data_in_sfr_mask_is_direction_gated(self):
        for remaining in (0, 1, 123, 0x12345678, 0xFFFFFFFF):
            result, _ = completion_case(self.stock, stage=False, data_in=True,
                                         state=0x66, length=0xFFFFFFFF,
                                         sfr_remaining=remaining)
            self.assertEqual(result["csw"]["residue"], remaining & 0x3FFFFFFF)
            result, _ = completion_case(self.stock, stage=False, data_in=False,
                                         state=0x67, length=0xFFFFFFFF,
                                         sfr_remaining=remaining)
            self.assertEqual(result["csw"]["residue"], 0xFFFFFFFF)

    def test_native_comparator_and_pio_arithmetic_are_consistent_hypotheses(self):
        result = arithmetic_native_checks(self.stock)
        self.assertEqual(len(result["timer_clamp"]), 10)
        self.assertEqual([r["residue"] for r in result["pio_accounting"]], [0, 0, 256, 1, 512])

    def test_rejected_prototype_zeros_residue_after_native_abort(self):
        results = rejected_prototype_counterexamples(self.stock, self.v8)
        self.assertEqual(len(results), 4)
        for result in results:
            self.assertEqual(result["rejected_prototype"]["csw"]["residue"], 0)
            self.assertEqual(result["trace_only_candidate"]["csw"]["residue"], 512)
        ck = results[-1]
        self.assertEqual(ck["rejected_prototype"]["csw"]["status"], 1)
        # CSW FAILED in this fixture is caused by CK_COND informational sense,
        # while the underlying ATA status was still GOOD (0x50).

    def test_unmapped_mmio_fails_closed(self):
        bus = make_bus()
        with self.assertRaises(Exception):
            bus.read(0xA123)
        with self.assertRaises(Exception):
            bus.write(0xA123, 0)


class BOTEvidence(unittest.TestCase):
    def test_user_excerpt_decodes_without_conflating_transport_and_processing(self):
        result = hardware_excerpt()["decoded"]
        self.assertEqual(result["tag"], "0x00000DFA")
        self.assertEqual(result["usb_completed_bytes"], 512)
        self.assertEqual(result["device_claimed_processed_bytes"], 0)
        self.assertTrue(result["matches_reported_ph8057_udma_anomaly"])
        self.assertTrue(result["sg_io_residue_matches_csw"])
        self.assertEqual(result["sat"]["protocol"], 11)
        self.assertEqual(result["sat"]["ata_command"], "0x35")

    def test_invalid_or_mismatched_wire_records_are_rejected(self):
        for raw in (RAW_CBW[:-1], RAW_CBW + b"\0", b"xxxx" + RAW_CBW[4:]):
            with self.assertRaises(ValueError):
                decode_cbw(raw)
        for index, value in ((12, 1), (13, 0x10), (14, 0), (14, 17), (14, 0x81)):
            raw = bytearray(RAW_CBW)
            raw[index] = value
            with self.assertRaises(ValueError):
                decode_cbw(bytes(raw))
        for raw in (RAW_CSW[:-1], RAW_CSW + b"\0", b"xxxx" + RAW_CSW[4:], RAW_CSW[:-1] + b"\3"):
            with self.assertRaises(ValueError):
                decode_csw(raw)
        csw = bytearray(RAW_CSW)
        csw[4] ^= 1
        with self.assertRaises(ValueError):
            analyze_transaction(RAW_CBW, bytes(csw), [])
        csw = bytearray(RAW_CSW)
        csw[8:12] = (513).to_bytes(4, "little")
        with self.assertRaises(ValueError):
            analyze_transaction(RAW_CBW, bytes(csw), [])

    def test_phase_error_has_no_meaningful_residue(self):
        csw = bytearray(RAW_CSW)
        csw[8:12] = (0xFFFFFFFF).to_bytes(4, "little")
        csw[12] = 2
        result = analyze_transaction(RAW_CBW, bytes(csw), [])
        self.assertFalse(result["csw_residue_meaningful"])
        self.assertIsNone(result["device_claimed_processed_bytes"])

    def test_partial_and_stalled_usb_are_not_full_success(self):
        for events in ([{"length": 256, "usb_status": 0}],
                       [{"length": 512, "usb_status": -32}], []):
            result = analyze_transaction(RAW_CBW, RAW_CSW, events)
            self.assertFalse(result["matches_reported_ph8057_udma_anomaly"])
        for events in ([{"length": 513, "usb_status": 0}],
                       [{"length": -1, "usb_status": 0}],
                       [{"length": 512}], [{"length": 512, "usb_status": "0"}]):
            with self.assertRaises(ValueError):
                analyze_transaction(RAW_CBW, RAW_CSW, events)


class DonorLayout(unittest.TestCase):
    def test_container_offset_and_vector_anchors_are_explicit(self):
        raw = bytearray(0x10600)
        raw[:6] = bytes.fromhex("0100152d0580")
        raw[0x400:0x40E] = bytes.fromhex("02a95f022ceb7f080275ea025ceb")
        branch = bytes.fromhex("e559b4640be4f558f557f556f555")
        sfr = bytes.fromhex("85ac5885ad5785ae56e5af543ff555")
        raw[0x400 + 0x1234:0x400 + 0x1234 + len(branch)] = branch
        raw[0x400 + 0x4567:0x400 + 0x4567 + len(sfr)] = sfr
        result = donor_record(bytes(raw), "synthetic_layout_fixture.bin")
        self.assertEqual(result["branch_cpu_offset"], "0x1234")
        self.assertEqual(result["branch_file_offset"], "0x01634")
        self.assertEqual(result["sfr_copy_cpu_offset"], "0x4567")
        self.assertEqual(result["sfr_copy_file_offset"], "0x04967")
        with self.assertRaises(ValueError):
            donor_record(bytes(raw[0x400:0x10400]), "bare_code.bin")
        raw[0x400] = 0
        with self.assertRaises(ValueError):
            donor_record(bytes(raw), "wrong_vector_offset.bin")


class FutureAccountingContract(unittest.TestCase):
    def decision(self, *, requested=512, processed=512, outcome="completed_good",
                 tag=42, epoch=3, source_tag=42, source_epoch=3,
                 qualified=True, stable=True):
        evidence = ProcessedBytes(processed, source_tag, source_epoch, qualified, stable)
        return future_residue_decision(requested=requested, current_residue=requested,
                                        tag=tag, epoch=epoch, outcome=outcome, evidence=evidence)

    def test_full_partial_zero_and_maximum_lengths(self):
        for requested in (0, 1, 255, 256, 512, 65536, 0xFFFFFFFF):
            for processed in sorted({0, requested // 2, requested}):
                for outcome in ("completed_good", "completed_ata_error", "short"):
                    with self.subTest(H=requested, P=processed, outcome=outcome):
                        result = self.decision(requested=requested, processed=processed, outcome=outcome)
                        self.assertTrue(result.update_allowed)
                        self.assertEqual(result.residue, requested - processed)

    def test_reset_abort_timeout_stall_and_phase_do_not_commit(self):
        for outcome in ("reset", "abort", "timeout", "stall", "phase_error"):
            for processed in (0, 128, 512):
                result = self.decision(outcome=outcome, processed=processed)
                self.assertFalse(result.update_allowed)
                self.assertEqual(result.residue, 512)

    def test_unqualified_zero_and_same_tag_after_reset_are_rejected(self):
        for kwargs in ({"qualified": False}, {"stable": False}, {"source_tag": 41},
                       {"source_epoch": 2}, {"processed": 513}, {"processed": -1},
                       {"qualified": "yes"}, {"stable": "yes"}):
            with self.subTest(kwargs=kwargs):
                result = self.decision(**kwargs)
                self.assertFalse(result.update_allowed)
                self.assertEqual(result.residue, 512)
        result = future_residue_decision(requested=512, current_residue=512,
                                         tag=42, epoch=3, outcome="completed_good", evidence=None)
        self.assertFalse(result.update_allowed)

    def test_invalid_bounds_raise_instead_of_wrapping(self):
        for requested in (-1, 1 << 32, True):
            with self.assertRaises(ValueError):
                self.decision(requested=requested)


if __name__ == "__main__":
    unittest.main()
