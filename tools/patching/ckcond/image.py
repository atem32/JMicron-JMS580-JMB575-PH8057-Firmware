"""Strict offline PH8057 image integrity and patch application.

The input is the complete 70,144-byte SPI capture. A 65,536-byte file is not
accepted: the historical ph8057-original.bin is a truncated SPI prefix, not
a full CPU CODE image. This module never opens devices.
"""
import hashlib
import os
from pathlib import Path
import stat
import zlib

STOCK_FULL_SHA = "ef5ad9af3f3b290c565a4dc65933d539b7bb8b8051ac9bd45386932a77862c09"
ORIGINAL_V8_SHA = "4b7ac3e5bd124d8e44281e9aa79b7b65f7b62c54410ffd1abd8af4a586d74e11"
REVISED_CKCOND_SHA = "2aaece707763b5dab32c46cf10c17c88345d73b8635365a354dcffe8817b422b"
IMAGE_SIZE = 0x11200
CODE_OFFSET = 0x1000
CODE_END = 0x11000
OEM_OFFSET = 0x11000
TRAILER_CPU = 0xFFEC


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def reverse_bits(value, width):
    result = 0
    for i in range(width):
        result = (result << 1) | ((value >> i) & 1)
    return result


def crc32_by_words_reflected(data):
    """CRC used by this capture; two independently evaluated formulations."""
    require(len(data) % 4 == 0, "CRC input is not word aligned")
    words = b"".join(data[i:i + 4][::-1] for i in range(0, len(data), 4))
    fast = reverse_bits(zlib.crc32(words) ^ 0xFFFFFFFF, 32)
    reference = 0xFFFFFFFF
    for byte in words:
        reference ^= reverse_bits(byte, 8) << 24
        for _ in range(8):
            reference = ((reference << 1) ^
                         (0x04C11DB7 if reference & 0x80000000 else 0)) & 0xFFFFFFFF
    require(fast == reference, "CRC implementations disagree")
    return fast


def check_crc(raw):
    require(isinstance(raw, (bytes, bytearray)), "Image must be bytes")
    require(len(raw) == IMAGE_SIZE, "Expected complete 70,144-byte SPI image")
    require(raw[:4] == bytes.fromhex("5a c3 69 e1"), "Wrong metadata signature")
    checks = {}
    for label, data, offset in (
        ("header", raw[0xE00:0xFFC], 0xFFC),
        ("metadata", raw[0xE00:0x1000] + raw[:0x1FC], 0x1FC),
        ("code", raw[0x1000:0x10FF8], 0x10FF8),
        ("full", raw[0xE00:0x1000] + raw[0x1000:0x10FFC], 0x10FFC),
    ):
        actual = crc32_by_words_reflected(data)
        expected = int.from_bytes(raw[offset:offset + 4], "big")
        require(actual == expected, f"{label} CRC mismatch: {actual:08x}/{expected:08x}")
        checks[label] = f"{actual:08X}"
    require(raw[12:16] == raw[0x10FFC:0x11000], "Full CRC mirror mismatch")
    return checks


def validate_stock(stock):
    require(len(stock) == IMAGE_SIZE and sha(stock) == STOCK_FULL_SHA,
            "Input is not the exact complete PH8057 factory capture")
    return check_crc(stock)


def read_stock(path):
    """Read only a regular file of the exact image size; never a device node."""
    path = Path(path)
    require(path.is_file(), "Stock input must be a regular file")
    require(path.stat().st_size == IMAGE_SIZE, "Stock input has the wrong file size")
    data = path.read_bytes()
    validate_stock(data)
    return data


def guard_output_tree(source, directory):
    """Keep all outputs outside the immutable input tree, including aliases.

    Source and output may share a parent, but the source must not be inside
    the directory that a generator owns. Resolve symlinks before comparing.
    """
    directory = Path(directory)
    require(not directory.is_symlink(), "Output directory must not be a symbolic link")
    if directory.exists():
        require(directory.is_dir(), "Output path must be a directory")
        for parent, directories, files in os.walk(directory, followlinks=False):
            for name in directories:
                require(not (Path(parent) / name).is_symlink(),
                        "Output tree contains a linked directory")
            for name in files:
                metadata = (Path(parent) / name).lstat()
                require(stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1,
                        "Output tree contains a linked or special file")
    source, directory = Path(source).resolve(), directory.resolve()
    require(not source.is_relative_to(directory),
            "Output directory must not contain the immutable source file")


