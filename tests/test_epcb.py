"""嘉立创 PCB (epcb) geometry parsing."""

from __future__ import annotations

from pathlib import Path

from migraeda.epcb import _parse_lceda_path, _parse_pour_contours, _path_is_closed


def test_parse_lceda_rectangle() -> None:
    verts = _parse_lceda_path(["R", 0.0, 0.0, 100.0, 50.0, 0, 0])
    assert verts == [(0.0, 0.0), (100.0, 0.0), (100.0, 50.0), (0.0, 50.0)]


def test_parse_lceda_closed_polyline() -> None:
    spec = [0.0, 0.0, "L", 10.0, 0.0, "L", 10.0, 10.0, "L", 0.0, 0.0]
    verts = _parse_lceda_path(spec)
    assert _path_is_closed(verts)
    assert len(_parse_pour_contours([spec])) == 1


def test_pour_empty_net_name_not_mapped_to_gnd() -> None:
    from migraeda.epcb import parse_epcb

    eprj = Path(__file__).resolve().parents[1] / "samples" / "SME-IOT-1" / "SME-IOT-1 A01.eprj"
    if not eprj.is_file():
        return
    nl = parse_epcb(eprj)
    unnamed = [p for p in nl.polygons if p.net_index >= 0 and nl.nets[p.net_index] == ""]
    assert len(unnamed) >= 1


def test_parse_epcb_sample_pours() -> None:
    from migraeda.epcb import parse_epcb

    eprj = Path(__file__).resolve().parents[1] / "samples" / "SME-IOT-1" / "SME-IOT-1 A01.eprj"
    if not eprj.is_file():
        return
    nl = parse_epcb(eprj)
    assert len(nl.polygons) >= 2
    nets = {nl.nets[p.net_index] for p in nl.polygons if p.net_index >= 0}
    assert "GND" in nets or "+12V" in nets
