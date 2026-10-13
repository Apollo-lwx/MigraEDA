"""Altium ASCII .SchDoc writer (and reader for closed-loop verification).

Format: first line `|HEADER=Protel for Windows - Schematic Capture Ascii
File Version 5.0|WEIGHT=N|...`, then one `|KEY=VALUE|...` record per line.
OWNERINDEX semantics follow KiCad's sch_io_altium: sequential record number,
0-based, counted AFTER the header line.
"""

from __future__ import annotations

import math
from pathlib import Path

from migraeda.ir import SchematicIR, pin_abs
from migraeda.netlist_model import NetlistModel
from migraeda.schdoc import model_from_records

_FONT = "FONTID=1"
_COL_DES = "COLOR=8388608"


def _q(s: str) -> str:
    """Sanitize a value for the pipe-delimited format."""
    return s.replace("|", "/").replace("\n", " ").replace("\r", " ")


def _uid(n: int) -> str:
    alpha = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    out = []
    x = n * 2654435761 % (36 ** 8)
    for _ in range(8):
        out.append(alpha[x % 36])
        x //= 36
    return "".join(out)


def _pt(v: float) -> str:
    i = round(v)
    return str(int(i))


def _records_out(ir: SchematicIR) -> list[str]:
    recs: list[str] = []

    def add(body: str) -> int:
        recs.append("|" + body)
        return len(recs) - 1  # sequential index

    # sheet record at index 0
    x0, y0, x1, y1 = ir.sheet_extent()
    sheet_w = max(1150, int(math.ceil((x1 - x0 + 200) / 50.0)) * 50)
    sheet_h = max(760, int(math.ceil((y1 - y0 + 200) / 50.0)) * 50)
    add(
        "RECORD=31|FONTIDCOUNT=1|SIZE1=10|FONTNAME1=Times New Roman"
        "|USEMBCS=T|ISBOC=T|HOTSPOTGRIDON=T|HOTSPOTGRIDSIZE=4"
        "|SYSTEMFONT=1|BORDERON=T|SHEETNUMBERSPACESIZE=4"
        "|AREACOLOR=16317695|SNAPGRIDON=T|SNAPGRIDSIZE=5"
        "|VISIBLEGRIDON=T|VISIBLEGRIDSIZE=10"
        f"|CUSTOMX={sheet_w}|CUSTOMY={sheet_h}|DISPLAY_UNIT=4"
    )

    # components
    for comp in ir.components:
        libref = _q(comp.device or comp.value or comp.ref)
        cidx = add(
            f"RECORD=1|LIBREFERENCE={libref}"
            f"|COMPONENTDESCRIPTION={_q(comp.description)}"
            "|PARTCOUNT=2|DISPLAYMODECOUNT=1"
            f"|INDEXINSHEET={len(recs) - 1}|OWNERPARTID=-1"
            f"|LOCATION.X={_pt(comp.x)}|LOCATION.Y={_pt(comp.y)}"
            "|CURRENTPARTID=1|SOURCELIBRARYNAME=*|TARGETFILENAME=*"
            f"|UNIQUEID={_uid(len(recs))}|AREACOLOR=11599871|COLOR=128"
            f"|PARTIDLOCKED=F|DESIGNITEMID={libref}|ALLPINCOUNT={len(comp.pins)}"
        )
        # body rectangle around pin body ends
        if comp.pins:
            xs: list[float] = []
            ys: list[float] = []
            for p in comp.pins:
                hx, hy = pin_abs(comp, p)
                rad = math.radians(p.orient_into_body)
                xs.append(hx + math.cos(rad) * p.length)
                ys.append(hy + math.sin(rad) * p.length)
            bx0, bx1 = min(xs) - 5, max(xs) + 5
            by0, by1 = min(ys) - 5, max(ys) + 5
            add(
                f"RECORD=14|OWNERINDEX={cidx}|ISNOTACCESIBLE=T|INDEXINSHEET=-1"
                "|OWNERPARTID=1|LINEWIDTH=1|COLOR=128|AREACOLOR=11599871"
                f"|ISSOLID=T|LOCATION.X={_pt(bx0)}|LOCATION.Y={_pt(by0)}"
                f"|CORNER.X={_pt(bx1)}|CORNER.Y={_pt(by1)}"
            )
        # pins
        for p in comp.pins:
            hx, hy = pin_abs(comp, p)
            rad = math.radians(p.orient_into_body)
            bx = hx + math.cos(rad) * p.length
            by = hy + math.sin(rad) * p.length
            orient_ad = int(round(((p.orient_into_body + 180.0) % 360.0) / 90.0)) % 4
            conglomerate = 32 | orient_ad
            pname = _q(p.name) if p.name else ""
            name_field = f"|NAME={pname}" if pname else ""
            add(
                f"RECORD=2|OWNERINDEX={cidx}|OWNERPARTID=1|FORMALTYPE=1"
                f"|ELECTRICAL=4|PINCONGLOMERATE={conglomerate}"
                f"|PINLENGTH={_pt(p.length)}"
                f"|LOCATION.X={_pt(bx)}|LOCATION.Y={_pt(by)}"
                f"{name_field}|DESIGNATOR={_q(p.number)}"
            )
        # designator + comment + footprint link
        add(
            f"RECORD=34|OWNERINDEX={cidx}|INDEXINSHEET=-1|OWNERPARTID=-1"
            f"|LOCATION.X={_pt(comp.x + 3)}|LOCATION.Y={_pt(comp.y + 11)}"
            f"|{_COL_DES}|{_FONT}|TEXT={_q(comp.ref)}|NAME=Designator"
            f"|READONLYSTATE=1|UNIQUEID={_uid(len(recs))}"
        )
        add(
            f"RECORD=41|OWNERINDEX={cidx}|INDEXINSHEET=-1|OWNERPARTID=-1"
            f"|LOCATION.X={_pt(comp.x + 3)}|LOCATION.Y={_pt(comp.y + 1)}"
            f"|{_COL_DES}|{_FONT}|TEXT={_q(comp.value)}|NAME=Comment"
            f"|UNIQUEID={_uid(len(recs))}"
        )
        if comp.footprint:
            lidx = add(f"RECORD=44|OWNERINDEX={cidx}")
            add(
                f"RECORD=45|OWNERINDEX={lidx}|INDEXINSHEET=-1"
                f"|MODELNAME={_q(comp.footprint)}|MODELTYPE=PCBLIB"
                f"|DATAFILECOUNT=1|MODELDATAFILEENTITY0={_q(comp.footprint)}"
                "|MODELDATAFILEKIND0=PCBLib|ISCURRENT=T"
                f"|UNIQUEID={_uid(len(recs))}"
            )

    # wires: degenerate "net point" wires (all points identical, an LCEDA
    # concept) are expanded to a minimal stub so labels can attach to them
    # in Altium's model (labels only attach to real segments)
    for w in ir.wires:
        pts = w.points
        if pts and all(p == pts[0] for p in pts):
            x0, y0 = pts[0]
            pts = [pts[0], (x0 + 2.0, y0)]
        parts = "".join(
            f"|X{i + 1}={_pt(px)}|Y{i + 1}={_pt(py)}" for i, (px, py) in enumerate(pts)
        )
        add(
            f"RECORD=27|INDEXINSHEET={len(recs) - 1}|OWNERPARTID=-1"
            f"|LINEWIDTH=1|COLOR=8388608|LOCATIONCOUNT={len(pts)}{parts}"
        )

    # net labels: when the label's parent wire is known, snap its position
    # onto that wire so the attachment survives any re-parse
    def _snap_to_wire(lb) -> tuple[float, float]:
        if lb.wire_idx is None or lb.wire_idx >= len(ir.wires):
            return lb.x, lb.y
        pts = ir.wires[lb.wire_idx].points
        if not pts:
            return lb.x, lb.y
        best = min(
            pts, key=lambda p: (p[0] - lb.x) ** 2 + (p[1] - lb.y) ** 2
        )
        return best

    for lb in ir.labels:
        lx, ly = _snap_to_wire(lb)
        add(
            f"RECORD=25|INDEXINSHEET={len(recs) - 1}|OWNERPARTID=-1"
            f"|LOCATION.X={_pt(lx)}|LOCATION.Y={_pt(ly)}"
            f"|COLOR=128|{_FONT}|TEXT={_q(lb.text)}"
        )

    # power ports
    for pp in ir.power_ports:
        orient = int(round(pp.orient / 90.0)) % 4
        add(
            f"RECORD=17|INDEXINSHEET={len(recs) - 1}|OWNERPARTID=-1"
            "|STYLE=4|SHOWNETNAME=T"
            f"|LOCATION.X={_pt(pp.x)}|LOCATION.Y={_pt(pp.y)}"
            f"|ORIENTATION={orient}|COLOR=128|TEXT={_q(pp.net)}"
        )

    # junctions: T-touches + hubs of >=3 wire endpoints
    segs = [
        (a, b)
        for w in ir.wires
        for a, b in zip(w.points, w.points[1:])
        if a != b
    ]
    endpoints: dict[tuple[int, int], list[int]] = {}
    for i, (a, b) in enumerate(segs):
        endpoints.setdefault((round(a[0]), round(a[1])), []).append(i)
        endpoints.setdefault((round(b[0]), round(b[1])), []).append(i)
    junctions: set[tuple[int, int]] = set()

    def _on_seg_i(px: float, py: float, s) -> bool:
        (x1, y1), (x2, y2) = s
        if abs((px - x1) * (y2 - y1) - (py - y1) * (x2 - x1)) > 1e-6:
            return False
        return (
            min(x1, x2) - 1e-6 <= px <= max(x1, x2) + 1e-6
            and min(y1, y2) - 1e-6 <= py <= max(y1, y2) + 1e-6
        )

    for pt, idxs in endpoints.items():
        if len(idxs) >= 3:
            junctions.add(pt)
            continue
        # T-touch: endpoint strictly inside another segment
        for k, s in enumerate(segs):
            if k in idxs:
                continue
            (x1, y1), (x2, y2) = s
            if _on_seg_i(pt[0], pt[1], s) and (pt != (round(x1), round(y1))) and (
                pt != (round(x2), round(y2))
            ):
                junctions.add(pt)
                break
    for jx, jy in sorted(junctions):
        add(
            f"RECORD=29|INDEXINSHEET=-1|OWNERPARTID=-1"
            f"|LOCATION.X={jx}|LOCATION.Y={jy}|COLOR=128"
        )

    return recs


