from migraeda.epro_parse import EproParseError, parse_epro
import pytest


def test_parse_simple(simple_epro):
    model = parse_epro(simple_epro)
    assert model.name == "simple"
    assert len(model.components) == 3
    assert "GND" in model.net_names
    assert len(model.vias) == 4
    assert model.layers == 2


def test_parse_bus(bus_epro):
    model = parse_epro(bus_epro)
    assert model.name == "bus_mismatch"
    assert len(model.components) == 4
    assert "LEGACY_CLK" in model.net_names


def test_parse_missing(tmp_path):
    with pytest.raises(EproParseError):
        parse_epro(tmp_path / "nope.epro")
