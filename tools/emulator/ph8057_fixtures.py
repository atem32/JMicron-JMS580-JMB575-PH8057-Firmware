"""Explicit instruction-fixture assumptions for PH8057 offline testing.

These classes are NOT a model of the complete controller. They implement only
the named contract needed by stock instruction sequences. No hardware IO.
"""
from mcs51 import CPU


class DualDPTRCPU(CPU):
    """Fixture: SFR86.bit0 selects82/83 or84/85 for DPTR opcodes.

    Direct SFR82/83 and84/85 reads/writes always address their named bank.
    This is the behavior required by the stock800A copy sequence; no additional
    DPS register functions, automatic increment or vendor semantics are assumed.
    """
    @property
    def dptr(self):
        base=0x84 if self.read_direct(0x86)&1 else 0x82
        return self.read_direct(base)|(self.read_direct(base+1)<<8)

    @dptr.setter
    def dptr(self,value):
        base=0x84 if self.read_direct(0x86)&1 else 0x82
        self.write_direct(base,value)
        self.write_direct(base+1,value>>8)
