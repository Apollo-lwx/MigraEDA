"""PCB-level diff tests with synthetic boards."""

from __future__ import annotations

import copy

from migraeda.pcbdiff import compare_pcb, copper_stats
from migraeda.pcbdoc import (
    PcbComponent,
    PcbNetlist,
    PcbPad,
    PcbTrack,
    PcbVia,
)


def _board() -> PcbNetlist:
    nl = PcbNetlist()
    nl.nets = ["GND", "VCC"]
    nl.components = [
        PcbComponent(designator="R1", pattern="0805R", layer="TOP",
                     x_mil=100.0, y_mil=100.0),
        PcbComponent(designator="C1", pattern="0805C", layer="TOP",
                     x_mil=200.0, y_mil=100.0),
    ]
    nl.pads = [
        PcbPad(name="1", net_index=0, component_index=0, x_mil=90.0, y_mil=100.0),
        PcbPad(name="2", net_index=1, component_index=0, x_mil=110.0, y_mil=100.0),
        PcbPad(name="1", net_index=1, component_index=1, x_mil=190.0, y_mil=100.0),
        PcbPad(name="2", net_index=0, component_index=1, x_mil=210.0, y_mil=100.0),
    ]
    nl.vias = [PcbVia(net_index=0, x_mil=150.0, y_mil=150.0,
                      diameter_mil=24.0, hole_mil=12.0)]
    nl.tracks = [
        # copper (layer 1 = top, layer 32 = bottom)
        PcbTrack(layer=1, net_index=1, x1=110, y1=100, x2=190, y2=100, width=10),
        PcbTrack(layer=32, net_index=0, x1=90, y1=100, x2=150, y2=150, width=10),
        # silkscreen (layer 33) — must be excluded from copper stats
        PcbTrack(layer=33, net_index=0, x1=0, y1=0, x2=500, y2=500, width=5),
    ]
    nl.board_outline = [(0.0, 0.0), (0.0, 500.0), (500.0, 500.0), (0.0, 0.0)]
    return nl


def test_identical_boards_pass() -> None:
    res = compare_pcb(_board(), _board())
    assert res.grade == "PASS"
    assert res.pads_checked == 4
    assert res.comps_common == 2


def test_moved_component_fails() -> None:
    b = _board()
    b.components[1].x_mil += 30.0
    res = compare_pcb(_board(), b)
    assert res.grade == "FAIL"
    assert any(m.startswith("C1") for m in res.comps_moved)


def test_moved_pad_fails() -> None:
    b = _board()
    b.pads[1].x_mil += 10.0
    res = compare_pcb(_board(), b)
    assert res.grade == "FAIL"
    assert any(m.startswith("R1.2") for m in res.pads_moved)


def test_via_difference_fails() -> None:
    b = _board()
    b.vias.append(PcbVia(net_index=0, x_mil=300.0, y_mil=300.0))
    res = compare_pcb(_board(), b)
    assert res.grade == "FAIL"
    assert res.vias_unmatched or res.vias_a != res.vias_b


def test_copper_length_difference_warns() -> None:
    b = _board()
    b.tracks[0].x2 += 500.0  # lengthen VCC track by 500 mil
    res = compare_pcb(_board(), b)
    assert res.grade == "WARN"
    assert any("VCC" in d for d in res.copper_diffs)


def test_silkscreen_excluded_from_copper() -> None:
    stats = copper_stats(_board())
    assert stats["VCC"].track_count == 1
    assert stats["GND"].track_count == 1  # not 2 (silkscreen excluded)
    assert stats["GND"].via_count == 1
