"""Multi-part component semantics (OWNERPARTID == CURRENTPARTID)."""

from __future__ import annotations

from migraeda.schdoc import model_from_records


def _rec(idx: int, props: dict) -> tuple[int, dict[str, str]]:
    return idx, {k.upper(): str(v) for k, v in props.items()}


def test_only_current_part_pins_are_active() -> None:
    """A 2-gate component placed as part 2: only gate-2 pins connect."""
    recs = [
        _rec(0, {"RECORD": "1", "LIBREFERENCE": "74HC00", "PARTCOUNT": "2",
                 "CURRENTPARTID": "2", "LOCATION.X": "100", "LOCATION.Y": "100",
                 "INDEXINSHEET": "1"}),
        _rec(1, {"RECORD": "34", "OWNERINDEX": "0", "TEXT": "U1"}),
        # gate 1 pins (OWNERPARTID=1) — should be dropped
        _rec(2, {"RECORD": "2", "OWNERINDEX": "0", "OWNERPARTID": "1", "DESIGNATOR": "1",
                 "PINCONGLOMERATE": "34", "PINLENGTH": "10",
                 "LOCATION.X": "90", "LOCATION.Y": "100"}),
        _rec(3, {"RECORD": "2", "OWNERINDEX": "0", "OWNERPARTID": "1", "DESIGNATOR": "2",
                 "PINCONGLOMERATE": "32", "PINLENGTH": "10",
                 "LOCATION.X": "110", "LOCATION.Y": "100"}),
        # gate 2 pins (OWNERPARTID=2) — active
        _rec(4, {"RECORD": "2", "OWNERINDEX": "0", "OWNERPARTID": "2", "DESIGNATOR": "3",
                 "PINCONGLOMERATE": "34", "PINLENGTH": "10",
                 "LOCATION.X": "90", "LOCATION.Y": "120"}),
        _rec(5, {"RECORD": "2", "OWNERINDEX": "0", "OWNERPARTID": "2", "DESIGNATOR": "4",
                 "PINCONGLOMERATE": "32", "PINLENGTH": "10",
                 "LOCATION.X": "110", "LOCATION.Y": "120"}),
        # wire touching gate-2 pin 4 hotspot at (120,120)
        _rec(6, {"RECORD": "27", "LOCATIONCOUNT": "2",
                 "X1": "120", "Y1": "120", "X2": "150", "Y2": "120"}),
    ]
    model = model_from_records(recs, source="test")
    assert ("U1", "1") not in model.pin_nets
    assert ("U1", "2") not in model.pin_nets
    assert ("U1", "3") in model.pin_nets
    assert ("U1", "4") in model.pin_nets
    assert any("multi-part pins skipped" in n for n in model.notes)


def test_single_part_unaffected() -> None:
    """PARTCOUNT=2 single-part symbol with CURRENTPARTID=1 keeps its pins."""
    recs = [
        _rec(0, {"RECORD": "1", "LIBREFERENCE": "RT", "PARTCOUNT": "2",
                 "CURRENTPARTID": "1", "LOCATION.X": "100", "LOCATION.Y": "100",
                 "INDEXINSHEET": "1"}),
        _rec(1, {"RECORD": "34", "OWNERINDEX": "0", "TEXT": "R1"}),
        _rec(2, {"RECORD": "2", "OWNERINDEX": "0", "OWNERPARTID": "1", "DESIGNATOR": "1",
                 "PINCONGLOMERATE": "34", "PINLENGTH": "10",
                 "LOCATION.X": "90", "LOCATION.Y": "100"}),
        _rec(3, {"RECORD": "27", "LOCATIONCOUNT": "2",
                 "X1": "80", "Y1": "100", "X2": "120", "Y2": "100"}),
    ]
    model = model_from_records(recs, source="test")
    assert ("R1", "1") in model.pin_nets
