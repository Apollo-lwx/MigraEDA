"""Local tool functions behind the MigraEDA MCP server.

No MCP or Pydantic imports here, so the conversion core stays zero-dependency
and these functions can be tested without the optional ``mcp`` extra.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Callable

from migraeda.convert import (
    PcbConvertResult,
    convert,
    default_artifact_dir,
    eprj_has_pcb,
    load_netlist,
    roundtrip,
    roundtrip_pcb,
)
from migraeda.lvs import LvsResult, compare_netlists

_TEXT_CAP = 8000
_NOTE_CAP = 8


class ToolError(Exception):
    """Bad input or a known failure the agent can act on."""


def clip_list(items: list[Any], limit: int) -> tuple[list[Any], int]:
    shown = list(items[:limit])
    return shown, max(0, len(items) - len(shown))


def existing_file(path: str) -> Path:
    text = (path or "").strip().strip('"')
    if not text:
        raise ToolError("路径为空。请传本机绝对路径，例如 D:/boards/demo.eprj。")
    file = Path(text).expanduser()
    if not file.is_file():
        raise ToolError(
            f"找不到文件 {file}。请传本机上已存在的绝对路径，不要传目录或 URL。"
        )
    return file.resolve()


def resolve_output_dir(src: Path, output_dir: str | None, *parts: str) -> Path:
    if output_dir and output_dir.strip():
        dest = Path(output_dir.strip().strip('"')).expanduser()
        if not dest.is_absolute():
            dest = Path.cwd() / dest
        dest = dest.resolve()
    else:
        dest = default_artifact_dir(src, *parts)
    if dest == src:
        raise ToolError(
            "输出目录不能是源文件本身。省略 output_dir 会写到源文件旁边的 .migraeda/。"
        )
    if dest.exists() and not dest.is_dir():
        raise ToolError(f"{dest} 是文件。output_dir 需要一个目录。")
    return dest


def render(data: dict[str, Any], fmt: str) -> str:
    if fmt == "json":
        return json.dumps(data, ensure_ascii=False, indent=2)
    return _markdown(data)


def run_convert(
    path: str,
    to: str,
    output_dir: str | None = None,
    verify: bool = True,
    panel_rows: int = 1,
    with_pcb: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    src = existing_file(path)
    if to not in {"ad", "eprj", "adpcb"}:
        raise ToolError("to 只能是 ad、eprj、adpcb。ad 出原理图，adpcb 出 PCB，eprj 转回嘉立创。")
    if panel_rows != 1 and to != "adpcb":
        raise ToolError("panel_rows 只在 to=adpcb 时生效。原理图转换请保持 1。")
    if with_pcb and to != "eprj":
        raise ToolError("with_pcb 只在 to=eprj 时使用，用来把已有的 .PcbDoc 嵌进新的嘉立创工程。")
    pcb = existing_file(with_pcb) if with_pcb else None
    dest = resolve_output_dir(src, output_dir)

    def _go() -> dict[str, Any]:
        res = convert(
            src,
            to,
            out_dir=dest,
            verify=verify,
            panel_rows=panel_rows,
            with_pcb=pcb,
        )
        if isinstance(res, PcbConvertResult):
            grade = res.verify_grade or "SKIPPED"
            return {
                "grade": grade,
                "direction": "eprj-pcb -> ad-ascii-pcbdoc",
                "written": str(res.out_path),
                "output_dir": str(dest),
                "components": res.components,
                "pads": res.pads,
                "tracks": res.tracks,
                "vias": res.vias,
                "polygons": res.polygons,
                "common_pins": res.common_pins,
                "mismatched": res.pin_mismatches,
                "details": res.verify_details,
                "panel_rows": panel_rows,
            }
        payload: dict[str, Any] = {
            "direction": res.direction,
            "written": str(res.out_path),
            "output_dir": str(dest),
            "source_components": res.src_components,
            "source_wires": res.src_wires,
            "notes": [_short(n) for n in res.notes[:_NOTE_CAP]],
        }
        if res.verify is None:
            payload["grade"] = "SKIPPED"
            return payload
        payload.update(_lvs_fields(res.verify, limit))
        return payload

    return _guard(_go)


def run_verify(file_a: str, file_b: str, limit: int = 20) -> dict[str, Any]:
    pa = existing_file(file_a)
    pb = existing_file(file_b)

    def _go() -> dict[str, Any]:
        a_pcb = pa.suffix.lower() == ".eprj" and pb.suffix.lower() == ".pcbdoc"
        b_pcb = pb.suffix.lower() == ".eprj" and pa.suffix.lower() == ".pcbdoc"
        left = load_netlist(pa, pcb=a_pcb)
        right = load_netlist(pb, pcb=b_pcb)
        res = compare_netlists(left, right)
        payload = _lvs_fields(res, limit)
        payload["file_a"] = str(pa)
        payload["file_b"] = str(pb)
        return payload

    return _guard(_go)


def run_pcbdiff(
    file_a: str,
    file_b: str,
    tol_mil: float = 2.0,
    limit: int = 20,
) -> dict[str, Any]:
    pa = existing_file(file_a)
    pb = existing_file(file_b)

    def _go() -> dict[str, Any]:
        from migraeda.pcbdiff import compare_pcb

        left = _load_pcb(pa)
        right = _load_pcb(pb)
        res = compare_pcb(left, right, pos_tol_mil=tol_mil)
        moved, moved_omitted = clip_list(res.comps_moved, limit)
        pads, pads_omitted = clip_list(res.pads_moved, limit)
        copper, copper_omitted = clip_list(res.copper_diffs, limit)
        only_a, only_a_omitted = clip_list(res.comps_only_a, limit)
        only_b, only_b_omitted = clip_list(res.comps_only_b, limit)
        return {
            "grade": res.grade,
            "file_a": str(pa),
            "file_b": str(pb),
            "tolerance_mil": tol_mil,
            "alignment": res.alignment,
            "outline_ok": res.outline_ok,
            "outline_a_mil": [res.outline_a[0], res.outline_a[1]],
            "outline_b_mil": [res.outline_b[0], res.outline_b[1]],
            "components_common": res.comps_common,
            "components_moved": moved,
            "components_moved_omitted": moved_omitted,
            "components_only_a": only_a,
            "components_only_a_omitted": only_a_omitted,
            "components_only_b": only_b,
            "components_only_b_omitted": only_b_omitted,
            "pads_checked": res.pads_checked,
            "pads_moved": pads,
            "pads_moved_omitted": pads_omitted,
            "vias_a": res.vias_a,
            "vias_b": res.vias_b,
            "vias_unmatched": len(res.vias_unmatched),
            "copper_diffs": copper,
            "copper_diffs_omitted": copper_omitted,
            "nets_only_a": len(res.nets_only_a),
            "nets_only_b": len(res.nets_only_b),
        }

    return _guard(_go)


def run_roundtrip(path: str, output_dir: str | None = None, limit: int = 20) -> dict[str, Any]:
    src = existing_file(path)
    if src.suffix.lower() not in {".eprj", ".schdoc"}:
        raise ToolError("roundtrip 只接受 .eprj 或 .SchDoc。PCB 往返会在 .eprj 含 PCB 页时自动附带。")
    dest = resolve_output_dir(src, output_dir, "roundtrip")

    def _go() -> dict[str, Any]:
        res = roundtrip(src, out_dir=dest)
        notes, notes_omitted = clip_list(res.notes, limit)
        payload: dict[str, Any] = {
            "grade": "PASS" if res.ok else "FAIL",
            "direction": res.direction,
            "intermediate": str(res.intermediate),
            "written": str(res.final),
            "output_dir": str(dest),
            "leg1_verify": res.leg1_verify,
            "common_pins": res.final_common_pins,
            "mismatched": res.final_mismatches,
            "nets_matched": res.nets_matched,
            "notes": [_short(n) for n in notes],
            "notes_omitted": notes_omitted,
        }
        if src.suffix.lower() == ".eprj" and eprj_has_pcb(src):
            pcb = roundtrip_pcb(src, out_dir=dest)
            payload["pcb"] = {
                "grade": "PASS" if pcb.ok else "FAIL",
                "leg1": str(pcb.leg1),
                "written": str(pcb.final),
                "leg1_grade": pcb.leg1_grade,
                "final_grade": pcb.final_grade,
                "details": pcb.final_details,
            }
        return payload

    return _guard(_go)


def run_libinspect(path: str) -> dict[str, Any]:
    src = existing_file(path)

    def _go() -> dict[str, Any]:
        from migraeda.libinspect import inspect_library

        return _clip_text(inspect_library(src))

    return _guard(_go)


def run_selfcheck(
    path: str,
    pcb: bool = False,
    converted: str | None = None,
) -> dict[str, Any]:
    src = existing_file(path)
    converted_path = existing_file(converted) if converted else None
    if pcb and src.suffix.lower() != ".eprj":
        raise ToolError("pcb=true 时 path 必须是含 PCB 页的 .eprj。")

    def _go() -> dict[str, Any]:
        if pcb:
            from migraeda.selfcheck_pcb import selfcheck_pcb

            text = selfcheck_pcb(src, converted_path)
        else:
            from migraeda.selfcheck import selfcheck

            text = selfcheck(src)
        payload = _clip_text(text)
        payload["pcb"] = pcb
        return payload

    return _guard(_go)


def _lvs_fields(res: LvsResult, limit: int) -> dict[str, Any]:
    mismatches = [
        {"ref": pm.ref, "pin": pm.pin, "a_net": pm.a_net, "b_net": pm.b_net}
        for pm in res.pin_mismatches
    ]
    shown, omitted = clip_list(mismatches, limit)
    refs_a, refs_a_omitted = clip_list(res.a_only_refs, limit)
    refs_b, refs_b_omitted = clip_list(res.b_only_refs, limit)
    named = sum(1 for m in res.matches if m.by_name)
    return {
        "grade": "FAIL" if res.pin_mismatches else "PASS",
        "common_pins": res.common_pin_count,
        "mismatched": len(res.pin_mismatches),
        "nets_matched": len(res.matches),
        "name_matched_nets": named,
        "structurally_matched_nets": len(res.matches) - named,
        "nets_only_a": len(res.a_only_nets),
        "nets_only_b": len(res.b_only_nets),
        "refs_only_a": refs_a,
        "refs_only_a_omitted": refs_a_omitted,
        "refs_only_b": refs_b,
        "refs_only_b_omitted": refs_b_omitted,
        "mismatches": shown,
        "mismatches_omitted": omitted,
    }


def _load_pcb(path: Path):
    from migraeda.epcb import parse_epcb
    from migraeda.pcbdoc import parse_pcbdoc

    suf = path.suffix.lower()
    if suf == ".pcbdoc":
        with open(path, "rb") as fh:
            head = fh.read(16)
        if head.startswith(b"|RECORD"):
            from migraeda.pcbascii import parse_pcb_ascii

            return parse_pcb_ascii(path)
        return parse_pcbdoc(path)
    if suf == ".eprj":
        return parse_epcb(path)
    raise ToolError(
        f"不支持的 PCB 文件 {path.name}。pcbdiff 接受 .PcbDoc，或含 PCB 页的 .eprj。"
    )


def _clip_text(text: str) -> dict[str, Any]:
    if len(text) <= _TEXT_CAP:
        return {"text": text, "truncated": False, "chars": len(text)}
    return {
        "text": text[:_TEXT_CAP] + "\n…(已截断，只保留前 8000 字)",
        "truncated": True,
        "chars": len(text),
    }


def _short(note: str) -> str:
    note = str(note)
    if len(note) <= 200:
        return note
    return note[:200] + "…"


def _guard(fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        return fn()
    except ToolError:
        raise
    except (OSError, ValueError, sqlite3.Error) as exc:
        raise ToolError(f"{exc}。可先调用 migraeda_libinspect 确认文件结构。") from exc


def _markdown(data: dict[str, Any]) -> str:
    lines: list[str] = []
    if "grade" in data:
        lines.append(f"grade: {data['grade']}")
    if data.get("direction"):
        lines.append(f"direction: {data['direction']}")
    if data.get("written"):
        lines.append(f"written: {data['written']}")
    if "common_pins" in data:
        lines.append(
            f"loop-verify: common_pins={data['common_pins']} "
            f"mismatched={data.get('mismatched', 0)} "
            f"nets_matched={data.get('nets_matched', 0)}"
        )
    if data.get("details"):
        lines.append(f"details: {data['details']}")
    pcb = data.get("pcb")
    if isinstance(pcb, dict):
        lines.append(
            f"pcb roundtrip: {pcb.get('grade')} ({pcb.get('details', '')})".rstrip()
        )
        if pcb.get("written"):
            lines.append(f"pcb written: {pcb['written']}")
    mismatches = data.get("mismatches") or []
    if mismatches:
        lines.append("mismatches:")
        for item in mismatches:
            lines.append(
                f"- {item['ref']}.{item['pin']}: A={item['a_net']!r} B={item['b_net']!r}"
            )
        omitted = data.get("mismatches_omitted") or 0
        if omitted:
            lines.append(f"- …另有 {omitted} 条未列出")
    for key, label in (
        ("components_moved", "components moved"),
        ("pads_moved", "pads moved"),
        ("copper_diffs", "copper diffs"),
    ):
        rows = data.get(key) or []
        if not rows:
            continue
        lines.append(f"{label}:")
        for row in rows:
            lines.append(f"- {row}")
        extra = int(data.get(f"{key}_omitted") or 0)
        if extra:
            lines.append(f"- …另有 {extra} 条未列出")
    if data.get("text"):
        if lines:
            lines.append("")
        lines.append(data["text"])
        if data.get("truncated"):
            lines.append(f"(原文 {data.get('chars')} 字，已截断)")
    return "\n".join(lines) if lines else json.dumps(data, ensure_ascii=False, indent=2)
