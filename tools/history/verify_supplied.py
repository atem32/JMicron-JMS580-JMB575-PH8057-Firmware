#!/usr/bin/env python3
"""Verify every extracted supplied file without executing any historical code."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat

from provenance import require_separate_output


MANIFEST = Path(__file__).with_name("supplied_files.json")


def verify(evidence, manifest=MANIFEST):
    evidence = Path(evidence).resolve()
    if (evidence / "audit_input").is_dir():
        evidence = evidence / "audit_input"
    data = json.loads(Path(manifest).read_text())
    checked, total, identities = 0, 0, set()
    for item in data["files"]:
        relative = PurePosixPath(item["path"])
        if relative.is_absolute() or ".." in relative.parts or "\\" in item["path"]:
            raise ValueError("Invalid supplied-file manifest path")
        path = evidence / relative
        for ancestor in [path, *path.parents]:
            if ancestor == evidence:
                break
            if ancestor.is_symlink():
                raise ValueError("Linked supplied input: " + item["path"])
        if not path.exists() or not stat.S_ISREG(path.lstat().st_mode):
            raise ValueError("Missing or nonregular supplied input: " + item["path"])
        raw = path.read_bytes()
        actual = hashlib.sha256(raw).hexdigest()
        if len(raw) != item["size"] or actual != item["sha256"]:
            raise ValueError("Supplied evidence changed: " + item["path"])
        checked += 1; total += len(raw); identities.add(actual)
    return {"status": "PASS", "verified_file_entries": checked,
            "unique_payload_sha256": len(identities), "expanded_bytes": total,
            "scope": "Integrity of all originally supplied extracted files; no source code executed"}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("evidence", type=Path)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    require_separate_output(a.evidence, a.out.parent)
    result = verify(a.evidence)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
