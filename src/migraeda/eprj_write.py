"""Write LCEDA / 嘉立创EDA Pro .eprj files (SQLite container).

Schema mirrors a real exported project: projects / schematics / documents
(one SCH sheet + one empty PCB stub) / components (docType=2 symbols,
docType=4 footprint stubs) / devices / attributes.
Symbols are synthesized rectangles with correctly positioned pins.
"""

from __future__ import annotations

import json
import math
import sqlite3
import time
import uuid as uuidlib
from pathlib import Path

from migraeda.ir import IRComponent, SchematicIR

_SCHEMA = [
    """
    CREATE TABLE "projects" (
        "uuid" varchar PRIMARY KEY NOT NULL,
        "archive" boolean NOT NULL,
        "name" varchar NOT NULL,
        "content" varchar NOT NULL,
        "cbb_project" boolean NOT NULL DEFAULT (0),
        "thumb" varchar NOT NULL,
        "ticket" integer NOT NULL,
        "g_ticket" integer NOT NULL DEFAULT (1),
        "owner_uuid" varchar,
        "creator_uuid" varchar,
        "created_at" datetime NOT NULL DEFAULT (datetime('now')),
        "updated_at" datetime NOT NULL DEFAULT (datetime('now')),
        "modifier_uuid" varchar,
        "boards" varchar NOT NULL DEFAULT ('{}'),
        "block_symbol_attrs_groups" varchar NOT NULL DEFAULT ('{}'),
        "pcb_count" integer NOT NULL DEFAULT (0),
        default_sheet TEXT DEFAULT ""
    )
    """,
    """
    CREATE TABLE "documents" (
        "uuid" varchar PRIMARY KEY NOT NULL,
        "title" varchar NOT NULL,
        "display_title" varchar NOT NULL,
        "description" varchar NOT NULL,
        "docType" integer NOT NULL,
        "dataStr" text NOT NULL,
        "sheet_id" integer NOT NULL DEFAULT (1),
        "ticket" integer NOT NULL DEFAULT (1),
        "sort_ticket" integer NOT NULL DEFAULT (0),
        "created_at" datetime NOT NULL DEFAULT (datetime('now')),
        "updated_at" datetime NOT NULL DEFAULT (datetime('now')),
        "creator_uuid" varchar,
        "schematic_uuid" varchar,
        "project_uuid" varchar
    )
    """,
    """
    CREATE TABLE "schematics" (
        "uuid" varchar PRIMARY KEY NOT NULL,
        "description" varchar NOT NULL DEFAULT (''),
        "ticket" integer NOT NULL DEFAULT (1),
        "sheet_count" integer NOT NULL DEFAULT (0),
        "project_uuid" varchar NOT NULL,
        "name" varchar NOT NULL,
        "display_name" varchar NOT NULL,
        "createtime" integer NOT NULL,
        "updatetime" integer NOT NULL,
        "created_at" datetime NOT NULL DEFAULT (datetime('now')),
        "updated_at" datetime NOT NULL DEFAULT (datetime('now')),
        "sort" varchar NOT NULL DEFAULT ('')
    )
    """,
    """
    CREATE TABLE "components" (
        "uuid" varchar PRIMARY KEY NOT NULL,
        "title" varchar NOT NULL,
        "display_title" varchar NOT NULL,
        "description" varchar NOT NULL,
        "source" varchar,
        "version" varchar,
        "created_at" datetime NOT NULL DEFAULT (datetime('now')),
        "updated_at" datetime NOT NULL DEFAULT (datetime('now')),
        "ticket" integer NOT NULL,
        "docType" integer NOT NULL,
        "dataStr" text NOT NULL,
        "createTime" datetime NOT NULL DEFAULT (datetime('now')),
        "updateTime" datetime NOT NULL DEFAULT (datetime('now')),
        "modifier_uuid" varchar,
        "creator_uuid" varchar,
        "owner_uuid" varchar,
        "project_uuid" varchar,
        "child_tag" varchar NOT NULL DEFAULT (''),
        "parent_tag" varchar NOT NULL DEFAULT (''),
        "custom_tags" varchar DEFAULT ('')
    )
    """,
    """
    CREATE TABLE "devices" (
        "uuid" varchar PRIMARY KEY NOT NULL,
        "description" varchar NOT NULL,
        "title" varchar NOT NULL,
        "display_title" varchar NOT NULL,
        "images" text NOT NULL DEFAULT (''),
        "source" varchar,
        "version" varchar,
        "ticket" integer NOT NULL,
        "footprint_type" integer,
        "symbol_type" integer,
        "created_at" datetime NOT NULL DEFAULT (datetime('now')),
        "updated_at" datetime NOT NULL DEFAULT (datetime('now')),
        "createTime" datetime NOT NULL DEFAULT (datetime('now')),
        "updateTime" datetime NOT NULL DEFAULT (datetime('now')),
        "modifier_uuid" varchar,
        "creator_uuid" varchar,
        "owner_uuid" varchar,
        "project_uuid" varchar NOT NULL,
        "child_tag" varchar NOT NULL DEFAULT (''),
        "parent_tag" varchar NOT NULL DEFAULT (''),
        "custom_tags" varchar DEFAULT ('')
    )
    """,
    """
    CREATE TABLE "attributes" (
        "key" text NOT NULL,
        "value" text NOT NULL,
        "device_uuid" varchar NOT NULL,
        PRIMARY KEY (device_uuid, key)
    )
    """,
]


