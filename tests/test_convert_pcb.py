"""PCB conversion fidelity (pin connectivity + geometry round-trip)."""

from __future__ import annotations

from pathlib import Path

from migraeda.convert import convert_pcb


def test_convert_pcb_preserves_pad_nets() -> None:
    eprj = Path(__file__).resolve().parents[1] / "samples" / "SME-IOT-1" / "SME-IOT-1 A01.eprj"
    if not eprj.is_file():
        return
    res = convert_pcb(eprj, out_dir=eprj.parent / "out" / "_pytest_pcb", verify=True)
    assert res.verify_grade == "PASS", res.verify_details
    assert res.pin_mismatches == 0
    assert res.common_pins >= 400
