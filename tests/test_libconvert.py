"""libconvert round-trip tests."""

from __future__ import annotations

from pathlib import Path

from migraeda.convert import libconvert
from migraeda.eprj_lib import extract_eprj_library
from migraeda.libdiff import compare_libraries
from migraeda.libmodel import LibDevice, LibFootprint, LibPad, LibPin, LibSymbol, Library


def _demo_lib() -> Library:
    lib = Library(source="demo")
    lib.symbols["RES"] = LibSymbol(
        name="RES",
        pins=[
            LibPin(number="1", name="P1", x=-20, y=0, length=10, orient=0),
            LibPin(number="2", name="P2", x=20, y=0, length=10, orient=180),
        ],
    )
    lib.footprints["R0805"] = LibFootprint(
        name="R0805",
        pads=[
            LibPad(number="1", x=-37.4, y=0, size_x=44.6, size_y=54.2, hole=0, shape="RECT"),
            LibPad(number="2", x=37.4, y=0, size_x=44.6, size_y=54.2, hole=0, shape="RECT"),
        ],
    )
    lib.footprints["CAP-TH"] = LibFootprint(
        name="CAP-TH",
        pads=[
            LibPad(number="1", x=-196.8, y=0, size_x=59.0, size_y=59.0, hole=35.4, shape="ELLIPSE"),
            LibPad(number="2", x=196.8, y=0, size_x=59.0, size_y=59.0, hole=35.4, shape="ELLIPSE"),
        ],
    )
    lib.devices["1K"] = LibDevice(name="1K", footprint="R0805", description="1k resistor")
    return lib


def test_libconvert_roundtrip(tmp_path: Path) -> None:
    lib = _demo_lib()
    src = tmp_path / "demo_src.eprj"

    # seed a source .eprj containing the library, then libconvert it
    from migraeda.eprj_write import write_library_eprj

    write_library_eprj(lib, src, project_name="demo")
    res = libconvert(src, out_dir=tmp_path / "out")
    assert res.symbols == 1
    assert res.footprints == 2
    assert res.verify_grade == "PASS"

    back = extract_eprj_library(res.output)
    diff = compare_libraries(lib, back, pos_tol=0.6)
    assert diff.grade == "PASS"

    # spot-check pad fidelity
    fp = back.footprints["CAP-TH"]
    assert len(fp.pads) == 2
    p1 = sorted(fp.pads, key=lambda p: p.number)[0]
    assert abs(p1.hole - 35.4) < 0.6
    assert p1.shape == "ELLIPSE"
    assert abs(abs(p1.x) - 196.8) < 0.6
    # through-hole layer code preserved as multi-layer pad
    assert p1.layer == "12"
