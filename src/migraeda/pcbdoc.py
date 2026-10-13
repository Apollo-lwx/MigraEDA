"""Parse Altium Designer .PcbDoc files (PCB 6.0 binary, OLE/CFB container).

Only extracts what functional verification needs:
- components (designator, footprint/pattern, lib reference, description)
- nets (names, stream order = index base for binary records)
- pads (pin name, net index, component index, position)
- vias (net index, position)

Binary layouts follow KiCad's Altium importer documentation
(https://dev-docs.kicad.org/en/import-formats/altium/).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

import olefile

MIL = 1.0 / 10000.0  # altium internal unit -> mil


@dataclass
class PcbComponent:
    designator: str
    pattern: str = ""
    lib_reference: str = ""
    description: str = ""
    layer: str = ""
    x_mil: float = 0.0
    y_mil: float = 0.0
    rotation: float = 0.0


@dataclass
class PcbPad:
    name: str
    net_index: int  # -1 = unconnected
    component_index: int  # -1 = free pad
    x_mil: float = 0.0
    y_mil: float = 0.0
    size_x_mil: float = 0.0
    size_y_mil: float = 0.0
    hole_mil: float = 0.0
    shape: int = 0  # 1=circle 2=rect 3=octagon 9=rounded-rect
    layer: int = 0


@dataclass
class PcbVia:
    net_index: int
    x_mil: float = 0.0
    y_mil: float = 0.0
    diameter_mil: float = 0.0
    hole_mil: float = 0.0


@dataclass
class PcbTrack:
    layer: int
    net_index: int
    x1: float
    y1: float
    x2: float
    y2: float
    width: float


@dataclass
class PcbArc:
    layer: int
    net_index: int
    cx: float
    cy: float
    radius: float
    start_angle: float
    end_angle: float
    width: float


@dataclass
class PcbFill:
    layer: int
    net_index: int
    x1: float
    y1: float
    x2: float
    y2: float
    rotation: float


@dataclass
class PcbPolygon:
    net_index: int
    layer: str
    vertices: list[tuple[float, float]] = field(default_factory=list)


@dataclass
class PcbNetlist:
    components: list[PcbComponent] = field(default_factory=list)
    nets: list[str] = field(default_factory=list)
    pads: list[PcbPad] = field(default_factory=list)
    vias: list[PcbVia] = field(default_factory=list)
    tracks: list[PcbTrack] = field(default_factory=list)
    arcs: list[PcbArc] = field(default_factory=list)
    fills: list[PcbFill] = field(default_factory=list)
    polygons: list[PcbPolygon] = field(default_factory=list)
    board_outline: list[tuple[float, float]] = field(default_factory=list)

    def pin_net_sets(self) -> dict[tuple[str, str], set[str]]:
        """(designator, pin_name) -> set of net names (>1 entry = conflict)."""
        out: dict[tuple[str, str], set[str]] = {}
        for pad in self.pads:
            if pad.net_index < 0 or pad.component_index < 0:
                continue
            if pad.component_index >= len(self.components):
                continue
            ref = self.components[pad.component_index].designator
            net = self.nets[pad.net_index] if pad.net_index < len(self.nets) else "?"
            out.setdefault((ref, pad.name), set()).add(net)
        return out

    def pin_net_map(self) -> dict[tuple[str, str], str]:
        """(designator, pin_name) -> net name (joins conflicts with '|')."""
        return {
            k: "|".join(sorted(v)) for k, v in self.pin_net_sets().items()
        }

    def distinct_designators(self) -> list[str]:
        seen: dict[str, None] = {}
        for c in self.components:
            if c.designator:
                seen[c.designator] = None
        return list(seen)

    def footprint_map(self) -> dict[str, list]:
        """Reconstruct footprint pad maps embedded in this board.

        Groups pads by component PATTERN, normalized into the component's
        own frame (translation + rotation undone). Returns
        {pattern: [PcbPad-with-relative-coords]} — comparable with library
        footprint pad maps without needing the .PcbLib file.
        """
        import math as _m

        out: dict[str, list] = {}
        for ci, comp in enumerate(self.components):
            if not comp.pattern:
                continue
            rad = _m.radians(-comp.rotation)
            c, s = _m.cos(rad), _m.sin(rad)
            for pad in self.pads:
                if pad.component_index != ci:
                    continue
                dx = pad.x_mil - comp.x_mil
                dy = pad.y_mil - comp.y_mil
                rx, ry = dx * c - dy * s, dx * s + dy * c
                if comp.layer.upper() == "BOTTOM":
                    ry = -ry  # bottom-side placement mirrors the footprint
                rel = PcbPad(
                    name=pad.name, net_index=pad.net_index,
                    component_index=pad.component_index,
                    x_mil=rx, y_mil=ry,
                    size_x_mil=pad.size_x_mil, size_y_mil=pad.size_y_mil,
                    hole_mil=pad.hole_mil, shape=pad.shape, layer=pad.layer,
                )
                out.setdefault(comp.pattern, []).append(rel)
        # dedupe pads shared by multiple instances of the same pattern
        for pattern, pads in out.items():
            seen: set[tuple] = set()
            uniq: list[PcbPad] = []
            for p in pads:
                key = (p.name, round(p.x_mil, 1), round(p.y_mil, 1))
                if key not in seen:
                    seen.add(key)
                    uniq.append(p)
            out[pattern] = uniq
        return out


def _decode(data: bytes) -> str:
    for enc in ("mbcs", "gbk", "utf-8", "latin-1"):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("latin-1", errors="replace")


def _read_props_records(data: bytes) -> list[dict[str, str]]:
    """Read 'Text Props' stream: uint32 length + '|KEY=VALUE|...' payload."""
    records: list[dict[str, str]] = []
    i = 0
    while i + 4 <= len(data):
        (ln,) = struct.unpack_from("<I", data, i)
        i += 4
        if ln == 0 or i + ln > len(data):
            break
        payload = _decode(data[i : i + ln]).rstrip("\x00")
        i += ln
        rec: dict[str, str] = {}
        for part in payload.split("|"):
            if not part:
                continue
            if "=" in part:
                k, v = part.split("=", 1)
                rec[k.strip().upper()] = v.strip()
        records.append(rec)
    return records


def _mil_str(s: str) -> float:
    s = s.strip()
    if s.lower().endswith("mil"):
        s = s[:-3]
    try:
        return float(s)
    except ValueError:
        return 0.0


def _float_str(s: str) -> float:
    try:
        return float(s.strip())
    except ValueError:
        return 0.0


def _parse_pads6(data: bytes) -> list[PcbPad]:
    pads: list[PcbPad] = []
    i = 0
    while i < len(data):
        rtype = data[i]
        i += 1
        if rtype != 2:  # PAD record type
            break
        name = ""
        net_index = -1
        comp_index = -1
        x = y = 0
        # six subrecords, each: uint32 length + data
        name = ""
        net_index = -1
        comp_index = -1
        x = y = 0
        sx = sy = hole = 0
        shape = 0
        layer = 0
        # six subrecords, each: uint32 length + data
        for sr in range(6):
            if i + 4 > len(data):
                break
            (ln,) = struct.unpack_from("<I", data, i)
            i += 4
            sub = data[i : i + ln]
            i += ln
            if sr == 0 and ln >= 1:  # pad name, pascal string
                nlen = sub[0]
                name = _decode(sub[1 : 1 + nlen])
            elif sr == 4 and ln >= 52:  # geometry/net/component/sizes
                layer = sub[0]
                net_raw = struct.unpack_from("<H", sub, 3)[0]
                comp_raw = struct.unpack_from("<H", sub, 7)[0]
                x, y = struct.unpack_from("<ii", sub, 13)
                sx, sy = struct.unpack_from("<ii", sub, 21)
                hole = struct.unpack_from("<i", sub, 45)[0]
                shape = sub[49]
                net_index = -1 if net_raw == 0xFFFF else net_raw
                comp_index = -1 if comp_raw == 0xFFFF else comp_raw
        pads.append(
            PcbPad(name=name, net_index=net_index, component_index=comp_index,
                   x_mil=x * MIL, y_mil=y * MIL,
                   size_x_mil=sx * MIL, size_y_mil=sy * MIL,
                   hole_mil=hole * MIL, shape=shape, layer=layer)
        )
    return pads


def _parse_vias6(data: bytes) -> list[PcbVia]:
    vias: list[PcbVia] = []
    i = 0
    while i < len(data):
        rtype = data[i]
        i += 1
        if rtype != 3:  # VIA record type
            break
        (ln,) = struct.unpack_from("<I", data, i)
        i += 4
        sub = data[i : i + ln]
        i += ln
        if ln < 29:
            continue
        net_raw = struct.unpack_from("<H", sub, 3)[0]
        x, y = struct.unpack_from("<ii", sub, 13)
        dia = hole = 0
        if ln >= 29:
            dia, hole = struct.unpack_from("<ii", sub, 21)
        vias.append(
            PcbVia(net_index=-1 if net_raw == 0xFFFF else net_raw,
                   x_mil=x * MIL, y_mil=y * MIL,
                   diameter_mil=dia * MIL, hole_mil=hole * MIL)
        )
    return vias


def _walk_binary_records(data: bytes, expect_type: int):
    """Yield subrecord payloads for [uint8 type][uint32 len][payload] streams."""
    i = 0
    while i + 5 <= len(data):
        rtype = data[i]
        i += 1
        if rtype != expect_type:
            break
        (ln,) = struct.unpack_from("<I", data, i)
        i += 4
        if ln == 0 or i + ln > len(data):
            break
        yield data[i : i + ln]
        i += ln


def _parse_tracks6(data: bytes) -> list[PcbTrack]:
    out: list[PcbTrack] = []
    for sub in _walk_binary_records(data, 4):
        if len(sub) < 33:
            continue
        layer = sub[0]
        net_raw = struct.unpack_from("<H", sub, 3)[0]
        x1, y1, x2, y2, width = struct.unpack_from("<iiiii", sub, 13)
        out.append(
            PcbTrack(layer=layer, net_index=-1 if net_raw == 0xFFFF else net_raw,
                     x1=x1 * MIL, y1=y1 * MIL, x2=x2 * MIL, y2=y2 * MIL,
                     width=width * MIL)
        )
    return out


def _parse_arcs6(data: bytes) -> list[PcbArc]:
    out: list[PcbArc] = []
    for sub in _walk_binary_records(data, 1):
        if len(sub) < 45:
            continue
        layer = sub[0]
        net_raw = struct.unpack_from("<H", sub, 3)[0]
        cx, cy, r = struct.unpack_from("<iii", sub, 13)
        sa, ea = struct.unpack_from("<dd", sub, 25)
        (width,) = struct.unpack_from("<i", sub, 41)
        out.append(
            PcbArc(layer=layer, net_index=-1 if net_raw == 0xFFFF else net_raw,
                   cx=cx * MIL, cy=cy * MIL, radius=r * MIL,
                   start_angle=sa, end_angle=ea, width=width * MIL)
        )
    return out


def _parse_fills6(data: bytes) -> list[PcbFill]:
    out: list[PcbFill] = []
    for sub in _walk_binary_records(data, 6):
        if len(sub) < 37:
            continue
        layer = sub[0]
        net_raw = struct.unpack_from("<H", sub, 3)[0]
        x1, y1, x2, y2 = struct.unpack_from("<iiii", sub, 13)
        (rot,) = struct.unpack_from("<d", sub, 29)
        out.append(
            PcbFill(layer=layer, net_index=-1 if net_raw == 0xFFFF else net_raw,
                    x1=x1 * MIL, y1=y1 * MIL, x2=x2 * MIL, y2=y2 * MIL,
                    rotation=rot)
        )
    return out


def parse_pcbdoc(path: str | Path) -> PcbNetlist:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    ole = olefile.OleFileIO(str(path))
    try:
        out = PcbNetlist()

        nets_data = ole.openstream("Nets6/Data").read()
        for rec in _read_props_records(nets_data):
            out.nets.append(rec.get("NAME", ""))

        comps_data = ole.openstream("Components6/Data").read()
        for rec in _read_props_records(comps_data):
            out.components.append(
                PcbComponent(
                    designator=rec.get("SOURCEDESIGNATOR", ""),
                    pattern=rec.get("PATTERN", ""),
                    lib_reference=rec.get("SOURCELIBREFERENCE", ""),
                    description=rec.get("SOURCEDESCRIPTION", ""),
                    layer=rec.get("LAYER", ""),
                    x_mil=_mil_str(rec.get("X", "0")),
                    y_mil=_mil_str(rec.get("Y", "0")),
                    rotation=_float_str(rec.get("ROTATION", "0")),
                )
            )

        if ole.exists("Pads6/Data"):
            out.pads = _parse_pads6(ole.openstream("Pads6/Data").read())
        if ole.exists("Vias6/Data"):
            out.vias = _parse_vias6(ole.openstream("Vias6/Data").read())
        if ole.exists("Tracks6/Data"):
            out.tracks = _parse_tracks6(ole.openstream("Tracks6/Data").read())
        if ole.exists("Arcs6/Data"):
            out.arcs = _parse_arcs6(ole.openstream("Arcs6/Data").read())
        if ole.exists("Fills6/Data"):
            out.fills = _parse_fills6(ole.openstream("Fills6/Data").read())
        if ole.exists("Polygons6/Data"):
            for rec in _read_props_records(ole.openstream("Polygons6/Data").read()):
                verts: list[tuple[float, float]] = []
                k = 0
                while f"VX{k}" in rec and f"VY{k}" in rec:
                    verts.append((_mil_str(rec[f"VX{k}"]), _mil_str(rec[f"VY{k}"])))
                    k += 1
                net_raw = rec.get("NET", "-1")
                out.polygons.append(
                    PcbPolygon(
                        net_index=int(net_raw) if net_raw.lstrip("-").isdigit() else -1,
                        layer=rec.get("LAYER", ""),
                        vertices=verts,
                    )
                )
        if ole.exists("Board6/Data"):
            boards = _read_props_records(ole.openstream("Board6/Data").read())
            if boards:
                b = boards[0]
                k = 0
                while f"VX{k}" in b and f"VY{k}" in b:
                    out.board_outline.append(
                        (_mil_str(b[f"VX{k}"]), _mil_str(b[f"VY{k}"]))
                    )
                    k += 1

        return out
    finally:
        ole.close()
