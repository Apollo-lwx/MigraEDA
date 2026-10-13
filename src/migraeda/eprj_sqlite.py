"""Parse LCEDA / 嘉立创EDA Pro .eprj files (SQLite container).

Extracts a pin-level netlist from the schematic sheets stored in the
`documents` table (line-based JSON records), using geometry-based
connectivity reconstruction via migraeda.schgeom.
"""

from __future__ import annotations

import html
import json
import math
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from migraeda.ir import (
    IRComponent,
    IRNetLabel,
    IRPin,
    IRPowerPort,
    IRWire,
    SchematicIR,
    pin_abs,
)
from migraeda.netlist_model import NetlistModel, SchComponent
from migraeda.schgeom import PinPoint, SchematicConnectivity


@dataclass
class SymbolPin:
    pin_id: str
    x: float
    y: float
    length: float
    orient: float
    number: str = ""
    name: str = ""


@dataclass
class SymbolDef:
    uuid: str
    title: str
    pins: list[SymbolPin] = field(default_factory=list)


def _load_symbols(con: sqlite3.Connection) -> dict[str, SymbolDef]:
    """docType=2 rows are symbol definitions."""
    out: dict[str, SymbolDef] = {}
    by_title: dict[str, SymbolDef] = {}
    rows = con.execute(
        "SELECT uuid, title, display_title, dataStr FROM components WHERE docType=2"
    ).fetchall()
    for uuid, title, display_title, data in rows:
        data = _maybe_decompress(data)
        sym = SymbolDef(uuid=uuid, title=display_title or title)
        pins: dict[str, SymbolPin] = {}
        pin_attrs: dict[str, dict[str, str]] = {}
        for line in data.splitlines():
            line = line.strip()
            if not line.startswith("["):
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec[0] == "PIN" and len(rec) >= 8:
                pin = SymbolPin(
                    pin_id=str(rec[1]),
                    x=float(rec[4]),
                    y=float(rec[5]),
                    length=float(rec[6]),
                    orient=float(rec[7]) if rec[7] is not None else 0.0,
                )
                pins[pin.pin_id] = pin
            elif rec[0] == "ATTR" and len(rec) >= 5:
                parent = str(rec[2])
                if parent in pins or parent.startswith("e"):
                    pin_attrs.setdefault(parent, {})[str(rec[3]).upper()] = str(rec[4])
        for pid, attrs in pin_attrs.items():
            if pid in pins:
                pins[pid].number = attrs.get("NUMBER", pins[pid].number)
                pins[pid].name = attrs.get("NAME", pins[pid].name)
        sym.pins = list(pins.values())
        out[uuid] = sym
        by_title[(title or "").lower()] = sym
        if display_title:
            by_title[display_title.lower()] = sym
    # expose title lookup
    for sym in list(out.values()):
        sym.title_lower = sym.title.lower()  # type: ignore[attr-defined]
    out["__by_title__"] = by_title  # type: ignore[assignment]
    return out


def _maybe_decompress(data: str) -> str:
    """Newer editor versions store documents as base64(gzip(dataStr))."""
    if data.startswith("base64"):
        import base64
        import zlib

        try:
            return zlib.decompress(
                base64.b64decode(data[6:]), 16 + zlib.MAX_WBITS
            ).decode("utf-8", errors="replace")
        except Exception:
            return data
    return data


def _sheet_records(con: sqlite3.Connection) -> list[list]:
    sheets: list[list] = []
    for (data,) in con.execute(
        "SELECT dataStr FROM documents WHERE docType=1 ORDER BY sort_ticket, sheet_id"
    ):
        data = _maybe_decompress(data)
        recs = []
        for line in data.splitlines():
            line = line.strip()
            if not line.startswith("["):
                continue
            try:
                recs.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        sheets.append(recs)
    return sheets


def _transform(px: float, py: float, rot: float, mirror: int, mode: int) -> tuple[float, float]:
    """Pin transform candidates; mode selects mirror semantics."""
    x, y = px, py
    if mirror:
        if mode == 0:
            x = -x
        elif mode == 1:
            y = -y
    rad = math.radians(-rot)  # try CW first; caller tests both signs
    c, s = math.cos(rad), math.sin(rad)
    return x * c - y * s, x * s + y * c


