"""Execution contracts for the integrated CK_COND patch.

Runs original and patched CPU bytes. The XDATA/SFR arrays are explicit static
fixtures; completion-bank updates between phases are injected observations,
not a simulation of USB/SATA engines, physical SRAM or hardware ownership.
"""
from test_config import STOCK_PATH, EVIDENCE_PATH, RESULTS
from pathlib import Path
import sys
import unittest
import hashlib
import json

from mcs51 import load_code
from ph8057_fixtures import DualDPTRCPU
import core_patch
import capture_wrappers
import abort_guard
import build_ckcond
from sense_patch import build_sense_patch,apply_to_code

STOCK=load_code(STOCK_PATH)
SOURCE_FULL=(STOCK_PATH).read_bytes()
CANDIDATE_FULL=build_ckcond.build(SOURCE_FULL)[0]
OBSERVED_MAX_SP=0


def image():
    out=bytearray(STOCK)
    intervals=[]
    for patch in core_patch.build_patches(STOCK)+capture_wrappers.build_patches(STOCK)+abort_guard.build_patches(STOCK):
        p=patch['cpu'];p=int(p,16) if isinstance(p,str) else p
        old,new=bytes.fromhex(patch['old']),bytes.fromhex(patch['new'])
        assert out[p:p+len(old)]==old and len(old)==len(new)
        assert not any(lo<p+len(new) and p<hi for lo,hi in intervals)
        intervals.append((p,p+len(new)))
        out[p:p+len(new)]=new
    manual=apply_to_code(bytes(out),build_sense_patch())
    built=CANDIDATE_FULL[0x1000:0x11000]
    assert manual[:0xFFF8]==built[:0xFFF8]
    return built


PATCHED=image()
PATHS={1:(6,0x0B8D,0x4A1C),2:(8,0xC7C2,0x4B24),
       3:(10,0xC8F0,0x4B24),4:(12,0xB2A5,0x4B24),5:(12,0x68F3,0x4B24)}


class TrackedCPU(DualDPTRCPU):
    def run(self,*args,**kwargs):
        global OBSERVED_MAX_SP
        try:return super().run(*args,**kwargs)
        finally:OBSERVED_MAX_SP=max(OBSERVED_MAX_SP,self.max_sp)


def new_cpu(code=PATCHED):
    c=TrackedCPU(code,xdata=bytearray(65536))
    c.sp=0x80;c.iram[0x5D]=15
    c.write_direct(0xA8,0x81)
    c.xdata[0x4592]=1
    c.xdata[0x5052]=1 # explicit static USB-side gate, no transfer simulation
    for lun in range(16):c.xdata[0x459C+lun]=(lun*3+2)&15
    return c


def admit(c,lun,opcode=0x85,wire=6,ck=True,extend=False,ata=0xE5,tag=None):
    c.xdata[0x7984:0x7988]=tag or bytes((0x31,lun,wire,ata))
    c.xdata[0x7988:0x798C]=bytes((0x40,0,0,0))
    c.xdata[0x798C]=0x80
    c.xdata[0x798D]=lun
    c.xdata[0x798F:0x799F]=bytes(16)
    c.xdata[0x798F]=opcode
    c.xdata[0x7990]=wire|int(extend)
    c.xdata[0x7991]=0x20 if ck else 0
    c.xdata[0x799D]=ata
    c.run(0x7BF4,stop={0x7C43})
    c.iram[0x2B]=c.xdata[0x459C+lun]
    c.xdata[0x417F]=c.iram[0x2B]


def begin(c):
    # Actual parser of the normalized16-byte ATA CDB and patched229E hook.
    c.run(0x222B,stop={0x22A1})


def launch(c,kind=1,override_call=None):
    wire,callsite,pointer=PATHS[kind]
    c.xdata[pointer:pointer+0x15]=bytes((0x33,))*0x15
    c.xdata[pointer+2]=c.xdata[0x799D]
    c.set_r(6,pointer>>8);c.set_r(7,pointer&255);c.set_r(5,8)
    c.iram[0x29]=0x37 if kind==1 else 0
    c.iram[0x2C]=1;c.xdata[0x4A49]=0x3C
    site=callsite if override_call is None else override_call
    c.run(site,stop={site+3}) # real LCALL8CA3 and full native launcher
    return pointer


