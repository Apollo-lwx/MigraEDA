from migraeda.diff import diff_stats
from migraeda.models import DiffGrade, ProjectStats
from migraeda.normalize import normalize_epro, normalize_stats_json


def test_diff_pass_identity(simple_epro):
    s = normalize_epro(simple_epro)
    r = diff_stats(s, s)
    assert r.grade == DiffGrade.PASS


def test_diff_warn(bus_epro, golden_dir):
    src = normalize_epro(bus_epro)
    tgt = normalize_stats_json(
        __import__("json").loads((golden_dir / "bus_mismatch_target_warn.json").read_text())
    )
    r = diff_stats(src, tgt)
    assert r.grade == DiffGrade.WARN


def test_diff_fail(bus_epro, golden_dir):
    src = normalize_epro(bus_epro)
    tgt = normalize_stats_json(
        __import__("json").loads((golden_dir / "bus_mismatch_target_fail.json").read_text())
    )
    r = diff_stats(src, tgt)
    assert r.grade == DiffGrade.FAIL


def test_via_warn():
    a = ProjectStats(name="a", component_count=1, component_refs=["R1"], net_names=["GND"], via_count=2)
    b = ProjectStats(name="b", component_count=1, component_refs=["R1"], net_names=["GND"], via_count=3)
    r = diff_stats(a, b)
    assert r.grade == DiffGrade.WARN
