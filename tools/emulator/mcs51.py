"""Small, strict, dependency-free Intel 8051 decoder and instruction executor.

This models the instruction set, not JMicron peripherals. XDATA/SFR hardware
behavior must be supplied explicitly. No device IO is implemented.
"""
from dataclasses import dataclass
from pathlib import Path
import argparse


def hx(x, width=2):
    return f"{x:0{width}X}h"


def signed(x):
    return x - 256 if x & 128 else x


@dataclass(frozen=True)
class Instruction:
    address: int
    raw: bytes
    mnemonic: str
    operands: str = ""
    targets: tuple = ()
    conditional: bool = False

    @property
    def size(self):
        return len(self.raw)

    @property
    def next(self):
        return (self.address + self.size) & 65535

    def __str__(self):
        return f"{self.address:04X}: {self.raw.hex(' ').upper():<8} {self.mnemonic:<5} {self.operands}".rstrip()


def decode(code, address):
    """Decode all standard 8051 opcodes. A5 is reserved, not a NOP."""
    p = address & 65535
    op = code[p]
    b = code[(p + 1) & 65535]
    c = code[(p + 2) & 65535]
    size, name, args, targets, conditional = 1, "???", "", (), False
    rel2 = (p + 2 + signed(b)) & 65535
    rel3 = (p + 3 + signed(c)) & 65535
    if op & 31 in (1, 17):
        size = 2
        name = "ACALL" if op & 16 else "AJMP"
        t = ((p + 2) & 0xF800) | ((op & 0xE0) << 3) | b
        args, targets = hx(t, 4), (t,)
    elif op in (2, 18):
        size, name = 3, "LJMP" if op == 2 else "LCALL"
        t = b * 256 + c
        args, targets = hx(t, 4), (t,)
    elif op in (0x10, 0x20, 0x30):
        size, name, args = 3, {0x10: "JBC", 0x20: "JB", 0x30: "JNB"}[op], f"{hx(b)},{hx(rel3,4)}"
        targets, conditional = (rel3,), True
    elif op in (0x40, 0x50, 0x60, 0x70, 0x80):
        size, name, args = 2, {0x40: "JC", 0x50: "JNC", 0x60: "JZ", 0x70: "JNZ", 0x80: "SJMP"}[op], hx(rel2, 4)
        targets, conditional = (rel2,), op != 0x80
    elif op == 0xD5:
        size, name, args, targets, conditional = 3, "DJNZ", f"{hx(b)},{hx(rel3,4)}", (rel3,), True
    elif 0xD8 <= op <= 0xDF:
        size, name, args, targets, conditional = 2, "DJNZ", f"R{op&7},{hx(rel2,4)}", (rel2,), True
    elif 0xB4 <= op <= 0xBF:
        size, name, targets, conditional = 3, "CJNE", (rel3,), True
        arg = "A," + (hx(b) if op == 0xB5 else "#" + hx(b)) if op < 0xB6 else (f"@R{op&1}" if op < 0xB8 else f"R{op&7}") + ",#" + hx(b)
        args = f"{arg},{hx(rel3,4)}"
    elif op in (0x00, 0x03, 0x13, 0x22, 0x23, 0x32, 0x33, 0x73, 0x83, 0x84, 0x93, 0xA3, 0xA4, 0xA5, 0xB3, 0xC3, 0xC4, 0xD3, 0xD4, 0xE4, 0xF4):
        name, args = {
            0x00:("NOP",""),0x03:("RR","A"),0x13:("RRC","A"),0x22:("RET",""),
            0x23:("RL","A"),0x32:("RETI",""),0x33:("RLC","A"),0x73:("JMP","@A+DPTR"),
            0x83:("MOVC","A,@A+PC"),0x84:("DIV","AB"),0x93:("MOVC","A,@A+DPTR"),
            0xA3:("INC","DPTR"),0xA4:("MUL","AB"),0xA5:("RESERVED",""),
            0xB3:("CPL","C"),0xC3:("CLR","C"),0xC4:("SWAP","A"),
            0xD3:("SETB","C"),0xD4:("DA","A"),0xE4:("CLR","A"),0xF4:("CPL","A")}[op]
    elif (op & 0xF0) in (0x00, 0x10) and (op & 15) >= 4:
        name = "INC" if op < 0x10 else "DEC"
        lo = op & 15
        args = "A" if lo == 4 else hx(b) if lo == 5 else f"@R{lo&1}" if lo < 8 else f"R{lo&7}"
        size = 2 if lo == 5 else 1
    elif (op & 0xF0) in (0x20, 0x30, 0x40, 0x50, 0x60, 0x90) and (op & 15) >= 4:
        name = {0x20:"ADD",0x30:"ADDC",0x40:"ORL",0x50:"ANL",0x60:"XRL",0x90:"SUBB"}[op & 0xF0]
        lo = op & 15
        arg = "#"+hx(b) if lo == 4 else hx(b) if lo == 5 else f"@R{lo&1}" if lo < 8 else f"R{lo&7}"
        args, size = "A,"+arg, 2 if lo < 6 else 1
    elif op in (0x42,0x43,0x52,0x53,0x62,0x63):
        name = {4:"ORL",5:"ANL",6:"XRL"}[op >> 4]
        size, args = (2, f"{hx(b)},A") if op & 1 == 0 else (3, f"{hx(b)},#{hx(c)}")
    elif op in (0x72, 0x82, 0xA0, 0xA2, 0xB0, 0x92):
        size = 2
        name = {0x72:"ORL",0x82:"ANL",0xA0:"ORL",0xA2:"MOV",0xB0:"ANL",0x92:"MOV"}[op]
        args = f"{hx(b)},C" if op == 0x92 else "C,"+("/" if op in (0xA0,0xB0) else "")+hx(b)
    elif op in (0x74,0x75,0x76,0x77) or 0x78 <= op <= 0x7F:
        name = "MOV"
        size = 3 if op == 0x75 else 2
        dst = "A" if op == 0x74 else hx(b) if op == 0x75 else f"@R{op&1}" if op < 0x78 else f"R{op&7}"
        args = dst+",#"+hx(c if op == 0x75 else b)
    elif op == 0x85:
        size, name, args = 3, "MOV", f"{hx(c)},{hx(b)}"
    elif op in (0x86,0x87) or 0x88 <= op <= 0x8F:
        size, name, args = 2, "MOV", hx(b)+","+(f"@R{op&1}" if op < 0x88 else f"R{op&7}")
    elif op == 0x90:
        size, name, args = 3, "MOV", "DPTR,#"+hx(b*256+c,4)
    elif op in (0xA6,0xA7) or 0xA8 <= op <= 0xAF:
        size, name, args = 2, "MOV", (f"@R{op&1}" if op < 0xA8 else f"R{op&7}")+","+hx(b)
    elif op in (0xB2,0xC2,0xD2,0xC0,0xD0):
        size, name, args = 2, {0xB2:"CPL",0xC2:"CLR",0xD2:"SETB",0xC0:"PUSH",0xD0:"POP"}[op], hx(b)
    elif op in (0xC5,0xC6,0xC7) or 0xC8 <= op <= 0xCF:
        name = "XCH"
        size, args = (2, "A,"+hx(b)) if op == 0xC5 else (1, "A,"+(f"@R{op&1}" if op < 0xC8 else f"R{op&7}"))
    elif op in (0xD6,0xD7):
        name, args = "XCHD", f"A,@R{op&1}"
    elif op in (0xE0,0xE2,0xE3,0xF0,0xF2,0xF3):
        name = "MOVX"
        ptr = "@DPTR" if op & 15 == 0 else f"@R{op&1}"
        args = "A,"+ptr if op < 0xF0 else ptr+",A"
    elif op in (0xE5,0xE6,0xE7) or 0xE8 <= op <= 0xEF:
        size, name, args = (2 if op == 0xE5 else 1), "MOV", "A,"+(hx(b) if op == 0xE5 else f"@R{op&1}" if op < 0xE8 else f"R{op&7}")
    elif op in (0xF5,0xF6,0xF7) or 0xF8 <= op <= 0xFF:
        size, name, args = (2 if op == 0xF5 else 1), "MOV", (hx(b) if op == 0xF5 else f"@R{op&1}" if op < 0xF8 else f"R{op&7}")+",A"
    else:
        raise AssertionError(f"Unhandled opcode {op:02X}")
    raw = bytes(code[(p+i)&65535] for i in range(size))
    return Instruction(p,raw,name,args,targets,conditional)


