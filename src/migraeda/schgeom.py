"""Geometry-based schematic connectivity reconstruction.

Shared by the LCEDA (.eprj) and Altium (.SchDoc) frontends: both provide
wire polylines, electrical pin points, net labels and power-port names;
this engine turns them into net -> pin memberships via union-find.

Connection semantics (standard EDA rules, no junction records available):
- shared endpoints connect;
- endpoint of one wire lying on another wire's segment (T-junction) connects;
- two segments crossing in their interiors does NOT connect (no junction dot);
- a pin point lying anywhere on a wire attaches to that wire's net.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class UnionFind:
    def __init__(self) -> None:
        self.parent: dict[object, object] = {}

    def find(self, x: object) -> object:
        p = self.parent.setdefault(x, x)
        while p != self.parent[p]:
            self.parent[p] = self.parent[self.parent[p]]
            p = self.parent[p]
        self.parent[x] = p
        return p

    def union(self, a: object, b: object) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


Point = tuple[float, float]
Segment = tuple[float, float, float, float]


def _on_segment(px: float, py: float, s: Segment, strict_interior: bool = False) -> bool:
    x1, y1, x2, y2 = s
    eps = 1e-6
    cross = (px - x1) * (y2 - y1) - (py - y1) * (x2 - x1)
    if abs(cross) > eps:
        return False
    dot = (px - x1) * (x2 - x1) + (py - y1) * (y2 - y1)
    if dot < -eps:
        return False
    seg_len2 = (x2 - x1) ** 2 + (y2 - y1) ** 2
    if dot - seg_len2 > eps:
        return False
    if strict_interior:
        return dot > eps and dot < seg_len2 - eps
    return True


def _seg_intersect_interior(a: Segment, b: Segment) -> bool:
    """True if two segments cross in a way that is NOT an endpoint/T touch."""

    def ccw(p1: Point, p2: Point, p3: Point) -> float:
        return (p2[0] - p1[0]) * (p3[1] - p1[1]) - (p2[1] - p1[1]) * (p3[0] - p1[0])

    a1, a2 = (a[0], a[1]), (a[2], a[3])
    b1, b2 = (b[0], b[1]), (b[2], b[3])
    d1 = ccw(b1, b2, a1)
    d2 = ccw(b1, b2, a2)
    d3 = ccw(a1, a2, b1)
    d4 = ccw(a1, a2, b2)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)) and d1 != 0 and d2 != 0 and d3 != 0 and d4 != 0


@dataclass
class PinPoint:
    """An electrical connection point (component pin, power port pin...)."""

    owner: str  # e.g. designator or synthetic id
    pin: str  # pin number
    x: float
    y: float
    no_connect: bool = False
    virtual: bool = False  # inferred from wire end near unresolved symbol


@dataclass
class NetGroup:
    net_id: int
    names: set[str] = field(default_factory=set)
    pins: list[PinPoint] = field(default_factory=list)
    seg_idxs: list[int] = field(default_factory=list)  # indices into self._segments


class SchematicConnectivity:
    def __init__(self) -> None:
        self._segments: list[tuple[int, Segment]] = []  # (wire_id, segment)
        self._pins: list[PinPoint] = []
        self._wire_names: dict[int, str] = {}  # wire_id -> label
        self._global_names: set[str] = set()
        self._junctions: list[Point] = []
        self._labels: list[tuple[float, float, str]] = []  # net labels by position

    def add_junction(self, x: float, y: float) -> None:
        self._junctions.append((x, y))

    def add_label(self, x: float, y: float, name: str,
                  wire_id: int | None = None) -> None:
        if wire_id is not None:
            # label bound to a specific wire: name it directly, no guessing
            self._wire_names[wire_id] = name
        else:
            self._labels.append((x, y, name))

    def add_wire(self, wire_id: int, points: list[Point], name: str | None = None) -> None:
        for i in range(len(points) - 1):
            seg: Segment = (points[i][0], points[i][1], points[i + 1][0], points[i + 1][1])
            if seg[0] == seg[2] and seg[1] == seg[3]:
                # degenerate "segment" = a connection point marker (LCEDA
                # stores these as named net points): junction + label there
                self._junctions.append((seg[0], seg[1]))
                if name:
                    self._labels.append((seg[0], seg[1], name))
                continue
            self._segments.append((wire_id, seg))
        if name:
            self._wire_names[wire_id] = name

    def add_pin(self, pin: PinPoint, net_name: str | None = None) -> None:
        self._pins.append(pin)
        if net_name:
            # power port style: pin itself names its net, globally
            self._global_names.add(net_name)
            self._pins[-1].no_connect = False
            self._power_name = getattr(self, "_power_name", {})
            self._power_name[(pin.owner, pin.pin, pin.x, pin.y)] = net_name

    def add_global_net(self, name: str) -> None:
        self._global_names.add(name)

    def resolve(self) -> list[NetGroup]:
        uf = UnionFind()
        # 1. union segments: endpoints equal, T-touches
        segs = self._segments
        for i in range(len(segs)):
            uf.find(("seg", i))
        endpoints: dict[tuple[float, float], list[int]] = {}
        for i, (_, s) in enumerate(segs):
            for pt in ((s[0], s[1]), (s[2], s[3])):
                endpoints.setdefault(pt, []).append(i)
        for idxs in endpoints.values():
            for j in idxs[1:]:
                uf.union(("seg", idxs[0]), ("seg", j))
        # T-touches: endpoint strictly inside another segment
        for pt, idxs in endpoints.items():
            for k, (_, s) in enumerate(segs):
                if k in idxs:
                    continue
                if _on_segment(pt[0], pt[1], s, strict_interior=True):
                    uf.union(("seg", idxs[0]), ("seg", k))
        # junction dots: connect every segment passing under the junction
        for jx, jy in self._junctions:
            hits = [k for k, (_, s) in enumerate(segs) if _on_segment(jx, jy, s)]
            for k in hits[1:]:
                uf.union(("seg", hits[0]), ("seg", k))
        # X crossings without junction: explicitly left unconnected.

        # net labels: attach their name to the segment they sit on,
        # or to pins at the same point (degenerate net-point wires)
        label_names: dict[int, list[str]] = {}
        pin_labels: dict[int, list[str]] = {}
        pin_points0: dict[tuple[float, float], list[int]] = {}
        for pi, pin in enumerate(self._pins):
            pin_points0.setdefault((pin.x, pin.y), []).append(pi)
        for lx, ly, lname in self._labels:
            best = None
            best_d = 9.0  # allow small placement offset
            for i, (_, s) in enumerate(segs):
                if _on_segment(lx, ly, s):
                    best = i
                    break
                # distance from point to segment (axis-aligned fast path)
                x1, y1, x2, y2 = s
                if x1 == x2:
                    d = abs(lx - x1) if min(y1, y2) <= ly <= max(y1, y2) else 1e9
                elif y1 == y2:
                    d = abs(ly - y1) if min(x1, x2) <= lx <= max(x1, x2) else 1e9
                else:
                    d = 1e9
                if d < best_d:
                    best_d = d
                    best = i
            if best is not None:
                label_names.setdefault(best, []).append(lname)
            else:
                for pi in pin_points0.get((lx, ly), []):
                    pin_labels.setdefault(pi, []).append(lname)

        # 2. pins onto segments + pins abutting other pins (Altium allows
        # direct pin-to-pin and pin-to-powerport connection with no wire).
        # A pin hotspot attaches to EVERY segment under it: at a crossing the
        # pin itself forms the junction (standard EDA semantics).
        pin_points: dict[tuple[float, float], list[int]] = {}
        for pi, pin in enumerate(self._pins):
            pin_points.setdefault((pin.x, pin.y), []).append(pi)
            hit_any = False
            for i, (_, s) in enumerate(segs):
                if _on_segment(pin.x, pin.y, s):
                    uf.union(("pin", pi), ("seg", i))
                    hit_any = True
            if not hit_any:
                uf.find(("pin", pi))  # standalone group (unconnected pin)
        for idxs in pin_points.values():
            for j in idxs[1:]:
                uf.union(("pin", idxs[0]), ("pin", j))

        # 3. group
        groups: dict[object, NetGroup] = {}

        def group_of(key: object) -> NetGroup:
            root = uf.find(key)
            if root not in groups:
                groups[root] = NetGroup(net_id=len(groups))
            return groups[root]

        power_names: dict[object, str] = getattr(self, "_power_name", {})
        for pi, pin in enumerate(self._pins):
            g = group_of(("pin", pi))
            g.pins.append(pin)
            pname = power_names.get((pin.owner, pin.pin, pin.x, pin.y))
            if pname:
                g.names.add(pname)
            for lname in pin_labels.get(pi, ()):  # degenerate net points at the pin
                g.names.add(lname)
        for i, (wid, _) in enumerate(segs):
            g = group_of(("seg", i))
            g.seg_idxs.append(i)
            if wid in self._wire_names:
                g.names.add(self._wire_names[wid])
            for lname in label_names.get(i, ()):  # labels sitting on this segment
                g.names.add(lname)

        # 4. merge groups that share a name (e.g. multiple GND power ports).
        # Altium treats net names case-insensitively (GRID1 == Grid1), so do we.
        by_name: dict[str, NetGroup] = {}
        merged: list[NetGroup] = []
        for g in groups.values():
            named = [n for n in g.names if n]
            target: NetGroup | None = None
            for n in named:
                key = n.upper()
                if key in by_name:
                    target = by_name[key]
                    break
            if target is g:
                target = None
            if target is not None and target is not g:
                target.names.update(g.names)
                target.pins.extend(g.pins)
                target.seg_idxs.extend(g.seg_idxs)
                for n in g.names:
                    by_name[n.upper()] = target
            else:
                for n in g.names:
                    by_name[n.upper()] = g
                merged.append(g)
        return merged
