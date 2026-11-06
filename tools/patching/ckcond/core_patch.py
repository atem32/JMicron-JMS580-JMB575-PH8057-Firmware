#!/usr/bin/env python3
"""CK_COND command state, command association and ATA result capture.

This is experimental code with explicit, unqualified XDATA and peripheral
assumptions. The builder is intentionally separate from any flash writer.
CPU code positions are not SPI offsets.
"""
from asm51 import Asm

ACTIVE = 0x4E00
SLOTS = 0x4D00
SYMBOLS = {
    'begin_wrapper': 0xE300,
    'launch_wrapper': 0xE500,
    'capture_core': 0xE800,
    'finalize_wrapper': 0xEA80,
    'owner_ok': 0xFC00,
    'ata_sense_map': 0xF200,
}


def read(a, address):
    a.emit(0x90, address >> 8, address & 255, 0xE0)


def write_const(a, address, value):
    a.emit(0x90, address >> 8, address & 255, 0x74, value, 0xF0)


def write_a(a, address):
    a.emit(0x90, address >> 8, address & 255, 0xF0)


def equal_jump(a, value, target):
    a.emit(0xB4, value, 3)
    a.jump(target)


def save(a):
    """17 bytes; preserve current register bank, both physical DPTRs and IE.

    IE is restored last. PSW bank bits are never modified. Direct 82..85 are
    the physical pointer SFRs; MOVX/MOVC/INC DPTR use the selected pointer.
    """
    a.hex('C0 A8 C2 AF')
    for d in (0xD0, 0xE0, 0xF0, 0x82, 0x83, 0x84, 0x85, 0x86):
        a.emit(0xC0, d)
    for r in range(8):
        a.emit(0xE8 + r, 0xC0, 0xE0)
    a.hex('75 86 00')


def restore(a):
    for r in reversed(range(8)):
        a.emit(0xD0, 0xE0, 0xF8 + r)
    for d in (0x86, 0x85, 0x84, 0x83, 0x82, 0xF0, 0xE0, 0xD0, 0xA8):
        a.emit(0xD0, d)


def block(a, limit):
    raw = a.resolve()
    if a.origin + len(raw) > limit:
        raise ValueError(f'Block {a.origin:04X} ends at {a.origin+len(raw):04X}, limit {limit:04X}')
    return a.origin, raw, dict(a.symbols)


def begin_block():
    a = Asm(SYMBOLS['begin_wrapper'])
    a.label('begin_wrapper')
    save(a)
    read(a, ACTIVE)
    a.cjne_a_imm(0xB0, 'begin_done', long=True)
    # Only admission from the real BOT parser can arm this patch.
    write_const(a, ACTIVE, 0)
    a.hex('E5 5E C3 94 10')
    a.jnc('begin_done', long=True)
    read(a, 0x798F)
    equal_jump(a, 0x85, 'begin_opcode_ok')
    a.cjne_a_imm(0xA1, 'begin_done', long=True)
    a.label('begin_opcode_ok')
    read(a, 0x7990)
    a.emit(0x54, 0x1E, 0xFF)  # A=wire protocol, retain in R7
    for proto in (0x06, 0x08, 0x0A, 0x0C, 0x0E, 0x14, 0x16):
        equal_jump(a, proto, 'begin_protocol_ok')
    a.jump('begin_done')
    a.label('begin_protocol_ok')
    a.hex('E5 5E')
    write_a(a, ACTIVE + 1)
    a.emit(0xEF)
    write_a(a, ACTIVE + 2)
    read(a, 0x4B48)
    a.emit(0x54, 0x20)
    write_a(a, ACTIVE + 3)
    read(a, 0x798F)
    a.cjne_a_imm(0x85, 'begin_12')
    read(a, 0x7990)
    a.emit(0x54, 1)
    a.jump('begin_extend')
    a.label('begin_12')
    a.emit(0xE4)
    a.label('begin_extend')
    write_a(a, ACTIVE + 4)
    read(a, 0x4B3B)
    write_a(a, ACTIVE + 5)
    write_const(a, ACTIVE + 6, 0)
    write_const(a, ACTIVE + 7, 0)
    # CBW tag is equality metadata only, never a generation counter.
    for i in range(4):
        read(a, 0x7984 + i)
        write_a(a, ACTIVE + 0x10 + i)
    write_const(a, ACTIVE, 0xA5)
    a.label('begin_done')
    restore(a)
    a.hex('90 79 90 22')  # exact displaced MOV DPTR,#7990; RET
    return block(a, 0xE500)