def result_bank(c,lun,status=0x50,error=0,ata=None):
    # Independent output values deliberately differ from request Count/LBA33.
    bank=bytearray((0x20+lun,0x30+lun,ata or c.xdata[0x799D],0xDD,
                    0x40+lun,0x50+lun,0x60+lun,0xA0+lun,
                    0x70+lun,0x80+lun,0x90+lun,0xDD,
                    0x80,error,status,status,0x18,0,c.iram[0x2B],0x34))
    c.xdata[0x6300:0x6314]=bank
    c.xdata[0x7094]=0x34;c.xdata[0x7097]=error
    c.write_direct(0xB9,status)
    c.xdata[0x6346]=0 # explicitly accepted peripheral status for fixture
    return bank


def expected_descriptor(bank,extend,status,error):
    return bytes((9,12,int(extend),error,bank[1] if extend else 0,bank[0],
                  bank[8] if extend else 0,bank[4],bank[9] if extend else 0,bank[5],
                  bank[10] if extend else 0,bank[6],bank[7],status))


def complete(c,kind,status=0x50,error=0,timer=1):
    if kind==1:
        c.xdata[0x4A18]=timer
        c.set_r(6,0x4A);c.set_r(7,0x1C);c.set_r(3,0x37);c.set_r(5,0)
        c.call(0x97E4)
        c.run(0x0CD0,stop={0x0ED0}) # native21-byte copyback; no hostloop guessed
        c.call(0xCD31)
    elif kind==2:
        c.call(0x96A7) # timer update, accepted34 branch, wrapper,82B8,AA9F
    elif kind==3:
        c.call(0xB339) # timer update, accepted34 branch, wrapper,B3C4,AA9F
    elif kind==4:
        c.write_bit(0x12,1) # native DMA-in cleanup reads staticSFR residue
        c.call(0x7357)
    else:
        c.xdata[0x416B]=0;c.xdata[0x4B25]=0
        c.call(0x9EA5)


def finalize(c):
    c.call(0x94F9)


def get_sense(c,lun,allocation=255):
    admit(c,lun,opcode=3,wire=0,ck=False,ata=0,tag=bytes((0xF1,lun,0xF2,0xF3)))
    c.xdata[0x7993]=allocation;c.xdata[0x7994]=0
    c.xdata[0x6300:0x6314]=bytes((0xEE,))*20
    c.call(0xC320)
    length=(c.iram[0x5B]<<8)|c.iram[0x5C]
    return bytes(c.xdata[0x3500:0x3500+length])


