"""Library model: symbols (pins), footprints (pads), device bindings."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LibPin:
    number: str
    name: str = ""
    x: float = 0.0
    y: float = 0.0
    length: float = 0.0
    orient: float = 0.0  # degrees, into-body direction


@dataclass
class LibPad:
    number: str
    x: float = 0.0
    y: float = 0.0
    size_x: float = 0.0
    size_y: float = 0.0
    hole: float = 0.0
    shape: str = ""
    layer: str = ""


@dataclass
class LibSymbol:
    name: str
    pins: list[LibPin] = field(default_factory=list)
    bbox: tuple[float, float, float, float] | None = None


@dataclass
class LibFootprint:
    name: str
    pads: list[LibPad] = field(default_factory=list)
    bbox: tuple[float, float, float, float] | None = None


@dataclass
class LibDevice:
    name: str
    symbol: str = ""
    footprint: str = ""
    description: str = ""


@dataclass
class Library:
    source: str = ""
    symbols: dict[str, LibSymbol] = field(default_factory=dict)
    footprints: dict[str, LibFootprint] = field(default_factory=dict)
    devices: dict[str, LibDevice] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