def disassemble(code, start, end):
    p = start
    while p < end:
        ins = decode(code,p)
        yield ins
        p += ins.size


def load_code(path, *, layout=None):
    """Load an explicitly identified image layout.

    A 64 KiB file is ambiguous: the archived ph8057-original.bin is the
    first 64 KiB of SPI, NOT a CPU-addressed CODE image. Require an explicit
    layout for raw CODE instead of silently disassembling it at wrong PCs.
    """
    raw = Path(path).read_bytes()
    if layout not in (None, "ph8057", "cpu"):
        raise ValueError("layout must be ph8057 or cpu")
    if len(raw) == 0x11200 and layout in (None, "ph8057"):
        return raw[0x1000:0x11000]
    if len(raw) == 0x10000 and layout == "cpu":
        if raw.startswith(bytes.fromhex("5A C3 69 E1")):
            raise ValueError("SPI-header signature in purported CPU CODE; truncated SPI is not CODE")
        return raw
    raise ValueError("Expected 70144-byte full readback; raw 65536-byte CODE requires layout='cpu'")


class ExecutionError(RuntimeError):
    pass


class FixtureBus:
    """Explicit test memory with access allowlists and MMIO callbacks.

    ram_ranges are half-open byte ranges backed by memory; they are test
    assumptions, NOT claims about real chip RAM. Unmapped accesses raise.
    read/write callbacks receive (bus,address) / (bus,address,value).
    """
    def __init__(self, *, ram_ranges=(), initial=None, reads=None, writes=None):
        self.memory = bytearray(65536)
        self.ram_ranges = list(ram_ranges)
        for lo, hi in self.ram_ranges:
            if not (isinstance(lo, int) and isinstance(hi, int) and 0 <= lo <= hi <= 65536):
                raise ValueError("Fixture RAM ranges must be within 0000..FFFF")
        self.reads, self.writes = dict(reads or {}), dict(writes or {})
        self.events = []
        if initial:
            for a,v in initial.items():
                if not isinstance(a, int) or not 0 <= a < 65536:
                    raise ValueError("Fixture address outside 0000..FFFF")
                if isinstance(v,(bytes,bytearray)):
                    if a + len(v) > 65536:
                        raise ValueError("Fixture bytes extend beyond FFFF")
                    self.memory[a:a+len(v)] = v
                else:
                    self.memory[a] = v

    def ram(self, a):
        return any(lo <= a < hi for lo,hi in self.ram_ranges)

    def read(self, a):
        a &= 65535
        if a in self.reads:
            fn = self.reads[a]
            value = fn(self,a) if callable(fn) else fn
        elif self.ram(a):
            value = self.memory[a]
        else:
            raise ExecutionError(f"Unmapped XDATA read {a:04X}")
        value &= 255
        self.events.append(("read",a,value))
        return value

    def write(self, a, v):
        a, v = a & 65535, v & 255
        if a in self.writes:
            self.writes[a](self,a,v)
        elif self.ram(a):
            self.memory[a] = v
        else:
            raise ExecutionError(f"Unmapped XDATA write {a:04X}={v:02X}")
        self.events.append(("write",a,v))


