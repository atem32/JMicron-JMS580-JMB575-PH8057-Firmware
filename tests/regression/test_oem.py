"""Public unit regressions; native tests use an explicitly supplied stock BIN."""
import json
import os
from pathlib import Path
import tempfile
import unittest

from oem import (BIT_FIELDS, CATEGORIES, REGIONS, REGISTER_ATLAS, build_atlas, decode_oem,
                 expected_7058, f2_slice_effect, retry_77da_model, setup_iram,
                 timer_value, validate_atlas_metadata, verify_atlas_evidence,
                 write_outputs)


def synthetic_oem():
    o = bytearray(512)
    o[0:4] = bytes.fromhex("2d1562a5")
    o[0xE0:0xE2] = b"HD"; o[0xF0:0xF2] = b"BC"; o[0xFE:0x100] = b"JM"
    o[0xF2] = 0x38; o[0xF3] = 0x40; o[0xF4:0xF8] = (5).to_bytes(4, "big")
    for start, text in ((0x0C, b"Example"), (0x30, b"ExampleBridge"), (0x54, b"SYNTHETIC-ID")):
        o[start] = 2 + 2 * len(text); o[start + 1] = 3
        o[start + 2:start + 2 + len(text)] = text
    return o


class DecoderTests(unittest.TestCase):
    def test_canonical_metadata_is_complete_and_references_resolve(self):
        self.assertTrue(validate_atlas_metadata())
        self.assertEqual(CATEGORIES, {"CONFIRMED", "INFERRED", "HYPOTHESIS", "UNKNOWN"})
        self.assertEqual({row["space"] for row in REGISTER_ATLAS["registers"]},
                         {"MMIO", "XDATA", "IRAM", "IRAM bit", "SFR", "PATCH XDATA"})
        root = Path(__file__).resolve().parents[2]
        for item in REGISTER_ATLAS["evidence"].values():
            self.assertIn(item["image"], REGISTER_ATLAS["images"])
            if item.get("reference"):
                self.assertTrue((root / item["reference"].split(":", 1)[0]).is_file(), item["reference"])

    def test_generated_views_share_metadata_and_keep_serial_private(self):
        with tempfile.TemporaryDirectory() as directory:
            write_outputs(synthetic_oem(), Path(directory))
            self.assertEqual({path.name for path in Path(directory).iterdir()},
                             {"oem_atlas.json", "register-map.md"})
            result = json.loads((Path(directory) / "oem_atlas.json").read_text())
            self.assertEqual(result["metadata"], "research/oem/registers.json")
            self.assertEqual(len(result["oem_bytes"]), 512)
            for path in Path(directory).iterdir():
                self.assertNotIn("SYNTHETIC-ID", path.read_text())
                self.assertNotIn("53594e5448455449432d4944", path.read_text().lower())
            table = (Path(directory) / "register-map.md").read_text()
            self.assertIn("| Address | Name / purpose | Read/write | Evidence | Confidence | Unknowns |", table)
            self.assertIn("0x7A06 + 8*LUN", table)

    def test_every_byte_has_exactly_one_region(self):
        rows = build_atlas(synthetic_oem())
        self.assertEqual(len(rows), 512)
        self.assertEqual([int(x["oem_offset"], 16) for x in rows], list(range(512)))
        self.assertTrue(all(x["category"] in CATEGORIES for x in rows))
        self.assertTrue(all(not x["global_unused_claim"] for x in rows))

    def test_all_thirty_two_bits_are_explicit(self):
        bits = decode_oem(synthetic_oem())["flags"]
        self.assertEqual(set(bits), {"E7", "F2", "F3", "F8"})
        self.assertTrue(all([b["bit"] for b in value["bits"]] == list(range(8)) for value in bits.values()))

    def test_serial_payload_is_redacted_by_default(self):
        o = synthetic_oem()
        self.assertNotIn("SYNTHETIC-ID", json.dumps(decode_oem(o)))
        self.assertEqual(decode_oem(o, include_sensitive=True)["serial"]["text"], "SYNTHETIC-ID")
        self.assertTrue(all(r["stock_byte"] == "REDACTED" for r in build_atlas(o)[0x56:0x78]))
        self.assertTrue(all(r["stock_byte"] != "REDACTED" for r in build_atlas(o, include_sensitive=True)[0x56:0x78]))

    def test_invalid_image_length_is_rejected(self):
        for length in (0, 511, 513, 65536, 67072, 70143, 70145):
            with self.assertRaises(ValueError):
                decode_oem(bytes(length))

    def test_packed_strings_are_ascii_not_utf16(self):
        d = decode_oem(synthetic_oem())
        self.assertEqual(d["manufacturer"]["text"], "Example")
        self.assertEqual(d["manufacturer"]["computed_char_slots"], 7)
        self.assertFalse(d["manufacturer"]["type_checked_by_loader"])

    def test_malformed_string_lengths_are_reported_without_overread(self):
        for length in (1, 3, 67, 255):
            o = synthetic_oem(); o[0x0C] = length
            self.assertFalse(decode_oem(o)["manufacturer"]["well_formed_length"])
        o = synthetic_oem(); o[0x0C] = 0
        self.assertIsNone(decode_oem(o)["manufacturer"]["computed_char_slots"])
        self.assertFalse(decode_oem(o)["manufacturer"]["loader_requested_by_length"])

    def test_BC_gates_auxiliary_fields_but_not_HD_flags(self):
        o = synthetic_oem(); o[0xF0] ^= 1
        d = decode_oem(o)
        self.assertEqual(d["active_groups"], {"base_OEM": True, "E7_F3": True, "F2_timer_aux": False})
        self.assertFalse(d["timer_conversion_reached_in_initializer"])
        o = synthetic_oem(); o[0xE0] ^= 1
        self.assertEqual(decode_oem(o)["active_groups"], {"base_OEM": True, "E7_F3": False, "F2_timer_aux": True})

    def test_JM_gates_both_groups(self):
        o = synthetic_oem(); o[0xFE] ^= 1; o[0x0A] = 0x0A
        self.assertFalse(any(decode_oem(o)["active_groups"].values()))
        self.assertTrue(decode_oem(o)["scsi_inquiry_marker_present"])
        self.assertFalse(decode_oem(o)["scsi_inquiry_enabled"])

    def test_F2_zero_memory_projection_is_not_state_transition(self):
        prior = {"44F3": 0xA5, "487D": 0xA5, "4583": 0xA5, "4584": 0xA5,
                 "4588": 0xA5, "IRAM.bit39": 1, "IRAM.bit3A": 1}
        corrected = f2_slice_effect(0, prior)
        self.assertEqual(corrected["44F3"], 0)
        for key in prior.keys() - {"44F3"}:
            self.assertEqual(corrected[key], prior[key])
        legacy_clean_projection = f2_slice_effect(0)
        self.assertNotEqual(legacy_clean_projection, corrected)

    def test_timer_clamp_and_overflow_are_explicit(self):
        self.assertEqual(timer_value(5)["runtime_szct"], 1800)
        self.assertEqual(timer_value(180)["runtime_szct"], 1800)
        self.assertEqual(timer_value(181)["runtime_szct"], 1810)
        self.assertEqual(timer_value(5)["scsi_seconds"], 180)
        self.assertFalse(timer_value(0x19999999)["arithmetic_wraps"])
        self.assertTrue(timer_value(0x1999999A)["arithmetic_wraps"])
        self.assertEqual(timer_value(0x1999999A)["runtime_szct"], 4)

    def test_timer_rejects_values_outside_machine_field(self):
        for value in (-1, 1 << 32, True, "5"):
            with self.assertRaises(ValueError):
                timer_value(value)

    def test_F8_retry_ten_attempt_claim_counterexample(self):
        self.assertEqual(retry_77da_model([False]), {"copies": 1, "counter_4BC5": 1, "mismatch_4BC4": 0})
        result = retry_77da_model([True])
        self.assertEqual(result, {"copies": 12, "counter_4BC5": 11, "mismatch_4BC4": 1})
        self.assertNotEqual(result["copies"], 10)

    def test_F8_mismatch_flag_is_sticky(self):
        self.assertEqual(retry_77da_model([True, False]), retry_77da_model([True]))
        self.assertEqual(retry_77da_model([False, True])["copies"], 1)

    def test_second_half_is_not_reserved(self):
        o = synthetic_oem(); o[0x100] = 1
        self.assertEqual(decode_oem(o)["second_half_nonzero_bytes"], 1)
        self.assertTrue(all(x["category"] == "UNKNOWN" for x in build_atlas(o)[256:]))
        self.assertFalse(any(x["included_in_F8_bit7_copy"] for x in build_atlas(o)[256:]))

    def test_7058_state_dependent_effects(self):
        self.assertEqual(expected_7058(0, True, True, 0), 0x30)
        self.assertEqual(expected_7058(3, True, True, 0xFF), 0xDF)
        self.assertEqual(expected_7058(5, False, True, 0xFF), 0xEF)
        self.assertEqual(expected_7058(7, True, True, 0xFF), 0xFF)

    def test_setup_fields_regression_asymmetric_value_index(self):
        fields = setup_iram(0xA1, 0xFE, 0x1234, 0x5678, 0x9ABC)
        self.assertEqual([fields[a] for a in range(0x18, 0x20)], [0xA1, 0xFE, 0x12, 0x34, 0x56, 0x78, 0x9A, 0xBC])
        legacy_swapped_value = fields[0x1C] << 8 | fields[0x1D]
        self.assertNotEqual(legacy_swapped_value, 0x1234)