class IntegratedTests(unittest.TestCase):
    def test_actual_begin_launch_capture_final_sense_all_paths_luns_extend(self):
        for kind in range(1,6):
            for lun in range(16):
                for extend in (False,True):
                    c=new_cpu();wire=PATHS[kind][0]
                    admit(c,lun,wire=wire,extend=extend);begin(c)
                    self.assertEqual(c.xdata[0x4E00],0xA5,(kind,lun))
                    launch(c,kind)
                    self.assertEqual(c.xdata[0x4E06],0x5A,(kind,lun))
                    bank=result_bank(c,lun)
                    complete(c,kind)
                    self.assertEqual(c.xdata[0x4E07],0xA5,(kind,lun))
                    self.assertEqual(c.xdata[0x4D00+16*lun],0)
                    finalize(c)
                    self.assertEqual(c.xdata[0x4D00+16*lun],0xA5,(kind,lun))
                    self.assertEqual(c.xdata[0x400C],1)
                    sense=get_sense(c,lun)
                    self.assertEqual(sense[0:4],bytes((0x72,1,0,0x1D)))
                    self.assertEqual(sense[8:],expected_descriptor(bank,extend,0x50,0),(kind,lun))

    def test_non_ckcond_success_matches_native_csw_payload_residual(self):
        for kind in range(1,6):
            cases=[]
            for code in (STOCK,PATCHED):
                c=new_cpu(code);admit(c,2,wire=PATHS[kind][0],ck=False);begin(c);launch(c,kind)
                result_bank(c,2);complete(c,kind)
                c.xdata[0x3600:0x3800]=bytes(range(256))*2
                c.iram[0x55:0x59]=bytes((1,2,3,4))
                finalize(c);cases.append(c)
            a,b=cases
            self.assertEqual(a.xdata[0x4004:0x400D],b.xdata[0x4004:0x400D])
            self.assertEqual(a.xdata[0x3600:0x3800],b.xdata[0x3600:0x3800])
            self.assertEqual(b.xdata[0x4D20],0)

    def test_ata_errors_keep_native_key_asc_ascq_and_return_descriptor(self):
        for kind in range(1,6):
            for error in (1,2,4,8,0x10,0x20,0x40,0x80):
                for ck in (False,True):
                    c=new_cpu();admit(c,4,wire=PATHS[kind][0],ck=ck,extend=True);begin(c);launch(c,kind)
                    bank=result_bank(c,4,status=0x51,error=error);complete(c,kind,0x51,error)
                    pending=c.iram[0x3E]
                    self.assertNotEqual(pending,0)
                    finalize(c)
                    sense=get_sense(c,4)
                    key,asc,ascq=STOCK[0x603D+3*pending:0x6040+3*pending]
                    self.assertEqual(sense[:4],bytes((0x72,key,asc,ascq)),(kind,error,ck))
                    self.assertEqual(sense[8:],expected_descriptor(bank,True,0x51,error))

    def test_nondata_timeout_never_publishes_stale_taskfile(self):
        c=new_cpu();admit(c,0);begin(c);launch(c)
        result_bank(c,0);complete(c,1,timer=0)
        finalize(c)
        self.assertEqual(c.xdata[0x4D00],0)
        self.assertEqual(get_sense(c,0)[0],0x70)

    def test_ownership_and_generation_negative_controls(self):
        mutations=(
            lambda c:c.xdata.__setitem__(0x4E06,0),
            lambda c:c.xdata.__setitem__(0x4E01,7),
            lambda c:c.xdata.__setitem__(0x7984,0xAA),
            lambda c:c.xdata.__setitem__(0x4E09,5),
            lambda c:c.xdata.__setitem__(0x6312,c.xdata[0x6312]^1),
            lambda c:c.xdata.__setitem__(0x6302,0xB0),
            lambda c:c.xdata.__setitem__(0x798F,0x28),
        )
        for mutate in mutations:
            c=new_cpu();admit(c,0);begin(c);launch(c);result_bank(c,0)
            mutate(c);complete(c,1);finalize(c)
            self.assertEqual(c.xdata[0x4D00],0)

    def test_odd_success_status_phase_error_and_pio_transport_error(self):
        for status in (0,0x10,0x80,0x48,0x58,0xC0):
            c=new_cpu();admit(c,0,wire=8);begin(c);launch(c,2)
            result_bank(c,0,status=status);complete(c,2,status)
            c.iram[0x5A]=1 # test promotion guard despite anomalous success state
            finalize(c)
            self.assertEqual(c.xdata[0x4D00],0,status)
        c=new_cpu();admit(c,0,wire=8);begin(c);launch(c,2);result_bank(c,0)
        complete(c,2);c.iram[0x59]=0x0D
        c.write_bit(0x12,1) # nativephaseerror avoids unrelatedCBE3wait
        finalize(c)
        self.assertEqual(c.xdata[0x400C],2)
        self.assertEqual(c.xdata[0x4D00],0)
        c=new_cpu();admit(c,0,wire=8);begin(c);launch(c,2);result_bank(c,0)
        c.xdata[0x6346]=0x20;complete(c,2);finalize(c)
        self.assertEqual(c.xdata[0x4D00],0)
        self.assertEqual(c.iram[0x3A],0x29)

    def test_other_lun_command_preserves_older_pending_descriptor(self):
        c=new_cpu();admit(c,3);begin(c);launch(c);bank=result_bank(c,3)
        complete(c,1);finalize(c)
        older=bytes(c.xdata[0x4D30:0x4D40])
        admit(c,7,wire=8);begin(c);launch(c,2);result_bank(c,7)
        complete(c,2);finalize(c)
        self.assertEqual(bytes(c.xdata[0x4D30:0x4D40]),older)
        self.assertEqual(get_sense(c,3)[8:],expected_descriptor(bank,False,0x50,0))
        self.assertEqual(c.xdata[0x4D70],0xA5)

    def test_intermediate_dma_chunk_never_publishes_and_next_launch_replaces(self):
        c=new_cpu();admit(c,6,wire=12);begin(c);launch(c,5);result_bank(c,6)
        c.xdata[0x416B]=1
        c.call(0x9EA5)
        self.assertEqual((c.iram[0x32]<<8)|c.iram[0x33],0x68C4)
        self.assertEqual(c.xdata[0x4D60],0)
        self.assertEqual(c.xdata[0x4E07],0xA5)
        launch(c,5)
        self.assertEqual(c.xdata[0x4E07],0)
        bank=result_bank(c,6);bank[0]=0xEF;c.xdata[0x6300]=0xEF
        complete(c,5);finalize(c)
        self.assertEqual(get_sense(c,6)[8:],expected_descriptor(bank,False,0x50,0))

    def test_sat12_real_dispatch_and_normalizer_then_full_completion(self):
        for kind in range(1,6):
            for lun in (0,3,7,15):
                wire=PATHS[kind][0]
                c=new_cpu();admit(c,lun,opcode=0xA1,wire=wire)
                # Real12-byteCDB, including dirtyEXTENDbit that stocknormalizes.
                command=0xE5 if kind==1 else 0xB0
                c.xdata[0x798F:0x799F]=bytes((0xA1,wire|1,0x20,0xD0,0x31,
                    0x41,0x4F,0xC2,0xA0,command,0,0,0xDD,0xDD,0xDD,0xDD))
                c.call(0x4A97) # nativeSCSIswitch+normalizer+control/length gates
                self.assertIn(0xA1A4,c.trace)
                self.assertIn(0xCAA9,c.trace)
                self.assertIn(0xBD5C,c.trace)
                self.assertEqual((c.iram[0x38]<<8)|c.iram[0x39],0x222B)
                self.assertEqual(c.xdata[0x798F],0xA1)
                self.assertEqual(c.xdata[0x799D],command)
                self.assertEqual(c.xdata[0x7990]&1,0)
                begin(c);launch(c,kind);bank=result_bank(c,lun)
                complete(c,kind);finalize(c)
                self.assertEqual(get_sense(c,lun)[8:],expected_descriptor(bank,False,0x50,0))

    def test_all_advertised_wire_protocols_and_launch_returns(self):
        scenarios=[]
        for return_pc,(kind,pointer) in core_patch.LAUNCH_RETURNS.items():
            protocols=(PATHS[kind][0],) if kind<4 else (0x0C,0x0E,0x14,0x16)
            for wire in protocols:scenarios.append((return_pc,kind,wire))
        for ret,kind,wire in scenarios:
            c=new_cpu();admit(c,1,wire=wire);begin(c);launch(c,kind,override_call=ret-3)
            self.assertEqual(c.xdata[0x4E06],0x5A,(hex(ret),wire))
            self.assertEqual(c.xdata[0x4E09],kind)
            bank=result_bank(c,1);complete(c,kind);finalize(c)
            self.assertEqual(get_sense(c,1)[8:],expected_descriptor(bank,False,0x50,0))

    def test_wrong_or_missing_bot_admission_and_launch_lookup_fail_closed(self):
        for reason in ('no_admission','wrong_opcode','wrong_protocol','unknown_launch','wrong_pointer','wrong_returnstate'):
            c=new_cpu();admit(c,0)
            if reason=='no_admission':c.xdata[0x4E00]=0
            if reason=='wrong_opcode':c.xdata[0x798F]=0x28
            if reason=='wrong_protocol':c.xdata[0x7990]=0x18
            begin(c)
            if reason in ('unknown_launch','wrong_pointer','wrong_returnstate'):
                # Run actual8CA3 but deliberately supply a different caller
                # returnPC or requestprovenance. No addedcallsites are patched.
                c.set_r(6,0x4A);c.set_r(7,0x1C);c.set_r(5,8)
                c.xdata[0x4A1E]=0xE5;c.iram[0x29]=0x37
                c.iram[0x2C]=1;c.xdata[0x4A49]=0x3C
                if reason=='wrong_pointer':c.set_r(7,0x1D)
                if reason=='wrong_returnstate':c.xdata[0x4A49]=0x3D
                return_pc=0x1234 if reason=='unknown_launch' else 0x0B90
                c.push_return(return_pc)
                c.run(0x8CA3,stop={return_pc})
            else:launch(c)
            self.assertEqual(c.xdata[0x4E06],0,reason)
            result_bank(c,0);complete(c,1);finalize(c)
            self.assertEqual(c.xdata[0x4D00],0,reason)

    def test_context_change_during_snapshot_blocks_publication(self):
        class ChangingMemory:
            def __init__(self,memory,target):self.memory=memory;self.target=target;self.fired=False
            def read(self,address):
                value=self.memory[address]
                if address==0x6305 and not self.fired:
                    self.fired=True;self.memory[self.target]^=1
                return value
            def write(self,address,value):self.memory[address]=value
            def __getitem__(self,key):return self.memory[key]
            def __setitem__(self,key,value):self.memory[key]=value
        for target in (0x6312,0x7984):
            c=new_cpu();admit(c,0);begin(c);launch(c);result_bank(c,0)
            c.xdata=ChangingMemory(c.xdata,target)
            complete(c,1);finalize(c)
            self.assertTrue(c.xdata.fired)
            self.assertEqual(c.xdata[0x4D00],0)