class CPU:
    """Bounded standard 8051 executor, with explicitly supplied memory fixtures.

    No timers, interrupts, DMA, SATA, USB, dual-DPTR or flash engine is implied.
    A plain xdata bytearray models exactly those supplied static bytes only.
    Prefer FixtureBus for strict RAM/MMIO separation. Nonstandard SFR effects
    belong in sfr_read/sfr_write callbacks, never implicit instruction behavior.
    """
    def __init__(self, code, *, xdata=None, sfr_read=None, sfr_write=None, hooks=None):
        if len(code) != 65536:
            raise ValueError("CPU code must be exactly 65536 bytes")
        self.code = bytes(code)
        self.iram = bytearray(256)
        self.sfr = bytearray(128)
        self.sfr[0x81-128] = 7
        self.pc = 0
        self.xdata = xdata
        self.sfr_read = dict(sfr_read or {})
        self.sfr_write = dict(sfr_write or {})
        self.hooks = dict(hooks or {})
        self.steps = 0
        self._active_pc = None
        self.trace = []
        self.events = []
        # Diagnostic call/RET balance only: compiler POP/JMP trampolines may
        # unwind return addresses without RET. SP/IRAM decide real stack state.
        self.call_depth = 0
        self.max_sp = 7

    def read_direct(self,a):
        a &= 255
        if a < 128:
            return self.iram[a]
        if a in self.sfr_read:
            return self.sfr_read[a](self,a) & 255
        return self.sfr[a-128]

    def write_direct(self,a,v):
        a, v = a & 255, v & 255
        if a < 128:
            self.iram[a] = v
        else:
            self.sfr[a-128] = v
            if a in self.sfr_write:
                self.sfr_write[a](self,a,v)
        if a == 0x81:
            self.max_sp = max(self.max_sp,v)

    @property
    def a(self):
        return self.read_direct(0xE0)

    @a.setter
    def a(self,v):
        self.write_direct(0xE0,v)

    @property
    def b(self):
        return self.read_direct(0xF0)

    @b.setter
    def b(self,v):
        self.write_direct(0xF0,v)

    @property
    def psw(self):
        return self.read_direct(0xD0)

    @psw.setter
    def psw(self,v):
        self.write_direct(0xD0,v)

    @property
    def cy(self):
        return (self.psw >> 7) & 1

    @cy.setter
    def cy(self,v):
        self.psw = (self.psw & 0x7F) | ((v & 1) << 7)

    @property
    def dptr(self):
        return self.read_direct(0x82) | self.read_direct(0x83) << 8

    @dptr.setter
    def dptr(self,v):
        self.write_direct(0x82,v)
        self.write_direct(0x83,v >> 8)

    @property
    def sp(self):
        return self.read_direct(0x81)

    @sp.setter
    def sp(self,v):
        self.write_direct(0x81,v)

    def r(self,i):
        return self.iram[(self.psw & 0x18)+(i & 7)]

    def set_r(self,i,v):
        self.iram[(self.psw & 0x18)+(i & 7)] = v & 255

    def bit_address(self,a):
        return ((0x20+(a >> 3),a & 7) if a < 128 else (a & 0xF8,a & 7))

    def read_bit(self,a):
        byte,bit = self.bit_address(a)
        return (self.read_direct(byte) >> bit) & 1

    def write_bit(self,a,v):
        byte,bit = self.bit_address(a)
        old = self.read_direct(byte)
        self.write_direct(byte,(old & ~(1 << bit)) | ((v & 1) << bit))

    def push(self,v):
        self.sp = (self.sp + 1) & 255
        self.iram[self.sp] = v & 255

    def pop(self):
        value = self.iram[self.sp]
        self.sp = (self.sp - 1) & 255
        return value

    def push_return(self,address):
        self.push(address & 255)
        self.push(address >> 8)
        self.call_depth += 1

    def ret(self):
        high = self.pop()
        low = self.pop()
        self.pc = (high << 8) | low
        self.call_depth -= 1

    def read_xdata(self,a):
        a &= 65535
        if self.xdata is None:
            raise ExecutionError(f"No explicit XDATA fixture for read {a:04X}")
        value = self.xdata.read(a) if hasattr(self.xdata,"read") else self.xdata[a]
        self.events.append(("xread",a,value,self.pc if self._active_pc is None else self._active_pc))
        return value

    def write_xdata(self,a,v):
        a, v = a & 65535,v & 255
        if self.xdata is None:
            raise ExecutionError(f"No explicit XDATA fixture for write {a:04X}")
        if hasattr(self.xdata,"write"):
            self.xdata.write(a,v)
        else:
            self.xdata[a] = v
        self.events.append(("xwrite",a,v,self.pc if self._active_pc is None else self._active_pc))

    def _alu_operand(self,op,b):
        mode = op & 15
        if mode == 4:
            return b
        if mode == 5:
            return self.read_direct(b)
        if mode < 8:
            return self.iram[self.r(mode & 1)]
        return self.r(mode & 7)

    def _set_flags_arith(self,a,b,carry,subtract=False):
        if subtract:
            result = a-b-carry
            cy = result < 0
            ac = (a & 15) < (b & 15)+carry
            ov = bool((a ^ b) & (a ^ result) & 128)
        else:
            result = a+b+carry
            cy = result > 255
            ac = (a & 15)+(b & 15)+carry > 15
            ov = bool((~(a ^ b)) & (a ^ result) & 128)
        self.psw = (self.psw & ~(0x80|0x40|0x04)) | (int(cy)<<7) | (int(ac)<<6) | (int(ov)<<2)
        self.a = result

    def _update_parity(self):
        p = self.a.bit_count() & 1
        self.psw = (self.psw & ~1) | p

    def step(self):
        self._active_pc = self.pc
        try:
            return self._step()
        finally:
            self._active_pc = None

    def _step(self):
        at = self.pc
        self.trace.append(at)
        self.steps += 1
        if at in self.hooks:
            self.events.append(("hook",at))
            self.hooks[at](self)
            self._update_parity()
            return
        ins = decode(self.code,at)
        op = ins.raw[0]
        b = ins.raw[1] if ins.size > 1 else 0
        c = ins.raw[2] if ins.size > 2 else 0
        self.pc = ins.next
        if op & 31 in (1,17):
            if op & 16:
                self.push_return(self.pc)
            self.pc = ins.targets[0]
        elif op in (2,18):
            if op == 18:
                self.push_return(self.pc)
            self.pc = ins.targets[0]
        elif op in (0x22,0x32):
            self.ret()
            if op == 0x32:
                self.events.append(("reti_no_interrupt_controller",at))
        elif op in (0x10,0x20,0x30):
            bit = self.read_bit(b)
            yes = not bit if op == 0x30 else bool(bit)
            if yes:
                if op == 0x10:
                    self.write_bit(b,0)
                self.pc = ins.targets[0]
        elif op in (0x40,0x50,0x60,0x70,0x80):
            # Evaluate only this instruction's condition. An eager dictionary
            # reads both ACC and PSW multiple times even for unconditional
            # SJMP, causing spurious effects through SFR-read fixtures.
            if op == 0x40:
                yes = bool(self.cy)
            elif op == 0x50:
                yes = not self.cy
            elif op == 0x60:
                yes = self.a == 0
            elif op == 0x70:
                yes = self.a != 0
            else:
                yes = True
            if yes:
                self.pc = ins.targets[0]
        elif op == 0xD5:
            value = (self.read_direct(b)-1) & 255
            self.write_direct(b,value)
            if value:
                self.pc = ins.targets[0]
        elif 0xD8 <= op <= 0xDF:
            value = (self.r(op & 7)-1) & 255
            self.set_r(op & 7,value)
            if value:
                self.pc = ins.targets[0]
        elif 0xB4 <= op <= 0xBF:
            if op == 0xB4:
                left,right=self.a,b
            elif op == 0xB5:
                left,right=self.a,self.read_direct(b)
            elif op < 0xB8:
                left,right=self.iram[self.r(op&1)],b
            else:
                left,right=self.r(op&7),b
            self.cy = int(left < right)
            if left != right:
                self.pc = ins.targets[0]
        elif op == 0x00:
            pass
        elif op == 0xA5:
            raise ExecutionError(f"Reserved opcode A5 at {at:04X}; vendor extensions not guessed")
        elif op in (0x03,0x13,0x23,0x33):
            old,carry=self.a,self.cy
            if op == 0x03:
                self.a = (old >> 1) | (old << 7)
            elif op == 0x13:
                self.a = (old >> 1) | (carry << 7)
                self.cy = old & 1
            elif op == 0x23:
                self.a = (old << 1) | (old >> 7)
            else:
                self.a = (old << 1) | carry
                self.cy = old >> 7
        elif op == 0x73:
            self.pc = (self.dptr+self.a) & 65535
        elif op == 0x83:
            self.a = self.code[(self.pc+self.a)&65535]
        elif op == 0x93:
            self.a = self.code[(self.dptr+self.a)&65535]
        elif op == 0x84:
            a,bv=self.a,self.b
            self.cy = 0
            if bv:
                self.a,self.b = divmod(a,bv)
                self.psw &= ~4
            else:
                self.psw |= 4
                self.events.append(("undefined_divide_zero",at))
                # A and B are architecturally undefined. Continuing with the
                # previous deterministic values can falsely validate a path.
                raise ExecutionError(f"DIV AB with B=0 at {at:04X}: undefined result")
        elif op == 0xA4:
            product=self.a*self.b
            self.a,self.b=product & 255,product >> 8
            self.psw=(self.psw & ~(0x80|4)) | (4 if product > 255 else 0)
        elif op == 0xA3:
            self.dptr=(self.dptr+1) & 65535
        elif op in (0xB3,0xC3,0xD3):
            self.cy=1-self.cy if op==0xB3 else int(op==0xD3)
        elif op == 0xC4:
            self.a=(self.a << 4) | (self.a >> 4)
        elif op == 0xD4:
            value=self.a
            carry=self.cy
            if (value & 15) > 9 or self.psw & 0x40:
                value += 6
            if value > 0x9F or carry:
                value += 0x60
            self.a=value
            self.cy=int(bool(carry) or value > 255)
        elif op in (0xE4,0xF4):
            self.a=0 if op==0xE4 else self.a ^ 255
        elif (op & 0xF0) in (0,0x10) and (op & 15) >= 4:
            delta=1 if op < 0x10 else -1
            mode=op & 15
            if mode==4:
                self.a+=delta
            elif mode==5:
                self.write_direct(b,self.read_direct(b)+delta)
            elif mode < 8:
                ptr=self.r(mode & 1)
                self.iram[ptr]=(self.iram[ptr]+delta) & 255
            else:
                self.set_r(mode & 7,self.r(mode & 7)+delta)
        elif (op & 0xF0) in (0x20,0x30,0x40,0x50,0x60,0x90) and (op & 15) >= 4:
            value=self._alu_operand(op,b)
            mode=op & 0xF0
            if mode in (0x20,0x30,0x90):
                self._set_flags_arith(self.a,value,self.cy if mode in (0x30,0x90) else 0,mode==0x90)
            else:
                self.a={0x40:lambda x,y:x|y,0x50:lambda x,y:x&y,0x60:lambda x,y:x^y}[mode](self.a,value)
        elif op in (0x42,0x43,0x52,0x53,0x62,0x63):
            value=self.a if op & 1==0 else c
            old=self.read_direct(b)
            self.write_direct(b,{4:lambda x,y:x|y,5:lambda x,y:x&y,6:lambda x,y:x^y}[op>>4](old,value))
        elif op in (0x72,0x82,0xA0,0xA2,0xB0,0x92):
            if op==0x92:
                self.write_bit(b,self.cy)
            else:
                value=self.read_bit(b)
                if op in (0xA0,0xB0):
                    value=1-value
                self.cy=self.cy|value if op in (0x72,0xA0) else self.cy&value if op in (0x82,0xB0) else value
        elif op in (0x74,0x75,0x76,0x77) or 0x78 <= op <= 0x7F:
            if op==0x74:
                self.a=b
            elif op==0x75:
                self.write_direct(b,c)
            elif op < 0x78:
                self.iram[self.r(op & 1)]=b
            else:
                self.set_r(op & 7,b)
        elif op==0x85:
            self.write_direct(c,self.read_direct(b))
        elif op in (0x86,0x87) or 0x88 <= op <= 0x8F:
            self.write_direct(b,self.iram[self.r(op & 1)] if op < 0x88 else self.r(op & 7))
        elif op==0x90:
            self.dptr=(b << 8)|c
        elif op in (0xA6,0xA7) or 0xA8 <= op <= 0xAF:
            value=self.read_direct(b)
            if op < 0xA8:
                self.iram[self.r(op & 1)]=value
            else:
                self.set_r(op & 7,value)
        elif op in (0xB2,0xC2,0xD2):
            self.write_bit(b,1-self.read_bit(b) if op==0xB2 else int(op==0xD2))
        elif op==0xC0:
            # PUSH increments SP before reading the direct source; PUSH SP
            # therefore pushes the incremented value (unlike self.push(v)).
            self.sp=(self.sp+1)&255
            self.iram[self.sp]=self.read_direct(b)
        elif op==0xD0:
            # POP SP writes popped value after decrementing SP, per 8051 order.
            value=self.pop()
            self.write_direct(b,value)
        elif op in (0xC5,0xC6,0xC7) or 0xC8 <= op <= 0xCF:
            old=self.a
            if op==0xC5:
                self.a=self.read_direct(b)
                self.write_direct(b,old)
            elif op < 0xC8:
                ptr=self.r(op & 1)
                self.a=self.iram[ptr]
                self.iram[ptr]=old
            else:
                self.a=self.r(op & 7)
                self.set_r(op & 7,old)
        elif op in (0xD6,0xD7):
            ptr=self.r(op & 1)
            old=self.iram[ptr]
            self.iram[ptr]=(old & 0xF0)|(self.a & 15)
            self.a=(self.a & 0xF0)|(old & 15)
        elif op in (0xE0,0xE2,0xE3,0xF0,0xF2,0xF3):
            ptr=self.dptr if op & 15==0 else (self.read_direct(0xA0)<<8)|self.r(op & 1)
            if op < 0xF0:
                self.a=self.read_xdata(ptr)
            else:
                self.write_xdata(ptr,self.a)
        elif op in (0xE5,0xE6,0xE7) or 0xE8 <= op <= 0xEF:
            self.a=self.read_direct(b) if op==0xE5 else self.iram[self.r(op & 1)] if op < 0xE8 else self.r(op & 7)
        elif op in (0xF5,0xF6,0xF7) or 0xF8 <= op <= 0xFF:
            if op==0xF5:
                self.write_direct(b,self.a)
            elif op < 0xF8:
                self.iram[self.r(op & 1)]=self.a
            else:
                self.set_r(op & 7,self.a)
        else:
            raise ExecutionError(f"Unhandled opcode {op:02X} at {at:04X}")
        self._update_parity()

    def run(self, entry=None, *, stop=(), max_steps=100000):
        if entry is not None:
            self.pc=entry & 65535
        stop=set(stop)
        before=self.steps
        while self.pc not in stop:
            if self.steps-before >= max_steps:
                last="\n".join(str(decode(self.code,p)) for p in self.trace[-12:])
                raise ExecutionError(f"Step limit {max_steps}, PC {self.pc:04X}\n{last}")
            self.step()
        return self

    def call(self, entry, *, sentinel=0xFFF0, max_steps=100000, stop=()):
        self.push_return(sentinel)
        return self.run(entry,stop=set(stop)|{sentinel},max_steps=max_steps)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Offline 8051 disassembler; no device IO")
    ap.add_argument("image")
    ap.add_argument("start",type=lambda x:int(x,0))
    ap.add_argument("end",type=lambda x:int(x,0))
    ap.add_argument("--layout", choices=("ph8057", "cpu"))
    a=ap.parse_args()
    for ins in disassemble(load_code(a.image, layout=a.layout),a.start,a.end):
        print(ins)
