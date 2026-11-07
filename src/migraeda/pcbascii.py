"""Altium ASCII .PcbDoc writer (and reader for closed-loop verification).

Format: line-based `|RECORD=X|KEY=VALUE|...` records, first record
`|RECORD=Board|KIND=Protel_Advanced_PCB|...`. Record/property keys follow
the Protel PCB ASCII specification and the binary stream property names
(SOURCEDESIGNATOR/PATTERN/NAME/X/Y/XSIZE/YSIZE/HOLESIZE/X1../WIDTH/...).
Net assignment is written as NET=<net name> on pads/tracks/vias.
"""

from __future__ import annotations

from pathlib import Path

from migraeda.pcbdoc import (
    PcbArc,
    PcbComponent,
    PcbFill,
    PcbNetlist,
    PcbPad,
    PcbPolygon,
    PcbTrack,
    PcbVia,
)

_V6_TO_NAME = {
    1: "TOP", 32: "BOTTOM", 33: "TOPOVERLAY", 34: "BOTTOMOVERLAY",
    37: "TOPSOLDER", 38: "BOTTOMSOLDER", 35: "TOPPASTE", 36: "BOTTOMPASTE",
    74: "MULTILAYER",
}
_NAME_TO_V6 = {v: k for k, v in _V6_TO_NAME.items()}
_SHAPE_TO_NAME = {0: "ROUND", 1: "ROUND", 2: "RECTANGLE", 3: "OCTAGONAL", 9: "ROUNDRECT"}
_NAME_TO_SHAPE = {v: k for k, v in _SHAPE_TO_NAME.items()}


def _mil(v: float) -> str:
    return f"{v:.10E}mil".replace("E+0", "E+").replace("E-0", "E-")


def _q(s: str) -> str:
    return s.replace("|", "/").replace("\n", " ").replace("\r", " ")


