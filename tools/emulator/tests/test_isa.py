"""Core validation only; no claim of peripheral or board emulation."""
import itertools
import unittest
from mcs51 import CPU, FixtureBus, ExecutionError, decode


def core(*bytes_, entry=0x100):
    code=bytearray(65536)
    code[entry:entry+len(bytes_)]=bytes_
    cpu=CPU(code)
    cpu.pc=entry
    return cpu


class CoreTests(unittest.TestCase):
    def test_lengths_from_standard_opcode_table(self):
        # Each digit is the documented instruction length, row00..F0.
        rows=(
            '1231121111111111','3231121111111111',
            '3211221111111111','3211221111111111',
            '2223221111111111','2223221111111111',
            '2223221111111111','2221232222222222',
            '2221132222222222','3221221111111111',
            '2221112222222222','2221333333333333',
            '2221121111111111','2221131122222222',
            '1211121111111111','1211121111111111',
        )
        code=bytearray(65536)
        for op in range(256):
            code[0]=op
            self.assertEqual(decode(code,0).size,int(rows[op>>4][op&15]),f'{op:02X}')

    def test_arithmetic_all_operands_and_flags(self):
        def signed(v): return v if v<128 else v-256
        for op,carry_values,subtract in ((0x24,(0,),False),(0x34,(0,1),False),(0x94,(0,1),True)):
            for b in range(256):
                cpu=core(op,b)
                for a in range(256):
                    for carry in carry_values:
                        cpu.pc=0x100;cpu.a=a;cpu.psw=carry<<7
                        cpu.step()
                        total=a-b-carry if subtract else a+b+carry
                        signed_total=signed(a)-signed(b)-carry if subtract else signed(a)+signed(b)+carry
                        ac=((a&15)-(b&15)-carry<0) if subtract else ((a&15)+(b&15)+carry>15)
                        cy=total<0 if subtract else total>255
                        self.assertEqual(cpu.a,total&255)
                        self.assertEqual(cpu.cy,int(cy))
                        self.assertEqual((cpu.psw>>6)&1,int(ac))
                        self.assertEqual((cpu.psw>>2)&1,int(not -128<=signed_total<=127))
                        self.assertEqual(cpu.psw&1,(total&255).bit_count()&1)

    def test_all_bit_addresses(self):
        for bit in range(256):
            if bit==0xD0: # P is recomputed from A at the instruction boundary.
                continue
            cpu=core(0xD2,bit,0xC2,bit)
            cpu.step();self.assertEqual(cpu.read_bit(bit),1)
            cpu.step();self.assertEqual(cpu.read_bit(bit),0)

    def test_register_banks_and_indirect_upper_iram(self):
        cpu=core(0x78,0xE0,0x76,0xA5,0x74,0x36,0xE6)
        cpu.psw=0x18
        for _ in range(5): cpu.step()
        self.assertEqual(cpu.iram[24],0xE0)
        self.assertEqual(cpu.iram[0],0)
        self.assertEqual(cpu.iram[0xE0],0xA5)
        self.assertEqual(cpu.a,0xA5)

    def test_mov_direct_source_destination_and_stack(self):
        cpu=core(0x75,0x30,0x5A,0x85,0x30,0x31,0xC0,0x31,0xD0,0x32)
        cpu.sp=0x60
        for _ in range(4): cpu.step()
        self.assertEqual(cpu.iram[0x31],0x5A)
        self.assertEqual(cpu.iram[0x32],0x5A)
        self.assertEqual(cpu.sp,0x60)

    def test_push_pop_sp_special_order(self):
        cpu=core(0xC0,0x81,0xD0,0x81)
        cpu.sp=0x60
        cpu.step()
        self.assertEqual(cpu.sp,0x61)
        self.assertEqual(cpu.iram[0x61],0x61)
        cpu.iram[0x61]=0x40
        cpu.step()
        self.assertEqual(cpu.sp,0x40)

    def test_explicit_dual_dptr_fixture(self):
        from ph8057_fixtures import DualDPTRCPU
        code=bytearray(65536)
        code[0x100:0x10A]=bytes.fromhex('90 12 34 75 86 01 90 AB CD A3')
        cpu=DualDPTRCPU(code)
        cpu.run(0x100,stop={0x10A})
        self.assertEqual(cpu.read_direct(0x82),0x34)
        self.assertEqual(cpu.read_direct(0x83),0x12)
        self.assertEqual(cpu.dptr,0xABCE)
        cpu.write_direct(0x86,0)
        self.assertEqual(cpu.dptr,0x1234)

    def test_call_ret_order_and_page_boundary(self):
        code=bytearray(65536)
        code[0x7FE:0x800]=bytes((0x11,0x42))
        code[0x842]=0x22
        cpu=CPU(code);cpu.pc=0x7FE;cpu.sp=0x60
        cpu.step()
        self.assertEqual(cpu.pc,0x842)
        self.assertEqual(cpu.iram[0x61:0x63],bytes((0,8)))
        cpu.step()
        self.assertEqual(cpu.pc,0x800)
        self.assertEqual(cpu.sp,0x60)

    def test_relative_branches_and_cjne_flags(self):
        for rel in (0,1,0x7F,0x80,0xFE,0xFF):
            cpu=core(0xB4,0x20,rel)
            cpu.a=0x1F;cpu.step()
            self.assertEqual(cpu.pc,(0x103+(rel if rel<128 else rel-256))&65535)
            self.assertEqual(cpu.cy,1)
        cpu=core(0xB4,0x20,0x80);cpu.a=0x20;cpu.cy=1;cpu.step()
        self.assertEqual(cpu.pc,0x103);self.assertEqual(cpu.cy,0)

    def test_movc_pc_and_dptr(self):
        code=bytearray(65536)
        code[0x100:0x108]=bytes((0x74,3,0x83,0,0,0,0xAB,0))
        code[0x110:0x116]=bytes((0x90,0x12,0x34,0x74,5,0x93))
        code[0x1239]=0xCD
        cpu=CPU(code);cpu.run(0x100,stop={0x103})
        self.assertEqual(cpu.a,0xAB)
        cpu.run(0x110,stop={0x116});self.assertEqual(cpu.a,0xCD)

    def test_explicit_xdata_required_and_unmapped_rejected(self):
        cpu=core(0xE0);cpu.dptr=0x6300
        with self.assertRaises(ExecutionError): cpu.step()
        bus=FixtureBus(ram_ranges=((0x4D00,0x4E00),),reads={0x6300:0xFF})
        cpu=core(0xE0,0xF0);cpu.xdata=bus;cpu.dptr=0x6300
        cpu.step();self.assertEqual(cpu.a,255)
        with self.assertRaises(ExecutionError):cpu.step()
        self.assertEqual(bus.events,[('read',0x6300,255)])

    def test_all_nonreserved_opcode_execution_smoke(self):
        # One step each verifies dispatch completeness, not full semantics.
        for op in range(256):
            cpu=core(op,0x30,0x40)
            cpu.xdata=bytearray(65536);cpu.b=3;cpu.a=7
            if op==0xA5:
                with self.assertRaises(ExecutionError): cpu.step()
            else:
                cpu.step()

    def test_bounded_execution(self):
        cpu=core(0x80,0xFE)
        with self.assertRaises(ExecutionError):cpu.run(max_steps=10)
        self.assertEqual(cpu.steps,10)


if __name__ == '__main__':
    unittest.main(verbosity=2)
