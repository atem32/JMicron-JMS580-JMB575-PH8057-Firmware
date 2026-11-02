"""Independent byte-execution contracts for proposed deferred-sense patch.

All external memory is a declared static fixture. Original991E/8000, control
validation, allocation clamp, D8AC and94F9 run as actual CPU instructions.
No USB/SATA completion is implied. These tests do not qualify physical SRAM.
"""
from test_config import STOCK_PATH, EVIDENCE_PATH, RESULTS
from pathlib import Path
import sys
import unittest

from mcs51 import load_code
from ph8057_fixtures import DualDPTRCPU
from sense_patch import build_sense_patch,apply_to_code

STOCK=load_code(STOCK_PATH)
SPEC=build_sense_patch()
PATCHED=apply_to_code(STOCK,SPEC)


def cpu(code=PATCHED,lun=0,dps=0):
    c=DualDPTRCPU(code,xdata=bytearray(65536))
    c.sp=0x90
    c.iram[0x5E]=lun
    c.write_direct(0xA8,0x81)
    c.write_direct(0x82,0x67);c.write_direct(0x83,0x45)
    c.write_direct(0x84,0x34);c.write_direct(0x85,0x12)
    c.write_direct(0x86,dps)
    return c


def prepare_sense(c,lun,pending=0x28,allocation=255,desc_flag=0):
    c.iram[0x3A+lun]=pending
    c.iram[0x59]=0
    c.xdata[0x798F]=3
    c.xdata[0x7990]=desc_flag
    c.xdata[0x7993]=allocation
    c.xdata[0x7994]=0
    # Recognizable independent descriptor payload, differing for each LUN.
    descriptor=bytes((9,12,lun&1,0x40^lun,0x10+lun,0x20+lun,
                      0x30+lun,0x40+lun,0x50+lun,0x60+lun,
                      0x70+lun,0x80+lun,0xA0+lun,0x50))
    off=0x4D00+16*lun
    c.xdata[off:off+16]=bytes((0xA5,pending))+descriptor
    c.xdata[0x3500:0x3520]=bytes((0xCC,))*32
    return descriptor


class SenseContractTests(unittest.TestCase):
    def test_pending_setter_matches_native_abi_all_luns_and_dps(self):
        for lun in range(16):
            for dps in (0,1):
                for pending in (0,2,0x28,0x29):
                    a=cpu(STOCK,lun,dps);b=cpu(PATCHED,lun,dps)
                    for c in (a,b):
                        c.set_r(7,pending)
                        c.a=0xB7;c.cy=1
                        c.xdata[0x1234]=0x77
                        c.xdata[0x4D00:0x4E00]=bytes((0xA5,))*256
                        c.call(0xD8AC)
                    self.assertEqual(b.xdata[0x4D00+16*lun],0,(lun,dps,pending))
                    self.assertEqual(b.xdata[0x1234],0x77,(lun,dps,pending))
                    self.assertEqual(b.iram[:0x80],a.iram[:0x80])
                    self.assertEqual(b.sfr,a.sfr)
                    for other in range(16):
                        if other!=lun:self.assertEqual(b.xdata[0x4D00+16*other],0xA5)

    def test_all_luns_saved_descriptor_after_cdb_replacement(self):
        for lun in range(16):
            for desc in (0,1):
                c=cpu(lun=lun)
                expected=prepare_sense(c,lun,desc_flag=desc)
                c.xdata[0x6300:0x6314]=bytes((0xEE,))*20
                c.call(0xC320)
                key,asc,ascq=STOCK[0x603D+0x28*3:0x6040+0x28*3]
                header=bytes((0x72,key,asc,ascq,0,0,0,14))
                self.assertEqual(c.xdata[0x3500:0x3516],header+expected)
                self.assertEqual((c.iram[0x5B]<<8)|c.iram[0x5C],22)
                self.assertEqual(c.iram[0x59],2)
                self.assertFalse(any(e[0]=='xread' and 0x6300<=e[1]<=0x6313 for e in c.events))

    def test_allocation_clamp_executes_stock_tail(self):
        for allocation in (0,1,7,8,13,18,21,22,23,32,255):
            c=cpu(lun=3)
            prepare_sense(c,3,allocation=allocation)
            c.call(0xC320)
            self.assertEqual((c.iram[0x5B]<<8)|c.iram[0x5C],min(allocation,22))
            self.assertIn(0xC339,c.trace)

    def test_native_fallback_no_valid_or_pending_mismatch(self):
        for reason in ('no_valid','zero_pending','mismatch'):
            for desc_flag in (0,1):
                a=cpu(STOCK,5);b=cpu(PATCHED,5)
                for c in (a,b):
                    prepare_sense(c,5,desc_flag=desc_flag)
                    if reason=='no_valid':c.xdata[0x4D50]=0
                    if reason=='zero_pending':c.iram[0x3F]=0
                    if reason=='mismatch':c.iram[0x3F]=2
                    c.call(0xC320)
                self.assertEqual(b.xdata[0x3500:0x3520],a.xdata[0x3500:0x3520],reason)
                self.assertEqual(b.iram[0x59:0x60],a.iram[0x59:0x60])
                self.assertEqual(b.iram[0x3A:0x4A],a.iram[0x3A:0x4A])

    def test_sense_consumption_preserves_native_tag_and_residual(self):
        for lun in range(16):
            c=cpu(lun=lun)
            prepare_sense(c,lun)
            for other in range(16):
                if other!=lun:c.xdata[0x4D00+16*other]=0xA5
            c.call(0xC320)
            # Driver has completed the sense data transfer. The stock finalizer
            # below performs CPU-side CSW creation, not a simulated USB transfer.
            c.iram[0x5A]=1
            c.xdata[0x7984:0x7988]=bytes((0x12,0x34,0x56,lun))
            c.iram[0x55:0x59]=bytes((0xAB,0xCD,0xEF,lun))
            c.call(0x94F9)
            self.assertEqual(c.xdata[0x4004:0x4008],bytes((0x12,0x34,0x56,lun)))
            self.assertEqual(c.xdata[0x4008:0x400C],bytes((lun,0xEF,0xCD,0xAB)))
            self.assertEqual(c.xdata[0x400C],0)
            self.assertEqual(c.iram[0x3A+lun],0)
            self.assertEqual(c.xdata[0x4D00+16*lun],0)
            for other in range(16):
                if other!=lun:self.assertEqual(c.xdata[0x4D00+16*other],0xA5)

    def test_invalid_request_sense_control_keeps_native_error(self):
        for control in (1,2,0x80,0xFF):
            a=cpu(STOCK,1);b=cpu(PATCHED,1)
            for c in (a,b):
                prepare_sense(c,1)
                c.xdata[0x7994]=control
                c.call(0xC320)
            self.assertEqual(b.iram[0x3B],2)
            self.assertEqual(b.iram[0x5A],a.iram[0x5A])
            self.assertEqual(b.xdata[0x3500:0x3520],a.xdata[0x3500:0x3520])
            self.assertEqual(b.xdata[0x4D10],0)


if __name__=='__main__':unittest.main(verbosity=2)
