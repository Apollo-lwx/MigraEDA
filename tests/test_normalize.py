from migraeda.normalize import normalize_epro, normalize_stats_json


def test_normalize_simple(simple_epro):
    stats = normalize_epro(simple_epro)
    assert stats.component_count == 3
    assert stats.component_refs == ["C1", "R1", "U1"]
    assert stats.net_names == sorted(["GND", "VCC_3V3", "NET_NRESET", "NET_SWDIO", "NET_SWCLK"])
    assert stats.via_count == 4


def test_normalize_stats_json():
    stats = normalize_stats_json(
        {"name": "x", "net_names": ["B", "A", "A"], "component_refs": ["R2", "R1"]}
    )
    assert stats.net_names == ["A", "B"]
    assert stats.component_refs == ["R1", "R2"]
    assert stats.component_count == 2