def owner_block():
    a = Asm(SYMBOLS['owner_ok'])
    a.label('owner_ok')
    read(a, ACTIVE)
    a.cjne_a_imm(0xA5, 'owner_bad', long=True)
    read(a, ACTIVE + 1)
    a.hex('65 5E')
    a.jnz('owner_bad', long=True)
    a.hex('E5 5E C3 94 10')
    a.jnc('owner_bad', long=True)
    read(a, 0x798F)
    equal_jump(a, 0x85, 'owner_cdb')
    a.cjne_a_imm(0xA1, 'owner_bad', long=True)
    a.label('owner_cdb')
    for i in range(4):
        read(a, 0x7984 + i)
        a.emit(0xF5, 0xF0)
        read(a, ACTIVE + 0x10 + i)
        a.emit(0x65, 0xF0)
        a.jnz('owner_bad', long=True)
    a.hex('D3 22')
    a.label('owner_bad')
    a.hex('C3 22')
    return block(a, 0xFD00)


# The return PCs distinguish known software launch paths, not hardware FIS
# ownership by themselves. A real BOT admission and original protocol/pointer
# checks are additional requirements.
LAUNCH_RETURNS = {
    0x0B90: (1, 0x4A1C),
    0xC7C5: (2, 0x4B24),
    0xC8F3: (3, 0x4B24),
    0xB2A8: (4, 0x4B24),
    0xC7AD: (4, 0x4B24),
    0x68F6: (5, 0x4B24),
    0x6901: (5, 0x4B24),
}


def launch_block():
    a = Asm(SYMBOLS['launch_wrapper'])
    a.label('launch_wrapper')
    save(a)
    # Every call through the common SATA launcher invalidates the old attempt.
    write_const(a, ACTIVE + 6, 0)
    write_const(a, ACTIVE + 7, 0)
    a.call(SYMBOLS['owner_ok'])
    a.jnc('launch_done', long=True)
    # Stack: 17 saved bytes above wrapper return (2), then original return.
    a.hex('E5 81 C3 94 13 F8 E6 FA 18 E6 FB')
    for n, (ret, (kind, ptr)) in enumerate(LAUNCH_RETURNS.items()):
        a.emit(0xEA)
        a.cjne_a_imm(ret >> 8, f'launch_next_{n}')
        a.emit(0xEB)
        a.cjne_a_imm(ret & 255, f'launch_next_{n}')
        a.emit(0x79, kind)
        a.jump('launch_route')
        a.label(f'launch_next_{n}')
    a.jump('launch_done')
    a.label('launch_route')
    a.emit(0xE9)
    a.cjne_a_imm(1, 'launch_data')
    a.emit(0xEE)
    a.cjne_a_imm(0x4A, 'launch_done', long=True)
    a.emit(0xEF)
    a.cjne_a_imm(0x1C, 'launch_done', long=True)
    read(a, ACTIVE + 2)
    a.cjne_a_imm(6, 'launch_done', long=True)
    a.hex('E5 29')
    a.cjne_a_imm(0x37, 'launch_done', long=True)
    # The host non-data lower operation returns to state3C. Reject internal
    # operations that happen to use the same 4A1C scratch structure.
    a.hex('E5 2C')
    a.jz('launch_done', long=True)
    a.hex('C3 94 05')
    a.jnc('launch_done', long=True)
    a.hex('E5 2C 24 48 F5 82 75 83 4A E0')
    a.cjne_a_imm(0x3C, 'launch_done', long=True)
    a.jump('launch_pointer_ok')
    a.label('launch_data')
    a.emit(0xEE)
    a.cjne_a_imm(0x4B, 'launch_done', long=True)
    a.emit(0xEF)
    a.cjne_a_imm(0x24, 'launch_done', long=True)
    read(a, ACTIVE + 2)
    a.emit(0xFC)  # R4=wire protocol
    a.emit(0xE9)
    a.cjne_a_imm(2, 'launch_not_pio_in')
    a.emit(0xEC)
    a.cjne_a_imm(8, 'launch_done', long=True)
    a.jump('launch_pointer_ok')
    a.label('launch_not_pio_in')
    a.cjne_a_imm(3, 'launch_dma')
    a.emit(0xEC)
    a.cjne_a_imm(0x0A, 'launch_done', long=True)
    a.jump('launch_pointer_ok')
    a.label('launch_dma')
    a.emit(0xEC)
    for p in (0x0C, 0x0E, 0x14, 0x16):
        equal_jump(a, p, 'launch_pointer_ok')
    a.jump('launch_done')
    a.label('launch_pointer_ok')
    # Match the command byte in the actual source taskfile, not only CDB.
    a.hex('EF 24 02 F5 82 EE 34 00 F5 83 E0 F5 F0')
    read(a, ACTIVE + 5)
    a.hex('65 F0')
    a.jnz('launch_done', long=True)
    a.hex('E5 2B C3 94 10')
    a.jnc('launch_done', long=True)
    a.hex('E5 2B')
    write_a(a, ACTIVE + 8)
    a.emit(0xE9)
    write_a(a, ACTIVE + 9)
    a.emit(0xEE)
    write_a(a, ACTIVE + 0x0A)
    a.emit(0xEF)
    write_a(a, ACTIVE + 0x0B)
    write_const(a, ACTIVE + 6, 0x5A)
    a.label('launch_done')
    restore(a)
    a.hex('90 4B C8 22')
    return block(a, 0xE800)


