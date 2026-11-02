"""Reproducible offline checks for PH8057 UDMA residue evidence and code."""
from __future__ import annotations

import os
from pathlib import Path

from bot_evidence import analyze_transaction
from fixtures import completion_case, new_cpu
from trace_patch import STOCK_SHA256, V8_SHA256, sha256, overlay_for_emulation
from unsafe_prototype_fixture import rejected_overlay_for_test

HERE = Path(__file__).resolve().parent
# Development: components/udma; released package: tools/patching/udma.
ROOT = HERE.parents[2] if HERE.parent.name == "patching" else HERE.parents[1]


def default_source(name, variable):
    if variable in os.environ:
        return Path(os.environ[variable])
    return ROOT / "firmware/original" / name


DEFAULT_STOCK = default_source("PH8057_FACTORY_COMPLETE_READBACK_DO_NOT_FLASH.bin", "PH8057_STOCK")
DEFAULT_V8 = default_source("PH8057_v8_EXPERIMENTAL_DO_NOT_FLASH.bin", "PH8057_V8")


def read_exact_image(path, expected):
    path = Path(path)
    if not path.is_file():
        raise ValueError("Input must be a regular local firmware file")
    if path.stat().st_size != 0x11200:
        raise ValueError("Only the complete 70,144-byte capture is accepted")
    raw = path.read_bytes()
    if sha256(raw) != expected:
        raise ValueError("Source SHA256 differs from the audited image")
    return raw


def load_sources(stock=DEFAULT_STOCK, v8=DEFAULT_V8):
    return read_exact_image(stock, STOCK_SHA256), read_exact_image(v8, V8_SHA256)


RAW_CBW = bytes.fromhex("55534243fa0d00000002000000011085170600000001001000000001403500")
RAW_CSW = bytes.fromhex("55534253fa0d00000002000000")


def hardware_excerpt():
    result = analyze_transaction(RAW_CBW, RAW_CSW, [{"length": 512, "usb_status": 0}],
                                 sg_io_resid=512)
    return {"provenance": "User-provided raw USB/BOT excerpt, repeated in supplied reassessment report; no full usbmon capture supplied",
            "raw_cbw": RAW_CBW.hex(), "raw_csw": RAW_CSW.hex(), "decoded": result}


def native_cases():
    """Cases distinguish code-level gates from physical error injection."""
    return [
        ("full_512_ck0", {}, 512, 0),
        ("full_4096_ck0", {"length": 4096}, 4096, 0),
        ("full_512_ck1", {"ck_cond": True}, 512, "ck_dependent"),
        ("ata_abrt_ck0", {"ata_status": 0x51, "ata_error": 4}, 512, 1),
        ("ata_device_fault", {"ata_status": 0x70}, 512, 1),
        ("ata_busy", {"ata_status": 0x80}, 512, 1),
        ("no_d2h_yet", {"d2h": 0}, 512, None),
        ("completion_bit21_clear", {"completion": False}, 512, 1),
        ("usb_short_or_pending_flag", {"usb": (0,), "max_steps": 200}, 512, None),
        ("endpoint_stall_or_busy_flag", {"endpoint": (0x80,), "max_steps": 200}, 512, None),
        ("inactive_or_abort_exit", {"usb": (0,), "active": (0,)}, 512, 0),
        ("late_inactive_exit", {"usb": (0,), "active": (4, 4, 0)}, 512, 0),
        ("stall_then_inactive_exit", {"endpoint": (0x80,), "active": (4, 0)}, 512, 0),
        ("usb_error_then_inactive_exit", {"usb": (0,), "error": (1,), "active": (4, 0)}, 512, 0),
        ("inactive_exit_ck1", {"usb": (0,), "active": (0,), "ck_cond": True}, 512, "ck_abort_dependent"),
        ("late_inactive_exit_ck1", {"usb": (0,), "active": (4, 4, 0), "ck_cond": True}, 512, "ck_abort_dependent"),
        ("stall_inactive_exit_ck1", {"endpoint": (0x80,), "active": (4, 0), "ck_cond": True}, 512, "ck_abort_dependent"),
        ("stale_ready_after_abort_ck1", {"usb": (0, 1), "active": (0,), "ck_cond": True}, 512, "ck_abort_dependent"),
        ("already_failed_csw_state", {"initial_csw_state": 2}, 512, 1),
        ("state64_control", {"state": 0x64, "stage": False}, 0, 0),
        ("data_in_complete_control", {"state": 0x66, "data_in": True}, 0, 0),
        ("data_in_partial_control", {"state": 0x66, "data_in": True, "sfr_remaining": 123}, 123, 0),
        ("phase_error_residue_is_ignored", {"state": 0x0D, "stage": False}, 512, 2),
        ("udma_unqualified_result384", {"unverified_arithmetic_result": 384}, 512, 0),
    ]


def semantic_result(result):
    return {key: result[key] for key in (
        "outcome", "residue_before_finalizer", "state", "sense_code", "scheduled_handler",
        "csw", "cc07_normal_wait_return_reached", "cbe3_inactive_return_reached",
        "final_sense_code", "ck_slot_header")}


