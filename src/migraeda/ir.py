"""Schematic intermediate representation (IR) for conversion.

Carries everything needed to rebuild a schematic document in another
EDA format: components with geometry and pins, wires, net labels and
power ports. Verification models (NetlistModel) can be derived from it,
and both directions of conversion pass through it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


def pin_abs(comp: "IRComponent", pin: "IRPin") -> tuple[float, float]:
    """Canonical pin transform: mirror (flip X) then rotate CW by
    comp.rotation, then translate to comp origin.

    This is the convention validated against real .eprj data; every
    extractor normalizes its source-specific transform into it, and
    every writer uses it to recompute absolute pin hotspots.
    """
    x = -pin.x if comp.mirror else pin.x
    y = pin.y
    rad = math.radians(-comp.rotation)
    c, s = math.cos(rad), math.sin(rad)
    tx, ty = x * c - y * s, x * s + y * c
    return comp.x + tx, comp.y + ty


@dataclass
class IRPin:
    number: str
    name: str = ""
    # position relative to component origin, in the component's own
    # (unrotated, unmirrored) frame; (x, y) is the ELECTRICAL hotspot.
    x: float = 0.0
    y: float = 0.0
    length: float = 10.0
    # angle the pin line goes from the hotspot INTO the symbol body,
    # degrees CCW in the component frame (0=+x, 90=+y, ...)
    orient_into_body: float = 0.0


@dataclass
class IRComponent:
    ref: str
    value: str = ""
    footprint: str = ""
    device: str = ""
    description: str = ""
    x: float = 0.0
    y: float = 0.0
    rotation: float = 0.0  # degrees CCW
    mirror: bool = False
    pins: list[IRPin] = field(default_factory=list)


@dataclass
class IRWire:
    points: list[tuple[float, float]]
    net: str | None = None  # attached net name, if labeled at the wire


@dataclass
class IRNetLabel:
    x: float
    y: float
    text: str
    wire_idx: int | None = None  # index of the wire this label names, if known


@dataclass
class IRPowerPort:
    x: float
    y: float
    net: str
    orient: float = 0.0


@dataclass
class SchematicIR:
    source: str = ""
    components: list[IRComponent] = field(default_factory=list)
    wires: list[IRWire] = field(default_factory=list)
    labels: list[IRNetLabel] = field(default_factory=list)
    power_ports: list[IRPowerPort] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def sheet_extent(self) -> tuple[float, float, float, float]:
        xs: list[float] = []
        ys: list[float] = []
        for w in self.wires:
            for px, py in w.points:
                xs.append(px)
                ys.append(py)
        for c in self.components:
            xs.append(c.x)
            ys.append(c.y)
        if not xs:
            return (0.0, 0.0, 1000.0, 800.0)
        return (min(xs), min(ys), max(xs), max(ys))
