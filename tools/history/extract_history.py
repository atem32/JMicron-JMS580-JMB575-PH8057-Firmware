#!/usr/bin/env python3
"""Offline, bounded recursive ZIP/TAR extraction with content provenance.

No archived script is executed. Originals are read only. One extraction per
archive SHA256 preserves duplicate provenance while avoiding duplicate trees.
"""
import argparse
from collections import deque
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import stat
import tarfile
import zipfile


def safe_relative(name):
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name or "\x00" in name:
        raise ValueError("Unsafe archive member: " + repr(name))
    if not path.parts:
        raise ValueError("Empty archive member")
    return path


def extract(archives, output, *, max_total_bytes=512 * 1024 * 1024, max_depth=12,
            max_archive_bytes=512 * 1024 * 1024):
    output = Path(output).resolve()
    archives = [Path(path).resolve() for path in archives]
    inventory = output / "inventory.json"
    # Check metadata output too, before creating a tree or writing any member.
    # A source ZIP can have any filename, including inventory.json.
    if inventory.is_symlink():
        raise ValueError("Refusing to write inventory through a symlink")
    if not inventory.resolve().is_relative_to(output):
        raise ValueError("Inventory output escapes extraction directory")
    for source in archives:
        if not source.is_file():
            raise ValueError("Archive input must be a regular local file")
        if (inventory.resolve() == source or
                (inventory.exists() and inventory.samefile(source))):
            raise ValueError("Inventory output would overwrite an original archive")
    if inventory.exists() and not inventory.is_file():
        raise ValueError("Inventory output must be a regular file")
    if inventory.exists() and inventory.stat().st_nlink != 1:
        raise ValueError("Refusing to write hardlinked inventory output")
    output.mkdir(parents=True, exist_ok=True)
    pending = deque((Path(p), "attachment:" + Path(p).name, 0) for p in archives)
    seen, archive_rows, file_rows = {}, [], []
    total = 0
    while pending:
        source, origin, depth = pending.popleft()
        if depth > max_depth:
            raise ValueError("Archive nesting limit exceeded")
        if not source.is_file():
            raise ValueError("Archive input must be a regular local file")
        if source.stat().st_size > max_archive_bytes:
            raise ValueError("Archive input byte budget exceeded")
        raw = source.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        record = {"source": source.name, "origin": origin, "sha256": sha,
                  "size": len(raw), "depth": depth}
        archive_rows.append(record)
        if sha in seen:
            record["duplicate_of"] = seen[sha]
            continue
        subdir = sha[:16]
        if subdir in seen.values():
            raise ValueError("Archive SHA prefix collision")
        seen[sha] = subdir
        destination = output / subdir
        destination.mkdir(exist_ok=True)
        record.update(extracted_to=subdir, entries=0)

        def save(name, data):
            nonlocal total
            rel = safe_relative(name)
            total += len(data)
            if total > max_total_bytes:
                raise ValueError("Expanded archive byte budget exceeded")
            target = destination / rel
            # An existing output tree may contain an unrelated symlink.
            if not target.resolve().is_relative_to(output.resolve()):
                raise ValueError("Output path escapes extraction directory")
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and target.read_bytes() != data:
                raise ValueError("Conflicting archive member: " + name)
            if not target.exists():
                target.write_bytes(data)
            record["entries"] += 1
            row = {"path": str(target.relative_to(output)), "member": name,
                   "container_sha256": sha, "size": len(data),
                   "sha256": hashlib.sha256(data).hexdigest()}
            file_rows.append(row)
            if name.lower().endswith((".zip", ".tar", ".tar.gz", ".tgz")):
                pending.append((target, row["path"], depth + 1))

        if zipfile.is_zipfile(io.BytesIO(raw)):
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                for member in archive.infolist():
                    safe_relative(member.filename)
                    if member.is_dir():
                        continue
                    mode = member.external_attr >> 16
                    kind = stat.S_IFMT(mode)
                    if kind not in (0, stat.S_IFREG):
                        raise ValueError("ZIP member is not a regular file")
                    if total + member.file_size > max_total_bytes:
                        raise ValueError("Expanded archive byte budget exceeded")
                    save(member.filename, archive.read(member))
        else:
            with tarfile.open(fileobj=io.BytesIO(raw), mode="r:*") as archive:
                for member in archive:
                    safe_relative(member.name)
                    if member.isdir():
                        continue
                    if not member.isfile():
                        raise ValueError("TAR links and special files are forbidden")
                    if total + member.size > max_total_bytes:
                        raise ValueError("Expanded archive byte budget exceeded")
                    save(member.name, archive.extractfile(member).read())
    result = {"archives": archive_rows, "files": file_rows,
              "unique_archives": len(seen), "expanded_bytes": total,
              "unique_file_hashes": len({x["sha256"] for x in file_rows})}
    inventory.write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("archives", nargs="+", type=Path)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    result = extract(a.archives, a.out)
    print(json.dumps({k: v for k, v in result.items() if k not in ("archives", "files")}, indent=2))
