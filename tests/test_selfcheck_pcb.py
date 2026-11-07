from __future__ import annotations

from pathlib import Path

from migraeda.selfcheck_pcb import selfcheck_pcb


def test_selfcheck_pcb_reports_line_parity() -> None:
    eprj = Path(__file__).resolve().parents[1] / "samples" / "SME-IOT-1" / "SME-IOT-1 A01.eprj"
    if not eprj.is_file():
        return
    out = eprj.parent / ".migraeda" / "SME-IOT-1 A01.PcbDoc"
    if not out.is_file():
        legacy = eprj.parent / "out" / "SME-IOT-1 A01.PcbDoc"
        if legacy.is_file():
            out = legacy
    text = selfcheck_pcb(eprj, converted_pcbdoc=out if out.is_file() else None)
    assert "LINE" in text and "2501" in text
    if out.is_file():
        assert "保真通过" in text and "❌ 存在差异" not in text
