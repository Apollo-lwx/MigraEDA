"""MCP tool functions. The server process itself needs the optional mcp extra."""

from __future__ import annotations

from pathlib import Path

import pytest

from migraeda.eprj_write import write_eprj
from migraeda.mcp_tools import (
    ToolError,
    clip_list,
    render,
    run_convert,
    run_libinspect,
    run_roundtrip,
    run_selfcheck,
    run_verify,
)
from test_convert import _demo_ir


def test_clip_list() -> None:
    shown, omitted = clip_list(["a", "b", "c"], 2)
    assert shown == ["a", "b"]
    assert omitted == 1


def test_convert_writes_beside_source(tmp_path: Path) -> None:
    src = tmp_path / "demo.eprj"
    write_eprj(_demo_ir(), src, project_name="demo")
    data = run_convert(str(src), "ad")
    written = Path(data["written"])
    assert data["grade"] == "PASS"
    assert data["mismatched"] == 0
    assert written.parent == (tmp_path / ".migraeda").resolve()
    assert written.name == "demo.SchDoc"
    checked = run_verify(str(src), str(written))
    assert checked["grade"] == "PASS"
    assert checked["common_pins"] == 6


def test_convert_honors_output_dir(tmp_path: Path) -> None:
    src = tmp_path / "demo.eprj"
    write_eprj(_demo_ir(), src, project_name="demo")
    dest = tmp_path / "custom"
    data = run_convert(str(src), "ad", output_dir=str(dest))
    assert Path(data["written"]) == dest.resolve() / "demo.SchDoc"


def test_roundtrip_demo(tmp_path: Path) -> None:
    src = tmp_path / "demo.eprj"
    write_eprj(_demo_ir(), src, project_name="demo")
    data = run_roundtrip(str(src))
    assert data["grade"] == "PASS"
    assert data["mismatched"] == 0
    assert Path(data["written"]).parent == (tmp_path / ".migraeda" / "roundtrip").resolve()
    assert "pcb" not in data


def test_missing_file_is_actionable() -> None:
    with pytest.raises(ToolError, match="找不到文件"):
        run_verify("D:/no/such/a.eprj", "D:/no/such/b.SchDoc")


def test_roundtrip_rejects_pcbdoc(tmp_path: Path) -> None:
    src = tmp_path / "board.PcbDoc"
    src.write_bytes(b"|RECORD")
    with pytest.raises(ToolError, match="roundtrip"):
        run_roundtrip(str(src))


def test_inspect_and_selfcheck(tmp_path: Path) -> None:
    src = tmp_path / "demo.eprj"
    write_eprj(_demo_ir(), src, project_name="demo")
    inspected = run_libinspect(str(src))
    assert "container:" in inspected["text"]
    assert inspected["truncated"] is False
    checked = run_selfcheck(str(src))
    assert "selfcheck:" in checked["text"]
    other = tmp_path / "demo.SchDoc"
    other.write_bytes(b"not-a-schematic")
    with pytest.raises(ToolError, match=r"\.eprj"):
        run_selfcheck(str(other), pcb=True)


def test_render_markdown_lists_mismatches() -> None:
    text = render(
        {
            "grade": "FAIL",
            "common_pins": 2,
            "mismatched": 1,
            "nets_matched": 1,
            "mismatches": [{"ref": "R1", "pin": "1", "a_net": "VCC", "b_net": "GND"}],
            "mismatches_omitted": 3,
        },
        "markdown",
    )
    assert "grade: FAIL" in text
    assert "R1.1" in text
    assert "另有 3 条" in text


def test_server_registers_six_tools() -> None:
    pytest.importorskip("mcp")
    import asyncio

    from migraeda.mcp_server import build_mcp

    mcp = build_mcp()
    tools = {tool.name: tool for tool in mcp._tool_manager.list_tools()}
    assert sorted(tools) == [
        "migraeda_convert",
        "migraeda_libinspect",
        "migraeda_pcbdiff",
        "migraeda_roundtrip",
        "migraeda_selfcheck",
        "migraeda_verify",
    ]
    assert "path" in tools["migraeda_libinspect"].parameters["properties"]
    assert "params" not in tools["migraeda_libinspect"].parameters["properties"]
    missing = asyncio.run(tools["migraeda_libinspect"].run({"path": "D:/no/such/file.eprj"}))
    assert "找不到文件" in missing


def test_convert_tool_call_returns_json(tmp_path: Path) -> None:
    pytest.importorskip("mcp")
    import asyncio
    import json

    from migraeda.mcp_server import build_mcp

    src = tmp_path / "demo.eprj"
    write_eprj(_demo_ir(), src, project_name="demo")
    mcp = build_mcp()
    tool = next(item for item in mcp._tool_manager.list_tools() if item.name == "migraeda_convert")
    text = asyncio.run(tool.run({
        "path": str(src),
        "to": "ad",
        "response_format": "json",
    }))
    data = json.loads(text)
    assert data["grade"] == "PASS"
    assert Path(data["written"]).name == "demo.SchDoc"
