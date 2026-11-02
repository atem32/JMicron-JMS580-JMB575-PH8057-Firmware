#!/usr/bin/env python3
"""Execute additional authentic PH8057 terminal paths with the integrated patch.

The byte arrays are explicit MMIO/SFR fixtures. The only time-dependent device
behavior supplied here is A9.bit0 becoming clear on a specified read. No target
firmware function is replaced by a test callback. This is not hardware testing.
"""
from test_config import STOCK_PATH, EVIDENCE_PATH, RESULTS
from pathlib import Path
import sys
import unittest

from test_integrated_patch import (
    new_cpu,admit,begin,launch,result_bank,expected_descriptor,finalize,get_sense,
)


def release_a9_after_reads(c, count=3):
    seen=[]
    def read(cpu,address):
        value=cpu.sfr[address-128]
        seen.append(value)
        if len(seen)>=count:
            value &= ~1
            cpu.sfr[address-128]=value
        return value
    c.sfr_read[0xA9]=read
    return seen


class TerminalEdgeTests(unittest.TestCase):
    def pio_in(self,lun=3,extend=True):
        c=new_cpu();admit(c,lun,wire=8,extend=extend,ata=0xB0)
        begin(c);launch(c,2);c.iram[0x59]=0x68
        return c

    def test_pio_setup_final_uses_estatus_after_native_data_wait(self):
        for status,error in ((0x50,0),(0x51,4),(0x70,0)):
            c=self.pio_in();bank=result_bank(c,3,status=status,error=error)
            c.xdata[0x7094]=0x5F;c.xdata[0x6313]=0x5F
            c.write_direct(0xB9,0x22);c.xdata[0x630E]=0x33
            c.xdata[0x630F]=status;c.xdata[0x630D]=error
            c.xdata[0x6318:0x631C]=bytes((0,2,0,0))
            c.xdata[0x70C0:0x70C4]=bytes(4)
            seen=release_a9_after_reads(c)
            c.call(0x96A7)
            self.assertGreaterEqual(len(seen),3)
            self.assertEqual(c.xdata[0x7094],0)
            self.assertEqual(c.xdata[0x4B31:0x4B33],bytes((status,error)))
            self.assertEqual(c.xdata[0x4E07],0xA5)
            self.assertEqual(c.xdata[0x4D30],0)
            self.assertLess(c.trace.index(0x96EE),c.trace.index(0x970D))
            self.assertEqual(c.xdata[0x638C:0x6390],bytes((0,2,0,0)))
            finalize(c)
            sense=get_sense(c,3)
            self.assertEqual(sense[8:],expected_descriptor(bank,True,status,error))
            self.assertFalse(any(event[0]=="hook"for event in c.events))

    def test_pio_setup_intermediate_drq_waits_without_capture(self):
        c=self.pio_in();result_bank(c,3,status=0x58)
        c.xdata[0x7094]=0x5F;c.xdata[0x6313]=0x5F
        c.xdata[0x630F]=0x58
        c.iram[0x32:0x34]=bytes((0x96,0xA7))
        release_a9_after_reads(c)
        c.call(0x96A7)
        self.assertNotIn(0x970D,c.trace)
        self.assertEqual(c.iram[0x32:0x34],bytes((0x96,0xA7)))
        self.assertEqual(c.xdata[0x4E07],0)
        self.assertEqual(c.xdata[0x4D30],0)

    def test_pio_setup_exception_bypasses_capture_and_keeps_phase_error(self):
        c=self.pio_in();result_bank(c,3)
        c.xdata[0x7094]=0x5F;c.xdata[0x6313]=0x5F
        c.xdata[0x70C5]=0x80
        c.call(0x96A7)
        self.assertIn(0xD310,c.trace)
        self.assertNotIn(0x970D,c.trace)
        self.assertEqual(c.iram[0x59],0x0D)
        self.assertEqual(c.xdata[0x4E07],0)
        finalize(c)
        self.assertEqual(c.xdata[0x400C],2)
        self.assertEqual(c.xdata[0x4D30],0)
        self.assertFalse(any(event[0]=="hook"for event in c.events))

    def test_pio_out_residual_keeps_original_usb_wait_and_residue(self):
        c=new_cpu();admit(c,4,wire=10,ata=0xB0);begin(c);launch(c,3)
        c.iram[0x59]=0x69;bank=result_bank(c,4)
        c.xdata[0x70C0:0x70C4]=bytes((3,0,0,0))
        c.call(0xB339)
        self.assertEqual(c.iram[0x32:0x34],bytes((0xD1,0x42)))
        self.assertEqual(c.xdata[0x4E07],0xA5)
        self.assertEqual(c.xdata[0x4D40],0)
        c.xdata[0x5052]=0;c.xdata[0x50E2]=0
        c.call(0xD142)
        self.assertEqual(c.iram[0x32:0x34],bytes((0xD1,0x42)))
        self.assertEqual(c.xdata[0x4D40],0)
        c.xdata[0x5052]=1
        c.call(0xD142)
        self.assertEqual(c.iram[0x32:0x34],bytes((0x94,0xF9)))
        finalize(c)
        self.assertEqual(c.xdata[0x4008:0x400C],bytes((3,0,0,0)))
        self.assertEqual(get_sense(c,4)[8:],expected_descriptor(bank,False,0x50,0))
        self.assertFalse(any(event[0]=="hook"for event in c.events))

    def test_main_dma_full_entry_transport_error_bypasses_d2h(self):
        c=new_cpu();admit(c,5,wire=12);begin(c);launch(c,4);result_bank(c,5)
        c.write_bit(0x12,1);c.write_bit(0x21,0);c.iram[0x59]=0x66
        c.call(0x7308)
        self.assertNotIn(0x735F,c.trace)
        self.assertIn(0xBB1D,c.trace)
        self.assertEqual(c.iram[0x3F],0x29)
        self.assertEqual(c.xdata[0x4E07],0)
        finalize(c)
        self.assertEqual(c.xdata[0x400C],1)
        self.assertEqual(c.xdata[0x4D50],0)
        self.assertEqual(get_sense(c,5)[0],0x70)

    def test_main_dma_full_entry_wrong_fis_waits_then_accepted_fis_captures(self):
        c=new_cpu();admit(c,5,wire=12);begin(c);launch(c,4);bank=result_bank(c,5)
        c.write_bit(0x12,1);c.write_bit(0x21,1);c.iram[0x59]=0x66
        for fis in (0x27,0x39,0x5F):
            c.xdata[0x6313]=fis;c.call(0x7308)
            self.assertEqual(c.xdata[0x4E07],0)
            self.assertEqual(c.xdata[0x4D50],0)
        c.xdata[0x6313]=0x34;c.call(0x7308)
        self.assertEqual(c.xdata[0x4E07],0xA5)
        finalize(c)
        self.assertEqual(get_sense(c,5)[8:],expected_descriptor(bank,False,0x50,0))

    def test_alternate_dma_next_actual_chunk_launcher_invalidates_old_result(self):
        for direction,wire in ((0,14),(1,12)):
            c=new_cpu();admit(c,6,wire=wire);begin(c);launch(c,5)
            c.write_bit(0x12,direction);c.iram[0x59]=0x66 if direction else 0x67
            result_bank(c,6)
            c.xdata[0x416B]=1;c.xdata[0x4B25]=0
            c.call(0x9EA5)
            self.assertEqual(c.iram[0x32:0x34],bytes((0x68,0xC4)))
            self.assertEqual(c.xdata[0x4E07],0xA5)
            self.assertEqual(c.xdata[0x4D60],0)
            c.xdata[0x4C16:0x4C1A]=bytes((0,2,0,0))
            c.call(0x68C4)
            self.assertEqual(c.xdata[0x4E06],0x5A)
            self.assertEqual(c.xdata[0x4E07],0)
            self.assertEqual(c.xdata[0x4D60],0)
            self.assertEqual(c.iram[0x32:0x34],bytes((0x9E,0xA5)))
            bank=result_bank(c,6);c.xdata[0x416B]=0;c.xdata[0x4B25]=0
            c.call(0x9EA5);finalize(c)
            self.assertEqual(get_sense(c,6)[8:],expected_descriptor(bank,False,0x50,0))
            self.assertFalse(any(event[0]=="hook"for event in c.events))


if __name__=="__main__":
    unittest.main(verbosity=2)