def _uuid() -> str:
    return uuidlib.uuid4().hex


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _n(v: float) -> int | float:
    r = round(v)
    return int(r) if abs(v - r) < 1e-9 else round(v, 2)


def _symbol_datastr(title: str, comp: IRComponent, ids) -> str:
    lines = [
        json.dumps(["DOCTYPE", "SYMBOL", "1.1"]),
        json.dumps(
            ["HEAD", {"originX": 0, "originY": 0, "version": "1.8.40.0e3c50",
                      "maxId": ids.max_id(), "symbolType": 2}],
            ensure_ascii=False,
        ),
        json.dumps(["FONTSTYLE", "st1", None, None, None, None, None, None, None, None, 2, 0]),
        json.dumps(["ATTR", ids.next(), "", "Symbol", title, 0, 0, None, None, 0, "st1", 0],
                   ensure_ascii=False),
    ]
    if comp.pins:
        xs = [p.x for p in comp.pins] + [p.x + math.cos(math.radians(p.orient_into_body)) * p.length for p in comp.pins]
        ys = [p.y for p in comp.pins] + [p.y + math.sin(math.radians(p.orient_into_body)) * p.length for p in comp.pins]
        bx0, bx1 = min(xs) - 5, max(xs) + 5
        by0, by1 = min(ys) - 5, max(ys) + 5
        lines.append(json.dumps(["PART", "", {"BBOX": [_n(bx0), _n(by1), _n(bx1), _n(by0)]}]))
        lines.append(json.dumps(["RECT", ids.next(), _n(bx0), _n(by1), _n(bx1), _n(by0), 0, 0, 0, "st1", 0]))
        for p in comp.pins:
            pid = ids.next()
            lines.append(
                json.dumps(["PIN", pid, 1, 1, _n(p.x), _n(p.y), _n(p.length),
                            _n(p.orient_into_body), None, 0, 0])
            )
            lines.append(
                json.dumps(["ATTR", ids.next(), pid, "NUMBER", p.number, 0, 1,
                            _n(p.x), _n(p.y), 0, "st4", 0], ensure_ascii=False)
            )
            if p.name:
                lines.append(
                    json.dumps(["ATTR", ids.next(), pid, "NAME", p.name, 0, 1,
                                _n(p.x), _n(p.y), 0, "st3", 0], ensure_ascii=False)
                )
    return "\n".join(lines)


class _IdGen:
    def __init__(self) -> None:
        self.n = 0

    def next(self) -> str:
        self.n += 1
        return f"e{self.n}"

    def max_id(self) -> int:
        return self.n + 100


_LAYER_RECORDS = [
    ["LAYER", 1, "TOP", "Top Layer", 3, "#ff0000", 1, "#7f0000", 1],
    ["LAYER", 2, "BOTTOM", "Bottom Layer", 3, "#0000ff", 1, "#00007f", 1],
    ["LAYER", 3, "TOP_SILK", "Top Silkscreen Layer", 3, "#ffcc00", 1, "#7f6600", 1],
    ["LAYER", 4, "BOT_SILK", "Bottom Silkscreen Layer", 3, "#66cc33", 1, "#336619", 1],
]


def _pad_shape_name(shape: str, hole: float) -> str:
    s = (shape or "").upper()
    if hole > 0:
        return "OVAL" if s == "OVAL" else "ELLIPSE"
    if s in ("RECT", "ROUND-RECT", "RECTANGLE"):
        return "RECT"
    if s == "OVAL":
        return "OVAL"
    return "ELLIPSE"


