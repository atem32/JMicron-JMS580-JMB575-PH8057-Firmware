# References and provenance

Exact local firmware bytes and executed instructions support PH8057-specific addresses. The primary references below support ISA/protocol interpretation or generic silicon capabilities; none supplies a complete JMS580/JMB575 register, SRAM or interrupt contract.

| Primary source | Use in this project | Limit |
|---|---|---|
| [Microchip/Atmel 8051 Microcontrollers Hardware Manual, doc4316](https://www.microchip.com/content/dam/mchp/documents/OTH/ProductDocuments/UserGuides/doc4316.pdf) | Address spaces, instruction lengths/semantics, flags, stack and undefined DIV results. | Classic ISA, not JMicron-specific peripherals or dual-DPTR behavior. |
| [USB Mass Storage Class Bulk-Only Transport 1.0](https://www.usb.org/sites/default/files/usbmassbulk_10.pdf) | CBW/CSW framing and tags; §6.7.3 processed-versus-transferred byte distinction. | Does not identify a bridge's processed-byte counter or implement UAS. |
| [T10 SAT ATA PASS-THROUGH proposal 06-291r1](https://www.t10.org/ftp/t10/document.06/06-291r1.pdf) | CK_COND and ATA Return Descriptor interpretation. | 2006 proposal/redline; not represented as the current final SAT standard. |
| [Linux libata SCSI implementation](https://github.com/torvalds/linux/blob/master/drivers/ata/libata-scsi.c) and [libata documentation](https://docs.kernel.org/driver-api/libata.html) | Primary implementation comparison for status/error, sense and CK_COND association. | Host behavior does not prove bridge firmware behavior. |
| [Linux USB chapter 9 definitions](https://github.com/torvalds/linux/blob/master/include/uapi/linux/usb/ch9.h) | Setup/configuration descriptor field structure. | No physical power or link guarantee. |
| [Seagate SCSI Commands Reference Manual, Rev. J](https://www.seagate.com/files/staticfiles/support/docs/manual/Interface%20manuals/100293068j.pdf), §5.3.20, p.424 | STANDBY_Z/SZCT fields and 100 ms wire units. | Does not identify JMS580 timer ticks or measure spindle timing. |
| [Infineon USB Configurator guide, 002-24357 Rev. Q](https://www.infineon.com/assets/row/public/documents/30/44/infineon-modustoolbox-usb-configurator-user-guide-usermanual-en.pdf) | Speed-dependent bMaxPower units; version 2.51 note on p.12 distinguishes 2 mA high-speed and 8 mA GenX units. | A descriptor reports demand; it does not control a power rail. |
| [JMicron JMS580 product brief](https://www.jmicron.com/file/download/1053/JMS580.pdf) | USB-to-SATA bridge architecture. | No qualification of this firmware or undocumented registers. |
| [JMicron JMB575 product brief](https://www.jmicron.com/file/download/1058/JMB575.pdf) | One-to-five SATA port-multiplier topology and command/FIS switching. | No proof of PH8057 NCQ concurrency, UASP or hot-swap implementation. |

## Bundled decoder

The independent disassembly oracle comes from [Jari Komppa/emu8051](https://github.com/jarikomppa/emu8051/tree/5dc681275151c4a5d7b85ec9ff4ceb1b25abd5a8), commit `5dc681275151c4a5d7b85ec9ff4ceb1b25abd5a8`. Its [license](../tools/emulator/oracle/LICENSE), header and disassembler are retained with their copyright notices. The test bridge compiles the disassembler only; no upstream CPU execution core is used as a hardware authority. Reserved opcode `A5h` is excluded from mnemonic equivalence because the external decoder prints it as NOP.

## Related controller work

[9500/ds500u3-jms567-uas](https://github.com/9500/ds500u3-jms567-uas/tree/743529e7a29febf501cc187b96f3691905ed3245), inspected commit `743529e7a29febf501cc187b96f3691905ed3245`, is a different JMS567/JMB575 enclosure experiment. Its [analysis](https://github.com/9500/ds500u3-jms567-uas/blob/743529e7a29febf501cc187b96f3691905ed3245/docs/firmware-analysis.md) and [test log](https://github.com/9500/ds500u3-jms567-uas/blob/743529e7a29febf501cc187b96f3691905ed3245/docs/test-log.md) describe disk aliasing after initial UAS enablement, a routing correction, per-disk NCQ success and a later cross-disk concurrency hang. Those observations are useful counterexamples to flag-only enablement, not JMS580 qualification or evidence that JMB575 lacks FIS switching. Its authored scripts/docs and vendor-derived firmware have different [license boundaries](https://github.com/9500/ds500u3-jms567-uas/blob/743529e7a29febf501cc187b96f3691905ed3245/LICENSE); no UAS patch is copied here.

Other reference projects are [jms567ctl](https://github.com/projectgus/jms567ctl), [jms567settings](https://github.com/xx25/jms567settings), [jms578flash](https://github.com/BertoldVdb/jms578flash) and [Zibri/JMS579](https://github.com/Zibri/JMS579). Related chip names or available writers do not establish safe flashing/recovery for this board. Attribution and redistribution boundaries are in [NOTICE](../NOTICE.md).

[external_sources.json](../research/external_sources.json) retains relevant source snapshot hashes and inspected commits. Mutable upstream URLs can change; the recorded hash identifies the referenced snapshot. These records do not establish where a supplied donor BIN was acquired or grant rights to redistribute it. Specifications are linked rather than redistributed, and vendor firmware/device identifiers are excluded from the public tree.
