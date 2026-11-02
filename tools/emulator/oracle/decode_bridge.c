/* Host-only adapter for independent decoder comparison; no target execution. */
#include <string.h>
#include "emu8051.h"
void disasm_setptrs(struct em8051 *cpu);

int emu8051_decode_bytes(unsigned op, unsigned b1, unsigned b2,
                         unsigned pc, char *out)
{
    static unsigned char code[65536];
    static struct em8051 cpu;
    static int initialized;
    if (!initialized) {
        memset(&cpu, 0, sizeof cpu);
        cpu.mCodeMem = code;
        cpu.mCodeMemMaxIdx = 65535;
        disasm_setptrs(&cpu);
        initialized = 1;
    }
    code[pc & 65535] = op;
    code[(pc + 1) & 65535] = b1;
    code[(pc + 2) & 65535] = b2;
    return cpu.dec[op & 255](&cpu, (uint16_t)pc, out);
}
