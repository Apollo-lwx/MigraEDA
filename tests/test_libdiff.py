"""Library extraction + libdiff tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from migraeda.eprj_lib import extract_eprj_library
from migraeda.libdiff import compare_libraries
from migraeda.libmodel import LibFootprint, LibPad, LibPin, LibSymbol, Library
from migraeda.pcbdoc import PcbComponent, PcbNetlist, PcbPad


def _mk_eprj_with_footprint(tmp_path: Path) -> Path:
    p = tmp_path / "lib.eprj"
    con = sqlite3.connect(str(p))
    con.execute(
        "CREATE TABLE components (uuid varchar PRIMARY KEY NOT NULL, title varchar NOT NULL,"
        " display_title varchar NOT NULL, description varchar NOT NULL, source varchar,"
        " version varchar, created_at datetime NOT NULL, updated_at datetime NOT NULL,"
        " ticket integer NOT NULL, docType integer NOT NULL, dataStr text NOT NULL,"
        " createTime datetime NOT NULL, updateTime datetime NOT NULL, modifier_uuid varchar,"
        " creator_uuid varchar, owner_uuid varchar, project_uuid varchar,"
        " child_tag varchar NOT NULL, parent_tag varchar NOT NULL, custom_tags varchar)"
    )
    con.execute(
        "CREATE TABLE devices (uuid varchar PRIMARY KEY NOT NULL, description varchar NOT NULL,"
        " title varchar NOT NULL, display_title varchar NOT NULL, images text NOT NULL,"
        " source varchar, version varchar, ticket integer NOT NULL, footprint_type integer,"
        " symbol_type integer, created_at datetime NOT NULL, updated_at datetime NOT NULL,"
        " createTime datetime NOT NULL, updateTime datetime NOT NULL, modifier_uuid varchar,"
        " creator_uuid varchar, owner_uuid varchar, project_uuid varchar NOT NULL,"
        " child_tag varchar NOT NULL, parent_tag varchar NOT NULL, custom_tags varchar)"
    )
    fp_data = "\n".join(
        [
            '["DOCTYPE","FOOTPRINT","1.3"]',
            '["PAD","e1",0,"",12,"1",-50,0,0,["ROUND",30,30],["ELLIPSE",60,60],[],0,0,0,1,0,2,2,0,0,0]',
            '["PAD","e2",0,"",12,"2",50,0,0,["ROUND",30,30],["ELLIPSE",60,60],[],0,0,0,1,0,2,2,0,0,0]',
        ]
    )
    con.execute(
        "INSERT INTO components VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("u1", "res0805", "R0805", "", "", "1", "now", "now", 1, 4, fp_data,
         "now", "now", "", "", "", "p", "", "", ""),
    )
    con.execute(
        "INSERT INTO devices VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("d1", "1k resistor", "1k", "1K", "", "", "1", 1, 0, 0,
         "now", "now", "now", "now", "", "", "", "p", "", "", ""),
    )
    con.commit()
    con.close()
    return p


def test_eprj_library_extract(tmp_path: Path) -> None:
    lib = extract_eprj_library(_mk_eprj_with_footprint(tmp_path))
    assert "R0805" in lib.footprints
    fp = lib.footprints["R0805"]
    assert len(fp.pads) == 2
    assert fp.pads[0].number == "1"
    assert abs(fp.pads[0].x + 50.0) < 1e-6
    assert fp.pads[0].size_x == 60.0
    assert fp.pads[0].hole == 30.0
    assert "1K" in lib.devices


def test_pcbdoc_footprint_map() -> None:
    nl = PcbNetlist()
    nl.nets = ["GND"]
    nl.components = [
        PcbComponent(designator="R1", pattern="R0805", layer="TOP",
                     x_mil=100.0, y_mil=100.0, rotation=90.0),
        PcbComponent(designator="R2", pattern="R0805", layer="TOP",
                     x_mil=500.0, y_mil=500.0, rotation=90.0),
    ]
    # two instances, same relative pad positions (rotated 90 CW around comp)
    nl.pads = [
        PcbPad(name="1", net_index=0, component_index=0, x_mil=100.0, y_mil=50.0),
        PcbPad(name="2", net_index=0, component_index=0, x_mil=100.0, y_mil=150.0),
        PcbPad(name="1", net_index=0, component_index=1, x_mil=500.0, y_mil=450.0),
        PcbPad(name="2", net_index=0, component_index=1, x_mil=500.0, y_mil=550.0),
    ]
    fpm = nl.footprint_map()
    assert "R0805" in fpm
    pads = sorted((p.name, round(p.x_mil, 1), round(p.y_mil, 1)) for p in fpm["R0805"])
    # duplicates from the two instances collapse; rotation undone -> pads on X axis
    assert pads == [("1", -50.0, 0.0), ("2", 50.0, 0.0)]


def test_libdiff_detects_pad_shift() -> None:
    a = Library(source="a")
    b = Library(source="b")
    a.footprints["R0805"] = LibFootprint(
        name="R0805",
        pads=[LibPad(number="1", x=-50, y=0, size_x=60, hole=30),
              LibPad(number="2", x=50, y=0, size_x=60, hole=30)],
    )
    b.footprints["R0805"] = LibFootprint(
        name="R0805",
        pads=[LibPad(number="1", x=-50, y=0, size_x=60, hole=30),
              LibPad(number="2", x=52, y=0, size_x=60, hole=30)],
    )
    res = compare_libraries(a, b, pos_tol=1.0)
    assert res.grade == "FAIL"
    assert res.fp_diffs and "pad 2 position" in res.fp_diffs[0].issues[0]

    res2 = compare_libraries(a, a, pos_tol=1.0)
    assert res2.grade == "PASS"


def test_libdiff_symbol_pin_check() -> None:
    a = Library(source="a")
    b = Library(source="b")
    a.symbols["OP"] = LibSymbol(
        name="OP",
        pins=[LibPin(number="1", name="IN+", x=-20, y=10),
              LibPin(number="2", name="IN-", x=-20, y=-10)],
    )
    b.symbols["OP"] = LibSymbol(
        name="OP",
        pins=[LibPin(number="1", name="IN+", x=-20, y=10),
              LibPin(number="2", name="IN-", x=-20, y=-10),
              LibPin(number="3", name="OUT", x=20, y=0)],
    )
    res = compare_libraries(a, b)
    assert res.symbol_diffs
    assert "pin numbers differ" in res.symbol_diffs[0].issues[0]
