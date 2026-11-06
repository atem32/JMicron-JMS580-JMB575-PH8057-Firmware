#!/usr/bin/env python3
"""Offline byte-execution tests of the generated capture wrappers.

Capture core is an explicit clobbering ABI stub in wrapper-isolation tests.
This tests wrapper preservation, not core ownership logic or SATA hardware.
Non-data branch tests execute original97E4 plus actual generated hook.
"""
from test_config import STOCK_PATH, EVIDENCE_PATH, RESULTS
from pathlib import Path
import json
import sys

from mcs51 import CPU
from ph8057_fixtures import DualDPTRCPU
from capture_wrappers import build_patches, SYMBOLS

STOCK=(STOCK_PATH).read_bytes()[0x1000:0x11000]
PATCHED=bytearray(STOCK)
for patch in build_patches(STOCK):
    at=int(patch["cpu"],16); data=bytes.fromhex(patch["new"])
    PATCHED[at:at+len(data)]=data

def make_cpu(bank=0,dps=0,ea=1):
    data=bytearray(65536)
    c=DualDPTRCPU(PATCHED,xdata=data)
    c.sp=0x90
    c.a=0x96
    c.psw=0xC4|(bank<<3)|(c.a.bit_count()&1)
    c.b=0x73
    c.write_direct(0xA8,(ea<<7)|0x25)
    for direct,val in ((0x82,0x2A),(0x83,0x4A),(0x84,0x6C),(0x85,0x31),(0x86,dps),(0xB9,0x51)):
        c.write_direct(direct,val)
    for i in range(8):c.set_r(i,(0x21+19*i)&255)
    c.set_r(6,0x4A);c.set_r(7,0x1C)
    data[0x4A29:0x4A2B]=bytes((0x50,0x11))
    data[0x4B31:0x4B33]=bytes((0x40,0x22))
    data[0x7097]=0x04
    return c,data

def state(c):
    return {"a":c.a,"psw":c.psw,"b":c.b,"regs":[c.r(i)for i in range(8)],
            "sfr":[c.read_direct(i)for i in (0xA8,0x82,0x83,0x84,0x85,0x86)]}

def assert_state_equal(got,want):
    assert got==want,(got,want)

def clobber_capture(c,records):
    records.append((c.r(4),c.r(7),c.r(5)))
    assert c.read_bit(0xAF)==0,"Capture core entered with interrupts enabled"
    assert c.read_direct(0x86)==0,"Capture core did not enter onDPTR0"
    bank=c.psw&0x18
    for i in range(8):c.set_r(i,(0xE1-13*i)&255)
    c.a=0x7D;c.b=0xD2;c.psw=bank|0x04
    for direct,val in ((0x82,0x99),(0x83,0x88),(0x84,0x77),(0x85,0x66),(0x86,0xA1)):
        c.write_direct(direct,val)
    c.ret()

def run_wrapper_abi():
    cases=0
    for bank in range(4):
      for dps in (0,1,0xFE,0xFF):
       for ea in (0,1):
        for name,kind,expected in (
          ("capture_nondata",1,(0x50,0x11)),
          ("capture_pio_in",2,(0x40,0x22)),
          ("capture_pio_out",3,(0x51,0x04)),
          ("capture_dma",4,(0x51,0x04)),
          ("capture_dma_alt",5,(0x51,0x04)),
        ):
          c,data=make_cpu(bank,dps,ea); before=state(c);records=[];original_calls=[]
          c.hooks[0xE800]=lambda cpu:clobber_capture(cpu,records)
          def original(cpu):
              assert_state_equal(state(cpu),before)
              original_calls.append(cpu.pc)
              cpu.a=0x5A;cpu.set_r(5,0xE3);cpu.cy=0
              cpu.ret()
          c.hooks[0x82B8]=original;c.hooks[0xB3C4]=original
          c.call(SYMBOLS[name])
          assert records==[(kind,*expected)],(name,records)
          expected_state={k:(list(v) if isinstance(v,list) else v)for k,v in before.items()}
          if kind==1:
              expected_state["regs"][7]=before["regs"][3]
          elif kind in (2,3):
              expected_state["a"]=0x5A
              expected_state["psw"]=(before["psw"]&0x7E)|(0x5A.bit_count()&1)
              expected_state["regs"][5]=0xE3
              assert original_calls==[0x82B8 if kind==2 else 0xB3C4]
          else:
              expected_state["a"]=0x51&0xE1
              expected_state["psw"]=(before["psw"]&0xFE)|((0x51&0xE1).bit_count()&1)
          assert_state_equal(state(c),expected_state)
          assert c.sp==0x90
          assert c.max_sp==0x90+2+17+2,(name,c.max_sp)
          cases+=1
    return cases

