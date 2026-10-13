"""Parse Altium Designer .SchDoc files (binary v5.0, OLE/CFB container).

Extracts a pin-level netlist via geometry-based connectivity reconstruction
(migraeda.schgeom). Record linking follows KiCad's sch_io_altium:
OWNERINDEX = sequential record number, 0-based, counted AFTER the
HEADER record of the FileHeader stream.

Component semantics implemented here (format-level, not project-specific):
- Multi-display-mode symbols: pins are stored once per display mode at
  different positions; only the component's active DISPLAYMODE is kept.
- Multi-part components (PARTCOUNT > 1): only pins whose OWNERPARTID equals
  the instance's CURRENTPARTID are electrically active (KiCad-consistent).
  Skipped pins are counted and reported in model.notes for diagnosability.
- Pin hotspots: LOCATION is the pin body end; the electrical hotspot is
  PINLENGTH away in the PINCONGLOMERATE&3 direction.
"""

from __future__ import annotations

import struct
from pathlib import Path

import olefile

from migraeda.ir import IRComponent, IRNetLabel, IRPin, IRPowerPort, IRWire, SchematicIR
from migraeda.netlist_model import NetlistModel, SchComponent
from migraeda.schgeom import PinPoint, SchematicConnectivity

# record type ids we care about
RT_COMPONENT = "1"
RT_PIN = "2"
RT_POWER_PORT = "17"
RT_PORT = "18"
RT_NET_LABEL = "25"
RT_WIRE = "27"
RT_JUNCTION = "29"
RT_DESIGNATOR = "34"
RT_PARAMETER = "41"
RT_IMPL_LIST = "44"
RT_IMPLEMENTATION = "45"


def _records(data: bytes):
    """uint32 length + '|KEY=VALUE|...' payload; yields (kicad_index, props)."""
    i = 0
    pos = -1
    while i + 4 <= len(data):
        (ln,) = struct.unpack_from("<I", data, i)
        i += 4
        if ln == 0 or i + ln > len(data):
            break
        payload = data[i : i + ln]
        i += ln
        pos += 1
        txt = payload.decode("mbcs", errors="replace").rstrip("\x00")
        rec: dict[str, str] = {}
        for part in txt.split("|"):
            if not part:
                continue
            if "=" in part:
                k, v = part.split("=", 1)
                rec[k.strip().upper()] = v.strip()
        # kicad index: 0-based count of records after the HEADER record
        yield pos - 1, rec


def _int(rec: dict[str, str], key: str, default: int = 0) -> int:
    try:
        return int(rec.get(key, "").strip())
    except ValueError:
        return default


def _loc(rec: dict[str, str]) -> tuple[float, float]:
    x = _int(rec, "LOCATION.X")
    y = _int(rec, "LOCATION.Y")
    # schematic FRAC fields are 1/10000 mil
    x += _int(rec, "LOCATION.X_FRAC") / 10000.0
    y += _int(rec, "LOCATION.Y_FRAC") / 10000.0
    return float(x), float(y)


def parse_schdoc(path: str | Path, debug: bool = False) -> NetlistModel:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    ole = olefile.OleFileIO(str(path))
    try:
        data = ole.openstream("FileHeader").read()
    finally:
        ole.close()
    return model_from_records(_records(data), source=f"schdoc:{path.name}")


