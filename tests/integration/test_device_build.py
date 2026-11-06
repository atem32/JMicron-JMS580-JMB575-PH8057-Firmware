"""Updater-container integrity and equivalence with the current CPU patch plan."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from ph8057 import ROOT, NAMES, construct
from image import STOCK_FULL_SHA, read_stock
from firmware_inspect import DONORS

DEVICE = ROOT / "firmware/ph8057-device/modified"
sys.path.insert(0, str(DEVICE))
from build_from_1bin import (BIN_SIZE, CODE_OFF, OEM_OFF, STOCK_SHA, EXPECTED_OUT_SHA,
                            build, check_record, read_package, read_stock_package, sha)


class PublicUpdaterBoundaries(unittest.TestCase):
    def test_identities_agree_with_builder_guards_and_current_cli(self):
        manifest = json.loads((ROOT / "firmware/manifests/images.json").read_text())
        self.assertEqual(manifest["schema"], 1)
        images = manifest["images"]
        self.assertEqual(images["factory-spi"]["sha256"], STOCK_FULL_SHA)
        self.assertEqual(images["factory-updater"]["sha256"], STOCK_SHA)
        self.assertEqual(images["ckcond-revised-updater"]["sha256"], EXPECTED_OUT_SHA)
        self.assertEqual(images["ckcond-v8"]["role"], "regression_baseline")
        self.assertNotIn("ckcond-v8", NAMES)
        self.assertEqual({row["sha256"] for row in manifest["donors"]}, DONORS)
        for variant, filename in NAMES.items():
            self.assertEqual(images[variant]["filename"], filename)
        for row in images.values():
            for key in ("cpu_patch_records", "trace_source", "hardware_evidence"):
                if key in row:
                    self.assertTrue((ROOT / row[key]).is_file(), row[key])
        for layout in manifest["layouts"].values():
            self.assertEqual(int(layout["code_file_offset"], 16) + layout["code_size_bytes"],
                             int(layout["oem_file_offset"], 16))
            self.assertEqual(int(layout["oem_file_offset"], 16) + layout["oem_size_bytes"],
                             layout["size_bytes"])

    def test_builder_rejects_unknown_and_wrong_format_inputs(self):
        for length in (512, 65536, BIN_SIZE, 70144):
            with self.subTest(length=length), self.assertRaises(ValueError):
                build(bytes(length), [])

    def test_file_reader_rejects_directory_and_incomplete_package(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            short = root / "short.bin"
            short.write_bytes(b"incomplete")
            for path in (root, short, root / "missing.bin"):
                with self.subTest(path=path.name), self.assertRaises(ValueError):
                    read_package(path)


@unittest.skipUnless(os.environ.get("PH8057_DEVICE_STOCK"),
                     "Exact 67,072-byte updater input required; use --device-stock")
class DeviceImageIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stock = read_stock_package(Path(os.environ["PH8057_DEVICE_STOCK"]))
        cls.records = json.loads((DEVICE / "ckcond_revised_patch_records.json").read_text())
        cls.candidate = build(cls.stock, cls.records)

    def test_exact_candidate_hash_crcs_and_preserved_regions(self):
        identity = json.loads((ROOT / "firmware/manifests/images.json").read_text())["images"]
        expected = identity["ckcond-revised-updater"]
        self.assertEqual(sha(self.stock), STOCK_SHA)
        self.assertEqual(sha(self.candidate), expected["sha256"])
        self.assertEqual(len(self.candidate), BIN_SIZE)
        self.assertEqual(check_record(self.candidate), expected["crc"])
        self.assertEqual(self.candidate[:0x200], self.stock[:0x200])
        self.assertEqual(self.candidate[OEM_OFF:], self.stock[OEM_OFF:])
        self.assertEqual(sha(self.candidate[CODE_OFF:OEM_OFF]), expected["code_sha256"])
        self.assertEqual(sum(a != b for a, b in zip(self.stock, self.candidate)),
                         expected["changed_bytes_vs_base"])

    def test_only_the_pinned_original_allows_a_blank_metadata_crc(self):
        self.assertEqual(self.stock[0x3FC:0x400], bytes(4))
        with self.assertRaisesRegex(ValueError, "Metadata header CRC"):
            check_record(self.stock)
        check_record(self.stock, allow_blank_header_crc=True)
        changed = bytearray(self.stock)
        changed[0x3FC:0x400] = bytes.fromhex("ffffffff")
        with self.assertRaises(ValueError):
            build(bytes(changed), self.records)

    def test_crc_fields_payload_and_mirror_corruption_are_rejected(self):
        for offset in (0x10, 0x1FC, 0x20C, 0x3FC, CODE_OFF, 0x103F8, 0x103FC):
            with self.subTest(offset=hex(offset)):
                changed = bytearray(self.candidate)
                changed[offset] ^= 1
                with self.assertRaises(ValueError):
                    check_record(bytes(changed))

    def test_overlap_expected_bytes_and_code_boundary_are_guarded(self):
        first = self.records[0]
        invalid = [
            ([first, first], "Overlapping"),
            ([{**first, "old": "ff" * len(bytes.fromhex(first["old"]))}], "Input bytes mismatch"),
            ([{"cpu": 0xFFEC, "old": "00", "new": "00"}], "Unsafe patch"),
            ([{**first, "new": ""}], "Unsafe patch"),
        ]
        for records, error in invalid:
            with self.subTest(error=error), self.assertRaisesRegex(ValueError, error):
                build(self.stock, records)

    def test_source_and_patch_records_are_not_overwritten_by_cli(self):
        for alias in ("stock", "records", "symlink", "hardlink"):
            with self.subTest(alias=alias), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                stock = root / "stock.bin"
                records = root / "records.json"
                stock.write_bytes(self.stock)
                records.write_text(json.dumps(self.records))
                old_records = records.read_bytes()
                target = {"stock": stock, "records": records}.get(alias, root / "alias.bin")
                if alias == "symlink":
                    target.symlink_to(stock)
                elif alias == "hardlink":
                    os.link(stock, target)
                cp = subprocess.run([sys.executable, "-B", str(DEVICE / "build_from_1bin.py"),
                                     "--stock", str(stock), "--patches", str(records),
                                     "--output", str(target)], capture_output=True, text=True)
                self.assertNotEqual(cp.returncode, 0)
                self.assertEqual(stock.read_bytes(), self.stock)
                self.assertEqual(records.read_bytes(), old_records)

    @unittest.skipUnless(os.environ.get("PH8057_STOCK"), "Factory SPI input also required")
    def test_code_matches_spi_candidate_while_containers_remain_distinct(self):
        stock = read_stock(os.environ["PH8057_STOCK"])
        candidate, _ = construct(stock, "ckcond-revised")
        self.assertEqual(self.stock[CODE_OFF:OEM_OFF], stock[0x1000:0x11000])
        self.assertEqual(self.candidate[CODE_OFF:OEM_OFF], candidate[0x1000:0x11000])
        self.assertEqual(self.candidate[OEM_OFF:], candidate[0x11000:])
        self.assertNotEqual(sha(self.candidate), sha(candidate))
        self.assertNotEqual(len(self.candidate), len(candidate))


if __name__ == "__main__":
    unittest.main(verbosity=2)
