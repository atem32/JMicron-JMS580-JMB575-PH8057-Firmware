"""Explicit peripheral hypotheses and staged native-code UDMA replay.

This is not a controller emulator. USB/SATA hardware progresses only according
to named test inputs. The arithmetic model is a competing explanation of the
70B0/B6/B8/C0 interface, derived from instruction data flow, not a datasheet.
All accesses outside the listed fixture regions fail closed.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
EMULATOR = HERE.parent.parent / "emulator" if HERE.parent.name == "patching" else HERE.parent / "common"
sys.path.insert(0, str(EMULATOR))
from mcs51 import ExecutionError, FixtureBus  # noqa: E402
from ph8057_fixtures import DualDPTRCPU  # noqa: E402

class ReadSequence:
    """One explicit sequence, with the final value held until the test ends."""
    def __init__(self, values):
        self.values = tuple(values)
        if not self.values or any(type(x) is not int or not 0 <= x <= 255 for x in self.values):
            raise ValueError("At least one byte-valued fixture sample is required")
        self.count = 0

    def __call__(self, *_):
        value = self.values[min(self.count, len(self.values) - 1)]
        self.count += 1
        return value


class ArithmeticHypothesis:
    """Hypothesis: 48-bit little-endian operands/result, not a DMA counter.

    C0 clears operands; 10 feeds the previous result into operand A; 00/01
    add/subtract; 02 compares (0 equal, 1 greater, 2 smaller); 03/04 shift.
    The hypothesis is tested against several unrelated native instruction
    consumers. Those tests establish consistency, not silicon validation.
    """
    MASK = (1 << 48) - 1

    def __init__(self):
        self.operations = []

    @staticmethod
    def get(bus, at):
        return int.from_bytes(bus.memory[at:at + 6], "little")

    @staticmethod
    def put(bus, at, value):
        bus.memory[at:at + 6] = (value & ArithmeticHypothesis.MASK).to_bytes(6, "little")

    def write(self, bus, address, command):
        bus.memory[address] = command
        a, b, before = (self.get(bus, p) for p in (0x70B0, 0x70B8, 0x70C0))
        result = before
        if command == 0xC0:
            self.put(bus, 0x70B0, 0)
            self.put(bus, 0x70B8, 0)
        elif command == 0x10:
            self.put(bus, 0x70B0, before)
        elif command == 0x00:
            result = a + b
        elif command == 0x01:
            result = a - b
        elif command == 0x02:
            result = 0 if a == b else 1 if a > b else 2
        elif command == 0x03:
            result = a >> min(b, 48)
        elif command == 0x04:
            result = 0 if b >= 48 else a << b
        else:
            raise ExecutionError(f"Unmodeled arithmetic hypothesis command {command:02X}")
        self.put(bus, 0x70C0, result)
        bus.memory[0x70B7] = 1  # explicit immediate-completion fixture
        self.operations.append({"command": f"0x{command:02X}", "operand_a": a,
                                "operand_b": b, "result_before": before,
                                "result_after": self.get(bus, 0x70C0)})


MMIO_RANGES = (
    (0x502F, 0x5030), (0x5040, 0x5048), (0x5052, 0x5053), (0x5056, 0x5057),
    (0x5082, 0x5083), (0x50E2, 0x50E3),
    (0x6300, 0x6314), (0x6318, 0x631C), (0x632C, 0x632D), (0x6346, 0x6347),
    (0x637C, 0x6380), (0x638C, 0x6390), (0x6920, 0x6921),
    (0x705C, 0x7064), (0x7086, 0x7087), (0x7094, 0x7098),
    (0x70B0, 0x70CE),
)
FIXTURE_RAM_RANGES = (
    (0x3500, 0x3510), (0x4000, 0x4C20),
    # These are CK_COND's scratch areas, modeled for compatibility tests;
    # listing them here does not establish real RAM ownership or safe use.
    (0x4D00, 0x4E20), (0x7980, 0x79A0),
)


def make_bus(*, usb=(1,), error=(0,), arithmetic=True):
    reads, writes = {}, {}
    for lo, hi in MMIO_RANGES:
        for address in range(lo, hi):
            reads[address] = lambda bus, a: bus.memory[a]
            writes[address] = lambda bus, a, v: bus.memory.__setitem__(a, v)
    reads[0x5052] = ReadSequence(usb)
    reads[0x50E2] = ReadSequence(error)
    bus = FixtureBus(ram_ranges=FIXTURE_RAM_RANGES, reads=reads, writes=writes)
    bus.alu = ArithmeticHypothesis() if arithmetic else None
    if bus.alu:
        bus.writes[0x70B6] = bus.alu.write
    return bus


class ObservedCPU(DualDPTRCPU):
    """Observe Python state at real instruction boundaries; no firmware hooks."""
    WATCH = {0x7377, 0xAEF4, 0xAF25, 0xCBE3, 0xCBF8, 0xCC06, 0xCC07,
             0x94F9, 0x9529, 0xFD20}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.snapshots = []

    def step(self):
        if self.pc in self.WATCH and (not self.snapshots or
                                      len(self.snapshots) < 100):
            self.snapshots.append({
                "pc": f"0x{self.pc:04X}", "step": self.steps,
                "residue": int.from_bytes(self.iram[0x55:0x59], "big"),
                "state": self.iram[0x59], "csw_state": self.iram[0x5A],
                "carry": self.cy, "data_in": self.read_bit(0x12),
                "sp": self.sp,
            })
        return super().step()


def build_cbw(*, length=512, tag=0xDFA, lun=1, protocol=11, ck_cond=False,
              sector_count=1, ata_command=0x35, data_in=False):
    if not 0 <= length <= 0xFFFFFFFF or not 0 <= sector_count <= 0xFFFF:
        raise ValueError("Transfer length/sector count outside field bounds")
    cdb = bytes([0x85, (protocol << 1) | 1, 0x06 | (0x20 if ck_cond else 0) |
                 (0x08 if data_in else 0), 0, 0, sector_count >> 8, sector_count & 255,
                 0, 0x10, 0, 0, 0, 1, 0x40, ata_command, 0])
    return (b"USBC" + tag.to_bytes(4, "little") + length.to_bytes(4, "little") +
            bytes([0x80 if data_in else 0, lun, 16]) + cdb)


def new_cpu(raw, *, usb=(1,), error=(0,), endpoint=(0,), active=(4,)):
    if len(raw) != 0x11200:
        raise ValueError("Native replay requires a complete image")
    bus = make_bus(usb=usb, error=error)
    cpu = ObservedCPU(raw[0x1000:0x11000], xdata=bus,
                      sfr_read={0xA3: ReadSequence(endpoint), 0x9F: ReadSequence(active)})
    cpu.sp = 0x90
    cpu.iram[0x5D] = 3
    bus.memory[0x4592] = 1
    bus.memory[0x459D] = 2  # explicit LUN1 -> physical-port2 fixture
    cpu.write_bit(0x02, 1)
    cpu.write_bit(0x21, 1)
    # Initial CSW signature is an explicit setup assumption. The tested
    # finalizer fills tag/residue/status, not the signature itself.
    bus.memory[0x4000:0x4004] = b"USBS"
    return cpu


def stage_cbw_and_launch(cpu, cbw):
    """Execute real factory/CK_COND fragments; scheduler and bus transport are inputs.

    Stages are deliberately bounded: parse CBW fields; ATA PASS-THROUGH(16)
    decoder; SAT transfer-length helper; BOT state dispatch/SATA programming.
    This does not synthesize physical SATA data movement.
    """
    if len(cbw) != 31:
        raise ValueError("31-byte CBW required")
    cpu.xdata.memory[0x7980:0x799F] = cbw
    # The 8051 region 7BF4..7C47 is the real CBW field parser, including the
    # LUN mapping call, its 417F store and CK_COND admission wrapper when present.
    # Discovery of the mapping table itself is outside this fixture.
    cpu.run(0x7BF4, stop=(0x7C48,), max_steps=3000)
    after_cbw = int.from_bytes(cpu.iram[0x55:0x59], "big")
    cpu.call(0x222B, max_steps=15000)
    decoded_state = cpu.iram[0x59]
    cpu.call(0x7D61, max_steps=15000)
    parsed_bytes = int.from_bytes(cpu.xdata.memory[0x4C16:0x4C1A], "little")
    prior_operations = len(cpu.xdata.alu.operations)
    # This table dispatch begins after its preceding asynchronous callback.
    cpu.call(0x380B, max_steps=20000)
    return {
        "cbw_parser_residue": after_cbw,
        "sat_state": decoded_state,
        "sat_requested_bytes_under_arithmetic_hypothesis": parsed_bytes,
        "sata_programmed_bytes_6318": int.from_bytes(cpu.xdata.memory[0x6318:0x631C], "little"),
        "sata_taskfile_6300_6313": bytes(cpu.xdata.memory[0x6300:0x6314]).hex(),
        "scheduled_handler": f"0x{int.from_bytes(cpu.iram[0x32:0x34], 'big'):04X}",
        "new_70B6_operations_during_launch": len(cpu.xdata.alu.operations) - prior_operations,
    }


def completion_case(raw, *, length=512, state=0x67, data_in=False, ata_status=0x50,
                    ata_error=0, d2h=0x34, completion=True, usb=(1,), error=(0,),
                    endpoint=(0,), active=(4,), initial_csw_state=1, ck_cond=False,
                    stage=True, max_steps=10000, sfr_remaining=0,
                    unverified_arithmetic_result=None):
    cpu = new_cpu(raw, usb=usb, error=error, endpoint=endpoint, active=active)
    stages = None
    if stage:
        cbw = build_cbw(length=length, ck_cond=ck_cond,
                        protocol=10 if data_in else 11,
                        ata_command=0x25 if data_in else 0x35,
                        sector_count=(length // 512 if length and length % 512 == 0
                                      and length // 512 <= 0xFFFF else 1),
                        data_in=data_in)
        stages = stage_cbw_and_launch(cpu, cbw)
    else:
        cpu.xdata.memory[0x7984:0x7988] = (0xDFA).to_bytes(4, "little")
        cpu.xdata.memory[0x798F:0x799F] = build_cbw(ck_cond=ck_cond)[15:]
    if stage:
        if int.from_bytes(cpu.iram[0x55:0x59], "big") != length or cpu.iram[0x59] != state:
            raise AssertionError("The native admission/launch stages did not preserve the requested test state")
    else:
        cpu.iram[0x55:0x59] = length.to_bytes(4, "big")
        cpu.iram[0x59] = state
    cpu.iram[0x5A] = initial_csw_state
    cpu.write_bit(0x12, int(data_in))
    cpu.write_bit(0x21, int(completion))
    cpu.write_bit(0x03, 0)
    cpu.xdata.memory[0x6313] = d2h
    cpu.xdata.memory[0x6312] = cpu.iram[0x2B]
    cpu.xdata.memory[0x630E] = ata_status
    cpu.xdata.memory[0x630F] = ata_status
    cpu.xdata.memory[0x630D] = ata_error
    cpu.xdata.memory[0x6346] = 0
    cpu.xdata.memory[0x7094] = d2h
    cpu.xdata.memory[0x7097] = ata_error
    cpu.write_direct(0xB9, ata_status)
    for i, b in enumerate(sfr_remaining.to_bytes(4, "little")):
        cpu.write_direct(0xAC + i, b)
    if unverified_arithmetic_result is not None:
        cpu.xdata.alu.put(cpu.xdata, 0x70C0, unverified_arithmetic_result)
    before = cpu.steps
    try:
        cpu.call(0x7308, max_steps=max_steps)
        outcome = "native_handler_returned"
    except ExecutionError as error_exc:
        if "Step limit" not in str(error_exc):
            raise
        outcome = "native_handler_waited_until_fixture_step_limit"
    result = {
        "stages": stages,
        "outcome": outcome,
        "completion_steps": cpu.steps - before,
        "residue_before_finalizer": int.from_bytes(cpu.iram[0x55:0x59], "big"),
        "state": cpu.iram[0x59], "sense_code": cpu.iram[0x3A + cpu.iram[0x5E]],
        "scheduled_handler": f"0x{int.from_bytes(cpu.iram[0x32:0x34], 'big'):04X}",
        "carry_after_handler": cpu.cy,
        "cc07_normal_wait_return_reached": 0xCC07 in cpu.trace,
        # CK_COND routes both native abort returns through snapshot invalidation.
        "cbe3_inactive_return_reached": any(pc in cpu.trace for pc in (0xCBF8, 0xCC06, 0xFD20)),
        "csw": None,
    }
    if outcome == "native_handler_returned" and result["scheduled_handler"] == "0x94F9":
        cpu.call(0x94F9, max_steps=max_steps)
        raw_csw = bytes(cpu.xdata.memory[0x4000:0x400D])
        result["csw"] = {"hex": raw_csw.hex(), "status": raw_csw[12],
                         "residue": int.from_bytes(raw_csw[8:12], "little"),
                         "qualification": "Conditional native result if the scheduled finalizer is run; external recovery scheduler not modeled"}
    result["observations"] = cpu.snapshots
    result["final_sense_code"] = cpu.iram[0x3A + cpu.iram[0x5E]]
    result["ck_slot_header"] = bytes(cpu.xdata.memory[0x4D00 + cpu.iram[0x5E] * 16:
                                                      0x4D02 + cpu.iram[0x5E] * 16]).hex()
    result["max_sp"] = cpu.max_sp
    result["end_sp"] = cpu.sp
    return result, cpu
