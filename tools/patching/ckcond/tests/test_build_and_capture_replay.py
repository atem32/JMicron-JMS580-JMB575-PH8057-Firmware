#!/usr/bin/env python3
"""Image-integrity contracts and replay of the actual v7 E5 register bytes.

Replay is software execution using previously observed bytes. It is explicitly
NOT a hardware measurement of the modified firmware.
"""
from test_config import STOCK_PATH, EVIDENCE_PATH, RESULTS
from pathlib import Path
import json
import sys
import unittest

from build_ckcond import DEFAULT_STOCK, build, collect_patches, sha
from image import repackage
from image import check_crc
from test_integrated_patch import new_cpu,admit,begin,launch,complete,finalize,get_sense


class BuildAndCaptureTests(unittest.TestCase):
    def test_full_image_only_exact_manifest_and_crcs_change(self):
        stock=DEFAULT_STOCK.read_bytes()
        result,changes,_=build(stock)
        self.assertEqual(len(result),0x11200)
        self.assertEqual(result[0xE00:0x1000],stock[0xE00:0x1000])
        self.assertEqual(result[0x11000:],stock[0x11000:])
        allowed=set(range(12,16))|set(range(0x1FC,0x200))|set(range(0x10FF8,0x11000))
        for p in changes:
            at=p['cpu']+0x1000
            old,new=bytes.fromhex(p['old']),bytes.fromhex(p['new'])
            self.assertEqual(stock[at:at+len(old)],old)
            self.assertEqual(result[at:at+len(new)],new)
            allowed.update(range(at,at+len(new)))
        self.assertTrue(all(a==b or i in allowed for i,(a,b) in enumerate(zip(stock,result))))
        check_crc(result)
        self.assertEqual(build(stock)[0],result)

    def test_wrong_input_and_corrupted_patch_contracts_are_rejected(self):
        stock=DEFAULT_STOCK.read_bytes()
        changes,_=collect_patches(stock)
        mutated=bytearray(stock);mutated[0x11000]^=1
        with self.assertRaises(Exception):build(bytes(mutated))
        with self.assertRaises(Exception):build(stock[:-1])
        bad=[dict(p) for p in changes]
        before=bytearray.fromhex(bad[0]['old']);before[0]^=1
        bad[0]['old']=before.hex()
        with self.assertRaises(Exception):repackage(stock,bad)
        with self.assertRaises(Exception):repackage(stock,changes+[dict(changes[0])])
        with self.assertRaises(Exception):
            repackage(stock,[{'cpu':0xFFEC,'old':'30','new':'31'}])

    def test_observed_stock_e5_bank_replayed_through_modified_instructions(self):
        evidence=json.loads(EVIDENCE_PATH.read_text())
        bank=bytes.fromhex(evidence['registers_6300_6313_hex'])
        getter=bytes.fromhex(evidence['getter_protocol15_hex'])
        # Real capture selectedUSB LUN1 and actualbank selectedport2. Use the
        # same pairing explicitly; this does not infer the complete port map.
        c=new_cpu();c.xdata[0x459D]=2
        admit(c,1,ck=True,ata=0xE5);begin(c);launch(c,1)
        c.xdata[0x6300:0x6314]=bank
        c.xdata[0x7094]=0x34;c.xdata[0x7097]=bank[0x0D]
        c.write_direct(0xB9,bank[0x0E])
        complete(c,1);finalize(c)
        result=get_sense(c,1)
        expected=bytes.fromhex('72 01 00 1D 00 00 00 0E')+getter
        self.assertEqual(result,expected)
        record={
            'status':'PASS_OFFLINE_REPLAY_NOT_NEW_HARDWARE_OBSERVATION',
            'stock_evidence':'ph8057_v7/PH8057_v7_stock_evidence.json',
            'observed_bank_hex':bank.hex(' '),
            'observed_original_getter_hex':getter.hex(' '),
            'candidate_software_sense_hex':result.hex(' '),
            'candidate_sha256':sha(build(DEFAULT_STOCK.read_bytes())[0]),
            'hardware_execution_of_modified_code':False,
        }
        (RESULTS/'e5_capture_replay_result.json').write_text(json.dumps(record,indent=2)+'\n')


if __name__=='__main__':unittest.main(verbosity=2)
