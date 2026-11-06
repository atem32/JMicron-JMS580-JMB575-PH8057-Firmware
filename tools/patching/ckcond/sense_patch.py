"""CK_COND deferred descriptor-sense and per-LUN lifecycle bytecode generator.

Offline construction only. Does not access a device or write a firmware image.
The table at 4D00 and active state at 4E00 are explicit unqualified RAM
assumptions of the integrated candidate, not proven allocations.

Slot: valid A5, saved nonzero sense code, 14-byte ATA Return Descriptor.
The completion wrapper publishes valid only after the stock D8AC call.
"""
from dataclasses import dataclass
import json
from pathlib import Path


class Code:
    def __init__(self, base):
        self.base, self.data, self.symbols, self.fixups = base, bytearray(), {}, []

    @property
    def pc(self):
        return self.base + len(self.data)

    def label(self, name):
        if name in self.symbols:
            raise ValueError(name)
        self.symbols[name] = self.pc

    def emit(self, *values):
        self.data.extend(values)

    def raw(self, value):
        self.data.extend(bytes.fromhex(value))

    def abs(self, op, target):
        self.emit(op, 0, 0)
        self.fixups.append((len(self.data) - 2, 'abs', target))

    def rel(self, op, target, operand=None):
        self.emit(op)
        if operand is not None:
            self.emit(operand)
        self.emit(0)
        self.fixups.append((len(self.data) - 1, 'rel', target))

    def finish(self):
        out = bytearray(self.data)
        for offset, kind, target in self.fixups:
            dest = self.symbols[target] if isinstance(target, str) else target
            if kind == 'abs':
                out[offset:offset+2] = dest.to_bytes(2, 'big')
            else:
                disp = dest - (self.base + offset + 1)
                if not -128 <= disp <= 127:
                    raise ValueError(f'Branch out of range: {target}: {disp}')
                out[offset] = disp & 255
        return bytes(out)