def parse_eprj(path: str | Path, debug: bool = False) -> NetlistModel:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    con = sqlite3.connect(str(path))
    try:
        symbols = _load_symbols(con)
        by_title: dict[str, SymbolDef] = symbols.pop("__by_title__")  # type: ignore[assignment]
        sheets = _sheet_records(con)
        devices = {
            r[0]: (r[1] or "", r[2] or "")
            for r in con.execute("SELECT uuid, display_title, description FROM devices")
        }
        footprints = {
            r[0]: (r[1] or "")
            for r in con.execute("SELECT uuid, display_title FROM components WHERE docType=4")
        }
    finally:
        con.close()

    model = NetlistModel(source=f"eprj:{path.name}")
    if not sheets:
        model.notes.append("no schematic sheets (docType=1) found")
        return model

    for recs in sheets:
        _parse_sheet(recs, symbols, by_title, devices, footprints, model, debug)
    return model


def _parse_sheet(
    recs: list,
    symbols: dict[str, SymbolDef],
    by_title: dict[str, SymbolDef],
    devices: dict[str, tuple[str, str]],
    footprints: dict[str, str],
    model: NetlistModel,
    debug: bool,
) -> None:
    attrs: dict[str, dict[str, str]] = {}
    for r in recs:
        if r[0] == "ATTR" and len(r) >= 5:
            val = r[4] if isinstance(r[4], str) else ("" if r[4] is None else str(r[4]))
            attrs.setdefault(str(r[2]), {})[str(r[3])] = html.unescape(val)

    wires: list[tuple[str, list[tuple[float, float]], str | None]] = []
    comps: list[dict] = []
    for r in recs:
        if r[0] == "WIRE" and len(r) >= 3:
            wid = str(r[1])
            pts: list[tuple[float, float]] = []
            for seg in r[2]:
                if len(seg) == 4:
                    start = (float(seg[0]), float(seg[1]))
                    end = (float(seg[2]), float(seg[3]))
                    if pts and pts[-1] == start:
                        pts.append(end)  # chained polyline
                    else:
                        if len(pts) > 1:
                            net = attrs.get(wid, {}).get("NET")
                            wires.append((wid, pts, net))
                        pts = [start, end]  # disjoint segment in same record
            net = attrs.get(wid, {}).get("NET")
            wires.append((wid, pts, net))
        elif r[0] == "COMPONENT" and len(r) >= 8:
            comps.append(
                {
                    "id": str(r[1]),
                    "sym": str(r[2]),
                    "x": float(r[3]),
                    "y": float(r[4]),
                    "rot": float(r[5]),
                    "mirror": int(r[6]) if r[6] is not None else 0,
                }
            )

    # choose mirror convention by pin-on-wire hit rate over transformed comps
    mode, cw, rate = select_transform(wires, comps, symbols, by_title, attrs)
    if debug:
        print(f"  [eprj] transform mode={mode} cw={cw} hit_rate={rate/10:.1f}%")

    conn = SchematicConnectivity()
    for idx, (wid, pts, net) in enumerate(wires):
        conn.add_wire(idx, pts, net)

    nc_pin_owners: set[tuple[str, str]] = set()
    for c in comps:
        ca = attrs.get(c["id"], {})
        ref = ca.get("Designator", "")
        name = ca.get("Name", "")
        sym = _resolve_symbol(c["sym"], ca, symbols, by_title)
        is_power = _is_power_symbol(sym, ca)

        if ref:
            dev_uuid = ca.get("Device", "")
            dev_title, dev_desc = devices.get(dev_uuid, ("", ""))
            fp_uuid = ca.get("Footprint", "")
            value = name if name and not name.startswith("=") else dev_title
            model.components[ref] = SchComponent(
                ref=ref,
                value=value,
                footprint=footprints.get(fp_uuid, fp_uuid),
                device=dev_title,
                description=dev_desc,
            )
        owner = ref or f"{name or c['sym']}@{c['id']}"

        if sym:
            for p in sym.pins:
                tx, ty = _xform(p.x, p.y, c["rot"], c["mirror"], mode, cw)
                ax, ay = c["x"] + tx, c["y"] + ty
                pin_no = p.number or p.pin_id
                pp = PinPoint(owner=owner, pin=pin_no, x=ax, y=ay)
                if is_power:
                    conn.add_pin(pp, net_name=name or None)
                else:
                    conn.add_pin(pp)
                if ref and attrs.get(c["id"], {}).get("NO_CONNECT"):
                    nc_pin_owners.add((ref, pin_no))
        # global net names
        gnn = ca.get("Global Net Name")
        if gnn:
            conn.add_global_net(str(gnn))

    # virtual pins for components whose symbols are not embedded in the file:
    # wire endpoints (degree-1 vertices) near the component origin act as pins.
    all_segs = [s for _, pts, _ in wires for s in zip(pts, pts[1:])]
    end_deg: dict[tuple[float, float], int] = {}
    for (x1, y1), (x2, y2) in all_segs:
        if (x1, y1) == (x2, y2):
            continue
        end_deg[(x1, y1)] = end_deg.get((x1, y1), 0) + 1
        end_deg[(x2, y2)] = end_deg.get((x2, y2), 0) + 1
    resolved_pts = [(p.x, p.y) for p in conn._pins]
    vp_radius = 65.0
    vp_count = 0
    for c in comps:
        ca = attrs.get(c["id"], {})
        if _resolve_symbol(c["sym"], ca, symbols, by_title) is not None:
            continue
        ref = ca.get("Designator", "")
        if not ref:
            continue  # power symbol without symbol def: contributes nothing
        cx, cy = c["x"], c["y"]
        cands: list[tuple[float, float]] = []
        for pt, deg in end_deg.items():
            if deg != 1:
                continue
            if abs(pt[0] - cx) > vp_radius or abs(pt[1] - cy) > vp_radius:
                continue
            if (pt[0] - cx) ** 2 + (pt[1] - cy) ** 2 > vp_radius * vp_radius:
                continue
            if any((pt[0] - rx) ** 2 + (pt[1] - ry) ** 2 < 4.0 for rx, ry in resolved_pts):
                continue  # already a resolved pin here
            cands.append(pt)
        cands.sort(key=lambda p: math.atan2(p[1] - cy, p[0] - cx))
        for i, pt in enumerate(cands, 1):
            conn.add_pin(PinPoint(owner=ref, pin=f"VP{i}", x=pt[0], y=pt[1], virtual=True))
            model.virtual_pins.add((ref, f"VP{i}"))
            vp_count += 1
    if vp_count:
        model.notes.append(
            f"virtual pins synthesized for unresolved symbols: {vp_count} "
            f"(pin numbers unknown, excluded from pin-level compare)"
        )

    groups = conn.resolve()

    synth = 0
    for g in groups:
        named = sorted(n for n in g.names if n)
        if named:
            net = named[0]
            if len(named) > 1:
                model.notes.append(
                    f"net name conflict, group has {named}, picked {net!r}"
                )
        else:
            real = [p for p in g.pins if not p.owner.startswith(("+", "~"))]
            if not real:
                continue
            anchor = min((p.owner, p.pin) for p in real)
            net = f"~Net{anchor[0]}_{anchor[1]}"
            synth += 1
        for p in g.pins:
            if p.owner in model.components or (p.owner, p.pin) not in model.pin_nets:
                model.pin_nets[(p.owner, p.pin)] = net
    model.notes.append(f"eprj unnamed nets synthesized: {synth}")
    model.no_connects.update(nc_pin_owners)