def run_pio_transport_guard():
    cases=0
    for bank in range(4):
      for dps in (0,1):
        c,data=make_cpu(bank,dps,1);data[0x6346]=0x20;data[0x4E07]=0xA5
        before=state(c);records=[];seen=[]
        c.hooks[0xE800]=lambda cpu:clobber_capture(cpu,records)
        def original(cpu):
            assert_state_equal(state(cpu),before);seen.append(cpu.pc);cpu.ret()
        c.hooks[0x82B8]=original
        c.call(SYMBOLS["capture_pio_in"])
        assert not records
        assert seen==[0x82B8]and data[0x4E07]==0
        assert_state_equal(state(c),before)
        cases+=1
    return cases

def run_nondata_branches():
    cases=0
    for timer,event,status,error in (
      (0,0x34,0x50,0),(0,0x00,0x51,4),
      (1,0x00,0x50,0),(1,0x27,0x50,0),(1,0x5F,0x50,0),
      (1,0x34,0x50,0),(1,0x34,0x40,0),(1,0x34,0x51,4),
      (1,0x34,0x70,0x80),(1,0x34,0x80,0x55),
    ):
        c,data=make_cpu();c.set_r(3,0x37);c.set_r(5,0);c.iram[0x29]=0x38
        data[0x4A18]=timer;data[0x7094]=event;data[0x7097]=error
        data[0x4A1C:0x4A31]=bytes(range(0x15))
        c.write_direct(0xB9,status);before=bytes(data[0x4A1C:0x4A31]);records=[]
        c.hooks[0xE800]=lambda cpu:clobber_capture(cpu,records)
        c.call(0x97E4)
        if timer==0:
            assert not records and c.r(7)==1 and c.iram[0x29]==0
            assert data[0x4A29]==0x20 and data[0x4A2A]==before[14]
        elif event!=0x34:
            assert not records and c.r(7)==0 and c.iram[0x29]==0x38
            assert bytes(data[0x4A1C:0x4A31])==before
        else:
            assert records==[(1,status,error)]
            assert c.r(7)==(3 if status&0xE1==0x40 else 2)
            assert c.iram[0x29]==0x37
            assert data[0x4A29:0x4A2B]==bytes((status,error))
        # No output capture may corrupt command fields used by retry.
        assert data[0x4A1C:0x4A29]==before[:13]
        cases+=1
    return cases

def run_mapper():
    # Exhaustive65,536input combinations against originalAA9F instruction code.
    # OriginalD8AC executes normally and its per-LUN pending slot is the oracle.
    original=CPU(STOCK,xdata=bytearray(65536));patched=CPU(PATCHED,xdata=bytearray(65536))
    count=0
    for status in range(256):
      for error in range(256):
        for c in (original,patched):
            c.sp=0x80;c.psw=0;c.a=0;c.set_r(7,status);c.set_r(5,error)
            c.iram[0x5E]=3;c.iram[0x3D]=0;c.iram[0x5A]=0
            c.trace.clear();c.events.clear()
        original.call(0xAA9F);patched.call(SYMBOLS["native_ata_sense_code"])
        assert patched.a==original.iram[0x3D],(status,error,patched.a,original.iram[0x3D])
        assert patched.r(7)==status and patched.r(5)==error
        assert patched.iram[0x3D]==0 and patched.iram[0x5A]==0
        count+=1
    return count

def main():
    result={
      "status":"PASS",
      "wrapper_abi_current_register_bank_dps_ea_cases":run_wrapper_abi(),
      "pio_transport_guard_cases":run_pio_transport_guard(),
      "authentic_nondata_branches_with_actual_wrapper":run_nondata_branches(),
      "native_mapper_against_original_AA9F_inputs":run_mapper(),
      "limitations":["CoreE800 is an explicit ABIclobber stub in wrapper-isolation tests",
       "StaticXDATA/SFRfixtures do not model SATA,USB,DMA,interrupt timing or realRAM",
       "New17-byte wrapper frame plus nestedcalls needs physical stack qualification"],
    }
    print(json.dumps(result,indent=2))
    (RESULTS/"capture_wrapper_test_results.json").write_text(json.dumps(result,indent=2)+"\n")

if __name__=="__main__":main()
