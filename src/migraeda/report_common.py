"""Shared report sections (comparison scope, acceptance, pitfalls)."""

from __future__ import annotations



def detect_comparison_kind(source_a: str, source_b: str) -> str:
    """Human-readable label for verify report header."""
    a, b = source_a.lower(), source_b.lower()
    if "eprj-pcb" in a or "eprj-pcb" in b:
        return "PCB 焊盘网表（嘉立创 PCB ↔ Altium/ASCII PcbDoc）"
    if "pcbdoc" in a and "pcbdoc" in b:
        return "PCB 焊盘网表（两份 PcbDoc）"
    if "eprj:" in a and "pcbdoc" in b:
        return "原理图网表 ↔ PCB 焊盘（跨页，网络名常不一致）"
    if "schdoc" in a and "pcbdoc" in b:
        return "原理图 ↔ PCB（原厂 AD 内部 LVS）"
    if "eprj:" in a and "schdoc" in b:
        return "嘉立创原理图 ↔ Altium 原理图"
    return "引脚级网表 LVS（通用）"


def render_scope_and_pitfalls(comparison_kind: str) -> list[str]:
    L: list[str] = []
    w = L.append
    w("## 0. 报告说明与比对口径")
    w("")
    w(f"- **比对类型**：{comparison_kind}")
    w("- **比对内容**：仅 `位号.引脚 → 网络名`（静态 LVS），**不**比对走线路径、铺铜形状、"
      "丝印、3D、DRC、仿真。")
    w("- **通过含义**：公共位号上，引脚所连网络在两边一致（或结构等价匹配）；"
      "**不**表示 PDF/截图视觉一致。")
    w("")
    w("### 常见误读（请对照场景）")
    w("")
    w("| 场景 | 正确金标准 | 误用报告 |")
    w("|---|---|---|")
    w("| `A01.eprj` → AD 转换是否改线/改网 | 同一份 eprj 的 **PCB** vs `.migraeda/*.PcbDoc` | "
      "用 A02 原厂 PcbDoc 或原理图 vs PCB |")
    w("| 原厂 AD 原理图↔PCB 是否自洽 | `A02.SchDoc` vs `A02.PcbDoc` | 用嘉立创 eprj 比 A02 |")
    w("| 走线条数为何 2501 vs ~2 万 | 看 eprj 内 **`LINE` 原稿条数** | 直接比 AD 总 Track（含丝印/拼板/碎化铺铜） |")
    w("| 嘉立创打开 eprj PCB 空白 | PCB 页 `dataStr` 是否只有 `DOCTYPE` 桩 | 只看 LVS PASS |")
    w("")
    w("### 推荐验收命令（嘉立创 → AD PCB）")
    w("")
    w("```bash")
    w("migraeda convert <工程.eprj> --to adpcb")
    w("migraeda verify <工程.eprj> .migraeda/<工程>.PcbDoc --report .migraeda/verify_convert.md")
    w("migraeda selfcheck --pcb <工程.eprj> --converted .migraeda/<工程>.PcbDoc --report .migraeda/fidelity_pcb.md")
    w("```")
    w("")
    if "原理图" in comparison_kind and "PCB" in comparison_kind:
        w("> ⚠️ 当前为 **原理图 ↔ PCB** 跨页比对：嘉立创 `$1Nxxx` / `~Net*` 与 AD 自动网名"
          "不对齐时，出现若干引脚差异**不一定**表示布线错误；转换保真请改用 "
          "`verify eprj.eprj converted.PcbDoc`（工具会自动用 eprj **PCB 页**网表）。")
        w("")
    return L


def render_pcb_fidelity_criteria() -> list[str]:
    L: list[str] = []
    w = L.append
    w("### PCB 转换保真验收项（核心设计要素）")
    w("")
    w("| 项目 | 要求 | 工具 |")
    w("|---|---|---|")
    w("| 引脚↔网络 | 与 eprj PCB `PAD_NET` **0 差异** | `verify` / `selfcheck --pcb` |")
    w("| 走线 `LINE` | 条数与源一致 | `selfcheck --pcb` |")
    w("| 过孔 | 条数一致 | `selfcheck --pcb` |")
    w("| 铺铜 `POUR`/闭合铜区 | Polygon 条数一致（当前解析范围内） | `selfcheck --pcb` |")
    w("| 板形/拼板 | 非强制；与 A02 视觉对比无 PASS/FAIL 含义 | `pcbdiff` 仅供参考 |")
    w("")
    w("**已知未写入或未比对项**（不影响上表 PASS，但可能影响肉眼/PDF）：")
    w("- 嘉立创 `POLY` 阻焊/机械层（layer 6/14 等）多数未导出到 AD")
    w("- 路径中的 **`ARC` 段**未 tessellate，尖角/圆弧可能与 AD 截图略有差异")
    w("- AD→eprj（`--with-pcb`）目前主要写 **LINE/过孔/焊盘**；AD Fill/Polygon 铺铜未完整回写")
    w("- 仅 `convert --to eprj` **不带** `--with-pcb` 时，PCB 页为空白桩")
    w("")
    return L


def render_pcbdiff_scope() -> list[str]:
    L: list[str] = []
    w = L.append
    w("## 0. 报告说明")
    w("")
    w("- **比对类型**：PCB **几何与铜皮统计**（板框、元件集合、焊盘坐标、按网络的走线条数/长度）。")
    w("- **不比对**：引脚网络是否正确（请用 `verify`）；走线是否逐段重合；丝印文字。")
    w("- **跨工具**（嘉立创 eprj vs AD A02）：常见 **FAIL**（坐标系、拼板、铺铜碎化、网络集合不同），"
      "**不能**当作「转换失败」的唯一依据。")
    w("- **AD 总 Track 数**常含丝印层线段；铜层统计见下方「铜皮差异」。")
    w("")
    return L
