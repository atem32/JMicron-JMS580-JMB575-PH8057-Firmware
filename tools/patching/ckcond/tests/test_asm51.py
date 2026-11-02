from test_config import STOCK_PATH, EVIDENCE_PATH, RESULTS
import unittest
from asm51 import Asm,AssemblyError
from mcs51 import CPU

class AsmTests(unittest.TestCase):
    def test_labels_and_absolute_fixups(self):
        a=Asm(0xE300)
        a.call('f').jump('done').label('f').hex('74 42 22').label('done').ret()
        self.assertEqual(a.resolve(),bytes.fromhex('12 E3 06 02 E3 09 74 42 22 22'))
        self.assertEqual(a.symbols,{'f':0xE306,'done':0xE309})

    def test_relative_edges_and_rejection(self):
        for displacement in (-128,127):
            a=Asm(0x300).branch(0x80,0x302+displacement)
            self.assertEqual(a.resolve(),bytes((0x80,displacement&255)))
        for displacement in (-129,128):
            with self.assertRaises(AssemblyError):Asm(0x300).branch(0x80,0x302+displacement).resolve()
        with self.assertRaises(AssemblyError):Asm().jump('missing').resolve()
        with self.assertRaises(AssemblyError):Asm().label('x').label('x')
        with self.assertRaises(AssemblyError):Asm().emit(256)

    def test_long_conditionals_execute_both_paths(self):
        for name in ('jz','jnz','jc','jnc'):
            for value in (0,1):
                a=Asm(0x200)
                getattr(a,name)('taken',long=True)
                a.hex('7F 11 22').label('taken').hex('7F 22 22')
                code=bytearray(65536);raw=a.resolve();code[0x200:0x200+len(raw)]=raw
                cpu=CPU(code);cpu.sp=0x60;cpu.a=value;cpu.cy=value;cpu.call(0x200)
                taken=(value==0 if name in ('jz','jnc') else value==1)
                self.assertEqual(cpu.r(7),0x22 if taken else 0x11)

    def test_long_cjne_both_paths_and_carry(self):
        for register in (None,0,7):
            for value in (0x10,0x20,0x30):
                a=Asm(0x200)
                if register is None:a.cjne_a_imm(0x20,'taken',long=True)
                else:a.cjne_r_imm(register,0x20,'taken',long=True)
                a.hex('7E 11 22').label('taken').hex('7E 22 22')
                code=bytearray(65536);raw=a.resolve();code[0x200:0x200+len(raw)]=raw
                cpu=CPU(code);cpu.sp=0x60
                if register is None:cpu.a=value
                else:cpu.set_r(register,value)
                cpu.call(0x200)
                self.assertEqual(cpu.r(6),0x22 if value!=0x20 else 0x11)
                self.assertEqual(cpu.cy,int(value<0x20))

if __name__=='__main__':unittest.main(verbosity=2)