def slot_store(a):
    """Write A into slot byte R2 and increment R2 (page4D)."""
    a.hex('8A 82 75 83 4D F0 0A')


def check_port(a, bad):
    read(a, ACTIVE + 8)
    a.hex('65 2B')
    a.jnz(bad, long=True)
    read(a, 0x6312)
    a.emit(0xF5, 0xF0)
    read(a, ACTIVE + 8)
    a.hex('65 F0')
    a.jnz(bad, long=True)


def capture_block():
    a = Asm(SYMBOLS['capture_core'])
    a.label('capture_core')
    # Caller holds interrupts and preserves the complete register context.
    # R7=accepted Status, R5=accepted Error, R4=software completion path1..5.
    write_const(a, ACTIVE + 7, 0)
    a.call(SYMBOLS['owner_ok'])
    a.jnc('capture_done', long=True)
    read(a, ACTIVE + 6)
    a.cjne_a_imm(0x5A, 'capture_done', long=True)
    read(a, ACTIVE + 9)
    a.hex('6C')  # XRL A,R4
    a.jnz('capture_done', long=True)
    check_port(a, 'capture_done')
    read(a, 0x6302)
    a.emit(0xF5, 0xF0)
    read(a, ACTIVE + 5)
    a.hex('65 F0')
    a.jnz('capture_done', long=True)
    a.emit(0xEF)
    write_a(a, ACTIVE + 0x0C)
    a.emit(0xED)
    write_a(a, ACTIVE + 0x0D)
    # Invalidate this unpublished slot before changing its payload.
    a.hex('E5 5E C4 54 F0 FA E4')
    slot_store(a)
    a.emit(0xE4)
    slot_store(a)
    for value in (0x09, 0x0C):
        a.emit(0x74, value)
        slot_store(a)
    read(a, ACTIVE + 4)
    a.emit(0xFB)  # R3=EXTEND for high-order field gating
    slot_store(a)
    a.emit(0xED)
    slot_store(a)
    for n, (source, high) in enumerate(((0x6301, True), (0x6300, False),
                                      (0x6308, True), (0x6304, False),
                                      (0x6309, True), (0x6305, False),
                                      (0x630A, True), (0x6306, False),
                                      (0x6307, False))):
        if high:
            a.emit(0xEB)
            a.jz(f'capture_high_zero_{n}')
            read(a, source)
            a.jump(f'capture_field_{n}')
            a.label(f'capture_high_zero_{n}')
            a.emit(0xE4)
            a.label(f'capture_field_{n}')
        else:
            read(a, source)
        slot_store(a)
    a.emit(0xEF)
    slot_store(a)
    # Port/software provenance is checked on both sides of the register read.
    # This is not a claim that a CPU interrupt mask stops autonomous hardware.
    a.call(SYMBOLS['owner_ok'])
    a.jnc('capture_done', long=True)
    check_port(a, 'capture_done')
    write_const(a, ACTIVE + 7, 0xA5)
    a.label('capture_done')
    a.ret()
    return block(a, 0xEA80)