def model_from_records(records, source: str) -> NetlistModel:
    """Build a NetlistModel from (kicad_index, props) record pairs.

    Shared by the binary FileHeader path and the ASCII variant reader.
    """
    model = NetlistModel(source=source)

    comps: dict[int, dict] = {}
    comp_des: dict[int, str] = {}
    comp_params: dict[int, dict[str, str]] = {}
    pins: list[dict] = []
    impl_owner: dict[int, int] = {}  # record idx -> owner idx
    impls: list[dict] = []
    wires: list[list[tuple[float, float]]] = []
    conn = SchematicConnectivity()

    for idx, rec in records:
        rt = rec.get("RECORD", "")
        if rt == RT_COMPONENT:
            comps[idx] = rec
        elif rt == RT_PIN:
            pins.append(rec)
        elif rt == RT_WIRE:
            n = _int(rec, "LOCATIONCOUNT")
            pts = []
            for k in range(1, n + 1):
                x = _int(rec, f"X{k}")
                y = _int(rec, f"Y{k}")
                pts.append((float(x), float(y)))
            if len(pts) >= 2:
                wires.append(pts)
        elif rt == RT_NET_LABEL:
            x, y = _loc(rec)
            conn.add_label(x, y, rec.get("TEXT", ""))
        elif rt == RT_POWER_PORT:
            x, y = _loc(rec)
            # power port: single pin at LOCATION, names the net globally
            pp = PinPoint(owner=f"PWR:{rec.get('TEXT', '')}@{idx}", pin="1", x=x, y=y)
            conn.add_pin(pp, net_name=rec.get("TEXT", ""))
        elif rt == RT_JUNCTION:
            x, y = _loc(rec)
            conn.add_junction(x, y)
        elif rt == RT_DESIGNATOR:
            comp_des[_int(rec, "OWNERINDEX", -1)] = rec.get("TEXT", "")
        elif rt == RT_PARAMETER:
            oi = _int(rec, "OWNERINDEX", -1)
            if oi >= 0:
                comp_params.setdefault(oi, {})[rec.get("NAME", "")] = rec.get("TEXT", "")
        elif rt in (RT_IMPL_LIST, RT_IMPLEMENTATION):
            impl_owner[idx] = _int(rec, "OWNERINDEX", -1)
            if rt == RT_IMPLEMENTATION:
                rec["_IDX"] = idx
                impls.append(rec)

    for i, pts in enumerate(wires):
        conn.add_wire(i, pts)

    # footprints: implementation -> impl_list -> component
    comp_fp: dict[int, str] = {}
    for imp in impls:
        if imp.get("ISCURRENT", "").upper() != "T":
            continue
        if imp.get("MODELTYPE", "").upper() not in ("PCBLIB", "PCBLIBRARY"):
            continue
        owner = impl_owner.get(imp["_IDX"], -1)
        # owner is the IMPLEMENTATION_LIST record; its owner is the component
        comp_idx = impl_owner.get(owner, owner)
        if comp_idx in comps:
            comp_fp[comp_idx] = imp.get("MODELNAME", "")

    # component table
    for idx, crec in comps.items():
        ref = comp_des.get(idx, f"#{idx}")
        params = comp_params.get(idx, {})
        model.components[ref] = SchComponent(
            ref=ref,
            value=params.get("Comment", "") or crec.get("DESIGNITEMID", ""),
            footprint=comp_fp.get(idx, ""),
            device=crec.get("LIBREFERENCE", ""),
            description=crec.get("COMPONENTDESCRIPTION", ""),
        )

    # pins -> conn (LOCATION is the body end; hotspot = LOCATION + dir*len)
    # multi-display-mode symbols store pins once per mode at different
    # positions; keep only the mode the component actually uses
    # (OWNERPARTDISPLAYMODE absent/0 or == component DISPLAYMODE).
    _DIRS = {0: (1, 0), 1: (0, 1), 2: (-1, 0), 3: (0, -1)}
    orphan = 0
    skipped_modes = 0
    skipped_parts = 0
    skipped_part_refs: dict[str, int] = {}
    for prec in pins:
        oi = _int(prec, "OWNERINDEX", -1)
        if oi not in comps:
            orphan += 1
            continue
        opdm = (prec.get("OWNERPARTDISPLAYMODE") or "").strip() or "0"
        comp_mode = (comps[oi].get("DISPLAYMODE") or "").strip() or "0"
        if opdm != "0" and opdm != comp_mode:
            skipped_modes += 1
            continue
        # multi-part component: only the pins of the part this instance
        # represents are electrically active (KiCad-consistent semantics)
        partcount = int((comps[oi].get("PARTCOUNT") or "1").strip() or "1")
        if partcount > 1:
            owner_part = (prec.get("OWNERPARTID") or "").strip()
            if owner_part and owner_part != "0":
                current_part = (comps[oi].get("CURRENTPARTID") or "1").strip()
                if owner_part != current_part:
                    skipped_parts += 1
                    ref_ = comp_des.get(oi, f"#{oi}")
                    skipped_part_refs[ref_] = skipped_part_refs.get(ref_, 0) + 1
                    continue
        ref = comp_des.get(oi, f"#{oi}")
        x, y = _loc(prec)
        orient = _int(prec, "PINCONGLOMERATE") & 3
        dx, dy = _DIRS.get(orient, (0, 0))
        ln = _int(prec, "PINLENGTH", 0)
        pin_no = prec.get("DESIGNATOR", "") or "?"
        conn.add_pin(PinPoint(owner=ref, pin=pin_no, x=x + dx * ln, y=y + dy * ln))
    if skipped_modes:
        model.notes.append(f"alt display-mode pins skipped: {skipped_modes}")
    if skipped_parts:
        top = sorted(skipped_part_refs.items(), key=lambda kv: -kv[1])[:8]
        model.notes.append(
            f"multi-part pins skipped (instance not the owning part): {skipped_parts}"
            f" across {len(skipped_part_refs)} refs; most: "
            + ", ".join(f"{r}×{n}" for r, n in top)
        )
    if orphan:
        model.notes.append(f"orphan pins (no component): {orphan}")

    groups = conn.resolve()
    # named-net groups are more authoritative (labels/power ports are
    # designer intent; synthesized fragments are not) — write them first
    # so duplicate (ref, pin) entries resolve to the named net.
    def _group_rank(g) -> tuple[int, str]:
        return (0 if any(g.names) else 1, sorted(g.names)[0] if g.names else "")

    synth = 0
    for g in sorted(groups, key=_group_rank):
        named = sorted(n for n in g.names if n)
        if named:
            net = named[0]
            if len(named) > 1:
                model.notes.append(
                    f"net name conflict, group has {named}, picked {net!r}"
                )
        else:
            real = [p for p in g.pins if not p.owner.startswith("PWR:")]
            if not real:
                continue
            anchor = min((p.owner, p.pin) for p in real)
            net = f"~Net{anchor[0]}_{anchor[1]}"
            synth += 1
        for p in g.pins:
            if not p.owner.startswith("PWR:"):
                model.pin_nets.setdefault((p.owner, p.pin), net)
    model.notes.append(f"schdoc unnamed nets synthesized: {synth}")
    return model


