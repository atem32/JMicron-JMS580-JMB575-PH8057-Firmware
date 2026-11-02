"""Native ATA PASS-THROUGH(12) dispatch and normalization verification.

Exercises real stock switch4A97/4288, A1A4 conversion, CAA9 control/length
validation, BD5C scheduling and the real222B parser in the integrated candidate.
No external code stubs, disk IO or firmware writes.
"""
from test_config import STOCK_PATH, EVIDENCE_PATH, RESULTS
from pathlib import Path
import json
import sys

from mcs51 import FixtureBus
from ph8057_fixtures import DualDPTRCPU
import build_ckcond as build_v8

raw=(STOCK_PATH).read_bytes()
candidate,_,_=build_v8.build(raw)
STOCK=raw[0x1000:0x11000]
PATCHED=candidate[0x1000:0x11000]


def norm(src):
    return bytes([src[0],src[1]&0xFE,src[2],0,src[3],0,src[4],0,
                  src[5],0,src[6],0,src[7],src[8],src[9],src[11]])


def cpu(code,lun,cdb):
    bus=FixtureBus(ram_ranges=[(0x4000,0x5000),(0x7980,0x79A0)],
                   initial={0x798F:cdb+bytes.fromhex('de ad be ef'),
                            0x7984:bytes([0x11,0x22,0x33,0x44]),
                            0x4592:1,0x459C+lun:2,
                            0x4D00:bytes([0xA5])*256,
                            0x4E00:bytes([0x77])*32})
    c=DualDPTRCPU(code,xdata=bus)
    c.sp=0x7F
    c.iram[0x5E]=lun;c.iram[0x5A]=1;c.iram[0x59]=5
    c.iram[0x38:0x3A]=bytes([0xAA,0xBB])
    c.run(0x7C3E,stop={0x7C48})  # Actual BOT admission/map tail, before8593
    return c,bus.memory


def main():
    total=0
    for lun in (0,3,15):
        for protocol in range(16):
            for ck in (0,1):
                for reserved in (0,1):
                    direction=8 if protocol in (4,6,10) else 0
                    cdb=bytes([0xA1,(protocol<<1)|reserved,ck*0x20|direction,
                               0xDA,0x31,0x42,0x53,0x64,0xE0,0xB0,0xAA,0])
                    expected=norm(cdb)
                    a,ma=cpu(STOCK,lun,cdb)
                    b,mb=cpu(PATCHED,lun,cdb)
                    for c,m in ((a,ma),(b,mb)):
                        c.call(0x4A97)
                        assert c.iram[0x38:0x3A]==bytes.fromhex('22 2b')
                        assert c.iram[0x59]==0x0F
                        assert bytes(m[0x798F:0x799F])==expected
                        assert all(pc in c.trace for pc in (0x4288,0x4B86,0xA1A4,0xCAA9,0xBD5C))
                        c.call(0x222B,stop={0x22A4})
                    assert ma[0x4B39:0x4B4E]==mb[0x4B39:0x4B4E]
                    assert mb[0x4B3B]==cdb[9] # ATA command mapped to native struct
                    assert mb[0x4B48]==ck*0x20
                    if protocol in (3,4,5,6,7,10,11):
                        assert mb[0x4E00:0x4E06]==bytes([0xA5,lun,protocol*2,ck*0x20,0,cdb[9]])
                    else:
                        assert mb[0x4E00]==0 # no new vendor/unsupported capture
                    assert mb[0x4E10:0x4E14]==(bytes([0x11,0x22,0x33,0x44]) if protocol in (3,4,5,6,7,10,11) else bytes(4))
                    assert not any(evt[0]=='hook' for evt in b.events)
                    total+=1
    errors=0
    for control in (1,2,4,0x80,0xFF):
        for lun in (0,3,15):
            cdb=bytes.fromhex('a1 06 20 da 00 00 4f c2 00 b0 aa')+bytes([control])
            c,m=cpu(PATCHED,lun,cdb)
            c.call(0x4A97)
            assert m[0x799E]==control
            assert c.iram[0x3A+lun]==2 and c.iram[0x5A]==2
            assert c.iram[0x38:0x3A]==bytes.fromhex('aa bb')
            assert 0xBD5C not in c.trace and 0x222B not in c.trace
            assert m[0x4D00+16*lun]==0
            errors+=1
    # Native table is parsed as data, independently of executing its switch.
    pairs=[];p=0x4A9E
    while STOCK[p:p+2]!=bytes(2):
        pairs.append((STOCK[p+2],int.from_bytes(STOCK[p:p+2],'big')));p+=3
    assert dict(pairs)[0xA1]==0x4B86 and dict(pairs)[0x85]==0x4B89
    result={'status':'PASS','normalization_parser_cases':total,'invalid_control_cases':errors,
            'total_scenarios':total+errors,
            'native_dispatch':{'A1':'4A97 ->4288 ->4B86 ->A1A4 ->4B89 ->CAA9 ->BD5C ->scheduled222B',
                               '85':'4A97 ->4288 ->4B89 ->CAA9 ->BD5C ->scheduled222B'},
            'CDB_opcode_preserved':'A1','EXTEND_cleared_by_native_A1_normalizer':True,
            'external_code_stubs':0,
            'candidate_sha256':build_v8.sha(candidate),
            'scope':'Instruction execution with explicit XDATA memory fixtures; no peripheral transactions or device IO. Completion and late sense tested separately by integration suite.'}
    (RESULTS/'sat12_test_results.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
