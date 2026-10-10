"""Normalize parsed projects into comparable ProjectStats."""

from __future__ import annotations

from pathlib import Path

from migraeda.epro_parse import parse_epro
from migraeda.models import ProjectModel, ProjectStats


def normalize_model(model: ProjectModel) -> ProjectStats:
    """Convert a ProjectModel into canonical ProjectStats."""
    stats = model.to_stats()
    # canonical sorting already done in to_stats; strip empty net names
    stats.net_names = sorted({n for n in stats.net_names if n})
    stats.component_refs = sorted({r for r in stats.component_refs if r})
    stats.component_count = len(stats.component_refs)
    return stats


def normalize_epro(path: str | Path) -> ProjectStats:
    """Parse + normalize an .epro path."""
    return normalize_model(parse_epro(path))


def normalize_stats_json(data: dict) -> ProjectStats:
    """Normalize a stats dict (e.g. from migrate output or kicad_stats.json)."""
    stats = ProjectStats.from_dict(data)
    stats.net_names = sorted({n for n in stats.net_names if n})
    stats.component_refs = sorted({r for r in stats.component_refs if r})
    if not stats.component_count:
        stats.component_count = len(stats.component_refs)
    return stats
