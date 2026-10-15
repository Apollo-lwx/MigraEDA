"""Parse LCEDA / 嘉立创EDA PCB documents (docType=3, line-JSON records).

Extracts a PcbNetlist-compatible model so the same pcbdiff engine works
for both Altium .PcbDoc and 嘉立创 PCB data:
- components via COMPONENT + ATTR(Designator/Footprint/Device)
- pin-level nets via PAD_NET records
- copper tracks via LINE records (net name inline)
- vias via MULTI-layer PAD records
- pours via POUR, board outline via POLY on the OUTLINE layer
"""

from __future__ import annotations

import html
import json
import math
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from migraeda.pcbdoc import (
    PcbComponent,
    PcbNetlist,
    PcbPad,
    PcbPolygon,
    PcbTrack,
    PcbVia,
)

_LAYER_TO_V6 = {1: 1, 2: 32}  # LCEDA TOP/BOTTOM -> v6 top/bottom
_COPPER_LAYER_IDS = {1, 2}


@dataclass
class EpcbComponent:
    cid: str
    designator: str
    footprint_uuid: str
    footprint_name: str
    device_uuid: str
    layer: int
    x: float
    y: float
    rotation: float


def _iter_pcb_records(con: sqlite3.Connection):
    from migraeda.eprj_sqlite import _maybe_decompress

    for (data,) in con.execute(
        "SELECT dataStr FROM documents WHERE docType=3 AND LENGTH(dataStr) > 1000"
    ):
        data = _maybe_decompress(data)
        for line in data.splitlines():
            line = line.strip()
            if not line.startswith("["):
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def parse_epcb(path: str | Path) -> PcbNetlist:
    """Parse the PCB document(s) inside an .eprj into a PcbNetlist."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    con = sqlite3.connect(str(path))
    try:
        footprints = {
            r[0]: (r[1] or "")
            for r in con.execute(
                "SELECT uuid, display_title FROM components WHERE docType=4"
            )
        }
        fp_pads: dict[str, list] = {}
        from migraeda.eprj_lib import _parse_footprint

        for fu, title, data in con.execute(
            "SELECT uuid, display_title, dataStr FROM components WHERE docType=4"
        ):
            fp_pads[fu] = _parse_footprint(data, title).pads

        recs = list(_iter_pcb_records(con))
    finally:
        con.close()

    net_order: list[str] = []
    for r in recs:
        if r[0] == "NET" and len(r) >= 2 and r[1]:
            net_order.append(html.unescape(str(r[1])))

    out = PcbNetlist()
    out.nets.append("")  # index 0 = no net, LCEDA indices start at 1 elsewhere

    net_idx: dict[str, int] = {}

    def net_id(name: str) -> int:
        name = html.unescape(name)
        if name not in net_idx:
            net_idx[name] = len(out.nets)
            out.nets.append(name)
        return net_idx[name]

    comps: dict[str, EpcbComponent] = {}
    comp_index: dict[str, int] = {}
    attrs: dict[str, dict[str, str]] = {}

    for r in recs:
        t = r[0]
        if t == "COMPONENT" and len(r) >= 8:
            cid = str(r[1])
            meta = r[7] if isinstance(r[7], dict) else {}
            comps[cid] = EpcbComponent(
                cid=cid,
                designator="",
                footprint_uuid="",
                footprint_name=str(meta.get("Origin Footprint", "")),
                device_uuid="",
                layer=int(r[3]) if str(r[3]).isdigit() else 1,
                x=float(r[4]),
                y=float(r[5]),
                rotation=float(r[6]) if r[6] is not None else 0.0,
            )
        elif t == "ATTR" and len(r) >= 9:
            parent = str(r[3])
            key = str(r[7])
            val = html.unescape(str(r[8]))
            attrs.setdefault(parent, {})[key] = val

    # finalize components
    for cid, c in comps.items():
        ca = attrs.get(cid, {})
        c.designator = ca.get("Designator", "")
        c.footprint_uuid = ca.get("Footprint", "")
        c.device_uuid = ca.get("Device", "")
        fp_name = footprints.get(c.footprint_uuid, "")
        if fp_name:
            c.footprint_name = fp_name
        if not c.designator:
            continue
        comp_index[cid] = len(out.components)
        out.components.append(
            PcbComponent(
                designator=c.designator,
                pattern=c.footprint_name,
                lib_reference="",
                description="",
                layer="TOP" if c.layer == 1 else "BOTTOM",
                x_mil=c.x,
                y_mil=c.y,
                rotation=c.rotation,
            )
        )

    # pin-level nets via PAD_NET (authoritative connectivity)
    _SHAPE_CODE = {"ELLIPSE": 1, "RECT": 2, "OVAL": 3, "ROUNDRECT": 9, "ROUND": 1}
    for r in recs:
        if r[0] == "PAD_NET" and len(r) >= 4:
            cid = str(r[1])
            pin = str(r[2])
            net = str(r[3])
            if cid not in comp_index:
                continue
            ci = comp_index[cid]
            # pad position + geometry: from footprint pad (transform by component)
            px = py = 0.0
            sx = sy = hole = 0.0
            shape = 1
            layer = 74
            comp = comps.get(cid)
            fp_uuid = comp.footprint_uuid if comp else ""
            if comp and fp_uuid in fp_pads:
                for lp in fp_pads[fp_uuid]:
                    if lp.number == pin:
                        rad = math.radians(-comp.rotation)
                        cs, sn = math.cos(rad), math.sin(rad)
                        rx = lp.x * cs - lp.y * sn
                        ry = lp.x * sn + lp.y * cs
                        px = comp.x + rx
                        py = comp.y + ry
                        sx, sy = lp.size_x, lp.size_y
                        hole = lp.hole
                        shape = _SHAPE_CODE.get(lp.shape.upper(), 1)
                        layer = 74 if lp.hole > 0 else (1 if comp.layer == 1 else 32)
                        break
            out.pads.append(
                PcbPad(name=pin, net_index=net_id(net), component_index=ci,
                       x_mil=px, y_mil=py, size_x_mil=sx, size_y_mil=sy,
                       hole_mil=hole, shape=shape, layer=layer)
            )

    # MULTI-layer PAD records -> vias / through-hole pads
    for r in recs:
        if r[0] == "PAD" and len(r) >= 11 and str(r[4]) == "12":
            net = str(r[3])
            hole_spec = r[9] if isinstance(r[9], list) else []
            hole = float(hole_spec[1]) if len(hole_spec) >= 2 else 0.0
            out.vias.append(
                PcbVia(net_index=net_id(net), x_mil=float(r[6]), y_mil=float(r[7]),
                       diameter_mil=0.0, hole_mil=hole)
            )

    # copper tracks via LINE
    for r in recs:
        if r[0] == "LINE" and len(r) >= 10:
            layer = _LAYER_TO_V6.get(int(r[4]) if str(r[4]).isdigit() else 0, 99)
            net = str(r[3])
            out.tracks.append(
                PcbTrack(layer=layer, net_index=net_id(net),
                         x1=float(r[5]), y1=float(r[6]),
                         x2=float(r[7]), y2=float(r[8]),
                         width=float(r[9]))
            )

    def _net_from_pour(r: list) -> int:
        if len(r) > 3 and r[3] is not None and str(r[3]).strip():
            return net_id(str(r[3]))
        if len(r) > 7 and isinstance(r[7], int):
            idx = r[7]
            if 0 <= idx < len(net_order):
                return net_id(net_order[idx])
        return net_id("")

    def _layer_label(layer_id: int) -> str:
        return "TOP" if layer_id == 1 else "BOTTOM"

    # copper pours (POUR) -> Altium polygon primitives
    for r in recs:
        if r[0] != "POUR" or len(r) < 9:
            continue
        layer_id = int(r[4]) if str(r[4]).isdigit() else 0
        if layer_id not in _COPPER_LAYER_IDS:
            continue
        ni = _net_from_pour(r)
        for verts in _parse_pour_contours(r[8]):
            if len(verts) >= 3:
                out.polygons.append(
                    PcbPolygon(
                        net_index=ni,
                        layer=_layer_label(layer_id),
                        vertices=verts,
                    )
                )

    # closed copper POLY regions (rare; most routing is LINE)
    for r in recs:
        if r[0] != "POLY" or len(r) < 7:
            continue
        layer_id = int(r[4]) if str(r[4]).isdigit() else 0
        if layer_id not in _COPPER_LAYER_IDS:
            continue
        spec = r[6]
        width = float(r[5]) if len(r) > 5 and r[5] is not None else 10.0
        pts = _parse_lceda_path(spec)
        if _path_is_closed(pts) and len(pts) >= 3:
            out.polygons.append(
                PcbPolygon(
                    net_index=net_id(""),
                    layer=_layer_label(layer_id),
                    vertices=_strip_closing_point(pts),
                )
            )
            continue
        v6 = _LAYER_TO_V6.get(layer_id, 1)
        for i in range(len(pts) - 1):
            x1, y1 = pts[i]
            x2, y2 = pts[i + 1]
            out.tracks.append(
                PcbTrack(
                    layer=v6,
                    net_index=net_id(""),
                    x1=x1,
                    y1=y1,
                    x2=x2,
                    y2=y2,
                    width=width,
                )
            )

    # board outline: POLY segments on OUTLINE layer (11)
    for r in recs:
        if r[0] == "POLY" and len(r) >= 8 and str(r[4]) == "11":
            spec = r[6]
            pts = _poly_points(spec)
            out.board_outline.extend(pts)

    return out


def _path_is_closed(pts: list[tuple[float, float]], tol: float = 0.01) -> bool:
    if len(pts) < 3:
        return False
    x0, y0 = pts[0]
    x1, y1 = pts[-1]
    return math.hypot(x1 - x0, y1 - y0) <= tol


def _strip_closing_point(pts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if _path_is_closed(pts):
        return pts[:-1]
    return pts


def _parse_pour_contours(raw) -> list[list[tuple[float, float]]]:
    out: list[list[tuple[float, float]]] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, list):
            continue
        verts = _parse_lceda_path(item)
        if verts:
            out.append(_strip_closing_point(verts) if _path_is_closed(verts) else verts)
    return out


def _parse_lceda_path(spec) -> list[tuple[float, float]]:
    """Walk LCEDA pour/poly path specs into vertex lists."""
    if not isinstance(spec, list) or not spec:
        return []
    if spec[0] == "R" and len(spec) >= 5:
        x, y, w, h = float(spec[1]), float(spec[2]), float(spec[3]), float(spec[4])
        return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    if spec[0] == "CIRCLE" and len(spec) >= 4:
        cx, cy, r = float(spec[1]), float(spec[2]), float(spec[3])
        n = 16
        return [
            (cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n))
            for i in range(n)
        ]
    pts: list[tuple[float, float]] = []
    i = 0
    while i < len(spec):
        v = spec[i]
        if isinstance(v, (int, float)):
            if i + 1 < len(spec) and isinstance(spec[i + 1], (int, float)):
                pts.append((float(v), float(spec[i + 1])))
                i += 2
                continue
        elif v in ("L", "ARC"):
            i += 1
            continue
        i += 1
    return pts


def _poly_points(spec) -> list[tuple[float, float]]:
    """Extract (x,y) points from POLY coordinate specs like
    [x1,y1,"L",x2,y2] or ["CIRCLE",x,y,r]."""
    return _parse_lceda_path(spec)
