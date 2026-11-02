"""Generate PH8057 v8 research hook wrappers; OFFLINE bytes only.

All addresses are CPU CODE addresses. This module has no device access and
does not write a firmware image. Caller integrates returned exact-byte patches.

The capture core ABI is R7=accepted ATA Status, R5=accepted ATA Error,
R4=path-kind (1 non-data, 2 PIO-in, 3 PIO-out, 4 main DMA, 5 alternate DMA).
Core may clobber A/B/R0..R7/DPTR/flags but MUST preserve PSW bank-select bits.
Both DPTR pairs, DPS, all current-bank registers, IE, A/B/PSW are preserved
around core. Interrupt masking serializes CPU access only, not SATA MMIO.
"""

CAPTURE_CORE = 0xE800
ACTIVE_RESULT_VALID = 0x4E07
SYMBOLS = {
    "capture_nondata": 0xED00,
    "capture_pio_in": 0xEE00,
    "capture_pio_out": 0xEF00,
    "capture_dma": 0xF000,
    "capture_dma_alt": 0xF100,
    "native_ata_sense_code": 0xF200,
}


class Bytes:
    def __init__(self):
        self.data = bytearray()
        self.labels = {}
        self.fixups = []

    def emit(self, *values):
        self.data.extend(values)

    def label(self, name):
        if name in self.labels:
            raise ValueError(f"Duplicate label: {name}")
        self.labels[name] = len(self.data)

    def branch(self, opcode, operands, target):
        self.emit(opcode, *operands, 0)
        self.fixups.append((len(self.data)-1, target))

    def finish(self):
        for pos, target in self.fixups:
            rel = self.labels[target] - (pos+1)
            if not -128 <= rel <= 127:
                raise ValueError(f"Branch to {target} is out of range")
            self.data[pos] = rel & 255
        return bytes(self.data)


def frame_save(out):
    # 17 saved bytes. Preserve original A before using it to save banked Rn.
    out.emit(0xC0,0xA8, 0xC2,0xAF, 0xC0,0xE0)
    for direct in (0xD0,0xF0,0x82,0x83,0x84,0x85,0x86):
        out.emit(0xC0,direct)
    for register in range(8):
        out.emit(0xE8+register, 0xC0,0xE0)
    # The explicit dual-DPTR model uses DPS bit0; core always enters on DPTR0.
    out.emit(0x75,0x86,0x00)


def frame_restore(out):
    for register in reversed(range(8)):
        out.emit(0xD0,0xE0, 0xF8+register)
    for direct in (0x86,0x85,0x84,0x83,0x82,0xF0,0xD0,0xE0,0xA8):
        out.emit(0xD0,direct)


def call(out, target):
    out.emit(0x12,target >> 8,target & 255)


def accepted_mmio_args(out):
    # Stock data callbacks use SFR B9 and XDATA7097, not working4B31/32.
    out.emit(0xAF,0xB9, 0x90,0x70,0x97, 0xE0, 0xFD)


