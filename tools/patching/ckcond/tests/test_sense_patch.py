"""Execute candidate sense/lifecycle instructions against stock-code controls.

No devices are opened. XDATA memory, register values and optional dual-DPTR
behavior are explicit fixtures; the tests do not establish physical RAM safety
or hardware completion correctness.
"""
from test_config import STOCK_PATH, EVIDENCE_PATH, RESULTS
from pathlib import Path
import json
import sys

from sense_patch import build_sense_patch, apply_to_code
from mcs51 import CPU, FixtureBus, load_code
from ph8057_fixtures import DualDPTRCPU

STOCK = load_code(STOCK_PATH)
SPEC = build_sense_patch()
PATCHED = apply_to_code(STOCK, SPEC)
COUNTS = {}
MAX_SP = 0


def checked(group, cpu=None):
    global MAX_SP
    COUNTS[group] = COUNTS.get(group, 0) + 1
    if cpu:
        MAX_SP = max(MAX_SP, cpu.max_sp)


def fresh(code=PATCHED, lun=0, pending=0x28, bank=0, dual=False, bus=False):
    memory = bytearray([0xCC]) * 65536
    memory[0x7980:0x79A0] = bytes(32)
    memory[0x4D00:0x4E20] = bytes([0x7B]) * 0x120
    for i in range(16):
        descriptor = bytes([9, 12, i & 1, 0xA0+i, 0xB0+i, 0xC0+i,
                            0xD0+i, 0xE0+i, 0xF0+i, i, 0x10+i, 0x20+i,
                            0x30+i, 0x40+i])
        memory[0x4D00+i*16:0x4D10+i*16] = bytes([0xA5, pending]) + descriptor
    memory[0x7993] = 96
    if bus:
        xdata = FixtureBus(ram_ranges=[(0x3500,0x3530),(0x4D00,0x4E20),
                                      (0x7980,0x79A0)], initial={0: memory})
    else:
        xdata = memory
    cls = DualDPTRCPU if dual else CPU
    c = cls(code, xdata=xdata)
    c.sp = 0x7F
    c.psw = bank * 8
    for i in range(8):
        c.set_r(i, 0x60+i)
    c.iram[0x5E], c.iram[0x5A] = lun, 1
    for i in range(16):
        c.iram[0x3A+i] = pending
    c.a = 0x92
    c.b = 0x73
    c.dptr = 0x1234
    c.write_direct(0x84, 0x56)
    c.write_direct(0x85, 0x78)
    c.write_direct(0x86, 0)
    c.write_bit(0xAF, 1)
    return c, memory if not bus else xdata.memory


def state(c):
    # Upper128 IDATA is stack scratch, not observable caller state.
    return bytes(c.iram[:128]), bytes(c.sfr)


def run_sense():
    allocs = (0,1,7,8,13,14,17,18,19,21,22,23,96,255)
    pending_codes = (0x02,0x0A,0x28,0x29,0x3F)
    for lun in range(16):
        for pending in pending_codes:
            for desc in (0,1):
                for allocation in allocs:
                    c,m = fresh(lun=lun, pending=pending, bank=lun%4, bus=True)
                    m[0x7990], m[0x7993] = desc, allocation
                    saved = bytes(m[0x4D00:0x4E20])
                    descriptor = bytes(m[0x4D02+lun*16:0x4D10+lun*16])
                    key,asc,ascq = STOCK[0x603D+pending*3:0x6040+pending*3]
                    expected = bytes([0x72,key,asc,ascq,0,0,0,14]) + descriptor
                    r34 = (c.r(3), c.r(4))
                    dptr1 = (c.read_direct(0x84), c.read_direct(0x85), c.read_direct(0x86))
                    c.call(0xC320)
                    assert bytes(m[0x3500:0x3516]) == expected
                    assert m[0x3516] == 0xCC
                    assert (c.iram[0x5B],c.iram[0x5C]) == (0,min(allocation,22))
                    assert c.iram[0x59] == 2 and c.iram[0x5A] == 1
                    assert c.iram[0x3A+lun] == pending
                    assert bytes(m[0x4D00:0x4E20]) == saved
                    assert r34 == (c.r(3),c.r(4))
                    assert dptr1 == (c.read_direct(0x84),c.read_direct(0x85),c.read_direct(0x86))
                    assert c.read_bit(0xAF) == 1 and c.sp == 0x7F
                    assert 0x991E in c.trace and 0xC339 in c.trace
                    assert 0x800A not in c.trace
                    checked('descriptor_native_mapping_allocation_lun_bank', c)


