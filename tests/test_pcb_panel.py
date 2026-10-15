"""PCB panelization."""

from __future__ import annotations

from migraeda.pcb_panel import panelize_rows
from migraeda.pcbdoc import PcbComponent, PcbNetlist, PcbTrack


def test_panelize_rows_doubles_components_and_tracks() -> None:
    nl = PcbNetlist()
    nl.nets = ["", "GND"]
    nl.components = [
        PcbComponent(designator="R1", pattern="R", layer="TOP", x_mil=0, y_mil=0),
    ]
    nl.tracks = [PcbTrack(layer=1, net_index=1, x1=0, y1=0, x2=10, y2=0, width=10)]
    nl.board_outline = [(0.0, 0.0), (100.0, 0.0), (100.0, 50.0), (0.0, 50.0)]

    out = panelize_rows(nl, 2)
    assert len(out.components) == 2
    assert out.components[1].y_mil == 50.0
    assert len(out.tracks) == 2
    assert out.tracks[1].y1 == 50.0
