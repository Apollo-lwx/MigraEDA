# MigraEDA

> KiCad 能打开你的嘉立创工程；我们告诉你哪里其实已经坏了，并能回滚。

**可验证迁移**（嘉立创 / EasyEDA 专业版 `.epro` → KiCad）：normalize → migrate → **diff** → report → audit / rollback。  
不是又一个库转换器。

| 别人做 | MigraEDA 做 |
|--------|-------------|
| 库转换（easyeda2kicad.py / EasyKiConverter / JLC2KiCad_lib） | **不做**库转换 |
| KiCad 原生 Import + 肉眼检查 | **差异报告**（元件 / 网络 / 过孔） |
| 官方 AD 导出免责 | 审计 + **可回滚** |

---

## 快速开始

```bash
git clone https://gitee.com/luowenxing/MigraEDA.git
cd MigraEDA
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 无 KiCad 也可跑通
migraeda migrate fixtures/golden/simple.epro -o /tmp/migraeda-out --dry-run
cat /tmp/migraeda-out/report.md

pytest -q
```

### CLI

```bash
migraeda migrate <input.epro> -o <outdir> [--dry-run]
migraeda diff <source.epro> <kicad_or_stats.json> -o report.md
migraeda report <diff.json> -o report.md|--html
migraeda rollback <migration_id>

# 三格式原理图转换（闭环自验证）与 LVS 比对
migraeda convert <input.eprj|input.SchDoc> --to ad|eprj [-o outdir] [--no-verify]
migraeda verify <a.eprj|a.SchDoc|a.PcbDoc> <b...> [--limit N]
```

**convert**：嘉立创 `.eprj` ↔ AD `.SchDoc` 原理图级转换（元件/引脚/导线/网络标签/电源符号，
符号为按引脚位置合成的方框；每次转换自动重解析输出并做引脚级 LVS 闭环验证，不一致退出码非零）。

**verify**：任意两份设计文件（嘉立创 `.eprj` / AD `.SchDoc` / AD `.PcbDoc`）的引脚级网表比对，
输出公共引脚、逐引脚差异、网络对应关系（先按名称匹配，再按引脚成员结构匹配）。

```bash
migraeda verify <a> <b> [--report out.md]   # + 标准验证报告
migraeda pcbdiff <a.PcbDoc> <b.PcbDoc>      # PCB 级 diff（板框/焊盘/过孔/铜皮）
migraeda libdiff <a> <b>                    # 库级 diff（符号引脚/封装焊盘）
migraeda libconvert <a> -o out              # 库 → eprj 库包（闭环验证）
migraeda samples                            # 列出 samples/ 下已识别的设计样本
```

### 样本目录约定

需要验证/转换的真实设计文件，按 [`samples/README.md`](samples/README.md) 的规范投到
`samples/<项目名>/`（按扩展名自动归类，目录内容不入库），`migraeda samples` 随时查看识别结果。

`migrate --dry-run`（默认在无 KiCad 时等价启用）会写出：

- `source_stats.json` / `kicad_stats.json`
- `diff.json` + `report.md` / `report.html`
- 占位 `.kicad_pro` / `.kicad_pcb` / `.kicad_sch`
- 审计记录（`MIGRAEDA_AUDIT_DIR` 或 `~/.migraeda/audit/<migration_id>/`）

### diff_v0 分级

| 等级 | 条件（摘要） |
|------|----------------|
| **PASS** | 元件数、网络名集合、过孔数均一致 |
| **WARN** | 网络对称差 ≤2，或过孔差 1（元件数须一致） |
| **FAIL** | 元件数不等，或网络对称差 >2，或过孔差 >1 |

---

## MVP 范围

**In scope（第一版）**

- 源：嘉立创 / EasyEDA **专业版** `.epro`（合成 fixture + 可扩展解析）
- 目标：KiCad 8/9/10 管道（无 KiCad 时 dry-run）
- 仅 **2 层**、≤200 元件；单 sheet 假设
- 输出：差异报告 + 审计 + 可回滚

**Out of scope（0–6 月不做）**

- Altium GA、多层/HDI、盲埋孔、完整 DRC 像级保证
- 账号、付费墙、重写 KiCad 导入引擎

架构细节与里程碑见 [`docs/PLAN.md`](docs/PLAN.md)。

---

## Fixtures

`fixtures/golden/*.epro` 是 **合成 ZIP + JSON**，字段名贴近公开资料，**不是**官方完整 schema。  
重建：`python scripts/build_fixtures.py`。

---

## 许可

核心 **MIT**。不要静态链接 GPL EasyKiConverter。

---

## 联系

仓库与产品名：**MigraEDA**。问题请开 Issue 或改本 README。
