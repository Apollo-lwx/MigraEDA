"""Parse synthetic (and loosely real-shaped) .epro ZIP archives.

NOTE: Fixtures are *synthetic* — field names approximate public EasyEDA Pro
descriptions (project.json, .esch / .epcb style JSON). This is NOT the official
complete schema.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

from migraeda.models import Component, ProjectModel, Via


class EproParseError(ValueError):
    """Raised when an .epro archive cannot be parsed."""


def _load_json_member(zf: zipfile.ZipFile, name: str) -> Any:
    with zf.open(name) as fh:
        return json.loads(fh.read().decode("utf-8"))


def _find_members(names: list[str], suffix: str) -> list[str]:
    return sorted(n for n in names if n.lower().endswith(suffix) and not n.endswith("/"))


def _extract_components(board: dict[str, Any]) -> list[Component]:
    raw = board.get("components") or board.get("FOOTPRINT") or []
    out: list[Component] = []
    for item in raw:
        if isinstance(item, str):
            out.append(Component(ref=item))
            continue
        if not isinstance(item, dict):
            continue
        ref = str(item.get("ref") or item.get("designator") or item.get("id") or "")
        if not ref:
            continue
        out.append(
            Component(
                ref=ref,
                value=str(item.get("value") or ""),
                footprint=str(item.get("footprint") or item.get("package") or ""),
                layer=str(item.get("layer") or ""),
            )
        )
    return out


def _extract_nets(board: dict[str, Any]) -> list[str]:
    nets = board.get("nets") or board.get("NETS") or []
    names: list[str] = []
    for n in nets:
        if isinstance(n, str):
            names.append(n)
        elif isinstance(n, dict):
            name = n.get("name") or n.get("net") or n.get("id")
            if name:
                names.append(str(name))
    return names


def _extract_vias(board: dict[str, Any]) -> list[Via]:
    vias = board.get("vias") or board.get("VIA") or []
    out: list[Via] = []
    for v in vias:
        if not isinstance(v, dict):
            out.append(Via())
            continue
        out.append(
            Via(
                x=float(v.get("x", 0)),
                y=float(v.get("y", 0)),
                net=str(v.get("net") or ""),
            )
        )
    return out


def parse_epro(path: str | Path) -> ProjectModel:
    """Parse an .epro (ZIP) into a ProjectModel."""
    path = Path(path)
    if not path.is_file():
        raise EproParseError(f"file not found: {path}")
    if not zipfile.is_zipfile(path):
        raise EproParseError(f"not a ZIP/.epro archive: {path}")

    member_names: list[str] = []
    with zipfile.ZipFile(path, "r") as zf:
        names = zf.namelist()
        member_names = list(names)
        project: dict[str, Any] = {}
        if "project.json" in names:
            project = _load_json_member(zf, "project.json")
        elif any(n.endswith("project.json") for n in names):
            pj = next(n for n in names if n.endswith("project.json"))
            project = _load_json_member(zf, pj)

        name = str(project.get("name") or project.get("title") or path.stem)
        layers = int(project.get("layers") or project.get("copper_layers") or 2)

        board_files = (
            _find_members(names, ".epcb.json")
            + _find_members(names, ".epcb")
            + [n for n in names if "boards/" in n and n.endswith(".json")]
        )
        # de-dupe preserving order
        seen: set[str] = set()
        unique_boards: list[str] = []
        for b in board_files:
            if b not in seen:
                seen.add(b)
                unique_boards.append(b)

        components: list[Component] = []
        net_names: list[str] = []
        vias: list[Via] = []

        if not unique_boards:
            # allow project.json-only fixtures with embedded board
            if "board" in project and isinstance(project["board"], dict):
                board = project["board"]
                components = _extract_components(board)
                net_names = _extract_nets(board)
                vias = _extract_vias(board)
            else:
                raise EproParseError("no board data found in .epro")
        else:
            for bf in unique_boards:
                try:
                    board = _load_json_member(zf, bf)
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    raise EproParseError(f"invalid JSON in {bf}: {exc}") from exc
                if not isinstance(board, dict):
                    continue
                components.extend(_extract_components(board))
                net_names.extend(_extract_nets(board))
                vias.extend(_extract_vias(board))
                if "layers" in board:
                    layers = int(board["layers"])

        # optional schematic nets merge
        sheet_files = _find_members(names, ".esch.json") + _find_members(names, ".esch")
        for sf in sheet_files:
            try:
                sheet = _load_json_member(zf, sf)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if isinstance(sheet, dict):
                net_names.extend(_extract_nets(sheet))

    # unique nets, keep order then sort later in stats
    uniq_nets = list(dict.fromkeys(net_names))

    return ProjectModel(
        name=name,
        source_path=str(path.resolve()),
        components=components,
        net_names=uniq_nets,
        vias=vias,
        layers=layers,
        meta={"synthetic_fixture": True, "archive_members": member_names},
    )
