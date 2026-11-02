"""Regression tests for immutable recursive evidence extraction."""
import io
import hashlib
import json
import os
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest import mock
import zipfile

from extract_history import extract
from provenance import verify_history


def zip_bytes(members):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        for name, raw in members:
            z.writestr(name, raw)
    return buffer.getvalue()


class HistoryExtraction(unittest.TestCase):
    def test_nested_duplicate_provenance_and_exact_bytes(self):
        inner = zip_bytes([("original.dat", b"never modify evidence")])
        outer = zip_bytes([("one.zip", inner), ("two.zip", inner)])
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source.zip"; source.write_bytes(outer)
            report = extract([source], root / "out")
            self.assertEqual(source.read_bytes(), outer)
            self.assertEqual(report["unique_archives"], 2)
            self.assertEqual(len(report["archives"]), 3)
            self.assertEqual(sum("duplicate_of" in row for row in report["archives"]), 1)
            row = next(row for row in report["files"] if row["member"] == "original.dat")
            self.assertEqual((root / "out" / row["path"]).read_bytes(), b"never modify evidence")

    def test_traversal_is_rejected(self):
        for name in ("../escape", "/absolute", "dir/../../escape", "windows\\escape"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as td:
                root = Path(td); source = root / "input.zip"
                source.write_bytes(zip_bytes([(name, b"x")]))
                with self.assertRaises(ValueError):
                    extract([source], root / "out")
                self.assertFalse((root / "escape").exists())

    def test_expansion_budget_is_enforced(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); source = root / "input.zip"
            source.write_bytes(zip_bytes([("large", b"x" * 100)]))
            with self.assertRaisesRegex(ValueError, "Expanded archive byte budget"):
                extract([source], root / "out", max_total_bytes=99)

    def test_conflicting_existing_evidence_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); source = root / "input.zip"
            source.write_bytes(zip_bytes([("evidence", b"original")]))
            report = extract([source], root / "out")
            target = root / "out" / report["files"][0]["path"]
            target.write_bytes(b"conflicting local state")
            with self.assertRaises(ValueError):
                extract([source], root / "out")
            self.assertEqual(target.read_bytes(), b"conflicting local state")

    def test_inventory_output_cannot_overwrite_a_source_archive(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            original = zip_bytes([("evidence", b"original")])
            source = root / "inventory.json"
            source.write_bytes(original)
            with self.assertRaisesRegex(ValueError, "overwrite an original"):
                extract([source], root)
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(list(root.iterdir()), [source])

    def test_inventory_link_cannot_modify_original_or_escape_output(self):
        for kind in ("symlink", "hardlink"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                source = root / "source.zip"
                original = zip_bytes([("evidence", b"original")])
                source.write_bytes(original)
                output = root / "out"; output.mkdir()
                target = output / "inventory.json"
                if kind == "symlink":
                    target.symlink_to(source)
                else:
                    os.link(source, target)
                with self.assertRaises(ValueError):
                    extract([source], output)
                self.assertEqual(source.read_bytes(), original)


class HistoryProvenance(unittest.TestCase):
    def fixture(self, root):
        evidence = root / "evidence"
        archive = "0123456789abcdef"
        source = evidence / archive / "audit.py"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"pass\n")
        manifest = root / "reviewed.json"
        data = {"schema": 1, "inventory_sha256": "f" * 64,
                "groups": {"test": [archive]},
                "archive_sha256": {archive: archive + "0" * 48},
                "files": {archive + "/audit.py": {
                    "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                    "size": source.stat().st_size}}}
        manifest.write_text(json.dumps(data))
        return evidence, source, manifest

    def test_exact_reviewed_content_is_accepted(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            evidence, source, manifest = self.fixture(root)
            report = verify_history(evidence, "test", output=root / "result",
                                    manifest_path=manifest)
            self.assertEqual(report["verified_files"], 1)
            self.assertEqual(report["verified_bytes"], 5)
            self.assertEqual(report["manifest_sha256"], hashlib.sha256(manifest.read_bytes()).hexdigest())

    def test_changed_missing_and_unlisted_files_fail_closed(self):
        for mutation in ("changed_same_size", "missing", "extra_python", "extra_native"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as td:
                evidence, source, manifest = self.fixture(Path(td))
                if mutation == "changed_same_size":
                    source.write_bytes(b"fail\n")
                elif mutation == "missing":
                    source.unlink()
                elif mutation == "extra_python":
                    (source.parent / "sitecustomize.py").write_text("pass\n")
                else:
                    extra = source.parent / "native-helper"
                    extra.write_bytes(b"\x7fELF"); extra.chmod(0o755)
                with self.assertRaises(ValueError):
                    verify_history(evidence, "test", manifest_path=manifest)

    def test_linked_file_or_directory_is_rejected(self):
        for directory_link in (False, True):
            with self.subTest(directory_link=directory_link), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                evidence, source, manifest = self.fixture(root)
                external = root / "external"; external.mkdir()
                if directory_link:
                    (source.parent / "importable").symlink_to(external, target_is_directory=True)
                else:
                    copy = external / "audit.py"; copy.write_bytes(source.read_bytes())
                    source.unlink(); source.symlink_to(copy)
                with self.assertRaises(ValueError):
                    verify_history(evidence, "test", manifest_path=manifest)

    def test_cache_is_ignored_but_sourceless_bytecode_is_not(self):
        with tempfile.TemporaryDirectory() as td:
            evidence, source, manifest = self.fixture(Path(td))
            cache = source.parent / "__pycache__"; cache.mkdir()
            (cache / "audit.cpython-312.pyc").write_bytes(b"unreviewed cache; never copied")
            self.assertEqual(verify_history(evidence, "test", manifest_path=manifest)["verified_files"], 1)
            (source.parent / "unreviewed.pyc").write_bytes(b"unreviewed sourceless module")
            with self.assertRaisesRegex(ValueError, "Unlisted file"):
                verify_history(evidence, "test", manifest_path=manifest)

    def test_output_and_evidence_trees_must_not_overlap(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            evidence, source, manifest = self.fixture(root)
            for output in (evidence, evidence / "results", root):
                with self.subTest(output=output), self.assertRaisesRegex(ValueError, "separate"):
                    verify_history(evidence, "test", output=output, manifest_path=manifest)

    def test_output_log_alias_cannot_modify_reviewed_evidence(self):
        for kind in ("symlink", "hardlink"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                evidence, source, manifest = self.fixture(root)
                output = root / "results"; output.mkdir()
                log = output / "historical_v8.log"
                if kind == "symlink":
                    log.symlink_to(source)
                else:
                    os.link(source, log)
                with self.assertRaisesRegex(ValueError, "linked"):
                    verify_history(evidence, "test", output=output, manifest_path=manifest)
                self.assertEqual(source.read_bytes(), b"pass\n")

    def test_modified_v8_entrypoint_rejected_before_any_archived_process(self):
        from replay_original_v8 import replay
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            evidence = root / "evidence"
            script = evidence / "6d36298a2afad5e4/ph8057_v8/work_v8/run_all.py"
            script.parent.mkdir(parents=True)
            script.write_text("raise AssertionError('must never execute unreviewed history')\n")
            with mock.patch("replay_original_v8.subprocess.run") as archived_process:
                with self.assertRaises(ValueError):
                    replay(evidence, root / "output")
                archived_process.assert_not_called()
            self.assertFalse((root / "output").exists())


class HistoricalLabAdapter(unittest.TestCase):
    def test_unreviewed_early_lab_input_rejected_before_any_archived_process(self):
        from replay_labs import replay
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            evidence = root / "evidence"
            script = evidence / "63fb1545420cb03d/PH8057_COMPLETE_HANDOVER_2026-11-02/archives/historical_lab_do_not_flash/PH8057_general_ckcond_lab.py"
            script.parent.mkdir(parents=True)
            script.write_text("raise AssertionError('unreviewed replacement must never execute')\n")
            with mock.patch("replay_labs.subprocess.run") as archived_process:
                with self.assertRaises(ValueError):
                    replay(evidence, root / "output")
                archived_process.assert_not_called()
            self.assertFalse((root / "output").exists())

    def test_binary_adapter_rejects_wrong_size_and_wrong_digest(self):
        from replay_labs import ADAPTER_SOURCE, MISSING_NAME
        for raw in (b"not an image", bytes(65536)):
            with self.subTest(bytes=len(raw)), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                (root / "supplied_pio_v3.img").write_bytes(raw)
                adapter = root / MISSING_NAME
                adapter.write_text(ADAPTER_SOURCE)
                with self.assertRaisesRegex(ValueError, "Unrecognized supplied PIOv3"):
                    runpy.run_path(str(adapter))

    def test_restricted_reconstruction_requires_verified_stock_prefix(self):
        from replay_labs import reconstruct_restricted
        for prefix in (b"partial", bytes(65536)):
            with self.subTest(bytes=len(prefix)), self.assertRaisesRegex(ValueError, "stock prefix"):
                reconstruct_restricted(prefix, bytes(65536))

    def test_adapter_fallback_refuses_when_missing_source_name_is_present(self):
        from replay_labs import inspect_missing_source, MISSING_NAME
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            evidence = root / "evidence"; evidence.mkdir()
            (evidence / MISSING_NAME).write_text("# Newly found source requires review\n")
            with self.assertRaisesRegex(ValueError, "adapter fallback refused"):
                inspect_missing_source(evidence, evidence / "report.md", root / "output")
            self.assertFalse((root / "output").exists())

    def test_fenced_log_recovery_keeps_verbatim_bytes(self):
        from replay_labs import fenced_blocks
        for newline in (b"\n", b"\r\n"):
            with self.subTest(newline=newline):
                body = b"RECORDED ONLY" + newline + b"PASS hypothetical case" + newline
                raw = b"Report" + newline + b"```text" + newline + body + b"```" + newline
                self.assertEqual(fenced_blocks(raw), [body])


if __name__ == "__main__":
    unittest.main(verbosity=2)
