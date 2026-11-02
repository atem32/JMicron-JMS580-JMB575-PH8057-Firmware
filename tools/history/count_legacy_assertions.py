"""Measure the historical reported-check count versus executed guard checks.

Instrumentation wraps Assert tests with identity and counts entry into the
historical boolean guard helpers. It does not alter any expected value,
condition, fixture or branch. Imported emulator internal asserts are excluded.
"""
import argparse
import ast
import contextlib
import hashlib
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile

from replay_legacy_oem import SOURCES, EXPECTED
from provenance import verify_emulator, verify_history


class CounterTransform(ast.NodeTransformer):
    def visit_Assert(self, node):
        node = self.generic_visit(node)
        node.test = ast.Call(func=ast.Name(id="__count_assert_identity", ctx=ast.Load()), args=[node.test], keywords=[])
        return node

    def visit_FunctionDef(self, node):
        # v23 check(ins,raw) contains an assert and is counted there. Other
        # check/ok/test_case helpers use if-not-condition:raise AssertionError.
        contains_assert = any(isinstance(n, ast.Assert) for statement in node.body for n in ast.walk(statement))
        node = self.generic_visit(node)
        if node.name in ("check", "ok", "test_case") and not contains_assert:
            increment = ast.parse("__audit_metrics['boolean_guard_calls'] += 1").body[0]
            node.body.insert(1 if isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant) else 0, increment)
        return node


def instrument_run(script, args, canonical, output):
    metrics = {"assert_statements": 0, "boolean_guard_calls": 0}
    def count_assert(condition):
        metrics["assert_statements"] += 1
        return condition
    tree = CounterTransform().visit(ast.parse(script.read_text(), filename=str(script)))
    ast.fix_missing_locations(tree)
    namespace = {"__name__": "__main__", "__file__": str(script),
                 "__audit_metrics": metrics, "__count_assert_identity": count_assert}
    argv, path = sys.argv[:], sys.path[:]
    old_emulator = sys.modules.pop("mcs51", None)
    sys.argv = [str(script), *map(str, args)]
    sys.path.insert(0, str(script.parent))
    log = io.StringIO()
    try:
        with contextlib.redirect_stdout(log):
            exec(compile(tree, str(script), "exec"), namespace)
    finally:
        sys.argv, sys.path = argv, path
        sys.modules.pop("mcs51", None)
        if old_emulator:
            sys.modules["mcs51"] = old_emulator
    output.write_text(log.getvalue())
    metrics["executed_validation_guards"] = sum(metrics.values())
    return metrics


def main(evidence, emulator, out):
    evidence, emulator, out = evidence.resolve(), emulator.resolve(), out.resolve()
    provenance = verify_history(evidence, "count", output=out)
    evidence = Path(provenance["root"])
    emulator_sha256 = verify_emulator(emulator)
    out.mkdir(parents=True, exist_ok=True)
    hand = evidence / "f3b3148c740947cb/PH8057_HANDOVER_V2-V29_2026-11-02"
    stock = hand / "firmware/PH8057_FACTORY_COMPLETE_READBACK_DO_NOT_FLASH.bin"
    results = {}
    for version, (directory, filename) in SOURCES.items():
        with tempfile.TemporaryDirectory(prefix="ph8057_count_guards_") as tmp:
            work = Path(tmp) / "work"
            shutil.copytree(evidence / directory, work,
                            ignore=shutil.ignore_patterns("__pycache__"))
            shutil.copyfile(emulator, work / "mcs51.py")
            destination = work / "count_output" if version == 26 else work / "count_output.json"
            args = [stock, "--out", destination]
            if version == 26:
                args += ["--donors", hand / "donor_JMS580"]
            counts = instrument_run(work / filename, args, emulator, out / f"instrumented_v{version}.log")
            counts["reported_units"] = EXPECTED[version]
            counts["source_sha256"] = hashlib.sha256((evidence / directory / filename).read_bytes()).hexdigest()
            results[str(version)] = counts
    with tempfile.TemporaryDirectory(prefix="ph8057_count_final_") as tmp:
        work = Path(tmp) / "work"
        shutil.copytree(evidence / "f3b3148c740947cb", work,
                        ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copyfile(emulator, work / "sources_v29/mcs51.py")
        counts = instrument_run(work / "final_audit.py", [], emulator, out / "instrumented_final.log")
        counts["reported_units"] = 1905
        results["final"] = counts
    summary = {"suites": results,
               "reviewed_history": provenance, "emulator_sha256": emulator_sha256,
               "reported_units": sum(r["reported_units"] for r in results.values()),
               "executed_validation_guards": sum(r["executed_validation_guards"] for r in results.values()),
               "expected_values_changed": False,
               "method": "AST identity wrapper around Assert tests; counter at bool guard-helper entry; excludes emulator internals",
               "qualification": "Neither count measures independent functionality or hardware coverage"}
    (out / "count_audit.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("evidence", type=Path); p.add_argument("emulator", type=Path); p.add_argument("--out", type=Path, required=True)
    a = p.parse_args(); main(a.evidence, a.emulator, a.out)
