"""Minimal label-aware 8051 byte assembler for inspectable offline patches.

This is deliberately not a text-language parser. Encoding of emitted bytes
remains explicit; labels/fixups cannot silently truncate branch distances.
"""

class AssemblyError(ValueError):
    pass


class Asm:
    def __init__(self, origin=0):
        if not isinstance(origin,int) or not 0<=origin<=0xFFFF:
            raise AssemblyError('origin must be a 16-bit CPU address')
        self.origin=origin
        self.data=bytearray()
        self.symbols={}
        self.fixups=[]

    @property
    def pc(self):
        return self.origin+len(self.data)

    @property
    def address(self):
        return self.pc

    @property
    def offset(self):
        return len(self.data)

    def emit(self,*values):
        for value in values:
            if isinstance(value,(bytes,bytearray,list,tuple)):
                self.emit(*value)
            elif isinstance(value,int) and 0<=value<=255:
                self.data.append(value)
            else:
                raise AssemblyError(f'not a byte: {value!r}')
        if self.pc>0x10000:
            raise AssemblyError('assembled program exceeds 64 KiB CPU address space')
        return self

    def hex(self,text):
        return self.emit(bytes.fromhex(text))

    def label(self,name):
        if not isinstance(name,str) or not name:
            raise AssemblyError('label must be a nonempty string')
        if name in self.symbols:
            raise AssemblyError(f'duplicate label {name}')
        self.symbols[name]=self.pc
        return self

    def _abs16(self,op,target):
        self.emit(op)
        self.fixups.append(('abs16',len(self.data),target,None))
        return self.emit(0,0)

    def call(self,target):
        return self._abs16(0x12,target)

    def jump(self,target):
        return self._abs16(0x02,target)

    def branch(self,op,target,*prefix_operands):
        expected={0x10:1,0x20:1,0x30:1,0x40:0,0x50:0,0x60:0,0x70:0,0x80:0,0xD5:1}
        expected.update({x:1 for x in range(0xB4,0xC0)})
        expected.update({x:0 for x in range(0xD8,0xE0)})
        if op not in expected or len(prefix_operands)!=expected[op]:
            raise AssemblyError(f'invalid relative branch {op:02X} operand count')
        self.emit(op,*prefix_operands)
        self.fixups.append(('rel8',len(self.data),target,self.pc+1))
        return self.emit(0)

    def _conditional(self,op,target,long=False):
        if long:
            inverse={0x40:0x50,0x50:0x40,0x60:0x70,0x70:0x60}[op]
            self.emit(inverse,3)
            return self.jump(target)
        return self.branch(op,target)

    def jz(self,target,long=False): return self._conditional(0x60,target,long)
    def jnz(self,target,long=False): return self._conditional(0x70,target,long)
    def jc(self,target,long=False): return self._conditional(0x40,target,long)
    def jnc(self,target,long=False): return self._conditional(0x50,target,long)
    def jz_long(self,target): return self.jz(target,True)
    def jnz_long(self,target): return self.jnz(target,True)
    def jc_long(self,target): return self.jc(target,True)
    def jnc_long(self,target): return self.jnc(target,True)
    long_jz=jz_long
    long_jnz=jnz_long
    long_jc=jc_long
    long_jnc=jnc_long

    def cjne_a_imm(self,imm,target,long=False):
        return self._cjne(0xB4,imm,target,long)

    def cjne_r_imm(self,r,imm,target,long=False):
        if not isinstance(r,int) or not 0<=r<=7:
            raise AssemblyError('register must be 0..7')
        return self._cjne(0xB8+r,imm,target,long)

    def _cjne(self,op,imm,target,long):
        if long:
            # Unequal: skip SJMP and execute LJMP; equal: skip LJMP.
            self.emit(op,imm,2,0x80,3)
            return self.jump(target)
        return self.branch(op,target,imm)

    def ret(self): return self.emit(0x22)
    def nop(self): return self.emit(0)

    def resolve(self):
        out=bytearray(self.data)
        for kind,offset,target,base in self.fixups:
            if isinstance(target,str):
                if target not in self.symbols:
                    raise AssemblyError(f'undefined label {target}')
                address=self.symbols[target]
            elif isinstance(target,int):
                address=target
            else:
                raise AssemblyError(f'invalid target {target!r}')
            if not 0<=address<=0xFFFF:
                raise AssemblyError(f'target outside 16-bit CPU address space: {address!r}')
            if kind=='abs16':
                out[offset:offset+2]=address.to_bytes(2,'big')
            else:
                # No implicit modulo wrap: crossing image end is disallowed.
                rel=address-base
                if not -128<=rel<=127:
                    raise AssemblyError(f'relative branch at {base-1:04X} to {address:04X} out of range: {rel}')
                out[offset]=rel&255
        return bytes(out)
