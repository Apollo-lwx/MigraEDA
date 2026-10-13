"""Write LCEDA / 嘉立创EDA PCB documents (docType=3) into .eprj files.

Serializes a PcbNetlist into the line-JSON PCB record format observed in
real exports: LAYER stack, NET, COMPONENT + ATTR (Designator/Footprint/
Device), PAD_NET, LINE (copper tracks), MULTI-layer PAD (vias), POLY
(board outline). Library footprints (docType=4) are carried over so the
component Footprint references resolve inside the same project.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid as uuidlib
from pathlib import Path

from migraeda.eprj_write import _SCHEMA, _footprint_datastr, _IdGen, _n, _now, _uuid
from migraeda.libmodel import LibFootprint
from migraeda.pcbdoc import PcbNetlist

_LAYER_RECORDS = [
    ["LAYER", 1, "TOP", "Top Layer", 3, "#ff0000", 1, "#ff0000", 1],
    ["LAYER", 2, "BOTTOM", "Bottom Layer", 3, "#0000ff", 1, "#0000ff", 1],
    ["LAYER", 3, "TOP_SILK", "Top Silkscreen Layer", 3, "#ffcc00", 1, "#7f6600", 1],
    ["LAYER", 4, "BOT_SILK", "Bottom Silkscreen Layer", 3, "#66cc33", 1, "#336619", 1],
    ["LAYER", 5, "TOP_SOLDER_MASK", "Top Solder Mask Layer", 3, "#800080", 0.7, "#800080", 1],
    ["LAYER", 6, "BOT_SOLDER_MASK", "Bottom Solder Mask Layer", 3, "#aa00ff", 0.7, "#aa00ff", 1],
    ["LAYER", 11, "OUTLINE", "Board Outline Layer", 3, "#ff00ff", 1, "#ff00ff", 1],
    ["LAYER", 12, "MULTI", "Multi-Layer", 3, "#c0c0c0", 1, "#c0c0c0", 1],
]

_V6_TO_LCEDA = {1: 1, 32: 2}
_SHAPE_TO_EPRJ = {1: "ELLIPSE", 2: "RECT", 3: "OVAL", 9: "RECT", 0: "ELLIPSE"}


def _uid8(n: int) -> str:
    alpha = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    out = []
    x = n * 2654435761 % (26 ** 8)
    for _ in range(8):
        out.append(alpha[x % 26])
        x //= 26
    return "".join(out)


def _pcb_datastr(nl: PcbNetlist, fp_uuid_by_pattern: dict[str, str],
                 dev_uuid_by_ref: dict[str, str]) -> str:
    ids = _IdGen()
    lines: list[str] = [
        json.dumps(["DOCTYPE", "PCB", "1.4"]),
        json.dumps(["CANVAS", 0, 0, "mil", 5, 5, 5, 5]),
    ]
    lines.extend(json.dumps(rec) for rec in _LAYER_RECORDS)
    lines.append(json.dumps(["ACTIVE_LAYER", 1]))

    # nets
    for name in nl.nets:
        if name:
            lines.append(json.dumps(["NET", name, None, None, 1, None, 0, None],
                                    ensure_ascii=False))

    # components + ATTRs + PAD_NET
    for ci, c in enumerate(nl.components):
        if not c.designator:
            continue
        cid = f"e{ci}"
        layer = 1 if (c.layer or "").upper() == "TOP" else 2
        meta = {"Unique ID": _uid8(ci + 1), "Origin Footprint": c.pattern}
        lines.append(
            json.dumps(["COMPONENT", cid, 0, layer, _n(c.x_mil), _n(c.y_mil),
                        _n(c.rotation), meta, 0], ensure_ascii=False)
        )
        fp_uuid = fp_uuid_by_pattern.get(c.pattern, "")
        dev_uuid = dev_uuid_by_ref.get(c.designator, "")
        lines.append(
            json.dumps(["ATTR", ids.next(), 0, cid, 3, _n(c.x_mil), _n(c.y_mil),
                        "Designator", c.designator, 0, 1, "default", 67.5, 6,
                        0, 0, 3, 0, 0, 0, 0, 0], ensure_ascii=False)
        )
        if fp_uuid:
            lines.append(
                json.dumps(["ATTR", ids.next(), 0, cid, 3, _n(c.x_mil), _n(c.y_mil),
                            "Footprint", fp_uuid, 0, 0, "default", 67.5, 6,
                            0, 0, 3, 0, 0, 0, 0, 0])
            )
        if dev_uuid:
            lines.append(
                json.dumps(["ATTR", ids.next(), 0, cid, 3, _n(c.x_mil), _n(c.y_mil),
                            "Device", dev_uuid, 0, 0, "default", 67.5, 6,
                            0, 0, 3, 0, 0, 0, 0, 0])
            )

    for p in nl.pads:
        if p.component_index < 0 or p.component_index >= len(nl.components):
            continue
        if p.net_index <= 0 or p.net_index >= len(nl.nets):
            continue
        ref = nl.components[p.component_index].designator
        if not ref:
            continue
        lines.append(
            json.dumps(["PAD_NET", f"e{p.component_index}", p.name,
                        nl.nets[p.net_index]], ensure_ascii=False)
        )

    # vias as MULTI-layer PAD records
    for v in nl.vias:
        net = nl.nets[v.net_index] if 0 <= v.net_index < len(nl.nets) else ""
        hole = v.hole_mil or 12.0
        dia = v.diameter_mil or hole * 2
        lines.append(
            json.dumps(
                ["PAD", ids.next(), 0, net, 12, "1", _n(v.x_mil), _n(v.y_mil), 0,
                 ["ROUND", _n(hole), _n(hole)],
                 ["ELLIPSE", _n(dia), _n(dia)],
                 [], 0, 0, 0, 1, 0, None, None, None, None, 0],
                ensure_ascii=False,
            )
        )

    # copper tracks
    for t in nl.tracks:
        layer = _V6_TO_LCEDA.get(t.layer, 1)
        net = nl.nets[t.net_index] if 0 <= t.net_index < len(nl.nets) else ""
        lines.append(
            json.dumps(
                ["LINE", ids.next(), 0, net, layer, _n(t.x1), _n(t.y1),
                 _n(t.x2), _n(t.y2), _n(t.width), 0],
                ensure_ascii=False,
            )
        )

    # board outline as POLY segments on the OUTLINE layer
    pts = nl.board_outline
    for i in range(len(pts) - 1):
        seg = [_n(pts[i][0]), _n(pts[i][1]), "L", _n(pts[i + 1][0]), _n(pts[i + 1][1])]
        lines.append(json.dumps(["POLY", ids.next(), 0, "", 11, 5, seg, 0]))

    return "\n".join(lines)


def write_eprj_pcb(nl: PcbNetlist, path: str | Path,
                   footprints: dict[str, LibFootprint] | None = None,
                   fp_uuid_by_pattern: dict[str, str] | None = None,
                   dev_uuid_by_ref: dict[str, str] | None = None,
                   project_name: str | None = None) -> Path:
    """Write an .eprj containing a real PCB document (docType=3).

    footprints: {uuid: LibFootprint} — inserted verbatim with those uuids so
    component Footprint references (fp_uuid_by_pattern) resolve.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()

    proj_uuid = _uuid()
    sch_uuid = _uuid()
    sheet_uuid = _uuid()
    pcb_uuid = _uuid()
    now = _now()
    epoch = int(time.time())

    con = sqlite3.connect(str(path))
    try:
        cur = con.cursor()
        for ddl in _SCHEMA:
            cur.execute(ddl)

        boards = json.dumps([{"sch": sch_uuid, "name": "Board1", "pcb": pcb_uuid}])
        cur.execute(
            "INSERT INTO projects (uuid, archive, name, content, cbb_project, thumb,"
            " ticket, g_ticket, owner_uuid, creator_uuid, created_at, updated_at,"
            " modifier_uuid, boards, block_symbol_attrs_groups, pcb_count, default_sheet)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (proj_uuid, 0, project_name or "pcb-converted", "", 0, "", 1, 1,
             "", "", now, now, "", boards, "{}", 1, ""),
        )
        cur.execute(
            "INSERT INTO schematics (uuid, description, ticket, sheet_count, project_uuid,"
            " name, display_name, createtime, updatetime, created_at, updated_at, sort)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (sch_uuid, "", 1, 1, proj_uuid, "schematic1", "Schematic1",
             epoch, epoch, now, now, sheet_uuid),
        )
        sch_data = "\n".join([
            json.dumps(["DOCTYPE", "SCH", "1.1"]),
            json.dumps(["HEAD", {"originX": 0, "originY": 0,
                                 "version": "1.8.40.0e3c50", "maxId": 1}]),
        ])
        cur.execute(
            "INSERT INTO documents (uuid, title, display_title, description, docType,"
            " dataStr, sheet_id, ticket, sort_ticket, created_at, updated_at,"
            " creator_uuid, schematic_uuid, project_uuid)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (sheet_uuid, "p1_1", "P1_1", "", 1, sch_data, 1, 1, 0, now, now,
             "", sch_uuid, proj_uuid),
        )
        cur.execute(
            "INSERT INTO documents (uuid, title, display_title, description, docType,"
            " dataStr, sheet_id, ticket, sort_ticket, created_at, updated_at,"
            " creator_uuid, schematic_uuid, project_uuid)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (pcb_uuid, "pcb1", "PCB1", "", 3,
             _pcb_datastr(nl, fp_uuid_by_pattern or {}, dev_uuid_by_ref or {}),
             1, 1, 0, now, now, "", "", proj_uuid),
        )

        # carry over footprint library verbatim (same uuids) so component
        # Footprint references resolve
        for fu, fp in (footprints or {}).items():
            cur.execute(
                "INSERT INTO components (uuid, title, display_title, description, source,"
                " version, created_at, updated_at, ticket, docType, dataStr, createTime,"
                " updateTime, modifier_uuid, creator_uuid, owner_uuid, project_uuid,"
                " child_tag, parent_tag, custom_tags)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (fu, fp.name.lower(), fp.name, "", "", str(epoch), now, now, 1, 4,
                 _footprint_datastr(fp, _IdGen()), now, now, "", "", "", proj_uuid,
                 "", "", ""),
            )
        con.commit()
    finally:
        con.close()
    return path