def completion_matrix(stock, v8, revised=None):
    rows = []
    variants = [("stock", stock), ("original_ckcond_v8", v8)]
    if revised is not None:
        variants.append(("revised_ckcond", revised))
    for name, base in variants:
        trace = overlay_for_emulation(base)
        for case, kwargs, residue, expected_status in native_cases():
            before, old_cpu = completion_case(base, **kwargs)
            after, new_cpu = completion_case(trace, **kwargs)
            if before["residue_before_finalizer"] != residue:
                raise AssertionError((name, case, before))
            status = before["csw"]["status"] if before["csw"] else None
            if expected_status == "ck_dependent":
                wanted = 0 if name == "stock" else 1
            elif expected_status == "ck_abort_dependent":
                wanted = 1 if name == "original_ckcond_v8" else 0
            else:
                wanted = expected_status
            if status != wanted:
                raise AssertionError((name, case, status, wanted))
            if semantic_result(before) != semantic_result(after):
                raise AssertionError((name, case, "Trace helper changed semantics"))
            if before["outcome"] == "native_handler_returned":
                # A popped stack is scratch; live IRAM, all SFRs, the entire
                # fixture address space and observable MMIO effects must match.
                if (old_cpu.iram[:0x91] != new_cpu.iram[:0x91] or old_cpu.sfr != new_cpu.sfr or
                        old_cpu.xdata.memory != new_cpu.xdata.memory or old_cpu.events != new_cpu.events):
                    raise AssertionError((name, case, "Architectural state or bus event divergence"))
            rows.append({"base": name, "case": case,
                         "native_result": semantic_result(before),
                         "trace_variant_equivalent": True,
                         "helper_entered": after["trace_helper_entered"],
                         "base_max_sp": before["max_sp"], "trace_max_sp": after["max_sp"],
                         "physical_scenario_qualified": False})
    return rows


def arithmetic_native_checks(stock):
    timer_results = []
    for requested in (0, 1, 599, 600, 601, 1800, 287999, 288000, 288001, 0xFFFFFFFF):
        cpu = new_cpu(stock)
        cpu.xdata.memory[0x3500:0x3504] = requested.to_bytes(4, "big")
        cpu.set_r(6, 0x35)
        cpu.set_r(7, 0)
        cpu.call(0x9711, max_steps=10000)
        actual = int.from_bytes(cpu.xdata.memory[0x4BA0:0x4BA4], "big")
        expected = max(600, min(288000, requested))
        if actual != expected:
            raise AssertionError((requested, actual, expected))
        timer_results.append({"requested": requested, "native_result": actual,
                              "model_operations": cpu.xdata.alu.operations})
    pio_results = []
    for chunks in ((512,), (128, 384), (0, 256), (255, 256), (0, 0)):
        cpu = new_cpu(stock)
        cpu.iram[0x55:0x59] = (512).to_bytes(4, "big")
        cpu.call(0xC7C5)
        expected = 512
        for chunk in chunks:
            cpu.xdata.memory[0x6318:0x631C] = chunk.to_bytes(4, "little")
            cpu.call(0xD1D7)
            expected -= chunk
            if cpu.xdata.alu.get(cpu.xdata, 0x70C0) != expected:
                raise AssertionError("PIO arithmetic chain differs")
        cpu.write_direct(0xB9, 0x50)
        cpu.call(0xB3C4)
        actual = int.from_bytes(cpu.iram[0x55:0x59], "big")
        if actual != expected:
            raise AssertionError((chunks, actual, expected))
        pio_results.append({"chunks": chunks, "residue": actual,
                            "model_operations": cpu.xdata.alu.operations})
    return {"classification": "CONSISTENT_ARITHMETIC_HYPOTHESIS__NOT_SILICON_PROOF",
            "timer_clamp": timer_results, "pio_accounting": pio_results}


def rejected_prototype_counterexamples(stock, v8):
    results = []
    for base_name, base in (("stock", stock), ("original_ckcond_v8", v8)):
        for ck_cond in (False, True):
            kwargs = dict(usb=(0, 1), active=(0,), unverified_arithmetic_result=0,
                          ck_cond=ck_cond)
            old, _ = completion_case(rejected_overlay_for_test(base), **kwargs)
            current, _ = completion_case(overlay_for_emulation(base), **kwargs)
            if not old["cbe3_inactive_return_reached"] or old["csw"]["residue"] != 0:
                raise AssertionError("Expected old-prototype falsification no longer reproduced")
            if current["csw"]["residue"] != 512:
                raise AssertionError("Trace candidate changed accounting")
            results.append({"base": base_name, "ck_cond": ck_cond,
                            "hypothesis": "CBE3 exits with CY1 after 5052=0 and 9F.bit2=0; a later read sees5052=1 while arithmetic result is stale zero",
                            "rejected_prototype": semantic_result(old),
                            "trace_only_candidate": semantic_result(current),
                            "established": "The old helper does not reject the native inactive/abort return and can erase nonzero residue",
                            "not_established": "That exact register timing has occurred on physical hardware"})
    return results


def static_checks(stock):
    code = stock[0x1000:0x11000]
    guards = {
        0x7BF4: "907988e0f558a3e0f557a3e0f556a3e0f555",
        0x248C: "75596722",
        0x7367: "e559b4640be4f558f557f556f5558019e4ff12aef48012",
        0xAEF9: "301229",
        0xAEFC: "85ac5885ad5785ae56e5af543ff555",
        0xAF30: "12cbe3",
        0xCC07: "c322",
        0xE140: "e59f20e202d322c322",
        0x9529: "904008e558f0a3e557f0a3e556f0a3e555f0",
    }
    for address, hex_bytes in guards.items():
        expected = bytes.fromhex(hex_bytes)
        if code[address:address + len(expected)] != expected:
            raise AssertionError(f"Native signature mismatch at {address:04X}")
    sequence = bytes.fromhex("9070b67402f09070c0e0")
    positions = [i for i in range(len(code) - len(sequence) + 1)
                 if code[i:i + len(sequence)] == sequence]
    return {"exact_instruction_guards": {f"0x{a:04X}": v for a, v in guards.items()},
            "command02_then_result_read_sites": [f"0x{x:04X}" for x in positions],
            "raw_signature_sites_are_not_a_complete_CFG": True}
