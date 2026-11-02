"""Read-only container identification; never infer CPU CODE from size alone."""
import hashlib
from pathlib import Path

FACTORY = "ef5ad9af3f3b290c565a4dc65933d539b7bb8b8051ac9bd45386932a77862c09"
PREFIX = "131bab19b558a25745c881c3c4193fd1f9fb541c0a6c89c7961bad31cecc60b2"
DONORS = {
    "ee9024d1abe886af2878aa469618826e3f1c370c7f3477badb3cfa28a94e4cfc",
    "c6147a3ccdb34bbd3f24d25b544418eb305a6b22e49f318f66054452351fc670",
    "5571a697dc3284b51b9d054c297b623460dc04d2e3c9bfa6da3c4c2beb1260a3",
    "ba0805c80658c0c12f47b27e316900c04fb61c83a2fb01e5e539062cc935091a",
    "40a4763ea54f19fdd8c89af78762f8d1828bf02372959272c63eda70e575c1b1",
    "4cd61e028d9a455b17f73b806022bbcff9de339efd6693c5f794ec11de2b383b",
    "61a8b6b452e384690d9c2968a0449793bcd8cb4bb18423bfa357aae4289f7f9e",
    "b9acde2388ed4e2b3ae0ebee15bf857988ad03d5b0a5bbf1bbf9e8b318c5faf8",
    "32dd2c643a52e85bf6fbf10f1ebbf134455c763e3cdcff207833810a0a6cfed9",
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def identify(raw, *, explicit_cpu=False):
    """Return metadata only. Recognition is not a firmware suitability verdict."""
    sha = digest(raw)
    report = {"size": len(raw), "sha256": sha, "hardware_suitability": "UNKNOWN"}
    if sha == PREFIX:
        report.update(layout="TRUNCATED_PH8057_SPI_PREFIX", code_complete=False,
                      code_file_offset="0x1000", oem_present=False,
                      error="This 64KiB file is not a CPU CODE image")
    elif len(raw) == 0x11200 and raw[:4] == bytes.fromhex("5ac369e1"):
        from image import check_crc
        report.update(layout="PH8057_COMPLETE_SPI", code_complete=True,
                      code_file_offset="0x1000", code_size=0x10000,
                      oem_file_offset="0x11000", oem_size=512,
                      code_sha256=digest(raw[0x1000:0x11000]),
                      oem_sha256=digest(raw[0x11000:]), crc=check_crc(raw),
                      exact_factory=sha == FACTORY)
    elif sha in DONORS:
        if len(raw) != 0x10600 or raw[0x400] != 0x02:
            raise ValueError("Known donor layout invariant failed")
        report.update(layout="JMS580_DONOR_UPDATE_CONTAINER", code_complete=True,
                      code_file_offset="0x0400", code_size=0x10000,
                      oem_file_offset="0x10400", oem_size=512,
                      code_sha256=digest(raw[0x400:0x10400]),
                      oem_sha256=digest(raw[0x10400:]),
                      note="Donor CODE offsets are file offsets minus0x400; not minus0x1000")
    elif explicit_cpu and len(raw) == 65536 and raw[:4] != bytes.fromhex("5ac369e1"):
        report.update(layout="EXPLICIT_RAW_CPU_CODE", code_complete=True,
                      code_file_offset="0x0000", code_size=65536,
                      note="Caller-supplied layout; container provenance not established")
    else:
        report.update(layout="UNKNOWN", code_complete=False,
                      error="No automatic CODE interpretation for an unrecognized file")
    return report


def inspect_file(path, *, explicit_cpu=False):
    path = Path(path)
    if not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("Expected a small regular local firmware file")
    return identify(path.read_bytes(), explicit_cpu=explicit_cpu)
