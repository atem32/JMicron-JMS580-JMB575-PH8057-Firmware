"""Integration checks for container boundaries and actual candidate composition."""
import os
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from firmware_inspect import identify
from image import (check_crc, repackage, STOCK_FULL_SHA, ORIGINAL_V8_SHA,
                   REVISED_CKCOND_SHA, read_stock, sha, guard_outputs)
from ph8057 import construct, ROOT


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
            directory = Path(td); source = directory / "oem_decoded.json"
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

    def test_no_builder_accepts_synthetic_or_truncated_stock(self):
        for variant in ("ckcond-v8", "ckcond-revised", "udma-trace", "combined-revised-trace"):
            for length in (512, 65536, 70144):
                with self.subTest(variant=variant, length=length):
                    with self.assertRaises(ValueError):
                        construct(b"\0" * length, variant)


@unittest.skipUnless(os.environ.get("PH8057_STOCK"), "Exact local factory image required")
class CandidateIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stock = read_stock(os.environ["PH8057_STOCK"])
        cls.built = {variant: construct(cls.stock, variant) for variant in
                     ("ckcond-v8", "ckcond-revised", "udma-trace", "combined-revised-trace")}

    def test_reproducible_hashes_and_crc(self):
        self.assertEqual(sha(self.stock), STOCK_FULL_SHA)
        self.assertEqual(sha(self.built["ckcond-v8"][0]), ORIGINAL_V8_SHA)
        self.assertEqual(sha(self.built["ckcond-revised"][0]), REVISED_CKCOND_SHA)
        self.assertEqual(sha(self.built["udma-trace"][0]),
                         "a4bf69164548003a26efebcb3f5fd6e59d0dfc3321eeda2ffb97d6e36ba63712")
        for raw, report in self.built.values():
            with self.subTest(variant=report["variant"]):
                self.assertEqual(len(raw), 70144)
                self.assertEqual(raw[0x11000:], self.stock[0x11000:])
                self.assertEqual(check_crc(raw), report["crc"])
                self.assertFalse(report["udma_residue_fix"])
                self.assertEqual(report["candidate_hardware_tests"], 0)

    def test_all_builder_sidecars_preserve_source_on_filename_collision(self):
        scripts = [
            ("ph8057.py", "ckcond-revised_manifest.json", ["build", "ckcond-revised"]),
            ("tools/patching/ckcond/build_ckcond.py", "ckcond_revised_manifest.json", []),
            ("tools/patching/udma/build_trace.py", "udma_trace_manifest.json", []),
        ]
        for script, filename, flags in scripts:
            with self.subTest(script=script), tempfile.TemporaryDirectory() as td:
                directory = Path(td); source = directory / filename
                source.write_bytes(self.stock)
                cp = subprocess.run([sys.executable, "-B", str(ROOT / script), *flags,
                                     "--stock", str(source), "--out", str(directory)],
                                    capture_output=True, text=True)
                self.assertNotEqual(cp.returncode, 0)
                self.assertIn("immutable source", cp.stderr)
                self.assertEqual(source.read_bytes(), self.stock)
                self.assertEqual(len(list(directory.iterdir())), 1)

    def test_combined_code_is_exact_revised_plus_observation_trampoline(self):
        from trace_patch import overlay_for_emulation
        revised = self.built["ckcond-revised"][0]
        combined = self.built["combined-revised-trace"][0]
        overlay = overlay_for_emulation(revised)
        # CRC locations are separately tested. Every executable byte must agree.
        self.assertEqual(combined[0x1000:0x10FF8], overlay[0x1000:0x10FF8])
        self.assertEqual(combined[0x11000:], revised[0x11000:])
        self.assertNotEqual(combined, revised)
        self.assertEqual(len(self.built["combined-revised-trace"][1]["patches"]),
                         len(self.built["ckcond-revised"][1]["patches"]) + 2)

    def test_combined_disjoint_guards_and_invalid_crc_rejected(self):
        with self.assertRaisesRegex(ValueError, "overlap"):
            repackage(self.stock, [{"cpu": 0xE700, "old": "00", "new": "00"}] * 2)
        with self.assertRaisesRegex(ValueError, "trailer"):
            repackage(self.stock, [{"cpu": 0xFFEC, "old": "00", "new": "00"}])
        for raw, report in self.built.values():
            for offset in (0x0C, 0x1FC, 0xFFC, 0x1000, 0x10FF8, 0x10FFC):
                altered = bytearray(raw); altered[offset] ^= 1
                with self.subTest(variant=report["variant"], offset=offset):
                    with self.assertRaises(ValueError):
                        check_crc(bytes(altered))

    def test_actual_combined_image_has_same_native_semantics_as_paired_trace(self):
        from fixtures import completion_case
        from audit import native_cases, semantic_result
        from trace_patch import overlay_for_emulation
        combined = self.built["combined-revised-trace"][0]
        reference = overlay_for_emulation(self.built["ckcond-revised"][0])
        for name, kwargs, _, _ in native_cases():
            with self.subTest(case=name):
                expected, old_cpu = completion_case(reference, **kwargs)
                actual, new_cpu = completion_case(combined, **kwargs)
                self.assertEqual(semantic_result(actual), semantic_result(expected))
                self.assertEqual(new_cpu.events, old_cpu.events)


if __name__ == "__main__":
    unittest.main(verbosity=2)
