# Authorship and distribution scope

## Project contributions

Project-authored analysis, documentation, tools, tests and firmware patches were
written with generative AI (ChatGPT) under the device owner's direction. This
does not attribute JMicron firmware or third-party source to the project.
Reverse-engineering conclusions and generated code may contain errors; no
independent professional safety or reliability certification is claimed.

The scoped MIT grant in [LICENSE](LICENSE) covers project-authored contributions.
Material is supplied **AS IS, WITHOUT WARRANTY**. Users remain responsible for
compatibility, backups, recovery, device damage and data loss, subject to the
applicable licenses and law.

## Vendor material and private evidence

Full original, donor and modified firmware binaries and proprietary Windows
flashers are omitted because permission to redistribute them has not been
established. Modified full images still contain vendor code. A hash identifies
an artifact; it does not grant redistribution rights.

This repository provides patch source, bounded instruction replacement records,
builders, manifests, redacted register interpretation and transaction excerpts.
It does not distribute vendor CODE/OEM dumps, raw disk sectors, unredacted device
logs, private research archives or external specification PDFs. The project
license grants no rights in those materials, board designs or vendor trademarks.
Users must obtain private inputs and proprietary tools through lawful means.

The OEM serial payload at offsets `0x056–0x077` is redacted by default in public
decoder output. Complete input images retain it and must remain private.
Product-level VID/PID and model strings identify the researched product.

## Included third-party source

`tools/emulator/oracle/emu8051_disasm.c` and `emu8051.h` originate in Jari Komppa's
[emu8051](https://github.com/jarikomppa/emu8051) project. Existing source copyright
notices and the [bundled MIT license](tools/emulator/oracle/LICENSE) are retained.
The reference upstream revision is
`5dc681275151c4a5d7b85ec9ff4ceb1b25abd5a8`.
Historical copyright years in source headers and the upstream license differ;
both notices are preserved. `decode_bridge.c` is this project's test adapter.

The bundled code is a disassembly oracle, not an execution core or authoritative
JMS580 silicon model. Reserved opcode `0xA5` is excluded from mnemonic comparison
because the upstream decoder renders it as NOP.

## Referenced material

The [references](docs/references.md) identify specifications and related
projects. Their inclusion is by link, with no transfer of their licenses or
hardware guarantees to this project. In particular, the MIT license of
[9500/ds500u3-jms567-uas](https://github.com/9500/ds500u3-jms567-uas) covers its
authored scripts and documentation, excludes vendor-derived firmware, and does
not authorize JMS567 or JMS580 binary redistribution. Its recorded research
snapshot is `743529e7a29febf501cc187b96f3691905ed3245`.

No code or firmware from the referenced JMS567/JMS578/JMS579 projects or Linux
drivers is bundled here. Their names, authorship and copyright remain with the
respective owners.

## Image attribution

`assets/images/ph8057.jpg` is a size-optimized product photograph supplied by the
repository owner, originally linked from
[Ozon](https://ir.ozone.ru/s3/multimedia-1-g/7106407540.jpg). It illustrates the
device. Copyright, if applicable, remains with the respective rightsholder;
the repository's MIT license does **not** cover this image. Attribution is not
a statement that redistribution permission has been obtained.