def run_fallbacks():
    for lun in (0,3,15,16):
        for reason in ('invalid','mismatch','zero_pending','desc_invalid','control_invalid'):
            a,ma=fresh(STOCK,lun=lun,pending=0x28)
            b,mb=fresh(PATCHED,lun=lun,pending=0x28)
            for c,m in ((a,ma),(b,mb)):
                if lun < 16:
                    slot=0x4D00+lun*16
                    if reason in ('invalid','desc_invalid'):
                        m[slot]=0
                    elif reason=='mismatch':
                        m[slot+1]=0x29
                    elif reason=='zero_pending':
                        c.iram[0x3A+lun]=0
                        m[slot+1]=0
                if reason=='desc_invalid': m[0x7990]=1
                if reason=='control_invalid': m[0x7994]=1
                c.call(0xC320)
            assert bytes(ma[0x3500:0x3530])==bytes(mb[0x3500:0x3530])
            assert bytes(a.iram[:128])==bytes(b.iram[:128]), (lun,reason)
            # D8AC extension clears a saved marker on native rejection; all
            # other XDATA matches unchanged stock behavior.
            expected=bytearray(ma)
            if reason in ('desc_invalid','control_invalid') and lun<16:
                expected[0x4D00+lun*16]=0
            assert expected==mb, (lun,reason)
            checked('native_fallback_invalid_mismatch_zero_control',b)


def run_sense_changes():
    for lun in range(17):
        for pending in (0,1,2,0x0A,0x28,0x29,0x3F,0xFF):
            for bank in range(4):
                a,ma=fresh(STOCK,lun=lun,bank=bank)
                b,mb=fresh(PATCHED,lun=lun,bank=bank)
                for c in (a,b):
                    c.set_r(7,pending)
                    c.call(0xD8AC)
                assert state(a)==state(b),(lun,pending,bank)
                expected=bytearray(ma)
                if lun<16: expected[0x4D00+16*lun]=0
                assert expected==mb
                checked('sense_setter_all_new_codes_invalidate',b)


def run_admission():
    for lun in (0,1,3,15,16):
        for opcode in (3,0x85,0xA1,0x28,0xDF):
            for mapping in (0,1):
                for bank in range(4):
                    a,ma=fresh(STOCK,lun=lun,bank=bank)
                    b,mb=fresh(PATCHED,lun=lun,bank=bank)
                    for c,m in ((a,ma),(b,mb)):
                        m[0x799F]=0xC7
                        m[0x798F]=opcode
                        m[0x4592]=mapping
                        m[0x459C+lun]=2
                        c.set_r(7,lun)
                        c.run(0x7C40,stop={0x7C43})
                    assert state(a)==state(b),(lun,opcode,mapping,bank)
                    expected=bytearray(ma)
                    expected[0x4E00:0x4E20]=bytes([0xB0])+bytes(31)
                    if lun<16 and opcode!=3:expected[0x4D00+16*lun]=0
                    assert expected==mb
                    checked('bot_admission_preserves_request_sense_only',b)


def run_resets():
    for hook,stop in ((0x67B3,0x67B9),(0x83DC,0x83E2)):
        for lun in range(16):
            for bank in range(4):
                a,ma=fresh(STOCK,lun=lun,bank=bank)
                b,mb=fresh(PATCHED,lun=lun,bank=bank)
                for c in (a,b):
                    c.set_r(7,lun)
                    c.run(hook,stop={stop})
                assert state(a)==state(b),(hook,lun,bank)
                expected=bytearray(ma)
                expected[0x4D00+16*lun]=0
                if lun==0:expected[0x4E00:0x4E20]=bytes(32)
                assert expected==mb
                checked('individual_reset_slots_register_flags',b)
    for entry,stop in ((0xBFB7,0xDAE3),(0x8635,0xC61C)):
        for bank in range(4):
            for acc in (0,0x7F,0x80,0xFF):
                a,ma=fresh(STOCK,bank=bank)
                b,mb=fresh(PATCHED,bank=bank)
                for c in (a,b):
                    c.a=acc
                    c.psw=(bank*8)|0xC4|(acc.bit_count()&1)
                    c.run(entry,stop={stop})
                assert state(a)==state(b),(entry,bank,acc)
                expected=bytearray(ma)
                expected[0x4E00:0x4E20]=bytes(32)
                for lun in range(16):expected[0x4D00+16*lun]=0
                assert expected==mb
                checked('cold_and_full_reset_preserve_caller',b)
    # Actual complete native IRAM clearing loops, not merely isolated hooks.
    for entry,stop,counter in ((0x83D2,0x83E7,0x4C36),(0x67A4,0x67F5,0x4BC9)):
        a,ma=fresh(STOCK)
        b,mb=fresh(PATCHED)
        for c,m in ((a,ma),(b,mb)):
            m[counter]=0
            c.run(entry,stop={stop})
        assert state(a)==state(b)
        expected=bytearray(ma)
        expected[0x4E00:0x4E20]=bytes(32)
        for lun in range(16):expected[0x4D00+16*lun]=0
        assert expected==mb
        assert all(b.iram[0x3A+i]==0 for i in range(16))
        checked('full_native_reset_loop_execution',b)


