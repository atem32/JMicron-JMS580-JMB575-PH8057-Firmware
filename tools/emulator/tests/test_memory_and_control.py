"""Independent instruction/fixture regressions; no vendor image or device I/O.

ISA oracle: Atmel 8051 Hardware Manual, doc4316, instruction descriptions.
Decimal arithmetic uses decimal integers as the independent oracle. Tests do
not infer anything about JMicron DMA, MMIO timing, interrupts or SRAM ownership.
"""
import tempfile
import unittest
from pathlib import Path

from mcs51 import CPU, FixtureBus, ExecutionError, decode, load_code
from ph8057_fixtures import DualDPTRCPU


def cpu_for(data, pc=0x100, cls=CPU, **kwargs):
    code = bytearray(65536)
    for i, value in enumerate(data):
        code[(pc + i) & 65535] = value
    cpu = cls(code, **kwargs)
    cpu.pc = pc
    return cpu


class AuditCoreTests(unittest.TestCase):
    def test_conditional_jumps_read_only_their_required_condition(self):
        # SFR callbacks may be effectful. Constructing an eager dictionary of
        # all conditions reads ACC and PSW for branches that do not use them.
        # The final ACC/PSW reads below belong to the explicit parity update.
        for opcode, condition_reads, taken in (
            (0x40, [0xD0], True),   # JC uses CY only
            (0x50, [0xD0], False),  # JNC uses CY only
            (0x60, [0xE0], False),  # JZ uses A only
            (0x70, [0xE0], True),   # JNZ uses A only
            (0x80, [], True),      # SJMP has no register condition
        ):
            with self.subTest(opcode=f"{opcode:02X}"):
                reads = []
                def observed_read(cpu, address):
                    reads.append(address)
                    return cpu.sfr[address-128]
                cpu = cpu_for(bytes((opcode, 2)),
                              sfr_read={0xD0: observed_read, 0xE0: observed_read})
                cpu.a, cpu.psw = 1, 0x80
                cpu.step()
                self.assertEqual(cpu.pc, 0x104 if taken else 0x102)
                self.assertEqual(reads, condition_reads + [0xE0, 0xD0])

    def test_reject_ambiguous_truncated_spi_as_cpu_code(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "original.bin"
            path.write_bytes(bytes.fromhex("5A C3 69 E1") + bytes(65532))
            with self.assertRaises(ValueError):
                load_code(path)
            with self.assertRaises(ValueError):
                load_code(path, layout="cpu")

    def test_explicit_cpu_and_complete_image_layout(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "cpu.bin"
            code = bytes(range(256)) * 256
            path.write_bytes(code)
            with self.assertRaises(ValueError):
                load_code(path)
            self.assertEqual(load_code(path, layout="cpu"), code)
            path.write_bytes(b"H" * 4096 + code + b"O" * 512)
            self.assertEqual(load_code(path), code)
            with self.assertRaises(ValueError):
                load_code(path, layout="cpu")

    def test_bus_initialization_cannot_resize_or_wrap(self):
        for initial in ({-1: 3}, {65536: 2}, {65535: b"ab"}):
            with self.subTest(initial=initial):
                with self.assertRaises(ValueError):
                    FixtureBus(initial=initial)
        for ranges in (((-1, 1),), ((0, 65537),), ((9, 8),)):
            with self.assertRaises(ValueError):
                FixtureBus(ram_ranges=ranges)
        bus = FixtureBus(initial={65535: b"a"})
        self.assertEqual(len(bus.memory), 65536)
        self.assertEqual(bus.memory[-1], 97)

    def test_mmio_trace_records_executed_pc_not_next_pc(self):
        bus = FixtureBus(ram_ranges=((0x2000, 0x2001),), initial={0x2000: 0xA7})
        cpu = cpu_for(bytes.fromhex("90 20 00 E0 F0"), xdata=bus)
        cpu.run(stop={0x105})
        self.assertEqual(cpu.events, [("xread", 0x2000, 0xA7, 0x103),
                                      ("xwrite", 0x2000, 0xA7, 0x104)])
        self.assertIsNone(cpu._active_pc)

    def test_divide_zero_is_not_a_deterministic_execution(self):
        cpu = cpu_for(b"\x84")
        cpu.a = 123
        cpu.b = 0
        cpu.cy = 1
        with self.assertRaises(ExecutionError):
            cpu.step()
        self.assertEqual(cpu.cy, 0)
        self.assertTrue(cpu.psw & 4)

    def test_mul_all_inputs_and_unaffected_psw(self):
        cpu = cpu_for(b"\xA4")
        for a in range(256):
            for b in range(256):
                cpu.pc = 0x100
                cpu.a, cpu.b, cpu.psw = a, b, 0xFA
                cpu.step()
                product = a * b
                self.assertEqual((cpu.b << 8) | cpu.a, product)
                self.assertEqual(cpu.cy, 0)
                self.assertEqual(bool(cpu.psw & 4), product >= 256)
                self.assertEqual(cpu.psw & 0x7A, 0x7A)
                self.assertEqual(cpu.psw & 1, (product & 255).bit_count() & 1)
            cpu.trace.clear()

    def test_div_all_defined_inputs(self):
        cpu = cpu_for(b"\x84")
        for a in range(256):
            for b in range(1, 256):
                cpu.pc = 0x100
                cpu.a, cpu.b, cpu.psw = a, b, 0xFE
                cpu.step()
                self.assertEqual((cpu.a, cpu.b), divmod(a, b))
                self.assertEqual(cpu.psw & 0x84, 0)
                self.assertEqual(cpu.psw & 0x7A, 0x7A)
            cpu.trace.clear()

    def test_decimal_adjust_20000_decimal_additions(self):
        def bcd(v):
            return (v // 10) * 16 + v % 10
        for rhs in range(100):
            cpu = cpu_for(bytes((0x34, bcd(rhs), 0xD4)))
            for lhs in range(100):
                for carry in (0, 1):
                    cpu.pc, cpu.a, cpu.psw = 0x100, bcd(lhs), carry << 7
                    cpu.step()
                    unaffected = cpu.psw & 0x7E
                    cpu.step()
                    total = lhs + rhs + carry
                    self.assertEqual(cpu.a, bcd(total % 100), (lhs, rhs, carry))
                    self.assertEqual(cpu.cy, int(total >= 100))
                    self.assertEqual(cpu.psw & 0x7E, unaffected)

    def test_movx_ri_uses_p2_and_bank_selected_r(self):
        for bank in range(4):
            for reg in (0, 1):
                bus = FixtureBus(ram_ranges=((0xAB00, 0xAC00),), initial={0xABF1: 0x42})
                cpu = cpu_for(bytes((0xE2 + reg, 0xF2 + reg)), xdata=bus)
                cpu.psw = bank << 3
                cpu.set_r(reg, 0xF1)
                cpu.write_direct(0xA0, 0xAB)
                cpu.step()
                self.assertEqual(cpu.a, 0x42)
                cpu.a = 0x7B
                cpu.step()
                self.assertEqual(bus.memory[0xABF1], 0x7B)

    def test_dual_dptr_does_not_alias_named_sfr_banks(self):
        cpu = cpu_for(bytes.fromhex("90 FF FF A3 75 86 01 90 FF FF A3"), cls=DualDPTRCPU)
        cpu.run(stop={0x10B})
        self.assertEqual(cpu.dptr, 0)
        self.assertEqual(cpu.read_direct(0x82) | cpu.read_direct(0x83) << 8, 0)
        cpu.dptr = 0xA123
        cpu.write_direct(0x86, 0)
        self.assertEqual(cpu.dptr, 0)
        self.assertEqual(cpu.read_direct(0x84), 0x23)

    def test_control_flow_wraparound_all_relative_offsets(self):
        for pc in (0, 0x7FE, 0xFFFE, 0xFFFF):
            for rel in range(256):
                cpu = cpu_for(bytes((0x80, rel)), pc=pc)
                cpu.step()
                expected = (pc + 2 + (rel if rel < 128 else rel - 256)) & 65535
                self.assertEqual(cpu.pc, expected)
        for op in range(1, 256, 32):
            for pc in (0x7FD, 0x7FE, 0xFFFF):
                cpu = cpu_for(bytes((op, 0x42)), pc=pc)
                cpu.step()
                self.assertEqual(cpu.pc, ((pc + 2) & 0xF800) | ((op & 0xE0) << 3) | 0x42)

    def test_xchd_preserves_upper_nibbles_and_indirect_sfr_separation(self):
        for bank in range(4):
            for reg in (0, 1):
                cpu = cpu_for(bytes((0xD6 + reg,)))
                cpu.psw = bank << 3
                cpu.set_r(reg, 0xE0)
                cpu.iram[0xE0], cpu.a = 0x53, 0xA9
                cpu.step()
                self.assertEqual(cpu.iram[0xE0], 0x59)
                self.assertEqual(cpu.a, 0xA3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
