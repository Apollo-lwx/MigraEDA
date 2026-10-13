"""PCB ASCII writer/reader round-trip tests."""

from __future__ import annotations

from pathlib import Path

from migraeda.pcbascii import parse_pcb_ascii, write_pcb_ascii
from migraeda.pcbdiff import compare_pcb
from migraeda.pcbdoc import (
    PcbComponent,
    PcbNetlist,
    PcbPad,
    PcbTrack,
    PcbVia,
)


def _demo_board() -> PcbNetlist:
    nl = PcbNetlist()
    nl.nets = ["", "GND", "+5V", "SIG"]
    nl.components = [
        PcbComponent(designator="R1", pattern="0805R", lib_reference="RES",
                     layer="TOP", x_mil=100.0, y_mil=100.0, rotation=90.0),
        PcbComponent(designator="C1", pattern="0805C", lib_reference="CAP",
                     layer="BOTTOM", x_mil=300.0, y_mil=100.0, rotation=0.0),
    ]
    nl.pads = [
        PcbPad(name="1", net_index=1, component_index=0, x_mil=50.0, y_mil=100.0,
               size_x_mil=50.0, size_y_mil=60.0, hole_mil=0.0, shape=2, layer=1),
        PcbPad(name="2", net_index=2, component_index=0, x_mil=150.0, y_mil=100.0,
               size_x_mil=50.0, size_y_mil=60.0, hole_mil=0.0, shape=2, layer=1),
        PcbPad(name="1", net_index=2, component_index=1, x_mil=250.0, y_mil=100.0,
               size_x_mil=50.0, size_y_mil=60.0, hole_mil=0.0, shape=2, layer=32),
        PcbPad(name="2", net_index=1, component_index=1, x_mil=350.0, y_mil=100.0,
               size_x_mil=50.0, size_y_mil=60.0, hole_mil=0.0, shape=2, layer=32),
        PcbPad(name="1", net_index=3, component_index=0, x_mil=100.0, y_mil=150.0,
               size_x_mil=70.0, size_y_mil=70.0, hole_mil=35.0, shape=1, layer=74),
    ]
    nl.vias = [PcbVia(net_index=1, x_mil=200.0, y_mil=200.0,
                      diameter_mil=24.0, hole_mil=12.0)]
    nl.tracks = [
        PcbTrack(layer=1, net_index=2, x1=150, y1=100, x2=250, y2=100, width=10),
        PcbTrack(layer=32, net_index=1, x1=50, y1=100, x2=200, y2=200, width=12),
    ]
    nl.board_outline = [(0.0, 0.0), (0.0, 400.0), (400.0, 400.0), (0.0, 0.0)]
    return nl


def test_pcb_ascii_roundtrip(tmp_path: Path) -> None:
    src = _demo_board()
    out = write_pcb_ascii(src, tmp_path / "demo.PcbDoc")
    back = parse_pcb_ascii(out)

    assert len(back.components) == 2
    assert back.components[0].designator == "R1"
    assert back.components[0].pattern == "0805R"
    assert len(back.pads) == 5
    assert len(back.tracks) == 2
    assert len(back.vias) == 1
    assert back.board_outline == src.board_outline

    # net names preserved
    r1p1 = next(p for p in back.pads
                if back.components[p.component_index].designator == "R1"
                and p.name == "1")
    assert back.nets[r1p1.net_index] == "GND"

    # full pcbdiff against source
    res = compare_pcb(src, back, pos_tol_mil=1.0)
    assert res.grade == "PASS", f"diffs: {res.comps_moved + res.pads_moved + res.copper_diffs}"
