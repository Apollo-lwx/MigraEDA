"""libinspect tests."""

from __future__ import annotations

from pathlib import Path

from migraeda.libinspect import _sniff, inspect_library


def test_sniff(tmp_path: Path) -> None:
    ole = tmp_path / "a.PcbDoc"
    ole.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 8)
    assert _sniff(ole) == "ole"

    sq = tmp_path / "b.eprj"
    sq.write_bytes(b"SQLite format 3\x00")
    assert _sniff(sq) == "sqlite"

    asc = tmp_path / "c.SchDoc"
    asc.write_bytes(b"|HEADER=Protel for Windows - Schematic Capture Ascii")
    assert _sniff(asc) == "ascii"

    other = tmp_path / "d.bin"
    other.write_bytes(b"\x01\x02\x03\x04")
    assert _sniff(other) == "unknown"


def test_inspect_ascii(tmp_path: Path) -> None:
    asc = tmp_path / "c.SchDoc"
    asc.write_text("|HEADER=Protel for Windows - Schematic Capture Ascii File Version 5.0|WEIGHT=0\n")
    out = inspect_library(asc)
    assert "ascii" in out.lower()
    assert "WEIGHT=0" in out


def test_inspect_unknown(tmp_path: Path) -> None:
    other = tmp_path / "d.bin"
    other.write_bytes(b"\x01\x02\x03\x04")
    out = inspect_library(other)
    assert "unknown" in out or "非 OLE" in out