@unittest.skipUnless(os.environ.get("PH8057_STOCK"), "Native CODE tests require PH8057_STOCK local factory image")
class NativeRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from native_oem import Audit
        cls.audit = Audit(Path(os.environ["PH8057_STOCK"]).read_bytes())

    def test_native_poisoned_F2_state(self):
        self.audit.f2()

    def test_native_F8_retry_faults(self):
        self.audit.f8_transfers()

    def test_native_correct_setup_mapping(self):
        self.audit.auxiliary()

    def test_atlas_instructions_match_exact_factory_image(self):
        result = verify_atlas_evidence(self.audit.raw)
        self.assertEqual(result["image"], "factory")
        self.assertGreater(result["instructions_checked"], 0)
        altered = bytearray(self.audit.raw)
        altered[0x1000 + 0x7BF4] ^= 1
        with self.assertRaises(ValueError):
            verify_atlas_evidence(altered)

    @unittest.skipUnless(os.environ.get("PH8057_CKCOND"),
                         "Generated candidate evidence requires PH8057_CKCOND")
    def test_atlas_instructions_match_generated_ckcond(self):
        result = verify_atlas_evidence(Path(os.environ["PH8057_CKCOND"]).read_bytes())
        self.assertEqual(result["image"], "ckcond")
        self.assertGreater(result["instructions_checked"], 0)


if __name__ == "__main__":
    unittest.main()