# ---------------------------------------------------------------------------
# IR extraction (for conversion)
# ---------------------------------------------------------------------------

_ORIENT_DIRS = {0: (1, 0), 1: (0, 1), 2: (-1, 0), 3: (0, -1)}


def parse_schdoc_ir(path: str | Path) -> SchematicIR:
    """Parse a binary .SchDoc into a SchematicIR.

    Pin positions are canonicalized to rotation=0/mirror=False:
    each pin's relative position is its sheet-frame offset from the
    component origin (exact absolute hotspots; rotation semantics of
    the original symbol is flattened into the pin offsets).
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    ole = olefile.OleFileIO(str(path))
    try:
        data = ole.openstream("FileHeader").read()
    finally:
        ole.close()
    return ir_from_records(_records(data), f"schdoc:{path.name}")


def ir_from_records(records, source: str) -> SchematicIR:
    """Build a SchematicIR from (kicad_index, props) record pairs.
    Shared by the binary FileHeader path and the ASCII variant reader."""
    ir = SchematicIR(source=source)

    comps: dict[int, dict] = {}
    comp_des: dict[int, str] = {}
    comp_params: dict[int, dict[str, str]] = {}
    comp_fp: dict[int, str] = {}
    impl_owner: dict[int, int] = {}
    impls: list[dict] = []
    pins: list[dict] = []

    for idx, rec in records:
        rt = rec.get("RECORD", "")
        if rt == RT_COMPONENT:
            comps[idx] = rec
        elif rt == RT_PIN:
            pins.append((idx, rec))
        elif rt == RT_WIRE:
            n = _int(rec, "LOCATIONCOUNT")
            pts = [
                (float(_int(rec, f"X{k}")), float(_int(rec, f"Y{k}")))
                for k in range(1, n + 1)
            ]
            if len(pts) >= 2:
                ir.wires.append(IRWire(points=pts))
        elif rt == RT_NET_LABEL:
            x, y = _loc(rec)
            ir.labels.append(IRNetLabel(x=x, y=y, text=rec.get("TEXT", "")))
        elif rt == RT_POWER_PORT:
            x, y = _loc(rec)
            ir.power_ports.append(
                IRPowerPort(x=x, y=y, net=rec.get("TEXT", ""),
                            orient=float(_int(rec, "ORIENTATION")) * 90.0)
            )
        elif rt == RT_DESIGNATOR:
            comp_des[_int(rec, "OWNERINDEX", -1)] = rec.get("TEXT", "")
        elif rt == RT_PARAMETER:
            oi = _int(rec, "OWNERINDEX", -1)
            if oi >= 0:
                comp_params.setdefault(oi, {})[rec.get("NAME", "")] = rec.get("TEXT", "")
        elif rt in (RT_IMPL_LIST, RT_IMPLEMENTATION):
            impl_owner[idx] = _int(rec, "OWNERINDEX", -1)
            if rt == RT_IMPLEMENTATION:
                rec["_IDX"] = idx
                impls.append(rec)

    for imp in impls:
        if imp.get("ISCURRENT", "").upper() != "T":
            continue
        if imp.get("MODELTYPE", "").upper() not in ("PCBLIB", "PCBLIBRARY"):
            continue
        owner = impl_owner.get(imp["_IDX"], -1)
        comp_idx = impl_owner.get(owner, owner)
        if comp_idx in comps:
            comp_fp[comp_idx] = imp.get("MODELNAME", "")

    comp_objs: dict[int, IRComponent] = {}
    for idx, crec in comps.items():
        ref = comp_des.get(idx, f"#{idx}")
        params = comp_params.get(idx, {})
        comp = IRComponent(
            ref=ref,
            value=params.get("Comment", "") or crec.get("DESIGNITEMID", ""),
            footprint=comp_fp.get(idx, ""),
            device=crec.get("LIBREFERENCE", ""),
            description=crec.get("COMPONENTDESCRIPTION", ""),
            x=float(_int(crec, "LOCATION.X")),
            y=float(_int(crec, "LOCATION.Y")),
            rotation=0.0,
            mirror=False,
        )
        comp_objs[idx] = comp
        ir.components.append(comp)

    for _, prec in pins:
        oi = _int(prec, "OWNERINDEX", -1)
        comp = comp_objs.get(oi)
        if comp is None:
            continue
        opdm = (prec.get("OWNERPARTDISPLAYMODE") or "").strip() or "0"
        comp_mode = (comps[oi].get("DISPLAYMODE") or "").strip() or "0"
        if opdm != "0" and opdm != comp_mode:
            continue
        partcount = int((comps[oi].get("PARTCOUNT") or "1").strip() or "1")
        if partcount > 1:
            owner_part = (prec.get("OWNERPARTID") or "").strip()
            if owner_part and owner_part != "0":
                current_part = (comps[oi].get("CURRENTPARTID") or "1").strip()
                if owner_part != current_part:
                    continue
        x, y = _loc(prec)
        orient = _int(prec, "PINCONGLOMERATE") & 3
        dx, dy = _ORIENT_DIRS.get(orient, (0, 0))
        ln = _int(prec, "PINLENGTH", 0)
        hx, hy = x + dx * ln, y + dy * ln  # hotspot (absolute)
        # body is on the opposite side: into-body dir = -dir(orient)
        into = (orient + 2) % 4
        idir = _ORIENT_DIRS[into]
        import math as _math

        comp.pins.append(
            IRPin(
                number=prec.get("DESIGNATOR", "") or "?",
                name=prec.get("NAME", ""),
                x=hx - comp.x,
                y=hy - comp.y,
                length=float(ln),
                orient_into_body=_math.degrees(_math.atan2(idir[1], idir[0])) % 360,
            )
        )
    return ir
