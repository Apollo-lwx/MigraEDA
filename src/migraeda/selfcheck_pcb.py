"""PCB fidelity checklist: 嘉立创 eprj PCB vs converted .PcbDoc (if given)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from migraeda.convert import netlist_from_pcb
from migraeda.epcb import parse_epcb
from migraeda.eprj_sqlite import _maybe_decompress
from migraeda.lvs import compare_netlists
from migraeda.pcbascii import parse_pcb_ascii
from migraeda.pcbdiff import compare_pcb
from migraeda.report_common import render_pcb_fidelity_criteria


def _eprj_pcb_raw_counts(path: Path) -> tuple[dict[str, int], int]:
    con = sqlite3.connect(str(path))
    try:
        row = con.execute(
            "SELECT dataStr FROM documents WHERE docType=3"
            " ORDER BY LENGTH(dataStr) DESC LIMIT 1"
        ).fetchone()
        if not row or not row[0]:
            return {}, 0
        raw_len = len(row[0]) if isinstance(row[0], str) else row[0]
        data = _maybe_decompress(row[0])
    finally:
        con.close()
    out = {"LINE": 0, "POUR": 0, "PAD": 0, "PAD_NET": 0, "POLY_outline": 0}
    for line in data.splitlines():
        line = line.strip()
        if not line.startswith("["):
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        t = rec[0]
        if t == "LINE":
            out["LINE"] += 1
        elif t == "POUR":
            out["POUR"] += 1
        elif t == "PAD" and len(rec) > 4 and str(rec[4]) == "12":
            out["PAD"] += 1
        elif t == "PAD_NET":
            out["PAD_NET"] += 1
        elif t == "POLY" and len(rec) > 4 and str(rec[4]) == "11":
            out["POLY_outline"] += 1
    return out, raw_len


def render_selfcheck_pcb_report(
    eprj: str | Path,
    converted_pcbdoc: str | Path | None = None,
) -> str:
    """Markdown report: source PCB inventory + optional convert fidelity."""
    eprj = Path(eprj)
    raw, raw_bytes = _eprj_pcb_raw_counts(eprj)
    nl = parse_epcb(eprj) if raw_bytes >= 100 else None
    L: list[str] = []
    w = L.append

    w(f"# PCB 保真验收报告 — `{eprj.name}`")
    w("")
    w("## 0. 本报告回答什么")
    w("")
    w("- **目标**：确认「嘉立创 → AD」转换是否改变 **引脚接线、走线、过孔、铺铜（已解析部分）**。")
    w("- **金标准**：本文件内 **docType=3 PCB 原稿**（非 A02 原厂、非原理图页）。")
    w("- **不回答**：与 A02 PDF 是否一模一样；拼板/板高是否对齐。")
    w("")
    L.extend(render_pcb_fidelity_criteria())

    w("## 1. 嘉立创 PCB 原稿清单")
    w("")
    if raw_bytes < 100:
        w(f"- **状态**：❌ PCB 页为空白占位（dataStr ≈ {raw_bytes} B，仅 `DOCTYPE` 桩）")
        w("- **现象**：嘉立创客户端打开 **PCB 页空白**；原理图页可能有内容。")
        w("- **修复**：`migraeda convert <SchDoc> --to eprj --with-pcb <PcbDoc>` 重新生成（写入源文件旁的 `.migraeda/`）。")
        w("")
        w("## 2. 转换结果")
        w("")
        w("源 PCB 无有效数据，跳过转换比对。")
        return "\n".join(L)

    assert nl is not None
    w("| 记录类型 | 文件内条数 | 解析后 | 说明 |")
    w("|---|---:|---:|---|")
    w(f"| `LINE`（铜走线） | {raw.get('LINE', 0)} | {len(nl.tracks)} | "
      f"{'✅ 一致' if raw.get('LINE', 0) == len(nl.tracks) else '❌ 解析缺口'} |")
    w(f"| `POUR` | {raw.get('POUR', 0)} | — | 解析为 Polygon（另含闭合铜 `POLY`） |")
    w(f"| 铺铜 Polygon（解析合计） | — | {len(nl.polygons)} | `POUR` + 铜层闭合 `POLY` |")
    w(f"| `PAD`（过孔） | {raw.get('PAD', 0)} | {len(nl.vias)} | "
      f"{'✅' if raw.get('PAD', 0) == len(nl.vias) else '⚠️ 核对'} |")
    w(f"| `PAD_NET` | {raw.get('PAD_NET', 0)} | {len(nl.pads)} 焊盘 | 引脚↔网络（LVS 依据） |")
    w(f"| 板框 `POLY`/11 | {raw.get('POLY_outline', 0)} | {len(nl.board_outline)} 顶点 | 折线展开 |")
    w("")
    w(f"- **元件** {len(nl.components)}，**网络** {max(0, len(nl.nets) - 1)}，"
      f"**PCB 数据体积** ≈ {raw_bytes} 字符（解压后）")
    w("")
    w("### 走线条数说明")
    w("")
    w(f"- 本工程嘉立创原稿铜走线为 **`LINE` {raw.get('LINE', 0)} 段**；转换应 **原样导出**，"
      "不会增至 AD 常见的上万段。")
    w("- AD 原厂 PcbDoc 的 **总 Track** 常含 **丝印/机械层**、**拼板重复**、**铺铜 tessellation**，"
      "与 `LINE` 条数 **不可直接对比**。")
    w("")

    overall = True
    if converted_pcbdoc:
        converted_pcbdoc = Path(converted_pcbdoc)
        back = parse_pcb_ascii(converted_pcbdoc)
        lvs = compare_netlists(
            netlist_from_pcb(nl, source=f"eprj-pcb:{eprj.name}"),
            netlist_from_pcb(back, source=f"pcbdoc:{converted_pcbdoc.name}"),
        )
        geom = compare_pcb(nl, back, pos_tol_mil=1.0)
        ok_pins = lvs.common_pin_count - len(lvs.pin_mismatches)
        w(f"## 2. 转换结果 — `{converted_pcbdoc.name}`")
        w("")
        w("| 验收项 | 源 (eprj PCB) | 转换后 | 判定 |")
        w("|---|---:|---:|---|")
        pin_ok = not lvs.pin_mismatches
        w(f"| **引脚↔网络（核心）** | {lvs.common_pin_count} 可比 | {ok_pins} 一致 | "
          f"{'✅ PASS' if pin_ok else '❌ FAIL'} |")
        tr_ok = len(nl.tracks) == len(back.tracks)
        w(f"| 走线 Track | {len(nl.tracks)} | {len(back.tracks)} | "
          f"{'✅' if tr_ok else '❌'} |")
        v_ok = len(nl.vias) == len(back.vias)
        w(f"| 过孔 | {len(nl.vias)} | {len(back.vias)} | {'✅' if v_ok else '❌'} |")
        p_ok = len(nl.polygons) == len(back.polygons)
        w(f"| 铺铜 Polygon | {len(nl.polygons)} | {len(back.polygons)} | "
          f"{'✅' if p_ok else '❌'} |")
        w(f"| 几何时序（回读） | — | pcbdiff **{geom.grade}** | "
          f"{'✅' if geom.grade == 'PASS' else '⚠️' if geom.grade == 'WARN' else '❌'} |")
        w("")
        if lvs.pin_mismatches:
            w("### 引脚差异明细（最多 20）")
            w("")
            for pm in lvs.pin_mismatches[:20]:
                w(f"- `{pm.ref}.{pm.pin}`：源 `{pm.a_net}` → 转换 `{pm.b_net}`")
            w("")
        if geom.copper_diffs and geom.grade != "PASS":
            w("### 铜皮统计差异（前 15，仅回环几何）")
            w("")
            for item in geom.copper_diffs[:15]:
                w(f"- `{item}`")
            w("")
        overall = pin_ok and tr_ok and v_ok and p_ok and geom.grade != "FAIL"
    else:
        w("## 2. 转换结果")
        w("")
        w("未提供 `--converted` PcbDoc。转换后请执行：")
        w("")
        w("```bash")
        w(f"migraeda selfcheck --pcb \"{eprj.as_posix()}\" \\")
        w(f"  --converted \"{eprj.parent.as_posix()}/.migraeda/{eprj.stem}.PcbDoc\" --report .migraeda/fidelity_pcb.md")
        w("```")
        w("")

    w("## 3. 总体结论")
    w("")
    if raw_bytes < 100:
        w("**❌ 源 PCB 空白，无法验收转换。**")
    elif converted_pcbdoc:
        w(f"**{'✅ 保真通过（引脚/走线/过孔/铺铜条数与源一致）' if overall else '❌ 存在差异，见 §2'}**")
    else:
        w("**ℹ️ 仅完成源清单；待提供转换 PcbDoc 后给出 PASS/FAIL。**")
    w("")
    w("## 4. 相关报告索引")
    w("")
    w("| 文件 | 用途 |")
    w("|---|---|")
    w("| `verify_*.md` | 引脚 LVS（注意 §0 比对口径） |")
    w("| `pcbdiff_*.md` | 布局/铜皮统计；跨 A01/A02 仅参考 |")
    w("| convert 控制台 `fidelity-verify` | 与 §2 同口径的快速结论 |")
    w("")
    return "\n".join(L)


def selfcheck_pcb(
    eprj: str | Path,
    converted_pcbdoc: str | Path | None = None,
) -> str:
    return render_selfcheck_pcb_report(eprj, converted_pcbdoc)


def write_selfcheck_pcb_report(
    eprj: str | Path,
    out: str | Path,
    converted_pcbdoc: str | Path | None = None,
) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_selfcheck_pcb_report(eprj, converted_pcbdoc), encoding="utf-8")
    return out
