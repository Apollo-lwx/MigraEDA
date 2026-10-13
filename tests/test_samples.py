"""Sample directory convention tests."""

from __future__ import annotations

from pathlib import Path

from migraeda.samples import classify, scan_samples, describe


def _mk_tree(root: Path) -> Path:
    proj = root / "G318"
    proj.mkdir(parents=True)
    (proj / "board.eprj").write_bytes(b"x")
    (proj / "a.SchDoc").write_bytes(b"x")
    (proj / "b.PcbDoc").write_bytes(b"x")
    (proj / "lib.SchLib").write_bytes(b"x")
    (proj / "lib.PcbLib").write_bytes(b"x")
    (proj / "notes.txt").write_text("ignore me")
    (proj / "out").mkdir()
    (proj / "out" / "report.md").write_text("ignored dir")
    return root


def test_classify() -> None:
    assert classify(Path("x.eprj")) == "lceda_project"
    assert classify(Path("x.SchDoc")) == "altium_schematic"
    assert classify(Path("x.PCBDOC")) == "altium_pcb"
    assert classify(Path("x.pcblib")) == "altium_footprint_lib"
    assert classify(Path("x.txt")) is None


def test_scan_samples(tmp_path: Path) -> None:
    root = _mk_tree(tmp_path / "samples")
    sets = scan_samples(root)
    assert "G318" in sets
    ss = sets["G318"]
    assert ss.first("lceda_project").name == "board.eprj"
    assert ss.first("altium_schematic").name == "a.SchDoc"
    assert ss.first("altium_pcb").name == "b.PcbDoc"
    assert ss.first("altium_symbol_lib").name == "lib.SchLib"
    assert ss.first("altium_footprint_lib").name == "lib.PcbLib"
    # notes.txt and out/ are not classified
    assert all("notes.txt" not in f.name for fs in ss.files.values() for f in fs)
    text = describe(root)
    assert "G318" in text and "AD封装库" in text


def test_scan_empty(tmp_path: Path) -> None:
    assert scan_samples(tmp_path / "nope") == {}
    assert "还没有" in describe(tmp_path / "nope")