def write_pcb_ascii(nl: PcbNetlist, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    recs: list[str] = []

    def add(body: str) -> None:
        recs.append("|" + body)

    add(
        "RECORD=Board|KIND=Protel_Advanced_PCB|VERSION=5.00"
        "|ORIGINX=0.00000000000000E+0000mil|ORIGINY=0.00000000000000E+0000mil"
        "|CURRENTWORKINGLAYER=TOP|DOTGRID=FALSE|DISPLAYUNIT=1"
    )
    for i, name in enumerate(nl.nets):
        if not name:
            continue
        add(f"RECORD=Net|ID={i}|SELECTION=FALSE|NAME={_q(name)}|VISIBLE=TRUE|COLOR=8421376")

    def net_of(idx: int) -> str:
        return nl.nets[idx] if 0 <= idx < len(nl.nets) else ""

    def emit_pad(p: PcbPad) -> None:
        layer_name = _V6_TO_NAME.get(p.layer if p.layer else 74, "MULTILAYER")
        if p.hole_mil > 0:
            layer_name = "MULTILAYER"
        add(
            f"RECORD=Pad|SELECTION=FALSE|LAYER={layer_name}|LOCKED=FALSE"
            f"|POLYGONOUTLINE=FALSE|USERROUTED=TRUE|NAME={_q(p.name)}"
            f"|X={_mil(p.x_mil)}|Y={_mil(p.y_mil)}"
            f"|XSIZE={_mil(p.size_x_mil)}|YSIZE={_mil(p.size_y_mil)}"
            f"|SHAPE={_SHAPE_TO_NAME.get(p.shape, 'ROUND')}"
            f"|HOLESIZE={_mil(p.hole_mil)}|ROTATION=0.000|PLATED=TRUE"
            + (f"|NET={_q(net_of(p.net_index))}" if p.net_index >= 0 else "")
        )

    comp_seq = 0
    pads_by_comp: dict[int, list] = {}
    for p in nl.pads:
        pads_by_comp.setdefault(p.component_index, []).append(p)

    for ci, c in enumerate(nl.components):
        if not c.designator:
            continue
        add(
            f"RECORD=Component|ID={comp_seq}|SELECTION=FALSE"
            f"|LAYER={c.layer or 'TOP'}|LOCKED=FALSE|POLYGONOUTLINE=FALSE"
            f"|USERROUTED=TRUE|PRIMITIVELOCK=TRUE"
            f"|X={_mil(c.x_mil)}|Y={_mil(c.y_mil)}|PATTERN={_q(c.pattern)}"
            "|NAMEON=TRUE|COMMENTON=TRUE|GROUPNUM=0|COUNT=0"
            f"|ROTATION={c.rotation:.3f}|HEIGHT=0.00000000000000E+0000mil"
            "|NAMEAUTOPOSITION=0|COMMENTAUTOPOSITION=0|UNIONINDEX=0"
            f"|SOURCEDESIGNATOR={_q(c.designator)}"
            f"|SOURCEDESCRIPTION={_q(c.description)}"
            f"|SOURCELIBREFERENCE={_q(c.lib_reference)}"
        )
        comp_seq += 1
        # component pads immediately follow their component record so the
        # pad->component linkage survives a line-based read
        for p in pads_by_comp.get(ci, []):
            emit_pad(p)

    # free pads (no owning component)
    for p in pads_by_comp.get(-1, []):
        emit_pad(p)
    for v in nl.vias:
        add(
            "RECORD=Via|SELECTION=FALSE|LAYER=MULTILAYER|LOCKED=FALSE"
            f"|POLYGONOUTLINE=FALSE|USERROUTED=TRUE"
            f"|X={_mil(v.x_mil)}|Y={_mil(v.y_mil)}"
            f"|DIAMETER={_mil(v.diameter_mil)}|HOLESIZE={_mil(v.hole_mil)}"
            "|STARTLAYER=TOP|ENDLAYER=BOTTOM"
            + (f"|NET={_q(net_of(v.net_index))}" if v.net_index >= 0 else "")
        )
    for t in nl.tracks:
        add(
            f"RECORD=Track|POLYGON=0|SELECTION=FALSE"
            f"|LAYER={_V6_TO_NAME.get(t.layer, 'TOP')}|LOCKED=FALSE"
            f"|POLYGONOUTLINE=FALSE|USERROUTED=TRUE"
            f"|X1={_mil(t.x1)}|Y1={_mil(t.y1)}|X2={_mil(t.x2)}|Y2={_mil(t.y2)}"
            f"|WIDTH={_mil(t.width)}|SUBPOLYINDEX=0"
            + (f"|NET={_q(net_of(t.net_index))}" if t.net_index >= 0 else "")
        )
    for a in nl.arcs:
        add(
            f"RECORD=Arc|SELECTION=FALSE|LAYER={_V6_TO_NAME.get(a.layer, 'TOP')}"
            f"|LOCKED=FALSE|POLYGONOUTLINE=FALSE|USERROUTED=TRUE"
            f"|LOCATION.X={_mil(a.cx)}|LOCATION.Y={_mil(a.cy)}"
            f"|RADIUS={_mil(a.radius)}|STARTANGLE={a.start_angle:.3f}"
            f"|ENDANGLE={a.end_angle:.3f}|WIDTH={_mil(a.width)}|SUBPOLYINDEX=0"
            + (f"|NET={_q(net_of(a.net_index))}" if a.net_index >= 0 else "")
        )
    for f in nl.fills:
        add(
            f"RECORD=Fill|SELECTION=FALSE|LAYER={_V6_TO_NAME.get(f.layer, 'TOP')}"
            f"|LOCKED=FALSE|POLYGONOUTLINE=FALSE|USERROUTED=TRUE"
            f"|X1={_mil(f.x1)}|Y1={_mil(f.y1)}|X2={_mil(f.x2)}|Y2={_mil(f.y2)}"
            f"|ROTATION={f.rotation:.3f}"
            + (f"|NET={_q(net_of(f.net_index))}" if f.net_index >= 0 else "")
        )
    for p in nl.polygons:
        verts = "".join(
            f"|VX{i}={_mil(x)}|VY{i}={_mil(y)}" for i, (x, y) in enumerate(p.vertices)
        )
        add(
            f"RECORD=Polygon|SELECTION=FALSE|LAYER={p.layer or 'BOTTOM'}|LOCKED=FALSE"
            f"|POLYGONOUTLINE=FALSE|USERROUTED=TRUE|PRIMITIVELOCK=TRUE"
            + (f"|NET={_q(net_of(p.net_index))}" if p.net_index >= 0 else "")
            + f"|POLYGONTYPE=Polygon|POUROVER=TRUE|REMOVEDEAD=FALSE"
            f"|GRIDSIZE=11.811mil|TRACKWIDTH=11.811mil|HATCHSTYLE=Solid"
            f"|USEOCTAGONS=FALSE|MINPRIMLENGTH=3mil{verts}"
        )
    if nl.board_outline:
        parts = ["RECORD=BoardOutline"]
        for i, (x, y) in enumerate(nl.board_outline):
            parts.append(f"|VX{i}={_mil(x)}|VY{i}={_mil(y)}|KIND{i}=0")
        add("".join(parts))

    path.write_text("\n".join(recs) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# reader (for closed-loop verification)
# ---------------------------------------------------------------------------


def _f(s: str) -> float:
    s = s.strip()
    if s.lower().endswith("mil"):
        s = s[:-3]
    try:
        return float(s)
    except ValueError:
        return 0.0


def parse_pcb_ascii(path: str | Path) -> PcbNetlist:
    path = Path(path)
    nl = PcbNetlist()
    nl.nets.append("")  # index 0 reserved: no net (matches parse_epcb)
    net_idx: dict[str, int] = {}

    def net_id(name: str) -> int:
        if name not in net_idx:
            net_idx[name] = len(nl.nets)
            nl.nets.append(name)
        return net_idx[name]

    cur_comp = -1
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        rec: dict[str, str] = {}
        for part in line.split("|"):
            if part and "=" in part:
                k, v = part.split("=", 1)
                rec[k.strip().upper()] = v.strip()
        rt = rec.get("RECORD", "")
        if rt == "Net":
            net_id(rec.get("NAME", ""))
        elif rt == "BoardOutline":
            k = 0
            while f"VX{k}" in rec and f"VY{k}" in rec:
                nl.board_outline.append((_f(rec[f"VX{k}"]), _f(rec[f"VY{k}"])))
                k += 1
        elif rt == "Component":
            cur_comp = len(nl.components)
            nl.components.append(
                PcbComponent(
                    designator=rec.get("SOURCEDESIGNATOR", ""),
                    pattern=rec.get("PATTERN", ""),
                    lib_reference=rec.get("SOURCELIBREFERENCE", ""),
                    description=rec.get("SOURCEDESCRIPTION", ""),
                    layer=rec.get("LAYER", "TOP"),
                    x_mil=_f(rec.get("X", "0")),
                    y_mil=_f(rec.get("Y", "0")),
                    rotation=_f(rec.get("ROTATION", "0")),
                )
            )
        elif rt == "Pad":
            nl.pads.append(
                PcbPad(
                    name=rec.get("NAME", ""),
                    net_index=net_id(rec["NET"]) if "NET" in rec else -1,
                    component_index=cur_comp,
                    x_mil=_f(rec.get("X", "0")),
                    y_mil=_f(rec.get("Y", "0")),
                    size_x_mil=_f(rec.get("XSIZE", "0")),
                    size_y_mil=_f(rec.get("YSIZE", "0")),
                    hole_mil=_f(rec.get("HOLESIZE", "0")),
                    shape=_NAME_TO_SHAPE.get(rec.get("SHAPE", "ROUND"), 1),
                    layer=_NAME_TO_V6.get(rec.get("LAYER", ""), 74),
                )
            )
        elif rt == "Via":
            nl.vias.append(
                PcbVia(
                    net_index=net_id(rec["NET"]) if "NET" in rec else -1,
                    x_mil=_f(rec.get("X", "0")),
                    y_mil=_f(rec.get("Y", "0")),
                    diameter_mil=_f(rec.get("DIAMETER", "0")),
                    hole_mil=_f(rec.get("HOLESIZE", "0")),
                )
            )
        elif rt == "Track":
            nl.tracks.append(
                PcbTrack(
                    layer=_NAME_TO_V6.get(rec.get("LAYER", "TOP"), 1),
                    net_index=net_id(rec["NET"]) if "NET" in rec else -1,
                    x1=_f(rec.get("X1", "0")), y1=_f(rec.get("Y1", "0")),
                    x2=_f(rec.get("X2", "0")), y2=_f(rec.get("Y2", "0")),
                    width=_f(rec.get("WIDTH", "0")),
                )
            )
        elif rt == "Arc":
            nl.arcs.append(
                PcbArc(
                    layer=_NAME_TO_V6.get(rec.get("LAYER", "TOP"), 1),
                    net_index=net_id(rec["NET"]) if "NET" in rec else -1,
                    cx=_f(rec.get("LOCATION.X", "0")), cy=_f(rec.get("LOCATION.Y", "0")),
                    radius=_f(rec.get("RADIUS", "0")),
                    start_angle=_f(rec.get("STARTANGLE", "0")),
                    end_angle=_f(rec.get("ENDANGLE", "0")),
                    width=_f(rec.get("WIDTH", "0")),
                )
            )
        elif rt == "Fill":
            nl.fills.append(
                PcbFill(
                    layer=_NAME_TO_V6.get(rec.get("LAYER", "TOP"), 1),
                    net_index=net_id(rec["NET"]) if "NET" in rec else -1,
                    x1=_f(rec.get("X1", "0")), y1=_f(rec.get("Y1", "0")),
                    x2=_f(rec.get("X2", "0")), y2=_f(rec.get("Y2", "0")),
                    rotation=_f(rec.get("ROTATION", "0")),
                )
            )
        elif rt == "Polygon":
            verts: list[tuple[float, float]] = []
            k = 0
            while f"VX{k}" in rec and f"VY{k}" in rec:
                verts.append((_f(rec[f"VX{k}"]), _f(rec[f"VY{k}"])))
                k += 1
            nl.polygons.append(
                PcbPolygon(
                    net_index=net_id(rec["NET"]) if "NET" in rec else -1,
                    layer=rec.get("LAYER", "TOP"),
                    vertices=verts,
                )
            )
    return nl