def build_sense_patch(base=0xF300, slot_base=0x4D00, active_base=0x4E00):
    if slot_base & 255 or active_base & 255:
        raise ValueError('Tables must begin at a 256-byte page boundary')
    slot_hi, active_hi = slot_base >> 8, active_base >> 8
    if slot_base == active_base:
        raise ValueError('Slot table and active block must not overlap')
    c = Code(base)

    # The CALLER already supplied a normal function return address. Replace the
    # whole C320 entry with LJMP; E1F9 control-byte validation remains original.
    c.label('request_sense')
    c.abs(0x12, 0xE1F9)
    c.rel(0x50, 'sense_check')              # JNC: native validation accepted
    c.emit(0x22)
    c.label('sense_check')
    # Native991E/8000 uses ordinary DPS0 conventions. Under a different DPS
    # retain the entire stock path instead of accessing new state through it.
    c.raw('E5 86')
    c.rel(0x30, 'sense_dps_ok', 0xE0)
    c.abs(0x02, 0xC325)
    c.label('sense_dps_ok')
    c.raw('E5 5E C3 94 10')               # LUN must fit sixteen native slots
    c.rel(0x40, 'sense_lun_ok')
    c.abs(0x02, 0xC325)
    c.label('sense_lun_ok')
    c.raw('74 3A 25 5E F8 E6')            # native pending code into A
    c.rel(0x60, 'sense_fallback')          # zero pending may never expose data
    c.emit(0xFF)                          # R7 = current nonzero pending code
    c.raw('E5 5E C4 F5 82')
    c.emit(0x75, 0x83, slot_hi)
    c.emit(0xE0)
    c.rel(0xB4, 'sense_fallback', 0xA5)
    c.raw('A3 E0 6F')                     # saved sense code must match current
    c.rel(0x70, 'sense_fallback')
    c.rel(0x80, 'sense_build')
    c.label('sense_fallback')
    c.abs(0x02, 0xC325)                   # unchanged stock DESC/fixed handling
    c.label('sense_build')
    c.raw('E4 FF')
    c.abs(0x12, 0x991E)                   # native key/ASC/ASCQ mapping + clear
    c.raw('90 35 02 E0 90 35 01 F0')      # fixed key -> descriptor key
    c.raw('90 35 0C E0 90 35 02 F0')      # fixed ASC -> descriptor ASC
    c.raw('90 35 0D E0 90 35 03 F0')      # fixed ASCQ -> descriptor ASCQ
    c.raw('90 35 00 74 72 F0')
    c.raw('90 35 07 74 0E F0')
    c.raw('E5 5E C4 24 02 FF')            # offset of saved 14-byte descriptor
    # Unrolled standard-DPTR copy avoids dual-DPTR/EA/register ABI assumptions.
    # Native991E has already overwritten R7; C339 later replaces it with alloc.
    for offset in range(14):
        c.emit(0x8F, 0x82, 0x75, 0x83, slot_hi, 0xE0)
        c.emit(0x90, 0x35, 0x08 + offset, 0xF0, 0x0F)
    c.raw('75 5B 00 75 5C 16')
    c.abs(0x02, 0xC339)                   # native min(allocation,length), state

    # For each accepted BOT CBW: remove the old active-command context; preserve
    # a pending result only when the new opcode is REQUEST SENSE. Preserve PSW
    # before tail-calling native D896, whose no-map return otherwise keeps CY.
    c.label('admit_bot')
    c.raw('C0 D0 C0 86 75 86 00 C0 82 C0 83')
    c.abs(0x12, 'clear_active')
    c.emit(0x90, active_hi, 0, 0x74, 0xB0, 0xF0)
    c.raw('90 79 8F E0')
    c.rel(0xB4, 'admit_clear_slot', 0x03)
    c.rel(0x80, 'admit_finish')
    c.label('admit_clear_slot')
    c.raw('E5 5E C3 94 10')
    c.rel(0x50, 'admit_finish')
    c.raw('E5 5E C4 F5 82')
    c.emit(0x75, 0x83, slot_hi, 0xE4, 0xF0)
    c.label('admit_finish')
    c.raw('D0 83 D0 82 D0 86 D0 D0')
    c.abs(0x02, 0xD896)

    # D8AC is the common pending-sense setter. Invalidate on EVERY invocation,
    # including code28. A new valid descriptor is committed after D8AC returns.
    # The original function does not touch DPTR; this wrapper preserves it.
    c.label('sense_changed')
    c.raw('E5 5E C3 94 10')
    c.rel(0x50, 'sense_changed_finish')
    c.raw('C0 86 75 86 00 C0 82 C0 83 E5 5E C4 F5 82')
    c.emit(0x75, 0x83, slot_hi, 0xE4, 0xF0)
    c.raw('D0 83 D0 82 D0 86')
    c.label('sense_changed_finish')
    c.raw('E5 5E C3')                     # exact instructions replaced at D8AC
    c.abs(0x02, 0xD8AF)

    # Two original loops already enumerate sixteen pending sense entries.
    # Preserve DPTR because one loop increments a counter through that pointer.
    # Recreate MOV A,#3A; ADD A,R7 exactly, including arithmetic flags.
    c.label('reset_slot')
    c.raw('C0 86 75 86 00 C0 82 C0 83 EF C4 F5 82')
    c.emit(0x75, 0x83, slot_hi, 0xE4, 0xF0)
    c.emit(0xEF)
    c.rel(0x70, 'reset_slot_finish')
    c.abs(0x12, 'clear_active')             # only index0 performs the32-byte clear
    c.label('reset_slot_finish')
    c.raw('D0 83 D0 82 D0 86 74 3A 2F 22')

    c.label('reset_all')
    c.abs(0x12, 'clear_all')
    c.abs(0x02, 0xDAE3)                   # original BFB7 tail destination
    c.label('cold_init')
    c.abs(0x12, 'clear_all')
    c.abs(0x02, 0xC61C)                   # original8635 destination, SP already7F

    # Helper: clear active32 bytes, preserving every Rn (A/DPTR/flags scratch).
    c.label('clear_active')
    c.raw('ED C0 E0')                     # push active-bank R5 through ACC
    c.emit(0x90, active_hi, 0, 0x7D, 0x20, 0xE4)
    c.label('clear_active_loop')
    c.raw('F0 A3')
    c.rel(0xDD, 'clear_active_loop')
    c.raw('D0 E0 FD 22')

    # Helper: clear sixteen valid markers and active32. All caller registers,
    # both arithmetic flags and DPTR are restored; other slot bytes are retained
    # but unreachable until the completion code publishes a fresh valid marker.
    c.label('clear_all')
    c.raw('C0 D0 C0 E0 C0 86 75 86 00 C0 82 C0 83 EF C0 E0')
    c.emit(0x90, slot_hi, 0, 0x7F, 0x10)
    c.label('clear_all_loop')
    c.raw('E4 F0 E5 82 24 10 F5 82')
    c.rel(0xDF, 'clear_all_loop')
    c.abs(0x12, 'clear_active')
    c.raw('D0 E0 FF D0 83 D0 82 D0 86 D0 E0 D0 D0 22')

    code = c.finish()
    if base + len(code) > 0xFC00:
        raise ValueError('Sense code exceeds assigned F300..FBFF area')
    hooks = []
    for address, expected, kind, symbol, reason in [
        (0xC320, '12 E1 F9', 0x02, 'request_sense', 'deferred descriptor or native fixed sense'),
        (0x7C40, '12 D8 96', 0x12, 'admit_bot', 'invalidate previous command context at BOT admission'),
        (0xD8AC, 'E5 5E C3', 0x02, 'sense_changed', 'invalidate descriptor whenever pending sense changes'),
        (0x67B3, '74 3A 2F', 0x12, 'reset_slot', 'reset-loop descriptor invalidation'),
        (0x83DC, '74 3A 2F', 0x12, 'reset_slot', 'second reset-loop descriptor invalidation'),
        (0xBFB7, '02 DA E3', 0x02, 'reset_all', 'third reset lifecycle invalidation'),
        (0x8635, '02 C6 1C', 0x02, 'cold_init', 'initialize patch state after SP initialization'),
    ]:
        target = c.symbols[symbol]
        hooks.append({'address': address, 'expected': bytes.fromhex(expected).hex(),
                      'replacement': bytes([kind, target >> 8, target & 255]).hex(),
                      'symbol': symbol, 'reason': reason})
    hooks.append({'address': base, 'expected': bytes(len(code)).hex(),
                  'replacement': code.hex(), 'symbol': 'sense_code',
                  'reason': 'deferred sense and lifecycle candidate routines'})
    return {'base': base, 'end': base + len(code), 'symbols': c.symbols,
            'slot_base': slot_base, 'active_base': active_base, 'patches': hooks}


def apply_to_code(code, spec):
    out = bytearray(code)
    for patch in spec['patches']:
        address = patch['address']
        old, new = bytes.fromhex(patch['expected']), bytes.fromhex(patch['replacement'])
        if len(old) != len(new) or out[address:address + len(old)] != old:
            raise ValueError(f'Unexpected original bytes at {address:04X}')
        out[address:address + len(new)] = new
    return bytes(out)


if __name__ == '__main__':
    spec = build_sense_patch()
    print(json.dumps(spec, indent=2))
