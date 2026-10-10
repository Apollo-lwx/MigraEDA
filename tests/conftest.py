from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "fixtures" / "golden"


@pytest.fixture
def golden_dir() -> Path:
    return GOLDEN


@pytest.fixture
def simple_epro(golden_dir: Path) -> Path:
    return golden_dir / "simple.epro"


@pytest.fixture
def bus_epro(golden_dir: Path) -> Path:
    return golden_dir / "bus_mismatch.epro"


@pytest.fixture
def audit_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "audit"
    root.mkdir()
    monkeypatch.setenv("MIGRAEDA_AUDIT_DIR", str(root))
    return root
