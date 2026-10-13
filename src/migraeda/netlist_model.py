"""Common netlist model shared by all frontends (eprj / SchDoc / PcbDoc)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SchComponent:
    ref: str
    value: str = ""
    footprint: str = ""
    device: str = ""
    description: str = ""


@dataclass
class NetlistModel:
    """Pin-level netlist + component table."""

    source: str = ""
    components: dict[str, SchComponent] = field(default_factory=dict)
    pin_nets: dict[tuple[str, str], str] = field(default_factory=dict)
    no_connects: set[tuple[str, str]] = field(default_factory=set)
    virtual_pins: set[tuple[str, str]] = field(default_factory=set)
    notes: list[str] = field(default_factory=list)

    def net_members(self) -> dict[str, list[tuple[str, str]]]:
        nets: dict[str, list[tuple[str, str]]] = {}
        for (ref, pin), net in self.pin_nets.items():
            nets.setdefault(net, []).append((ref, pin))
        for members in nets.values():
            members.sort()
        return nets

    def unnamed_net_count(self, marker: str = "~") -> int:
        return sum(1 for n in self.net_members() if n.startswith(marker))
