"""Standard verification report (Markdown) for `migraeda verify --report`."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from migraeda.lvs import LvsResult, norm_ref
from migraeda.netlist_model import NetlistModel
from migraeda.report_common import detect_comparison_kind, render_scope_and_pitfalls
from migraeda.report_common import detect_comparison_kind, render_scope_and_pitfalls


def _verdict(res: LvsResult) -> str:
    if res.common_pin_count == 0:
        return "无法比对：两边没有共同位号的引脚（位号体系完全不同）"
    n_mis = len(res.pin_mismatches)
    if n_mis == 0:
        if not res.a_only_nets and not res.b_only_nets:
            return "一致 ✅：公共引脚全部匹配，无独有网络"
        return "一致 ✅：公共引脚全部匹配（存在各自独有网络，见 §4）"
    ratio = n_mis / res.common_pin_count
    if ratio < 0.05:
        return f"基本一致 ⚠️：{n_mis}/{res.common_pin_count} 引脚存在差异（{ratio:.1%}）"
    return f"不一致 ❌：{n_mis}/{res.common_pin_count} 引脚存在差异（{ratio:.1%}）"


def _stats_of(m: NetlistModel) -> str:
    n_vp = len(m.virtual_pins)
    vp = f"，含 {n_vp} 个虚拟引脚" if n_vp else ""
    return f"{len(m.components)} 元件 / {len(m.pin_nets)} 引脚 / {len(m.net_members())} 网络{vp}"


def render_verify_report(a: NetlistModel, b: NetlistModel, res: LvsResult) -> str:
    L: list[str] = []
    w = L.append
    w("# 设计文件功能验证报告（LVS）")
    w("")
    kind = detect_comparison_kind(a.source, b.source)
    L.extend(render_scope_and_pitfalls(kind))
    w("| 侧 | 文件 | 解析统计 |")
    w("|---|---|---|")
    w(f"| A | `{res.a_name}` | {_stats_of(a)} |")
    w(f"| B | `{res.b_name}` | {_stats_of(b)} |")
    w("")
    w("方法：提取两边引脚级网表，以 `位号.引脚→网络` 为锚点做 LVS 比对；"
      "网络对应先按名称（忽略大小写）再按引脚成员结构贪心匹配。")
    w("")
    w("## 总体结论")
    w("")
    w(f"**{_verdict(res)}**")
    w("")
    w(f"- 公共引脚 {res.common_pin_count}，不匹配 {len(res.pin_mismatches)}；"
      f"网络匹配 {len(res.matches)}（名称匹配 {sum(1 for m in res.matches if m.by_name)}，"
      f"结构匹配 {sum(1 for m in res.matches if not m.by_name)}）")
    w(f"- 位号：A 侧独有 {len(res.a_only_refs)}，B 侧独有 {len(res.b_only_refs)}")
    if res.a_only_refs:
        w(f"  - A: {', '.join(f'`{r}`' for r in res.a_only_refs)}")
    if res.b_only_refs:
        w(f"  - B: {', '.join(f'`{r}`' for r in res.b_only_refs)}")
    w("")

    w("## 1. 网络对应表")
    w("")
    w("| A 网络 | B 网络 | 共享引脚 | 匹配方式 |")
    w("|---|---|---|---|")
    for m in res.matches:
        w(f"| `{m.a_net}` | `{m.b_net}` | {m.shared_pins}（A {m.a_size} / B {m.b_size}） "
          f"| {'名称' if m.by_name else '结构'} |")
    w("")

    w("## 2. 引脚级差异（按网络对分组）")
    w("")
    if not res.pin_mismatches:
        w("无。")
        w("")
    else:
        groups: dict[tuple[str, str], list[str]] = defaultdict(list)
        for pm in res.pin_mismatches:
            groups[(pm.a_net, pm.b_net)].append(f"{pm.ref}.{pm.pin}")
        w("| A 网络 | B 网络 | 引脚 |")
        w("|---|---|---|")
        for (na, nb), pins in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            show = ", ".join(f"`{p}`" for p in pins[:10])
            w(f"| `{na}` | `{nb}` | {len(pins)}：{show}{'…' if len(pins) > 10 else ''} |")
        w("")

    w("## 3. 各自独有的引脚（位号在两边都存在但引脚只在一侧有网络）")
    w("")
    if res.a_only_pins or res.b_only_pins:
        if res.a_only_pins:
            w(f"- 仅 A 侧（{len(res.a_only_pins)}）："
              + ", ".join(f"`{r}.{p}`" for r, p in res.a_only_pins[:40]))
        if res.b_only_pins:
            w(f"- 仅 B 侧（{len(res.b_only_pins)}）："
              + ", ".join(f"`{r}.{p}`" for r, p in res.b_only_pins[:40]))
    else:
        w("无。")
    w("")

    w("## 4. 各自独有的网络")
    w("")
    if res.a_only_nets:
        w(f"**仅 A**（{len(res.a_only_nets)}）：`{'`, `'.join(res.a_only_nets)}`")
        w("")
    if res.b_only_nets:
        w(f"**仅 B**（{len(res.b_only_nets)}）：`{'`, `'.join(res.b_only_nets)}`")
        w("")
    if not res.a_only_nets and not res.b_only_nets:
        w("无。")
        w("")

    w("## 5. BOM 对比（共有位号）")
    w("")
    a_by = {norm_ref(r): c for r, c in a.components.items()}
    b_by = {norm_ref(r): c for r, c in b.components.items()}
    common = sorted(set(a_by) & set(b_by))
    w("| 位号 | A 值 / 封装 | B 值 / 封装 |")
    w("|---|---|---|")
    for ref in common:
        ca, cb = a_by[ref], b_by[ref]
        w(f"| {ref} | {ca.value or '—'} / {ca.footprint or '—'} "
          f"| {cb.value or '—'} / {cb.footprint or '—'} |")
    w("")

    w("## 6. 覆盖度与限制")
    w("")
    for m in (a, b):
        for n in m.notes:
            w(f"- [{m.source}] {n}")
    w("- 比对基于静态网表，不含电气仿真；命名单元以两边文件为准。")
    w("- **不含**：走线几何、铺铜轮廓、过孔在 AD 二进制流中的解析完整性、PDF 视觉。")
    w("")
    w("## 7. 与其它报告的分工")
    w("")
    w("| 问题 | 应查看 |")
    w("|---|---|")
    w("| 转换有没有改引脚/走线/过孔/铺铜条数 | `selfcheck --pcb` / convert 的 `fidelity-verify` |")
    w("| 板子布局/铜皮统计是否像 A02 | `pcbdiff`（参考，跨版通常 FAIL） |")
    w("| 原厂 AD 原理图与 PCB 是否一致 | `verify SchDoc PcbDoc` |")
    w("| 嘉立创 eprj 能否打开 PCB 页 | `selfcheck` 是否提示 PCB 桩；或 `--with-pcb` 重建 |")
    w("")
    return "\n".join(L)


def write_verify_report(a: NetlistModel, b: NetlistModel, res: LvsResult,
                        out: str | Path) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_verify_report(a, b, res), encoding="utf-8")
    return out