def guard_outputs(source, paths):
    """Check every destination before writing any BIN or sidecar."""
    source = Path(source)
    resolved = []
    for path in map(Path, paths):
        require(not path.is_symlink(), "Refusing to write through an output symlink")
        if path.exists():
            require(path.is_file(), "Output must be a regular file")
            require(not path.samefile(source), "Output aliases the immutable source file")
        require(path.resolve() != source.resolve(), "Output aliases the immutable source file")
        require(path.resolve() not in resolved, "Duplicate output destinations")
        resolved.append(path.resolve())


def repackage(stock, changes):
    """Apply guarded CPU patches and update CRCs; reject overlaps and extras."""
    validate_stock(stock)
    require(isinstance(changes, list), "Patch manifest must be a list")
    data = bytearray(stock)
    occupied = set()
    for patch in changes:
        require(isinstance(patch, dict) and set(patch) == {"cpu", "old", "new"},
                "Patch fields must be cpu, old, new")
        cpu = patch["cpu"]
        if isinstance(cpu, str):
            cpu = int(cpu, 16)
        require(type(cpu) is int, "CPU address must be an integer or hexadecimal string")
        require(isinstance(patch["old"], str) and isinstance(patch["new"], str),
                "Expected/replacement bytes must be hexadecimal strings")
        old, new = bytes.fromhex(patch["old"]), bytes.fromhex(patch["new"])
        require(0 <= cpu < TRAILER_CPU and 0 < len(old) == len(new) and
                cpu + len(old) <= TRAILER_CPU, "Patch crosses CODE/trailer or has invalid length")
        positions = set(range(cpu, cpu + len(old)))
        require(not occupied.intersection(positions), "Patch ranges overlap")
        occupied.update(positions)
        at = cpu + CODE_OFFSET
        require(data[at:at + len(old)] == old, f"Expected bytes differ at CPU {cpu:04X}")
        data[at:at + len(new)] = new
    data[0x10FF8:0x10FFC] = crc32_by_words_reflected(data[0x1000:0x10FF8]).to_bytes(4, "big")
    data[0x10FFC:0x11000] = crc32_by_words_reflected(
        data[0xE00:0x1000] + data[0x1000:0x10FFC]).to_bytes(4, "big")
    data[12:16] = data[0x10FFC:0x11000]
    data[0x1FC:0x200] = crc32_by_words_reflected(
        data[0xE00:0x1000] + data[:0x1FC]).to_bytes(4, "big")
    result = bytes(data)
    check_crc(result)
    require(result[OEM_OFFSET:] == stock[OEM_OFFSET:], "OEM bytes changed")
    require(result[0xE00:0x1000] == stock[0xE00:0x1000], "Header changed")
    allowed = {CODE_OFFSET + x for x in occupied}
    allowed.update(range(12, 16))
    allowed.update(range(0x1FC, 0x200))
    allowed.update(range(0x10FF8, 0x11000))
    require(all(a == b or i in allowed for i, (a, b) in enumerate(zip(stock, result))),
            "Unexpected change outside patch and CRC fields")
    return result


def changed_ranges(before, after):
    require(len(before) == len(after), "Diff requires equal-size images")
    ranges, start = [], None
    for i in range(len(before) + 1):
        different = i < len(before) and before[i] != after[i]
        if different and start is None:
            start = i
        elif not different and start is not None:
            ranges.append({"file_offset": f"0x{start:05X}",
                           "end_exclusive": f"0x{i:05X}",
                           "cpu_address": (f"0x{start-CODE_OFFSET:04X}"
                                           if CODE_OFFSET <= start < CODE_END else None),
                           "old": before[start:i].hex(), "new": after[start:i].hex()})
            start = None
    return ranges