def _footprint_datastr(fp, ids: "_IdGen") -> str:
    """Serialize a LibFootprint into FOOTPRINT dataStr (line-JSON records)."""
    lines: list[str] = [json.dumps(["DOCTYPE", "FOOTPRINT", "1.3"])]
    lines.extend(json.dumps(rec) for rec in _LAYER_RECORDS)
    lines.append(json.dumps(["CANVAS", 0, 0, "mil", 5, 5]))
    for pad in fp.pads:
        layer_code = 12 if pad.hole > 0 else 1
        hole_spec = ["ROUND", _n(pad.hole), _n(pad.hole)] if pad.hole > 0 else None
        pad_spec = [_pad_shape_name(pad.shape, pad.hole), _n(pad.size_x), _n(pad.size_y)]
        lines.append(
            json.dumps(
                ["PAD", ids.next(), 0, "", layer_code, pad.number, _n(pad.x), _n(pad.y),
                 0, hole_spec, pad_spec, [], 0, 0, 0, 1, 0, 2, 2, 0, 0, 0],
                ensure_ascii=False,
            )
        )
    lines.append(
        json.dumps(
            ["ATTR", ids.next(), 0, "", 3, None, None, "Footprint", fp.name,
             0, 0, "default", 45, 6, 0, 0, 3, 0, 0, 0, 0, 0],
            ensure_ascii=False,
        )
    )
    return "\n".join(lines)


def _power_symbol_datastr(net: str, ids: _IdGen) -> str:
    lines = [
        json.dumps(["DOCTYPE", "SYMBOL", "1.1"]),
        json.dumps(["HEAD", {"originX": 0, "originY": 0, "version": "1.8.40.0e3c50",
                             "maxId": ids.max_id(), "symbolType": 2}]),
        json.dumps(["ATTR", ids.next(), "", "Symbol", f"PWR-{net}", 0, 0, None, None, 0, "st1", 0],
                   ensure_ascii=False),
        json.dumps(["PIN", ids.next(), 1, 1, 0, 0, 10, 0, None, 0, 0]),
    ]
    return "\n".join(lines)


def _insert_component_row(cur, uuid_, title, description, version, now,
                          doc_type, data_str, proj_uuid) -> None:
    cur.execute(
        "INSERT INTO components (uuid, title, display_title, description, source,"
        " version, created_at, updated_at, ticket, docType, dataStr, createTime,"
        " updateTime, modifier_uuid, creator_uuid, owner_uuid, project_uuid,"
        " child_tag, parent_tag, custom_tags)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (uuid_, title.lower(), title, description, "", version, now, now, 1,
         doc_type, data_str, now, now, "", "", "", proj_uuid, "", "", ""),
    )


def write_library_eprj(lib, path: str | Path, project_name: str | None = None) -> Path:
    """Write a Library (symbols/footprints/devices) as an .eprj package."""
    from migraeda.ir import IRComponent, IRPin

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
            (proj_uuid, 0, project_name or lib.source or "library", "", 0, "", 1, 1,
             "", "", now, now, "", boards, "{}", 1, ""),
        )
        cur.execute(
            "INSERT INTO schematics (uuid, description, ticket, sheet_count, project_uuid,"
            " name, display_name, createtime, updatetime, created_at, updated_at, sort)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (sch_uuid, "", 1, 1, proj_uuid, "schematic1", "Schematic1",
             epoch, epoch, now, now, sheet_uuid),
        )
        # empty schematic sheet + pcb stub (structure mirrors a real project)
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
            (pcb_uuid, "pcb1", "PCB1", "", 3, '["DOCTYPE","PCB","1.0"]', 1, 1, 0,
             now, now, "", "", proj_uuid),
        )

        version = str(epoch)
        for sym in lib.symbols.values():
            comp = IRComponent(ref=sym.name)
            comp.pins = [
                IRPin(number=p.number, name=p.name, x=p.x, y=p.y,
                      length=p.length, orient_into_body=p.orient)
                for p in sym.pins
            ]
            _insert_component_row(cur, _uuid(), sym.name, "", version, now, 2,
                                  _symbol_datastr(sym.name, comp, _IdGen()), proj_uuid)
        for fp in lib.footprints.values():
            _insert_component_row(cur, _uuid(), fp.name, "", version, now, 4,
                                  _footprint_datastr(fp, _IdGen()), proj_uuid)
        for dev in lib.devices.values():
            cur.execute(
                "INSERT INTO devices (uuid, description, title, display_title, images,"
                " source, version, ticket, footprint_type, symbol_type, created_at,"
                " updated_at, createTime, updateTime, modifier_uuid, creator_uuid,"
                " owner_uuid, project_uuid, child_tag, parent_tag, custom_tags)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (_uuid(), dev.description, dev.name.lower(), dev.name, "", "", version,
                 1, 0, 0, now, now, now, now, "", "", "", proj_uuid, "", "", ""),
            )
        con.commit()
    finally:
        con.close()
    return path


