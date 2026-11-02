# Authorship, provenance and distribution scope

The project-specific patch builders, emulator, test fixtures and historical research were supplied by the project owner as the output of the PH8057 investigation and are consolidated here with independent corrections. Historical file hashes are preserved. The archive does not independently certify every earlier author's identity or acquisition chain; it provides traceable supplied-source provenance instead of attributing vendor work to this project.

The project license covers project-authored contributions only. Proprietary firmware, board design, private register definitions and vendor names remain their respective owners' material. A checksum is an identity, not a redistribution permission. All original, donor and modified full BIN files are omitted from the public package. Modified full images still contain vendor code and are therefore retained only in the separately supplied private research archive.

## Included external source

`tools/emulator/oracle/emu8051_disasm.c` and `emu8051.h` come from Jari Komppa's [emu8051](https://github.com/jarikomppa/emu8051). Existing source copyright notices are retained, and its MIT LICENSE is included verbatim in that directory. Source headers and the current repository LICENSE carry different historical years; neither notice was rewritten. `decode_bridge.c` is the project's small historical test adapter. The decoder, header and adapter were already present in the supplied v5/v6 material. This consolidation independently fetched the pinned upstream disassembler and verified an exact source match, and independently checked the current upstream license.

The bundled upstream decoder was independently compared with the project's decoder on 20,480 opcode/operand/address samples. It is a **disassembly oracle only**. This project neither imports nor treats the upstream execution core as an authoritative silicon model. Reserved opcode A5 is explicitly excluded from mnemonic equivalence because that external decoder renders it as NOP.

## Referenced projects, not ported or vendored

| Project / author | License inspected | Use and limit |
|---|---|---|
| [9500/ds500u3-jms567-uas](https://github.com/9500/ds500u3-jms567-uas), 9500 | MIT, copyright 2026, explicitly scoped to authored scripts/docs and excluding its vendor-derived firmware | Read as a JMS567/JMB575 UAS research precedent; no patch or firmware transplanted |
| [projectgus/jms567ctl](https://github.com/projectgus/jms567ctl), Angus Gratton | BSD-3-Clause, copyright 2023 | Historical protocol/tool reference; not shipped or executed against a device |
| [xx25/jms567settings](https://github.com/xx25/jms567settings), contributors and attributed Angus Gratton portions | BSD-3-Clause in actual LICENSE | Settings-layout reference; does not establish PH8057 private registers |
| [BertoldVdb/jms578flash](https://github.com/BertoldVdb/jms578flash) | MIT | Different-controller flashing research; not a PH8057 recovery qualification or supplied flasher |
| [Zibri/JMS579](https://github.com/Zibri/JMS579) | No redistribution license identified in the inspected root/tree | Link only; no source copied |
| Linux libata / USB source | Kernel licensing retained by upstream; inspected files not redistributed here | Primary protocol implementation comparison, not code imported into this project |

Actual license files were read; a hosting service's `NOASSERTION` metadata was not treated as the license. The 9500 source snapshot inspected was commit `743529e7a29febf501cc187b96f3691905ed3245`. Its MIT grant cannot authorize redistribution of JMS567 or JMS580 firmware. The emu8051 upstream commit checked was `5dc681275151c4a5d7b85ec9ff4ceb1b25abd5a8`; the exact bundled source hashes are separately recorded.

## Public/private split

The public release includes current project sources, small guarded instruction replacement records, redacted OEM interpretation, hashes, bounded transaction excerpts, primary-source links and tests. It excludes full vendor CODE/BIN/OEM dumps, raw disk-sector backups, unredacted device logs, original nested archives and external specification PDFs. The full private package preserves those supplied research materials and clearly separates downloaded reference identities/license notices from user-supplied evidence. Newly downloaded specifications are identified by URLs and hashes rather than redistributed as full PDFs.

The factory serial payload at OEM `056..077` is redacted in every public byte table and decoded view. Original full images necessarily retain that payload privately. Product-level VID/PID and model strings are retained because they identify the researched product, not an individual unit. No commit-author email or unrelated account data is included in the public source metadata.

No GitHub repository was created or published by this task. The distribution boundary is explicit; the private archive and candidate bundle must not be uploaded as a public release asset merely because the source project has an MIT license.