def build_bodies(capture_core=CAPTURE_CORE):
    bodies = {}

    out = Bytes()
    frame_save(out)
    # At9837 R6:R7 still points at the exact just-completed taskfile.
    # Read Status/Error already written by9824..9836; do not reread B9.
    out.emit(0xEF,0x24,0x0D,0xF5,0x82,0xE4,0x3E,0xF5,0x83,
             0xE0,0xFF,0xA3,0xE0,0xFD,0x7C,0x01)
    call(out,capture_core)
    frame_restore(out)
    out.emit(0xCF,0xEB,0xCF,0x22)  # exact displaced9837 instructions +RET
    bodies["capture_nondata"] = out.finish()

    out = Bytes()
    frame_save(out)
    out.emit(0x90,0x63,0x46,0xE0)
    out.branch(0x20,(0xE5,),"transport_error")
    out.emit(0x90,0x4B,0x31,0xE0,0xFF,0xA3,0xE0,0xFD,0x7C,0x02)
    call(out,capture_core)
    out.branch(0x80,(),"restore")
    out.label("transport_error")
    #82B8 forces native sense29 for6346.bit5. Never attach an ATA snapshot
    #to that transport-origin failure, even if native ATA mapper also says29.
    out.emit(0x90,ACTIVE_RESULT_VALID >> 8,ACTIVE_RESULT_VALID & 255,0xE4,0xF0)
    out.label("restore")
    frame_restore(out)
    call(out,0x82B8)
    out.emit(0x22)
    bodies["capture_pio_in"] = out.finish()

    for name,kind,original_call in (
        ("capture_pio_out",3,0xB3C4),
        ("capture_dma",4,None),
        ("capture_dma_alt",5,None),
    ):
        out = Bytes()
        frame_save(out)
        accepted_mmio_args(out)
        out.emit(0x7C,kind)
        call(out,capture_core)
        frame_restore(out)
        if original_call is not None:
            call(out,original_call)
        else:
            # Four-byte accepted-D2H test prefix is replaced with LCALL+NOP.
            # Its result A is restored exactly before returning to stock FF.
            out.emit(0xE5,0xB9,0x54,0xE1)
        out.emit(0x22)
        bodies[name] = out.finish()

    # Pure mapping of the original AA9F policy: returns native sense index A.
    # Input R7=status,R5=error; no writes to pending sense, transport or XDATA.
    # Clobbers A and parity only; preserves input regs, carry and other flags.
    out = Bytes()
    out.emit(0xEF)
    out.branch(0x20,(0xE7,),"sense32")
    out.branch(0x20,(0xE5,),"sense26")
    out.branch(0x30,(0xE0,),"sense00")
    out.emit(0xED)
    for bit,code in ((7,0x29),(6,0x13),(5,0x20),(4,0x1B),(3,0x27),(1,0x0E),(2,0x04)):
        out.branch(0x20,(0xE0+bit,),f"sense{code:02X}")
    out.emit(0x74,0x36,0x22)
    for code in (0x32,0x26,0x00,0x29,0x13,0x20,0x1B,0x27,0x0E,0x04):
        out.label(f"sense{code:02X}")
        out.emit(0x74,code,0x22)
    bodies["native_ata_sense_code"] = out.finish()

    for name,body in bodies.items():
        if len(body) > 0x100:
            raise ValueError(f"Capture wrapper exceeds allocated page: {name}")
    return bodies


HOOKS = (
    (0x9837,"cfebcf","capture_nondata",3),
    (0x970D,"1282b8","capture_pio_in",3),
    (0xB37B,"12b3c4","capture_pio_out",3),
    (0x735F,"e5b954e1","capture_dma",4),
    (0x9EB2,"e5b954e1","capture_dma_alt",4),
)


def build_patches(stock_code, capture_core=CAPTURE_CORE):
    if len(stock_code)!=65536:
        raise ValueError("Expected exactly65536 bytes ofCPU CODE")
    bodies = build_bodies(capture_core)
    changes = []
    for cpu,expected,name,length in HOOKS:
        old = bytes.fromhex(expected)
        if stock_code[cpu:cpu+length] != old:
            raise ValueError(f"Wrong original hook {name} at CPU {cpu:04X}")
        target = SYMBOLS[name]
        new = bytes((0x12,target >> 8,target & 255))+bytes(length-3)
        changes.append({"cpu":f"{cpu:04X}","old":old.hex(),"new":new.hex()})
    for name,body in bodies.items():
        cpu = SYMBOLS[name]
        expected = stock_code[cpu:cpu+len(body)]
        if expected != bytes(len(body)):
            raise ValueError(f"Nonempty candidate cave {name} at CPU {cpu:04X}")
        changes.append({"cpu":f"{cpu:04X}","old":expected.hex(),"new":body.hex()})
    return changes