def _resolve_symbol(
    sym_ref: str, comp_attrs: dict[str, str], symbols: dict[str, SymbolDef],
    by_title: dict[str, SymbolDef],
) -> SymbolDef | None:
    uuid = comp_attrs.get("Symbol")
    if uuid and uuid in symbols:
        return symbols[uuid]
    # sym_ref may be "name.version", "name_version" or bare "name"
    candidates = [sym_ref]
    if "." in sym_ref:
        candidates.append(sym_ref.rsplit(".", 1)[0])
    if "_" in sym_ref:
        candidates.append(sym_ref.rsplit("_", 1)[0])
    for cand in candidates:
        sym = by_title.get(cand.lower())
        if sym is not None:
            return sym
    return None


def _is_power_symbol(sym: SymbolDef | None, comp_attrs: dict[str, str]) -> bool:
    if comp_attrs.get("Designator"):
        return False
    name = (comp_attrs.get("Name") or "").strip()
    if not name:
        return False
    if sym is not None and len(sym.pins) == 1:
        return True
    low = name.lower()
    return low.startswith(("gnd", "vcc", "vdd", "vss", "+", "-")) or "gnd" in low


def _xform(
    px: float, py: float, rot: float, mirror: int, mode: int, cw: bool
) -> tuple[float, float]:
    x, y = px, py
    if mirror:
        if mode == 0:
            x = -x
        else:
            y = -y
    rad = math.radians(-rot if cw else rot)
    c, s = math.cos(rad), math.sin(rad)
    return x * c - y * s, x * s + y * c


