#!/usr/bin/env python3
"""Compare project decoder to independently authored MIT emu8051 disasm.c.

Only textual syntax is normalized: hex representation, known classic SFR
aliases, bit address notation, and relative branches versus absolute targets.
Reserved A5 is excluded from mnemonic comparison because emu8051 displays it
as NOP. Its length remains compared. This is not firmware emulation.
"""
import ctypes
import hashlib
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from mcs51 import decode
import subprocess, tempfile, unittest

REG = {'ACC':0xe0,'B':0xf0,'PSW':0xd0,'SP':0x81,'DPL':0x82,
       'DPH':0x83,'P0':0x80,'P1':0x90,'P2':0xa0,'P3':0xb0,
       'IP':0xb8,'IE':0xa8,'TMOD':0x89,'TCON':0x88,'TH0':0x8c,
       'TL0':0x8a,'TH1':0x8d,'TL1':0x8b,'SCON':0x98,'SBUF':0x99,
       'PCON':0x87}
REL = {'JBC','JB','JNB','JC','JNC','JZ','JNZ','SJMP','CJNE','DJNZ'}
ABS = {'ACALL','AJMP','LCALL','LJMP'}

def operand(s):
    s = s.strip().upper()
    if s in REG: return str(REG[s])
    if s[:1] in ('#','/'):
        return s[0] + operand(s[1:])
    if '.' in s:
        m = re.fullmatch(r'([^\.]+)\.([0-7])', s)
        if m:
            base = int(operand(m[1]))
            return str((base if base >= 0x80 else base * 8) + int(m[2]))
    if re.fullmatch(r'[0-9A-F]+H', s):return str(int(s[:-1], 16))
    if s.startswith('0X'):return str(int(s, 16))
    if re.fullmatch(r'[+-]?[0-9]+', s):return str(int(s, 10))
    return s.replace(' ', '')

def canonical(text, pc, size, external=False):
    parts = text.strip().upper().split(None, 1)
    mn = parts[0]
    args = [s.strip() for s in parts[1].split(',')] if len(parts)>1 else []
    args = [operand(s) for s in args]
    if args and external and mn in REL:
        if not args[-1].startswith('#'):
            raise ValueError((mn,args))
        args[-1] = str((pc + size + int(args[-1][1:])) & 65535)
    if args and mn in ABS:
        args[-1] = args[-1].removeprefix('#')
    return (mn, tuple(args))

class DecoderOracleTests(unittest.TestCase):
    def test_upstream_decoder_20480_samples(self):
        import shutil
        compiler = shutil.which("cc") or shutil.which("gcc")
        if not compiler:
            self.skipTest("C compiler missing; independent decoder comparison not run")
        src = HERE.parent / "oracle"
        with tempfile.TemporaryDirectory() as td:
            lib = Path(td) / "decode.so"
            subprocess.run([compiler, "-shared", "-fPIC", "-O2", "-I", str(src),
                            str(src / "emu8051_disasm.c"), str(src / "decode_bridge.c"),
                            "-o", str(lib)], check=True, capture_output=True)
            fn = ctypes.CDLL(str(lib)).emu8051_decode_bytes
            fn.argtypes = [ctypes.c_uint] * 4 + [ctypes.c_char_p]
            fn.restype = ctypes.c_int
            code = bytearray(65536)
            out = ctypes.create_string_buffer(128)
            pairs = [(0, 0), (0x12, 0x34), (0x83, 0x82), (0xFF, 0x80), (0x80, 0xFF),
                     (0x7F, 0), (0xA8, 0xFE), (0xE0, 0x81), (0x20, 0x7F), (0xD0, 0x80)]
            for op in range(256):
                for b1, b2 in pairs:
                    for pc in (0, 0x7FE, 0x7FF, 0x1234, 0x7FFE, 0xFFFD, 0xFFFE, 0xFFFF):
                        code[pc] = op
                        code[(pc + 1) & 65535] = b1
                        code[(pc + 2) & 65535] = b2
                        ours = decode(code, pc)
                        size = fn(op, b1, b2, pc, out)
                        self.assertEqual(ours.size, size, (pc, op, b1, b2))
                        if op == 0xA5:
                            # External decoder displays reserved A5 as NOP.
                            self.assertEqual(ours.mnemonic, "RESERVED")
                            continue
                        ours_text = (ours.mnemonic + " " + ours.operands).strip()
                        self.assertEqual(canonical(ours_text, pc, ours.size),
                                         canonical(out.value.decode("ascii"), pc, size, True),
                                         (pc, op, b1, b2))


if __name__ == "__main__":
    unittest.main(verbosity=2)