if __name__=='__main__':
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(IntegratedTests)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    groups={
        'actual_begin_launch_capture_final_sense_all_paths_luns_extend':160,
        'ata_errors_keep_native_key_asc_ascq_and_return_descriptor':80,
        'non_ckcond_success_matches_native_csw_payload_residual':5,
        'nondata_timeout_never_publishes_stale_taskfile':1,
        'ownership_and_generation_negative_controls':7,
        'odd_success_status_phase_error_and_pio_transport_error':8,
        'other_lun_command_preserves_older_pending_descriptor':1,
        'intermediate_dma_chunk_never_publishes_and_next_launch_replaces':1,
        'sat12_real_dispatch_and_normalizer_then_full_completion':20,
        'all_advertised_wire_protocols_and_launch_returns':19,
        'wrong_or_missing_bot_admission_and_launch_lookup_fail_closed':6,
        'context_change_during_snapshot_blocks_publication':2,
    }
    report={
        'status':'PASS' if result.wasSuccessful() else 'FAIL',
        'test_groups':result.testsRun,'scenario_counts_by_group':groups,
        'total_integrated_scenarios':sum(groups.values()),
        'source_sha256':hashlib.sha256(SOURCE_FULL).hexdigest(),
        'candidate_sha256':hashlib.sha256(CANDIDATE_FULL).hexdigest(),
        'observed_max_sp':f'{OBSERVED_MAX_SP:02X}',
        'initial_sp':'80','max_observed_stack_bytes_above_initial':OBSERVED_MAX_SP-0x80,
        'instruction_code_stubs':[],
        'fixture_limits':['staticXDATA/SFR values; injectedcompletionbanks',
                         'explicitdualDPTR model; noUSB/SATAengine',
                         'noasynchronousinterrupts orphysicalRAMaliasing',
                         'boundedphaseentrycontexts; notcontinuousboottohostexecution',
                         '16syntheticLUNslots are not16physicalports'],
        'failures':len(result.failures),'errors':len(result.errors),
    }
    (RESULTS/'integrated_test_results.json').write_text(json.dumps(report,indent=2)+'\n')
    raise SystemExit(0 if result.wasSuccessful() else 1)
