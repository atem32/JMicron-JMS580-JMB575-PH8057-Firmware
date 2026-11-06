"""Integration checks for the CK_COND build, source integrity and container boundaries."""
import os
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from firmware_inspect import identify
from image import (check_crc, repackage, STOCK_FULL_SHA, CKCOND_SHA,
                   read_stock, sha, guard_outputs)
from ph8057 import construct, ROOT, NAMES


class PublicBoundaryTests(unittest.TestCase):
    def test_ck_runner_refuses_log_alias_before_any_execution(self):
        script = ROOT / "tools/patching/ckcond/run_tests.py"
        spec = importlib.util.spec_from_file_location("ck_runner_under_test", script)
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        for kind in ("symlink", "hardlink"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as td:
                base = Path(td)
                original = base / "original.dat"
                original.write_bytes(b"immutable original")
                out = base / "results"
                out.mkdir()
                log = out / "test_asm51.log"
                if kind == "symlink":
                    log.symlink_to(original)
                else:
                    os.link(original, log)
                with mock.patch.object(sys, "argv", [str(script), "--out", str(out)]), \
                        mock.patch.dict(os.environ, {"PH8057_STOCK": "/nonexistent"}), \
                        mock.patch.object(runner.subprocess, "run") as process:
                    with self.assertRaises(ValueError):
                        runner.main()
                    process.assert_not_called()
                self.assertEqual(original.read_bytes(), b"immutable original")
                self.assertFalse((out / "ckcond_suite_results.json").exists())

    def test_unified_runner_refuses_log_alias_before_any_execution(self):
        spec = importlib.util.spec_from_file_location("unified_runner_under_test", ROOT / "run_tests.py")
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        for kind in ("symlink", "hardlink", "linked_directory"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as td:
                base = Path(td)
                original = base / "original.dat"
                original.write_bytes(b"immutable original")
                out = base / "results"
                out.mkdir()
                if kind == "linked_directory":
                    (out / "nested").symlink_to(base, target_is_directory=True)
                elif kind == "symlink":
                    (out / "emulator.log").symlink_to(original)
                else:
                    os.link(original, out / "emulator.log")
                with mock.patch.object(sys, "argv", ["run_tests.py", "--out", str(out)]), \
                        mock.patch.object(runner.subprocess, "run") as process:
                    with self.assertRaises(ValueError):
                        runner.main()
                    process.assert_not_called()
                self.assertEqual(original.read_bytes(), b"immutable original")
                self.assertFalse((out / "summary.json").exists())

    def test_output_guard_rejects_direct_symlink_and_hardlink_source_aliases(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td); source = base / "original.dat"
            source.write_bytes(b"immutable original")
            sym, hard = base / "sym", base / "hard"
            sym.symlink_to(source); os.link(source, hard)
            for target in (source, sym, hard):
                with self.subTest(target=target.name), self.assertRaises(ValueError):
                    guard_outputs(source, [base / "candidate.bin", target])
            self.assertEqual(source.read_bytes(), b"immutable original")
            self.assertFalse((base / "candidate.bin").exists())

    def test_oem_sidecar_cannot_overwrite_input(self):
        from oem import write_outputs
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td); source = directory / "oem_atlas.json"
            source.write_bytes(b"\0" * 512)
            with self.assertRaises(ValueError):
                write_outputs(source.read_bytes(), directory, source_path=source)
            self.assertEqual(source.read_bytes(), b"\0" * 512)
            self.assertEqual(len(list(directory.iterdir())), 1)

    def test_64k_does_not_implicitly_mean_cpu_code(self):
        raw = b"\0" * 65536
        self.assertEqual(identify(raw)["layout"], "UNKNOWN")
        self.assertEqual(identify(raw, explicit_cpu=True)["layout"], "EXPLICIT_RAW_CPU_CODE")
        self.assertEqual(identify(bytes.fromhex("5ac369e1") + raw[4:], explicit_cpu=True)["layout"], "UNKNOWN")

    def test_unknown_container_not_given_a_donor_cpu_offset(self):
        raw = b"\0" * 0x10600
        self.assertEqual(identify(raw)["layout"], "UNKNOWN")

    def test_only_ckcond_is_exposed_and_unknown_variants_are_rejected(self):
        self.assertEqual(set(NAMES), {"ckcond"})
        with self.assertRaisesRegex(ValueError, "only ckcond"):
            construct(b"", "not-a-firmware")
        help_result = subprocess.run([sys.executable, str(ROOT / "ph8057.py"), "build", "--help"],
                                     capture_output=True, text=True, check=True)
        self.assertIn("{ckcond}", help_result.stdout)
        import build_ckcond
        with self.assertRaises(TypeError):
            build_ckcond.build(b"", variant="not-a-firmware")

    def test_no_builder_accepts_synthetic_or_truncated_stock(self):
        for length in (512, 65536, 67072, 70144):
            with self.subTest(length=length), self.assertRaises(ValueError):
                construct(b"\0" * length, "ckcond")


@unittest.skipUnless(os.environ.get("PH8057_STOCK"), "Exact local factory image required")
class CandidateIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stock = read_stock(os.environ["PH8057_STOCK"])
        cls.candidate, cls.report = construct(cls.stock, "ckcond")

    def test_reproducible_hashes_and_crc(self):
        expected = json.loads((ROOT / "firmware/manifests/images.json").read_text())["images"]["ckcond"]
        self.assertEqual(sha(self.stock), STOCK_FULL_SHA)
        self.assertEqual(sha(self.candidate), CKCOND_SHA)
        self.assertEqual(sha(self.candidate), expected["sha256"])
        self.assertEqual(sha(self.candidate[0x1000:0x11000]), expected["code_sha256"])
        self.assertEqual(self.report["crc"], expected["crc"])
        self.assertEqual(len(self.candidate), 70144)
        self.assertEqual(self.candidate[0x11000:], self.stock[0x11000:])
        self.assertEqual(check_crc(self.candidate), self.report["crc"])
        self.assertFalse(self.report["udma_residue_fix"])
        self.assertEqual(self.report["artifact_hardware_status"], "NOT TESTED")

    def test_inspector_recognizes_exact_factory_and_ckcond_spi_containers(self):
        for data, variant in ((self.stock, "factory"), (self.candidate, "ckcond")):
            with self.subTest(variant=variant):
                report = identify(data)
                self.assertEqual(report["layout"], "PH8057_COMPLETE_SPI")
                self.assertEqual(report["image_format"], "full_spi")
                self.assertEqual(report["firmware_variant"], variant)
                self.assertEqual(int(report["code_file_offset"], 16), 0x1000)
                self.assertEqual(int(report["oem_file_offset"], 16), 0x11000)
                self.assertEqual(report["exact_factory"], variant == "factory")
                self.assertEqual(report["exact_ckcond"], variant == "ckcond")
                self.assertEqual(report["crc"], check_crc(data))

    def test_all_builder_outputs_preserve_source_on_filename_collision(self):
        scripts = [
            ("ph8057.py", ["build", "ckcond"]),
            ("tools/patching/ckcond/build_ckcond.py", []),
        ]
        for script, flags in scripts:
            for filename in ("ckcond_manifest.json", "ckcond_patch_records.json", NAMES["ckcond"]):
                with self.subTest(script=script, filename=filename), tempfile.TemporaryDirectory() as td:
                    directory = Path(td)
                    source = directory / filename
                    source.write_bytes(self.stock)
                    cp = subprocess.run([sys.executable, "-B", str(ROOT / script), *flags,
                                         "--stock", str(source), "--out", str(directory)],
                                        capture_output=True, text=True)
                    self.assertNotEqual(cp.returncode, 0)
                    self.assertIn("immutable source", cp.stderr)
                    self.assertEqual(source.read_bytes(), self.stock)
                    self.assertEqual(len(list(directory.iterdir())), 1)

    def test_updater_records_equal_the_current_cpu_patch_plan(self):
        records = json.loads((ROOT / "firmware/ph8057-device/modified/ckcond_patch_records.json").read_text())
        normalize = lambda rows: [{"cpu": int(row["cpu"], 16) if isinstance(row["cpu"], str) else row["cpu"],
                                   "old": row["old"], "new": row["new"]} for row in rows]
        self.assertEqual(normalize(records), normalize(self.report["patches"]))
        self.assertEqual(len(records), 32)

    def test_patch_overlap_boundaries_and_invalid_crc_rejected(self):
        with self.assertRaisesRegex(ValueError, "overlap"):
            repackage(self.stock, [{"cpu": 0xE700, "old": "00", "new": "00"}] * 2)
        with self.assertRaisesRegex(ValueError, "trailer"):
            repackage(self.stock, [{"cpu": 0xFFEC, "old": "00", "new": "00"}])
        for offset in (0x0C, 0x1FC, 0xFFC, 0x1000, 0x10FF8, 0x10FFC):
            altered = bytearray(self.candidate)
            altered[offset] ^= 1
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                check_crc(bytes(altered))

    def test_canonical_cli_emits_the_exact_spi_image_and_patch_records(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td)
            subprocess.run([sys.executable, str(ROOT / "ph8057.py"), "build", "ckcond",
                            "--stock", os.environ["PH8057_STOCK"], "--out", str(output)],
                           capture_output=True, text=True, check=True)
            self.assertEqual((output / NAMES["ckcond"]).read_bytes(), self.candidate)
            manifest = json.loads((output / "ckcond_manifest.json").read_text())
            self.assertEqual(manifest["variant"], "ckcond")
            self.assertEqual(manifest["image_format"], "full_spi")
            records = json.loads((output / "ckcond_patch_records.json").read_text())
            self.assertEqual(len(records), 32)
            self.assertEqual(repackage(self.stock, records), self.candidate)


if __name__ == "__main__":
    unittest.main(verbosity=2)
