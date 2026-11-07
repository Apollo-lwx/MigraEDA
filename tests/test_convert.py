"""Round-trip conversion tests: IR -> target format -> re-parse -> compare."""

from __future__ import annotations

from pathlib import Path

from migraeda.adascii import parse_schdoc_ascii, write_schdoc_ascii
from migraeda.convert import convert, netlist_from_ir
from migraeda.eprj_sqlite import parse_eprj
from migraeda.eprj_write import write_eprj
from migraeda.ir import (
    IRComponent,
    IRNetLabel,
    IRPin,
    IRPowerPort,
    IRWire,
    SchematicIR,
)
from migraeda.lvs import compare_netlists


def _demo_ir() -> SchematicIR:
    """Small hand-verified schematic: R1.1-R2.1 on SIG; R1.2-C1.1; C1.2=GND."""
    ir = SchematicIR(source="demo")
    r1 = IRComponent(ref="R1", value="10K", footprint="0805R", x=100, y=100)
    r1.pins = [
        IRPin(number="1", x=-10, y=0, length=10, orient_into_body=0),
        IRPin(number="2", x=10, y=0, length=10, orient_into_body=180),
    ]
    r2 = IRComponent(ref="R2", value="10K", footprint="0805R", x=150, y=130, rotation=90)
    r2.pins = [
        IRPin(number="1", x=-10, y=0, length=10, orient_into_body=0),
        IRPin(number="2", x=10, y=0, length=10, orient_into_body=180),
    ]
    c1 = IRComponent(ref="C1", value="100n", footprint="0805C", x=110, y=50, mirror=True)
    c1.pins = [
        IRPin(number="1", x=0, y=10, length=10, orient_into_body=270),
        IRPin(number="2", x=0, y=-10, length=10, orient_into_body=90),
    ]
    ir.components = [r1, r2, c1]
    ir.wires = [
        IRWire(points=[(90, 100), (150, 100)]),          # R1.1 .. (150,100)
        IRWire(points=[(150, 100), (150, 140)]),         # .. R2.1
        IRWire(points=[(110, 100), (110, 60)]),          # R1.2 .. C1.1
    ]
    ir.labels = [IRNetLabel(x=120, y=100, text="SIG")]
    ir.power_ports = [IRPowerPort(x=110, y=40, net="GND", orient=0)]
    return ir


def _assert_roundtrip(model_a, model_b, expect_pins):
    res = compare_netlists(model_a, model_b)
    assert res.common_pin_count == expect_pins, (
        f"common pins {res.common_pin_count} != {expect_pins}; "
        f"a_only={res.a_only_pins} b_only={res.b_only_pins}"
    )
    assert not res.pin_mismatches, f"mismatches: {res.pin_mismatches}"


def test_roundtrip_ad_ascii(tmp_path: Path) -> None:
    ir = _demo_ir()
    src = netlist_from_ir(ir)
    assert len(src.pin_nets) == 6
    assert src.pin_nets[("R1", "1")] == "SIG"
    assert src.pin_nets[("R2", "1")] == "SIG"
    assert src.pin_nets[("C1", "2")] == "GND"

    out = write_schdoc_ascii(ir, tmp_path / "demo.SchDoc")
    back = parse_schdoc_ascii(out)
    _assert_roundtrip(src, back, expect_pins=6)
    assert back.pin_nets[("R1", "1")] == "SIG"
    assert back.pin_nets[("C1", "2")] == "GND"


def test_roundtrip_eprj(tmp_path: Path) -> None:
    ir = _demo_ir()
    src = netlist_from_ir(ir)

    out = write_eprj(ir, tmp_path / "demo.eprj", project_name="demo")
    back = parse_eprj(out)
    _assert_roundtrip(src, back, expect_pins=6)
    assert back.pin_nets[("R1", "1")] == "SIG"
    assert back.pin_nets[("C1", "2")] == "GND"
    # BOM-ish fields survive
    assert back.components["R1"].value == "10K"
    assert back.components["C1"].footprint == "0805C"


def test_degenerate_netpoint_preserved(tmp_path: Path) -> None:
    """LCEDA-style zero-length named wires (net points) must survive eprj write."""
    from migraeda.ir import IRWire

    ir = _demo_ir()
    # degenerate named wire exactly on R1 pin 1 hotspot (90,100)
    ir.wires.append(IRWire(points=[(90.0, 100.0), (90.0, 100.0)], net="NETPOINT"))
    src = netlist_from_ir(ir)
    assert src.pin_nets[("R1", "1")] == "NETPOINT"

    out = write_eprj(ir, tmp_path / "dp.eprj")
    back = parse_eprj(out)
    assert back.pin_nets[("R1", "1")] == "NETPOINT"


def test_eprj_is_sqlite(tmp_path: Path) -> None:
    import sqlite3

    ir = _demo_ir()
    out = write_eprj(ir, tmp_path / "demo.eprj")
    con = sqlite3.connect(str(out))
    try:
        tables = {
            r[0]
            for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert {"projects", "documents", "schematics", "components",
                "devices", "attributes"} <= tables
        (sch_data,) = con.execute(
            "SELECT dataStr FROM documents WHERE docType=1"
        ).fetchone()
        assert '"WIRE"' in sch_data and '"COMPONENT"' in sch_data
    finally:
        con.close()


def test_convert_defaults_to_dot_migraeda(tmp_path: Path) -> None:
    src = tmp_path / "demo.eprj"
    write_eprj(_demo_ir(), src, project_name="demo")
    res = convert(src, "ad")
    assert res.out_path == tmp_path / ".migraeda" / "demo.SchDoc"
    assert res.out_path.is_file()