def select_transform(
    wires: list,
    comps: list,
    symbols: dict[str, SymbolDef],
    by_title: dict[str, SymbolDef],
    attrs: dict[str, dict[str, str]],
) -> tuple[int, bool, int]:
    """Pick the (mirror-mode, rotation-sign) convention that maximizes the
    pin-on-wire hit rate for rotated components. Tie-break prefers the
    format's actual convention (mirror flips X = mode 0)."""

    def hit_rate(mode: int, cw: bool) -> int:
        hits = total = 0
        segs = [s for _, pts, _ in wires for s in zip(pts, pts[1:])]
        for c in comps:
            if c["rot"] == 0 and c["mirror"] == 0:
                continue
            sym = _resolve_symbol(c["sym"], attrs.get(c["id"], {}), symbols, by_title)
            if not sym:
                continue
            for p in sym.pins:
                tx, ty = _xform(p.x, p.y, c["rot"], c["mirror"], mode, cw)
                ax, ay = c["x"] + tx, c["y"] + ty
                total += 1
                for (x1, y1), (x2, y2) in segs:
                    if abs((ax - x1) * (y2 - y1) - (ay - y1) * (x2 - x1)) < 1e-6 and (
                        min(x1, x2) - 1e-6 <= ax <= max(x1, x2) + 1e-6
                    ) and (
                        min(y1, y2) - 1e-6 <= ay <= max(y1, y2) + 1e-6
                    ):
                        hits += 1
                        break
        return hits * 1000 // max(total, 1)

    best = max(
        ((hit_rate(m, cw), m, cw) for m in (0, 1) for cw in (True, False)),
        key=lambda t: (t[0], -t[1], t[2]),
    )
    _, mode, cw = best
    return mode, cw, best[0]


# ---------------------------------------------------------------------------
# IR extraction (for conversion)
# ---------------------------------------------------------------------------


