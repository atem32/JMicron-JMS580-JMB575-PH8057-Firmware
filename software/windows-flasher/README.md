# Windows firmware update tools (staging folder)

This folder was reserved for an owner-supplied JMicron JMS580/PH8057 Windows flash utility.

No vendor MPTool, executable, DLL, installer or activation file is included because the software's redistributable license and authenticity have not been established. **Only add files you are permitted to distribute**, and retain the original developer's license, download URL, version, SHA256 and source information.

## Suggested layout when legally permitted

- `README.md` — this index and tool safety notes.
- `JMicron-1.19.16.48/` — owner-installed tool **after** verifying publication permission and provenance.
- `SHA256SUMS.txt` — hashes of any future uploaded artifacts.

Observed on one PH8057: JMicron updater version `1.19.16.48` detected `JMS580 Series`; the SPI flash type was displayed as `Unknown`. The owner later reported a successful update and reboot. This is a single observation, **not** a tool-wide safety certification.

**Danger:** erase-all-flash, NVRAM resets, forced chip selection and incomplete SPI compatibility can permanently disable the enclosure. Do not use read-only firmware tooling as a substitute for establishing a recovery path before further experiments.
