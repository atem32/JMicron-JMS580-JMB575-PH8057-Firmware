#!/usr/bin/env python3
"""Stock port-ownership observations replayed through revised CK_COND code.

This is intentionally an offline unit test. Device=21/31/41 decoding by native
CPU 2426 is NOT executed here: selected ports are provided as hardware fixtures.
"""
from pathlib import Path
from test_config import RESULTS
import json
import sys

from test_integrated_patch import (new_cpu, admit, begin, launch, complete, finalize,
                                   get_sense, expected_descriptor)

CAPTURE=bytes.fromhex('00 00 25 00 00 00 01 40 00 00 00 00 80 00 50 d0 18 00 02 34')


def case(lun,port,wire,foreign_port=None):
    c=new_cpu()
    c.xdata[0x459C+lun] = port
    admit(c,lun,wire=wire,ck=True,extend=True,ata=0x25)
    device={2:0x21,3:0x31,4:0x41}[port] if wire==12 else 0x40
    c.xdata[0x799C]=device
    begin(c)
    launch(c,kind=4)
    assert c.xdata[0x4E06] == 0x5A, 'failed to activate launch'
    assert c.xdata[0x4E08] == port
    bank=bytearray(CAPTURE);bank[18]=port if foreign_port is None else foreign_port
    c.xdata[0x6300:0x6314]=bank
    c.xdata[0x7094]=0x34;c.xdata[0x7097]=0
    c.write_direct(0xB9,0x50)
    c.xdata[0x6346]=0
    complete(c,kind=4)
    finalize(c)
    slot=0x4D00+16*lun
    if foreign_port is not None:
        assert c.xdata[slot] == 0, 'foreign-port bank published'
        return dict(lun=lun,port=port,bank_port=foreign_port,wire=wire,valid=False)
    assert c.xdata[slot] == 0xA5, 'expected captured descriptor not published'
    sense=get_sense(c,lun)
    assert sense[0:4]==bytes((0x72,1,0,0x1D)),sense.hex(' ')
    assert sense[8:]==expected_descriptor(bank,True,0x50,0),sense.hex(' ')
    return dict(lun=lun,port=port,bank_port=port,wire=wire,valid=True,
                descriptor_hex=sense.hex(' '))


def main():
    out=[]
    for wire in (12,20):
        for lun,port in ((1,2),(2,3),(3,4)):
            out.append(case(lun,port,wire))
    # Vendor protocol6 may target port4 from an SCSI command issued to LUN1.
    # A matching completion belongs to the SCSI issuer, not an imagined port-to-LUN map.
    out.append(case(1,4,12))
    for lun,port,foreign in ((1,2,4),(2,3,2),(3,4,3)):
        out.append(case(lun,port,12,foreign_port=foreign))
    result=dict(status='PASS',cases=len(out),observations=out,
                disclaimer='Offline 8051 fixture; no physical CPU/RAM/USB/SATA/DF register writes')
    path=RESULTS/'port_owner_results.json'
    path.write_text(json.dumps(result,indent=2)+'\n')
    print('PASS port-ownership offline scenarios:',len(out))
    print('report:',path)

if __name__=='__main__':main()
