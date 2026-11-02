"""Require the original reviewed history before any archived Python executes.

The adjacent metadata-only manifest was derived from audit_inventory.json.
This checks provenance; it is not a sandbox for arbitrary replacement scripts.
Ignored bytecode caches must also be excluded from every temporary tree copy.
"""
from pathlib import Path, PurePosixPath
import hashlib
import json
import os
import stat


MANIFEST = Path(__file__).with_name("reviewed_history_manifest.json")


def sha_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_regular(path):
    path = Path(path)
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise ValueError("Missing reviewed file: " + str(path)) from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError("Reviewed input must be a regular file, without symlinks: " + str(path))
    return metadata


def require_separate_output(source, output):
    if output is None:
        return
    source, output = Path(source).resolve(), Path(output).resolve()
    if output.is_relative_to(source) or source.is_relative_to(output):
        raise ValueError("Historical output and immutable evidence must be separate directory trees")
    if output.exists() and not output.is_dir():
        raise ValueError("Historical output must be a directory")
    # Reruns may encounter old log files. Do not follow aliases back into
    # evidence or elsewhere when the reviewed runner later replaces a log.
    if output.exists():
        for parent, subdirs, files in os.walk(output, followlinks=False):
            for name in subdirs:
                if (Path(parent) / name).is_symlink():
                    raise ValueError("Historical output contains a linked directory")
            for name in files:
                path = Path(parent) / name
                metadata = path.lstat()
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                    raise ValueError("Historical output contains a linked or special file")


def verify_history(evidence, group, *, output=None, manifest_path=MANIFEST):
    """Fail closed on changed, missing, unlisted or linked reviewed inputs.

``manifest_path`` exists for synthetic unit fixtures; CLI runners always use
the shipped manifest. Every file in every selected archive root is required.
Only __pycache__ directories are ignored, and runners never copy those caches.
"""
    if not __debug__:
        raise RuntimeError("Historical assertions must remain enabled; Python -O is unsupported")
    evidence = Path(evidence).resolve()
    if (evidence / "audit_input").is_dir():
        evidence = (evidence / "audit_input").resolve()
    if not evidence.is_dir():
        raise ValueError("Historical evidence must be an extracted local directory")
    require_separate_output(evidence, output)
    manifest_path = Path(manifest_path)
    require_regular(manifest_path)
    manifest_raw = manifest_path.read_bytes()
    manifest = json.loads(manifest_raw)
    if manifest.get("schema") != 1 or group not in manifest.get("groups", {}):
        raise ValueError("Unknown reviewed history manifest schema or group")
    roots = manifest["groups"][group]
    if not roots or len(roots) != len(set(roots)):
        raise ValueError("Reviewed history group must contain distinct archive roots")
    for root in roots:
        if len(root) != 16 or any(char not in "0123456789abcdef" for char in root):
            raise ValueError("Invalid reviewed archive root")
        archive_sha = manifest.get("archive_sha256", {}).get(root, "")
        if len(archive_sha) != 64 or not archive_sha.startswith(root):
            raise ValueError("Reviewed archive hash does not identify its root")
    expected = {}
    for relative, metadata in manifest.get("files", {}).items():
        path = PurePosixPath(relative)
        if (path.is_absolute() or ".." in path.parts or "\\" in relative or
                not path.parts or path.as_posix() != relative):
            raise ValueError("Unsafe path in reviewed history manifest")
        if path.parts[0] not in roots:
            continue
        if (set(metadata) != {"sha256", "size"} or type(metadata["size"]) is not int or
                metadata["size"] < 0 or len(metadata["sha256"]) != 64 or
                any(char not in "0123456789abcdef" for char in metadata["sha256"])):
            raise ValueError("Invalid reviewed file metadata: " + relative)
        expected[relative] = metadata
    if any(not any(path.startswith(root + "/") for path in expected) for root in roots):
        raise ValueError("Reviewed archive has no expected files")
    seen, total = set(), 0
    for root in roots:
        directory = evidence / root
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError("Missing or linked reviewed archive root: " + root)
        for parent, subdirs, files in os.walk(directory, followlinks=False):
            for name in tuple(subdirs):
                path = Path(parent) / name
                if name == "__pycache__":
                    subdirs.remove(name)
                elif path.is_symlink():
                    raise ValueError("Linked directory in reviewed history: " + str(path))
            for name in files:
                path = Path(parent) / name
                relative = path.relative_to(evidence).as_posix()
                if relative not in expected:
                    raise ValueError("Unlisted file in reviewed history: " + relative)
                info = require_regular(path)
                wanted = expected[relative]
                if info.st_size != wanted["size"] or sha_file(path) != wanted["sha256"]:
                    raise ValueError("Reviewed history hash/size mismatch: " + relative)
                seen.add(relative)
                total += info.st_size
    missing = sorted(set(expected) - seen)
    if missing:
        raise ValueError("Missing reviewed history file: " + missing[0])
    return {"root": str(evidence), "group": group, "archive_roots": roots,
            "verified_files": len(seen), "verified_bytes": total,
            "manifest_sha256": hashlib.sha256(manifest_raw).hexdigest(),
            "source_inventory_sha256": manifest["inventory_sha256"],
            "scope": "Exact reviewed original files; no general execution sandbox guarantee"}


def verify_emulator(emulator):
    """Permit only the canonical bundled emulator, even if supplied by copy."""
    emulator = Path(emulator)
    require_regular(emulator)
    here = Path(__file__).resolve().parent
    if here.parent.name == "tools":
        reference = here.parent / "emulator/mcs51.py"
    elif here.parent.name == "components":
        reference = here.parent / "common/mcs51.py"
    else:
        raise ValueError("Unknown canonical emulator package layout")
    require_regular(reference)
    observed, expected = sha_file(emulator), sha_file(reference)
    if observed != expected:
        raise ValueError("Supplied emulator differs from the canonical bundled emulator")
    return observed


def replay_environment():
    env = os.environ.copy()
    env.pop("PYTHONOPTIMIZE", None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env
