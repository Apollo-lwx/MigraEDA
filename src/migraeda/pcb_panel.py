"""Duplicate PCB panel rows (vertical step-and-repeat)."""

from __future__ import annotations

from dataclasses import replace

from migraeda.pcbdoc import (
    PcbNetlist,
    PcbPolygon,
)


def _bbox_height(outline: list[tuple[float, float]]) -> float:
    if not outline:
        return 0.0
    ys = [p[1] for p in outline]
    return max(ys) - min(ys)


def panelize_rows(nl: PcbNetlist, rows: int) -> PcbNetlist:
    """Stack ``rows`` identical copies vertically (LCEDA / Altium panel style)."""
    if rows <= 1:
        return nl
    step = _bbox_height(nl.board_outline)
    if step <= 0:
        return nl

    out = PcbNetlist()
    out.nets = list(nl.nets)
    out.components = list(nl.components)
    out.pads = list(nl.pads)
    out.vias = list(nl.vias)
    out.tracks = list(nl.tracks)
    out.arcs = list(nl.arcs)
    out.fills = list(nl.fills)
    out.polygons = list(nl.polygons)
    out.board_outline = list(nl.board_outline)

    n_comp = len(nl.components)
    for row in range(1, rows):
        dy = step * row
        for c in nl.components:
            out.components.append(replace(c, y_mil=c.y_mil + dy))
        for p in nl.pads:
            ci = p.component_index
            out.pads.append(
                replace(
                    p,
                    y_mil=p.y_mil + dy,
                    component_index=ci + n_comp * row if ci >= 0 else -1,
                )
            )
        for v in nl.vias:
            out.vias.append(replace(v, y_mil=v.y_mil + dy))
        for t in nl.tracks:
            out.tracks.append(
                replace(t, y1=t.y1 + dy, y2=t.y2 + dy)
            )
        for a in nl.arcs:
            out.arcs.append(replace(a, cy=a.cy + dy))
        for f in nl.fills:
            out.fills.append(replace(f, y1=f.y1 + dy, y2=f.y2 + dy))
        for pg in nl.polygons:
            out.polygons.append(
                PcbPolygon(
                    net_index=pg.net_index,
                    layer=pg.layer,
                    vertices=[(x, y + dy) for x, y in pg.vertices],
                )
            )
        for x, y in nl.board_outline:
            out.board_outline.append((x, y + dy))
    return out