def write_eprj(ir: SchematicIR, path: str | Path, project_name: str | None = None) -> Path:
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
            (proj_uuid, 0, project_name or ir.source or "converted", "", 0, "", 1, 1,
             "", "", now, now, "", boards, "{}", 1, ""),
        )
        cur.execute(
            "INSERT INTO schematics (uuid, description, ticket, sheet_count, project_uuid,"
            " name, display_name, createtime, updatetime, created_at, updated_at, sort)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (sch_uuid, "", 1, 1, proj_uuid, "schematic1", "Schematic1",
             epoch, epoch, now, now, sheet_uuid),
        )

        ids = _IdGen()
        lines: list[str] = [
            json.dumps(["DOCTYPE", "SCH", "1.1"]),
            json.dumps(["HEAD", {"originX": 0, "originY": 0,
                                 "version": "1.8.40.0e3c50", "maxId": 999999}]),
            json.dumps(["FONTSTYLE", "st1", None, None, None, None, None, None, None, None, 2, 0]),
            json.dumps(["FONTSTYLE", "st7", None, None, None, None, None, None, None, None, 2, 0]),
            json.dumps(["LINESTYLE", "st9", None, None, None, None]),
        ]

        # --- symbols / devices / footprints (dedup by content signature)
        sym_uuid_by_sig: dict[tuple, tuple[str, str]] = {}
        dev_uuid_by_value: dict[str, str] = {}
        fp_uuid_by_name: dict[str, str] = {}

        def ensure_symbol(comp: IRComponent) -> tuple[str, str]:
            sig = (
                comp.device or comp.value or comp.ref,
                tuple((p.number, round(p.x, 1), round(p.y, 1), round(p.orient_into_body))
                      for p in comp.pins),
            )
            if sig in sym_uuid_by_sig:
                return sym_uuid_by_sig[sig]
            title = (comp.device or comp.value or comp.ref).replace(" ", "_")[:80]
            su = _uuid()
            sym_ids = _IdGen()
            cur.execute(
                "INSERT INTO components (uuid, title, display_title, description, source,"
                " version, created_at, updated_at, ticket, docType, dataStr, createTime,"
                " updateTime, modifier_uuid, creator_uuid, owner_uuid, project_uuid,"
                " child_tag, parent_tag, custom_tags)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (su, title.lower(), title, comp.description, "", str(epoch), now, now,
                 1, 2, _symbol_datastr(title, comp, sym_ids), now, now,
                 "", "", "", proj_uuid, "", "", ""),
            )
            sym_uuid_by_sig[sig] = (su, title)
            return sym_uuid_by_sig[sig]

        def ensure_device(comp: IRComponent) -> str:
            value = comp.value or comp.device or comp.ref
            if value in dev_uuid_by_value:
                return dev_uuid_by_value[value]
            du = _uuid()
            cur.execute(
                "INSERT INTO devices (uuid, description, title, display_title, images,"
                " source, version, ticket, footprint_type, symbol_type, created_at,"
                " updated_at, createTime, updateTime, modifier_uuid, creator_uuid,"
                " owner_uuid, project_uuid, child_tag, parent_tag, custom_tags)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (du, comp.description, value.lower(), value, "", "", str(epoch), 1,
                 0, 0, now, now, now, now, "", "", "", proj_uuid, "", "", ""),
            )
            dev_uuid_by_value[value] = du
            return du

        def ensure_footprint(name: str) -> str:
            if name in fp_uuid_by_name:
                return fp_uuid_by_name[name]
            fu = _uuid()
            data = json.dumps(["DOCTYPE", "FOOTPRINT", "1.3"]) + "\n" + json.dumps(
                ["HEAD", {"originX": 0, "originY": 0, "version": "1.8.40.0e3c50", "maxId": 1}]
            )
            cur.execute(
                "INSERT INTO components (uuid, title, display_title, description, source,"
                " version, created_at, updated_at, ticket, docType, dataStr, createTime,"
                " updateTime, modifier_uuid, creator_uuid, owner_uuid, project_uuid,"
                " child_tag, parent_tag, custom_tags)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (fu, name.lower(), name, "", "", str(epoch), now, now, 1, 4, data,
                 now, now, "", "", "", proj_uuid, "", "", ""),
            )
            fp_uuid_by_name[name] = fu
            return fu

        # --- component instances
        for comp in ir.components:
            cid = ids.next()
            su, stitle = ensure_symbol(comp)
            du = ensure_device(comp)
            lines.append(
                json.dumps(["COMPONENT", cid, f"{stitle}.1", _n(comp.x), _n(comp.y),
                            _n(comp.rotation), 1 if comp.mirror else 0, {}, 0],
                           ensure_ascii=False)
            )
            lines.append(
                json.dumps(["ATTR", ids.next(), cid, "Designator", comp.ref, 0, 1,
                            _n(comp.x), _n(comp.y + 10), 0, "st1", 0], ensure_ascii=False)
            )
            lines.append(
                json.dumps(["ATTR", ids.next(), cid, "Name", comp.value, 0, 1,
                            _n(comp.x), _n(comp.y), 0, "st1", 0], ensure_ascii=False)
            )
            lines.append(
                json.dumps(["ATTR", ids.next(), cid, "Symbol", su, 0, 0, None, None, 0, "st1", 0])
            )
            lines.append(
                json.dumps(["ATTR", ids.next(), cid, "Device", du, 0, 0,
                            _n(comp.x), _n(comp.y), 0, "st1", 0])
            )
            if comp.footprint:
                lines.append(
                    json.dumps(["ATTR", ids.next(), cid, "Footprint",
                                ensure_footprint(comp.footprint), 0, 0,
                                _n(comp.x), _n(comp.y), 0, "st1", 0])
                )

        # --- power ports (as 1-pin symbol components without designator)
        psym_by_net: dict[str, tuple[str, str]] = {}
        for pp in ir.power_ports:
            net = pp.net or "?"
            if net not in psym_by_net:
                su = _uuid()
                title = f"PWR-{net}"
                cur.execute(
                    "INSERT INTO components (uuid, title, display_title, description,"
                    " source, version, created_at, updated_at, ticket, docType, dataStr,"
                    " createTime, updateTime, modifier_uuid, creator_uuid, owner_uuid,"
                    " project_uuid, child_tag, parent_tag, custom_tags)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (su, title.lower(), title, "", "", str(epoch), now, now, 1, 2,
                     _power_symbol_datastr(net, _IdGen()), now, now, "", "", "",
                     proj_uuid, "", "", ""),
                )
                psym_by_net[net] = (su, title)
            su, stitle = psym_by_net[net]
            cid = ids.next()
            lines.append(
                json.dumps(["COMPONENT", cid, f"{stitle}.1", _n(pp.x), _n(pp.y),
                            _n(pp.orient), 0, {}, 0], ensure_ascii=False)
            )
            lines.append(
                json.dumps(["ATTR", ids.next(), cid, "Name", net, 0, 0,
                            _n(pp.x), _n(pp.y), 0, "st1", 0], ensure_ascii=False)
            )
            lines.append(
                json.dumps(["ATTR", ids.next(), cid, "Symbol", su, 0, 0, None, None, 0, "st1", 0])
            )

        # --- wires (+NET attrs from labels on nearest wire point)
        def nearest_wire_pt(lx: float, ly: float):
            best = None
            bestd = 1e18
            for wi, w in enumerate(ir.wires):
                for px, py in w.points:
                    d = (px - lx) ** 2 + (py - ly) ** 2
                    if d < bestd:
                        bestd = d
                        best = (wi, px, py)
            return best if bestd < 20 ** 2 else None

        label_of_wire: dict[int, tuple[str, float, float]] = {}
        for lb in ir.labels:
            hit = nearest_wire_pt(lb.x, lb.y)
            if hit:
                label_of_wire[hit[0]] = (lb.text, hit[1], hit[2])

        for wi, w in enumerate(ir.wires):
            wid = ids.next()
            segs = [[_n(a[0]), _n(a[1]), _n(b[0]), _n(b[1])]
                    for a, b in zip(w.points, w.points[1:]) if a != b]
            if not segs:
                continue
            lines.append(json.dumps(["WIRE", wid, segs, "st9", 0]))
            net = w.net
            if wi in label_of_wire:
                net, lx, ly = label_of_wire[wi]
            elif net:
                lx, ly = w.points[len(w.points) // 2]
            if net:
                lines.append(
                    json.dumps(["ATTR", ids.next(), wid, "NET", net, 0, 1,
                                _n(lx), _n(ly), 0, "st7", 0], ensure_ascii=False)
                )

        sch_data = "\n".join(lines)

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
            (pcb_uuid, "pcb1", "PCB1", "", 3, '["DOCTYPE","PCB","1.0"]', 1, 1, 0,
             now, now, "", "", proj_uuid),
        )

        con.commit()
    finally:
        con.close()
    return path