def write_schdoc_ascii(ir: SchematicIR, path: str | Path) -> Path:
    path = Path(path)
    recs = _records_out(ir)
    header = (
        "|HEADER=Protel for Windows - Schematic Capture Ascii File "
        f"Version 5.0|WEIGHT={len(recs)}|MINORVERSION=2|UNIQUEID={_uid(97)}"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + "\n" + "\n".join(recs) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# reader (for closed-loop verification)
# ---------------------------------------------------------------------------


def _read_ascii_records(path: Path) -> list[tuple[int, dict[str, str]]]:
    recs: list[tuple[int, dict[str, str]]] = []
    idx = -1
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        props: dict[str, str] = {}
        for part in line.split("|"):
            if part and "=" in part:
                k, v = part.split("=", 1)
                props[k.strip().upper()] = v.strip()
        if "HEADER" in props:
            idx = -1  # reset at headers, like KiCad
            continue
        idx += 1
        recs.append((idx, props))
    return recs


def parse_schdoc_ascii(path: str | Path) -> NetlistModel:
    """Read an ASCII .SchDoc into a NetlistModel."""
    path = Path(path)
    return model_from_records(_read_ascii_records(path),
                              source=f"schdoc-ascii:{path.name}")


def parse_schdoc_ascii_ir(path: str | Path) -> "SchematicIR":
    """Read an ASCII .SchDoc into a SchematicIR (round-trip capable)."""
    from migraeda.schdoc import ir_from_records

    path = Path(path)
    return ir_from_records(_read_ascii_records(path),
                           f"schdoc-ascii:{path.name}")
