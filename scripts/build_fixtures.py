#!/usr/bin/env python3
"""Build synthetic .epro golden fixtures (ZIP + JSON). Not official schema."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "fixtures" / "golden"


def write_epro(path: Path, project: dict, board: dict, sheet: dict | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("project.json", json.dumps(project, indent=2) + "\n")
        zf.writestr("boards/main.epcb.json", json.dumps(board, indent=2) + "\n")
        if sheet is not None:
            zf.writestr("sheets/main.esch.json", json.dumps(sheet, indent=2) + "\n")
        zf.writestr(
            "README_FIXTURE.txt",
            "SYNTHETIC MigraEDA fixture — NOT official EasyEDA Pro schema.\n",
        )


def main() -> None:
    # --- simple: clean 2-layer board ---
    simple_project = {
        "name": "simple",
        "layers": 2,
        "version": "synthetic-1",
        "note": "synthetic fixture",
    }
    simple_board = {
        "layers": 2,
        "components": [
            {"ref": "R1", "value": "10k", "footprint": "R_0805"},
            {"ref": "C1", "value": "100n", "footprint": "C_0805"},
            {"ref": "U1", "value": "STM32", "footprint": "LQFP48"},
        ],
        "nets": ["GND", "VCC_3V3", "NET_NRESET", "NET_SWDIO", "NET_SWCLK"],
        "vias": [
            {"x": 10, "y": 10, "net": "GND"},
            {"x": 12, "y": 10, "net": "GND"},
            {"x": 14, "y": 10, "net": "VCC_3V3"},
            {"x": 16, "y": 10, "net": "VCC_3V3"},
        ],
    }
    simple_sheet = {"nets": ["GND", "VCC_3V3", "NET_NRESET", "NET_SWDIO", "NET_SWCLK"]}
    write_epro(GOLDEN / "simple.epro", simple_project, simple_board, simple_sheet)

    # --- bus_mismatch: same comps/vias, net set differs (for WARN/FAIL demos) ---
    bus_project = {
        "name": "bus_mismatch",
        "layers": 2,
        "version": "synthetic-1",
        "note": "intentional net-name drift for diff demos",
    }
    bus_board = {
        "layers": 2,
        "components": [
            {"ref": "R1", "value": "10k", "footprint": "R_0805"},
            {"ref": "C1", "value": "100n", "footprint": "C_0805"},
            {"ref": "U1", "value": "STM32", "footprint": "LQFP48"},
            {"ref": "J1", "value": "HDR", "footprint": "PinHeader_1x04"},
        ],
        "nets": ["GND", "VCC_3V3", "BUS_D0", "BUS_D1", "BUS_D2", "LEGACY_CLK"],
        "vias": [
            {"x": 1, "y": 1, "net": "GND"},
            {"x": 2, "y": 1, "net": "VCC_3V3"},
            {"x": 3, "y": 1, "net": "BUS_D0"},
        ],
    }
    write_epro(GOLDEN / "bus_mismatch.epro", bus_project, bus_board)

    # also write a companion "post-migrate" stats with intentional WARN (1 net rename)
    warn_stats = {
        "name": "bus_mismatch",
        "component_count": 4,
        "component_refs": ["C1", "J1", "R1", "U1"],
        "net_names": ["BUS_D0", "BUS_D1", "BUS_D2", "GND", "VCC_3V3", "CLK"],  # LEGACY_CLK→CLK
        "via_count": 3,
        "layers": 2,
        "source": "fixture-companion",
    }
    (GOLDEN / "bus_mismatch_target_warn.json").write_text(
        json.dumps(warn_stats, indent=2) + "\n", encoding="utf-8"
    )

    fail_stats = {
        "name": "bus_mismatch",
        "component_count": 2,
        "component_refs": ["R1", "C1"],
        "net_names": ["GND"],
        "via_count": 0,
        "layers": 2,
        "source": "fixture-companion-fail",
    }
    (GOLDEN / "bus_mismatch_target_fail.json").write_text(
        json.dumps(fail_stats, indent=2) + "\n", encoding="utf-8"
    )

    print(f"wrote fixtures under {GOLDEN}")


if __name__ == "__main__":
    main()
