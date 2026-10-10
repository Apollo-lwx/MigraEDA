"""Shared data models for MigraEDA."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class DiffGrade(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass
class Component:
    ref: str
    value: str = ""
    footprint: str = ""
    layer: str = ""


@dataclass
class Via:
    x: float = 0.0
    y: float = 0.0
    net: str = ""


@dataclass
class ProjectModel:
    """Parsed EasyEDA / MigraEDA project content."""

    name: str
    source_path: str = ""
    components: list[Component] = field(default_factory=list)
    net_names: list[str] = field(default_factory=list)
    vias: list[Via] = field(default_factory=list)
    layers: int = 2
    meta: dict[str, Any] = field(default_factory=dict)

    def to_stats(self) -> "ProjectStats":
        return ProjectStats(
            name=self.name,
            component_count=len(self.components),
            component_refs=sorted(c.ref for c in self.components),
            net_names=sorted(set(self.net_names)),
            via_count=len(self.vias),
            layers=self.layers,
            source=self.source_path,
        )


@dataclass
class ProjectStats:
    name: str
    component_count: int = 0
    component_refs: list[str] = field(default_factory=list)
    net_names: list[str] = field(default_factory=list)
    via_count: int = 0
    layers: int = 2
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProjectStats":
        return cls(
            name=str(data.get("name", "")),
            component_count=int(data.get("component_count", 0)),
            component_refs=list(data.get("component_refs") or []),
            net_names=list(data.get("net_names") or []),
            via_count=int(data.get("via_count", 0)),
            layers=int(data.get("layers", 2)),
            source=str(data.get("source", "")),
        )


@dataclass
class DiffCheck:
    name: str
    grade: DiffGrade
    message: str
    source_value: Any = None
    target_value: Any = None


@dataclass
class DiffResult:
    grade: DiffGrade
    checks: list[DiffCheck] = field(default_factory=list)
    source: ProjectStats | None = None
    target: ProjectStats | None = None
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "grade": self.grade.value,
            "summary": self.summary,
            "checks": [
                {
                    "name": c.name,
                    "grade": c.grade.value,
                    "message": c.message,
                    "source_value": c.source_value,
                    "target_value": c.target_value,
                }
                for c in self.checks
            ],
            "source": self.source.to_dict() if self.source else None,
            "target": self.target.to_dict() if self.target else None,
        }
