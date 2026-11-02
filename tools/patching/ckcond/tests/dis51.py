from pathlib import Path
import sys

TABLE = [None] * 256
def add(op, fmt, n=1): TABLE[op] = (fmt, n)
for op,fmt,n in [
(0x00,'NOP',1),(0x02,'LJMP {w}',3),(0x03,'RR A',1),(0x04,'INC A',1),(0x05,'INC {d}',2),
(0x10,'JBC {d},{r3}',3),(0x12,'LCALL {w}',3),(0x13,'RRC A',1),(0x14,'DEC A',1),(0x15,'DEC {d}',2),
(0x20,'JB {d},{r3}',3),(0x22,'RET',1),(0x23,'RL A',1),(0x24,'ADD A,#{d}',2),(0x25,'ADD A,{d}',2),
(0x30,'JNB {d},{r3}',3),(0x32,'RETI',1),(0x33,'RLC A',1),(0x34,'ADDC A,#{d}',2),(0x35,'ADDC A,{d}',2),
(0x40,'JC {r2}',2),(0x42,'ORL {d},A',2),(0x43,'ORL {d},#{e}',3),(0x44,'ORL A,#{d}',2),(0x45,'ORL A,{d}',2),
(0x50,'JNC {r2}',2),(0x52,'ANL {d},A',2),(0x53,'ANL {d},#{e}',3),(0x54,'ANL A,#{d}',2),(0x55,'ANL A,{d}',2),
(0x60,'JZ {r2}',2),(0x62,'XRL {d},A',2),(0x63,'XRL {d},#{e}',3),(0x64,'XRL A,#{d}',2),(0x65,'XRL A,{d}',2),
(0x70,'JNZ {r2}',2),(0x72,'ORL C,{d}',2),(0x73,'JMP @A+DPTR',1),(0x74,'MOV A,#{d}',2),(0x75,'MOV {d},#{e}',3),
(0x80,'SJMP {r2}',2),(0x82,'ANL C,{d}',2),(0x83,'MOVC A,@A+PC',1),(0x84,'DIV AB',1),(0x85,'MOV {e},{d}',3),
(0x90,'MOV DPTR,#{w}',3),(0x92,'MOV {d},C',2),(0x93,'MOVC A,@A+DPTR',1),(0x94,'SUBB A,#{d}',2),(0x95,'SUBB A,{d}',2),
(0xA0,'ORL C,/{d}',2),(0xA2,'MOV C,{d}',2),(0xA3,'INC DPTR',1),(0xA4,'MUL AB',1),(0xA5,'RESERVED',1),
(0xB0,'ANL C,/{d}',2),(0xB2,'CPL {d}',2),(0xB3,'CPL C',1),(0xB4,'CJNE A,#{d},{r3}',3),(0xB5,'CJNE A,{d},{r3}',3),
(0xC0,'PUSH {d}',2),(0xC2,'CLR {d}',2),(0xC3,'CLR C',1),(0xC4,'SWAP A',1),(0xC5,'XCH A,{d}',2),
(0xD0,'POP {d}',2),(0xD2,'SETB {d}',2),(0xD3,'SETB C',1),(0xD4,'DA A',1),(0xD5,'DJNZ {d},{r3}',3),
(0xE0,'MOVX A,@DPTR',1),(0xE2,'MOVX A,@R0',1),(0xE3,'MOVX A,@R1',1),(0xE4,'CLR A',1),(0xE5,'MOV A,{d}',2),
(0xF0,'MOVX @DPTR,A',1),(0xF2,'MOVX @R0,A',1),(0xF3,'MOVX @R1,A',1),(0xF4,'CPL A',1),(0xF5,'MOV {d},A',2),
]: add(op,fmt,n)
for k in range(8):
    add(0x01+32*k,'AJMP {a}',2); add(0x11+32*k,'ACALL {a}',2)
for base,fmt,n in [(0x06,'INC @R{k}',1),(0x16,'DEC @R{k}',1),(0x26,'ADD A,@R{k}',1),(0x36,'ADDC A,@R{k}',1),(0x46,'ORL A,@R{k}',1),(0x56,'ANL A,@R{k}',1),(0x66,'XRL A,@R{k}',1),(0x76,'MOV @R{k},#{d}',2),(0x86,'MOV {d},@R{k}',2),(0x96,'SUBB A,@R{k}',1),(0xA6,'MOV @R{k},{d}',2),(0xB6,'CJNE @R{k},#{d},{r3}',3),(0xC6,'XCH A,@R{k}',1),(0xD6,'XCHD A,@R{k}',1),(0xE6,'MOV A,@R{k}',1),(0xF6,'MOV @R{k},A',1)]:
    for k in range(2): add(base+k,fmt.replace('{k}',str(k)),n)
for base,fmt,n in [(0x08,'INC R{k}',1),(0x18,'DEC R{k}',1),(0x28,'ADD A,R{k}',1),(0x38,'ADDC A,R{k}',1),(0x48,'ORL A,R{k}',1),(0x58,'ANL A,R{k}',1),(0x68,'XRL A,R{k}',1),(0x78,'MOV R{k},#{d}',2),(0x88,'MOV {d},R{k}',2),(0x98,'SUBB A,R{k}',1),(0xA8,'MOV R{k},{d}',2),(0xB8,'CJNE R{k},#{d},{r3}',3),(0xC8,'XCH A,R{k}',1),(0xD8,'DJNZ R{k},{r2}',2),(0xE8,'MOV A,R{k}',1),(0xF8,'MOV R{k},A',1)]:
    for k in range(8): add(base+k,fmt.replace('{k}',str(k)),n)
assert all(TABLE)
def decode(b,pc):
    op=b[pc]; fmt,n=TABLE[op]; d=b[(pc+1)&65535]; e=b[(pc+2)&65535]
    signed=lambda x:x-256 if x&128 else x
    fields={'d':f'{d:02X}','e':f'{e:02X}','w':f'{(d<<8)|e:04X}','a':f'{((pc+2)&0xF800)|((op&0xE0)<<3)|d:04X}','r2':f'{(pc+2+signed(d))&65535:04X}','r3':f'{(pc+3+signed(e))&65535:04X}'}
    return n,fmt.format(**fields)
def dump(b,start,end):
    pc=start
    while pc<end:
        n,t=decode(b,pc)
        print(f'{pc:04X} {b[pc:pc+n].hex(" ").upper():8} {t}')
        pc+=n
if __name__=='__main__':
    src=Path(__file__).resolve().parents[2]/'ph8057_v7/PH8057_FACTORY_COMPLETE_READBACK_DO_NOT_FLASH.bin'
    code=src.read_bytes()[0x1000:0x11000]
    for span in sys.argv[1:]:
        start,end=map(lambda s:int(s,16),span.split(':'))
        dump(code,start,end)
