# Primary references and external provenance

References were inspected on 2026-11-02. Local exact-image evidence takes precedence for board-specific addresses. External documents support ISA/protocol interpretation and generic product capabilities; they do not supply an undocumented PH8057 register map.

| Reference | What it supports | Limitation |
|---|---|---|
| [Atmel/Microchip8051 Microcontrollers Hardware Manual, doc4316](https://www.microchip.com/content/dam/mchp/documents/OTH/ProductDocuments/UserGuides/doc4316.pdf) | Instruction lengths/semantics, direct versus indirect addressing, flags, stack operations, undefined DIV results | Classic ISA; no JMicron-specific peripheral/dual-DPTR contract |
| [USB Mass Storage Class Bulk-Only Transport1.0](https://www.usb.org/sites/default/files/usbmassbulk_10.pdf) | CBW/CSW fields, tag/direction/residue rules, error cases; §6.7.3 distinguishes processed bytes from transferred bytes | USB BOT, not UAS or SATA engine internals |
| [T10 SAT ATA PASS-THROUGH proposal06-291r1](https://www.t10.org/ftp/t10/document.06/06-291r1.pdf) | Historical SAT command/descriptor and CK_COND intent | A proposal/redline, not asserted to be the current final SAT standard |
| [Linux libata SCSI integration source](https://github.com/torvalds/linux/blob/master/drivers/ata/libata-scsi.c) and [libata documentation](https://docs.kernel.org/driver-api/libata.html) | Primary implementation comparison for ATA status/error and sense association, CK_COND handling | Host implementation does not prove bridge behavior |
| [Linux USB chapter9 definitions](https://github.com/torvalds/linux/blob/master/include/uapi/linux/usb/ch9.h) | USB setup/configuration descriptor field structure | Physical current and link behavior need measurement |
| [Seagate SCSI Commands Reference Manual, Rev.J, §5.3.20, p.424](https://www.seagate.com/files/staticfiles/support/docs/manual/Interface%20manuals/100293068j.pdf) | STANDBY_Z timer/SZCT field and 100 ms wire units | Does not identify JMS580 timer ticks or motor timing |
| [Infineon ModusToolbox USB Configurator user guide, 002-24357 Rev.Q](https://www.infineon.com/assets/row/public/documents/30/44/infineon-modustoolbox-usb-configurator-user-guide-usermanual-en.pdf) | Speed-dependent bMaxPower units; p.12 version 2.51 note gives 2 mA high-speed and 8 mA GenX units | Descriptor reporting is not power-rail control |
| [JMicron JMS580 product brief](https://www.jmicron.com/file/download/1053/JMS580.pdf) | Generic USB/SATA bridge capabilities | Does not qualify the supplied PH8057 image |
| [JMicron JMB575 product brief](https://www.jmicron.com/file/download/1058/JMB575.pdf) | Generic port-multiplier topology and command/FIS switching capabilities | Does not prove PH8057 UAS, NCQ concurrency or hot-swap implementation |

The bundled external decoder is from [Jari Komppa/emu8051](https://github.com/jarikomppa/emu8051), MIT. Its exact local source hashes and retained LICENSE are under `tools/emulator/oracle/`. Only the disassembler is used as an independent software oracle. A separate examination of upstream execution source found reasons not to adopt it as an unquestioned hardware authority; no upstream CPU core is used by current tests.

The explicitly requested [9500/ds500u3-jms567-uas](https://github.com/9500/ds500u3-jms567-uas) investigation was read at commit `743529e7a29febf501cc187b96f3691905ed3245`, including [its analysis](https://github.com/9500/ds500u3-jms567-uas/blob/743529e7a29febf501cc187b96f3691905ed3245/docs/firmware-analysis.md), [tests](https://github.com/9500/ds500u3-jms567-uas/blob/743529e7a29febf501cc187b96f3691905ed3245/docs/test-log.md), and [license](https://github.com/9500/ds500u3-jms567-uas/blob/743529e7a29febf501cc187b96f3691905ed3245/LICENSE). Its authorship and license scope are recorded in NOTICE. Its different controller and observed concurrency failures prevent direct portability claims.

Other historical references include [jms567ctl](https://github.com/projectgus/jms567ctl), [jms567settings](https://github.com/xx25/jms567settings), [jms578flash](https://github.com/BertoldVdb/jms578flash) and [Zibri/JMS579](https://github.com/Zibri/JMS579). Their actual license files or absence of a license were inspected. None is run against hardware by this repository.

Some supplied reports link vendor update utilities or firmware catalogs. Such links do not establish that each donor was acquired there, that redistribution is permitted, or that a JMS578/JMS579 writer is safe for JMS580. The manifests identify the received bytes without inventing an upstream chain of custody.

`research/external_sources.json` records URLs, local snapshot hashes and inspected commit identities without public account metadata. Primary specifications are linked, not redistributed as full PDFs. Downloaded reference content is distinguished from user-supplied evidence. All original content in the supplied two archives remains preserved in the private archive.

GitHub Actions dependencies are pinned to verified v6 tag targets: checkout `d23441a48e516b6c34aea4fa41551a30e30af803`, setup-python `ece7cb06caefa5fff74198d8649806c4678c61a1`. The workflow itself has not been run on GitHub because this project was not published; the underlying local entry point was run here.
