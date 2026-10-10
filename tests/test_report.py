from migraeda.diff import diff_stats
from migraeda.normalize import normalize_epro
from migraeda.report import load_diff_json, render_html, render_markdown, write_report


def test_report_md_html(simple_epro, tmp_path):
    s = normalize_epro(simple_epro)
    d = diff_stats(s, s)
    md = render_markdown(d)
    assert "PASS" in md
    assert "component_count" in md
    html = render_html(d)
    assert "<html" in html
    p = write_report(d, tmp_path / "r.md")
    assert p.read_text(encoding="utf-8").startswith("# MigraEDA")
    jp = write_report(d, tmp_path / "d.json", fmt="json")
    loaded = load_diff_json(jp)
    assert loaded.grade.value == "PASS"