def run_consumption():
    for lun in range(16):
        a,ma=fresh(STOCK,lun=lun,dual=True)
        b,mb=fresh(PATCHED,lun=lun,dual=True)
        for c,m in ((a,ma),(b,mb)):
            c.iram[0x59]=2
            c.iram[0x5A]=1
            c.iram[0x55:0x59]=bytes([0x12,0x34,0x56,0x78])
            m[0x7984:0x7988]=bytes([9,8,7,6])
            c.call(0x94F9)
        assert state(a)==state(b)
        expected=bytearray(ma)
        expected[0x4D00+16*lun]=0
        assert expected==mb
        assert b.iram[0x3A+lun]==0
        assert mb[0x4004:0x4008]==bytes([9,8,7,6])
        assert mb[0x4008:0x400C]==bytes([0x78,0x56,0x34,0x12])
        assert mb[0x400C]==0
        checked('native_bot_finalizer_consumes_only_selected_lun',b)


def run_dps_contracts():
    for entry,stop in ((0x7C40,0x7C43),(0x67B3,0x67B9),(0x83DC,0x83E2),
                       (0xBFB7,0xDAE3),(0x8635,0xC61C)):
        for bank in range(4):
            for lun in (0,3,15):
                a,ma=fresh(STOCK,lun=lun,bank=bank,dual=True)
                b,mb=fresh(PATCHED,lun=lun,bank=bank,dual=True)
                for c,m in ((a,ma),(b,mb)):
                    c.write_direct(0x86,1)
                    c.set_r(7,lun)
                    m[0x798F]=0x85
                    m[0x4592]=0
                    c.run(entry,stop={stop})
                assert state(a)==state(b),(entry,bank,lun)
                expected=bytearray(ma)
                if entry==0x7C40:
                    expected[0x4E00:0x4E20]=bytes([0xB0])+bytes(31)
                    expected[0x4D00+lun*16]=0
                elif entry in (0x67B3,0x83DC):
                    expected[0x4D00+lun*16]=0
                    if lun==0:expected[0x4E00:0x4E20]=bytes(32)
                else:
                    expected[0x4E00:0x4E20]=bytes(32)
                    for i in range(16):expected[0x4D00+i*16]=0
                assert expected==mb,(entry,bank,lun)
                checked('dps1_hook_preservation_negative_control',b)
    for lun in (0,3,15):
        a,ma=fresh(STOCK,lun=lun,dual=True)
        b,mb=fresh(PATCHED,lun=lun,dual=True)
        for c in (a,b):
            c.write_direct(0x86,1)
            c.call(0xC320)
        assert state(a)==state(b)
        assert ma==mb
        checked('dps1_request_sense_retains_native_path',b)


def main():
    run_sense()
    run_fallbacks()
    run_sense_changes()
    run_admission()
    run_resets()
    run_consumption()
    run_dps_contracts()
    result={'status':'PASS','total_scenarios':sum(COUNTS.values()),
            'groups':COUNTS,'max_observed_stack_pointer':f'{MAX_SP:02X}',
            'initial_stack_pointer':'7F','code_start':f'{SPEC["base"]:04X}',
            'code_end_exclusive':f'{SPEC["end"]:04X}',
            'code_bytes':SPEC['end']-SPEC['base'],
            'evidence_scope':'Original + newly generated 8051 instructions in explicitly supplied memory fixtures. No USB, SATA, interrupts, autonomous DMA, physical RAM validation, or flash writes.'}
    (RESULTS/'sense_test_results.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
