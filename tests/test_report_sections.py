from migraeda.report_common import detect_comparison_kind, render_scope_and_pitfalls
from migraeda.verify_report import render_verify_report
from migraeda.lvs import LvsResult
from migraeda.netlist_model import NetlistModel


def test_verify_report_includes_scope_section() -> None:
    a = NetlistModel(source="eprj-pcb:A.eprj")
    b = NetlistModel(source="pcbdoc:B.PcbDoc")
    text = render_verify_report(a, b, LvsResult(a_name=a.source, b_name=b.source))
    assert "## 0. 报告说明与比对口径" in text
    assert detect_comparison_kind(a.source, b.source) in text
    assert "selfcheck --pcb" in text