def finalize_block():
    a = Asm(SYMBOLS['finalize_wrapper'])
    a.label('finalize_wrapper')
    save(a)
    a.call(SYMBOLS['owner_ok'])
    a.jnc('final_done', long=True)
    a.hex('E5 59')
    equal_jump(a, 0x0D, 'final_done')  # native BOT phase-error path owns status
    read(a, ACTIVE + 7)
    a.cjne_a_imm(0xA5, 'final_done', long=True)
    read(a, ACTIVE + 0x0C)
    a.emit(0xFF, 0x54, 0x88)  # BSY/DRQ is not accepted terminal ATA status.
    a.jnz('final_done', long=True)
    read(a, ACTIVE + 0x0D)
    a.emit(0xFD)
    a.hex('E5 5A')
    a.cjne_a_imm(1, 'final_existing_failure')
    a.emit(0xEF, 0x54, 0xE1)
    a.cjne_a_imm(0x40, 'final_done', long=True)
    read(a, ACTIVE + 3)
    a.jz('final_done', long=True)
    a.emit(0x7F, 0x28)
    a.call(0xD8AC)
    a.emit(0x74, 0x28)
    a.jump('final_publish')
    a.label('final_existing_failure')
    a.cjne_a_imm(2, 'final_done', long=True)
    a.emit(0xEF, 0x54, 0x21)
    a.jnz('final_ata_error')
    a.emit(0xEF, 0x54, 0xE1)
    a.cjne_a_imm(0x40, 'final_done', long=True)
    read(a, ACTIVE + 3)
    a.jz('final_done', long=True)
    a.emit(0x74, 0x28)
    a.jump('final_compare')
    a.label('final_ata_error')
    a.call(SYMBOLS['ata_sense_map'])  # pure mapping, A=stock AA9F code
    a.jz('final_done', long=True)
    a.label('final_compare')
    a.emit(0xFB)  # R3=expected pending code
    a.hex('E5 5E 24 3A F8 E6 6B')
    a.jnz('final_done', long=True)
    a.emit(0xEB)
    a.label('final_publish')
    a.emit(0xFB)
    a.hex('E5 5E C4 54 F0 F5 82 75 83 4D A3 EB F0')
    a.hex('15 82 74 A5 F0')  # publish valid only after descriptor and code
    a.label('final_done')
    write_const(a, ACTIVE, 0)
    write_const(a, ACTIVE + 6, 0)
    write_const(a, ACTIVE + 7, 0)
    restore(a)
    a.hex('7E 79 7F 84 22')  # displaced MOV R6,#79;MOV R7,#84;RET
    return block(a, 0xED00)


def build_bodies():
    return [begin_block(), launch_block(), capture_block(), finalize_block(), owner_block()]


def build_patches(code):
    if len(code) != 65536:
        raise ValueError('Expected full 65536-byte CPU image')
    patches = []
    for address, data, _ in build_bodies():
        old = code[address:address + len(data)]
        if any(old):
            raise ValueError(f'Expected zero code-cave bytes at {address:04X}')
        patches.append({'cpu': address, 'old': old.hex(), 'new': data.hex()})
    hooks = (
        (0x229E, '90 79 90', SYMBOLS['begin_wrapper'], False),
        (0x8CA3, '90 4B C8', SYMBOLS['launch_wrapper'], False),
        (0x9503, '7E 79 7F 84', SYMBOLS['finalize_wrapper'], True),
    )
    for address, expected, target, pad in hooks:
        old = bytes.fromhex(expected)
        if code[address:address+len(old)] != old:
            raise ValueError(f'Hook bytes differ at {address:04X}')
        new = bytes((0x12, target >> 8, target & 255)) + (b'\0' if pad else b'')
        patches.append({'cpu': address, 'old': old.hex(), 'new': new.hex()})
    return patches


if __name__ == '__main__':
    for address, body, labels in build_bodies():
        print(f'{address:04X}..{address+len(body)-1:04X}: {len(body)} bytes')