def parse_eprj_ir(path: str | Path) -> SchematicIR:
    """Parse an .eprj into a SchematicIR (geometry + pins + nets)."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    con = sqlite3.connect(str(path))
    try:
        symbols = _load_symbols(con)
        by_title: dict[str, SymbolDef] = symbols.pop("__by_title__")  # type: ignore[assignment]
        sheets = _sheet_records(con)
        devices = {
            r[0]: (r[1] or "", r[2] or "")
            for r in con.execute("SELECT uuid, display_title, description FROM devices")
        }
        footprints = {
            r[0]: (r[1] or "")
            for r in con.execute("SELECT uuid, display_title FROM components WHERE docType=4")
        }
    finally:
        con.close()

    ir = SchematicIR(source=f"eprj:{path.name}")
    for recs in sheets:
        attrs: dict[str, dict[str, str]] = {}
        for r in recs:
            if r[0] == "ATTR" and len(r) >= 5:
                val = r[4] if isinstance(r[4], str) else ("" if r[4] is None else str(r[4]))
                attrs.setdefault(str(r[2]), {})[str(r[3])] = html.unescape(val)

        # pass 1: wires (with disjoint-segment splitting, same as netlist parser)
        wire_idx_by_id: dict[str, list[int]] = {}
        for r in recs:
            if r[0] == "WIRE" and len(r) >= 3:
                wid = str(r[1])
                net = attrs.get(wid, {}).get("NET")
                pts: list[tuple[float, float]] = []
                for seg in r[2]:
                    if len(seg) != 4:
                        continue
                    start = (float(seg[0]), float(seg[1]))
                    end = (float(seg[2]), float(seg[3]))
                    if pts and pts[-1] == start:
                        pts.append(end)
                    else:
                        if len(pts) > 1:
                            wire_idx_by_id.setdefault(wid, []).append(len(ir.wires))
                            ir.wires.append(IRWire(points=list(pts), net=net))
                        pts = [start, end]
                if len(pts) > 1:
                    wire_idx_by_id.setdefault(wid, []).append(len(ir.wires))
                    ir.wires.append(IRWire(points=list(pts), net=net))

        # pass 2: net labels (name + nominal position + parent wire reference)
        for r in recs:
            if r[0] == "ATTR" and len(r) >= 9 and r[3] == "NET":
                parent_wire = str(r[2])
                idxs = wire_idx_by_id.get(parent_wire)
                pos_x = float(r[7]) if r[7] is not None else 0.0
                pos_y = float(r[8]) if r[8] is not None else 0.0
                ir.labels.append(
                    IRNetLabel(
                        x=pos_x, y=pos_y,
                        text=html.unescape(str(r[4])),
                        wire_idx=idxs[0] if idxs else None,
                    )
                )

        # components — pins are canonicalized to rotation=0/mirror=False:
        # each pin's relative position is its exact sheet-frame offset from
        # the component origin, computed with the sheet's selected transform
        # (identical to what the netlist parser uses).
        sel_wires = [(str(i), w.points, None) for i, w in enumerate(ir.wires)]
        comp_dicts = [
            {"id": str(r[1]), "sym": str(r[2]), "x": float(r[3]), "y": float(r[4]),
             "rot": float(r[5]), "mirror": int(r[6]) if r[6] is not None else 0}
            for r in recs if r[0] == "COMPONENT" and len(r) >= 8
        ]
        mode, cw, _rate = select_transform(sel_wires, comp_dicts, symbols, by_title, attrs)

        for c in comp_dicts:
            cid = c["id"]
            ca = attrs.get(cid, {})
            ref = ca.get("Designator", "")
            name = ca.get("Name", "")
            sym = _resolve_symbol(c["sym"], ca, symbols, by_title)
            comp = IRComponent(
                ref=ref or name or f"#{cid}",
                value=(name if name and not name.startswith("=") else ""),
                footprint=footprints.get(ca.get("Footprint", ""), ca.get("Footprint", "")),
                device=devices.get(ca.get("Device", ""), ("", ""))[0],
                description=devices.get(ca.get("Device", ""), ("", ""))[1],
                x=c["x"],
                y=c["y"],
                rotation=0.0,
                mirror=False,
            )
            if sym:
                for p in sym.pins:
                    tx, ty = _xform(p.x, p.y, c["rot"], c["mirror"], mode, cw)
                    # pin body direction in sheet frame (into-body vector)
                    brad = math.radians(p.orient)
                    dvx, dvy = math.cos(brad), math.sin(brad)
                    tvx, tvy = _xform(dvx, dvy, c["rot"], c["mirror"], mode, cw)
                    comp.pins.append(
                        IRPin(
                            number=p.number or p.pin_id,
                            name=p.name,
                            x=tx,
                            y=ty,
                            length=p.length,
                            orient_into_body=math.degrees(math.atan2(tvy, tvx)) % 360,
                        )
                    )
            is_power = _is_power_symbol(sym, ca)
            if is_power and not ref:
                if comp.pins:
                    hx, hy = comp.x + comp.pins[0].x, comp.y + comp.pins[0].y
                else:
                    hx, hy = comp.x, comp.y
                ir.power_ports.append(
                    IRPowerPort(x=hx, y=hy, net=name or "?", orient=c["rot"])
                )
                continue
            if ref:
                ir.components.append(comp)

    missing = [c.ref for c in ir.components if not c.pins]
    if missing:
        ir.notes.append(
            f"components without embedded symbols (pins unknown): {len(missing)}: "
            + ", ".join(missing)
        )
    return ir
