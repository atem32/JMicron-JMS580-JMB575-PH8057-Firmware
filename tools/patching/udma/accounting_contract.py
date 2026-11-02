"""Reference contract for a future residue fix, deliberately not firmware.

The absence of a qualified per-command processed-byte source is represented
explicitly. USB receive length, ATA GOOD, and an unqualified MMIO zero cannot
instantiate that source. This makes the previous unsafe inference testable.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProcessedBytes:
    value: int
    command_tag: int
    command_epoch: int
    qualified_source: bool
    stable_snapshot: bool


@dataclass(frozen=True)
class Decision:
    residue: int
    update_allowed: bool
    reason: str


def future_residue_decision(*, requested: int, current_residue: int,
                            tag: int, epoch: int, outcome: str,
                            evidence: ProcessedBytes | None) -> Decision:
    """Prove H-P only with attributable, stable, qualified P.

    Completion status remains a separate concern. An ATA-error command may
    have processed some data; CSW FAILED is not permission to force P=0.
    Reset/abort/timeout have no completed BOT accounting contract here.
    """
    for name, value in (("requested", requested), ("current_residue", current_residue),
                        ("tag", tag), ("epoch", epoch)):
        if type(value) is not int or not 0 <= value <= 0xFFFFFFFF:
            raise ValueError(f"{name} must be an unsigned 32-bit integer")
    if current_residue > requested:
        raise ValueError("Existing residue exceeds the CBW transfer length")
    if outcome not in ("completed_good", "completed_ata_error", "short", "stall",
                       "reset", "abort", "timeout", "phase_error"):
        raise ValueError("Unknown outcome")
    if outcome in ("reset", "abort", "timeout", "phase_error", "stall"):
        return Decision(current_residue, False, "Transport/recovery outcome has no qualified terminal snapshot")
    if evidence is None:
        return Decision(current_residue, False, "No processed-byte evidence")
    if evidence.qualified_source is not True or evidence.stable_snapshot is not True:
        return Decision(current_residue, False, "Unqualified or unstable processed-byte source")
    if evidence.command_tag != tag or evidence.command_epoch != epoch:
        return Decision(current_residue, False, "Stale or differently attributed command snapshot")
    if type(evidence.value) is not int or not 0 <= evidence.value <= requested:
        return Decision(current_residue, False, "Processed count is outside the CBW bounds")
    return Decision(requested - evidence.value, True, "H minus attributable processed bytes")
