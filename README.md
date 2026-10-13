# MigraEDA

> 嘉立创 ↔ Altium 双向转换，每一步转换都有独立验证兜底。

**转换 + 验证闭环**：原理图 / PCB / 库三条链路，**不写一行"请相信转换器"的代码**——
每次转换自动重解析产物并做引脚级 LVS 比对，不一致即返回非零退出码。

| 别人做 | MigraEDA 做 |
|--------|-------------|
| 静默转换（嘉立创官方导入导出，丢了不告诉你） | 转换 + **引脚级闭环验证**，错位精确到 `位号.引脚` |
| 肉眼开两个 EDA 比图 | 自动 LVS 报告（PASS / WARN / FAIL + 标准 Markdown 报告） |
| 只转原理图 | 原理图 + **PCB（走线/过孔/铜皮）** + **库（符号/封装）** |

---

## 支持的格式

| 格式 | 读 | 写 | 说明 |
|------|----|----|------|
| 嘉立创 `.eprj` | ✅ 原理图 + **PCB**（docType=3）+ 内嵌库 | ✅ 原理图 + **PCB** + 库包 | SQLite 工程，零依赖解析 |
| AD `.SchDoc` | ✅ 二进制 + ASCII | ✅ ASCII | 多部件/多显示模式语义完整实现 |
| AD `.PcbDoc` | ✅ 二进制 + ASCII | ✅ ASCII | 焊盘/过孔/走线/圆弧/铺铜/板框 |
| AD `.SchLib` / `.PcbLib` | ✅ | 待样本验证后开放 | 可用 `libinspect` 结构自检 |
| 嘉立创专业版 `.epro` | ✅（早期 MVP 管道） | — | 见下文「.epro → KiCad 管道」 |

---

## 快速开始

```bash
git clone https://gitee.com/luowenxing/MigraEDA.git
cd MigraEDA
pip install -e ".[dev]"
pytest -q        # 40 项测试全绿即可
```

设计文件按 [`samples/README.md`](samples/README.md) 投到 `samples/<项目名>/`（按扩展名自动归类，**内容不入库**）：

```bash
migraeda samples                                        # 查看识别到的样本
migraeda roundtrip samples/XXX/板子.eprj                 # 一键：转换+往返+自比对
```

---

## 命令一览

### 转换（全部自动闭环验证）

```bash
migraeda convert 板子.eprj   --to ad     # 嘉立创 → AD ASCII 原理图
migraeda convert 板子.SchDoc --to eprj   # AD 原理图 → 嘉立创工程
migraeda convert 板子.eprj   --to adpcb  # 嘉立创 PCB → AD ASCII PcbDoc
migraeda libconvert 库.PcbLib -o out     # 库 → 嘉立创库包
```

### 验证

```bash
migraeda verify a.eprj b.SchDoc [--report out.md]   # 引脚级 LVS（网表等价性）
migraeda pcbdiff a.PcbDoc b.PcbDoc [--report out.md] # PCB 级 diff（板框/元件/焊盘/过孔/铜皮）
migraeda libdiff a b [--report out.md]               # 库级 diff（符号引脚/封装焊盘）
```

`verify` / `pcbdiff` / `libdiff` 均支持 `.eprj` / `.SchDoc` / `.PcbDoc`（二进制或 ASCII）混比，
坐标系/拼板差异自动做刚体对齐后再比位置。

### 往返自比对

```bash
migraeda roundtrip 板子.eprj    # 原理图+PCB 双程：转出→转回→与原文件逐点比
migraeda roundtrip 板子.SchDoc
```

中间产物全部留档（`out/roundtrip/`），结论只有两种：`IDENTICAL ✅` / `DIFFERS ❌`。

### 辅助

```bash
migraeda samples                  # 列出 samples/ 下的设计样本
migraeda libinspect 文件          # 结构自检（仅元数据，可安全外发求助）
```

---

## 为什么可信：验证方法论

本工具的核心不是"能转"，而是"**转完可证**"：

1. **loop-verify（内环）**：转换产物立即重新解析，与源文件做引脚级 LVS——0 不匹配才放行。
2. **全管线比对（外环）**：产物与"原厂另一份文件"比对，差异必须等于两版设计的已知差异，
   多一处都是转换器 bug（旋转手性 bug 就是这样被抓到归零的）。
3. **往返自比对（闭环）**：`A → B → A`，终件与原文件必须逐点一致。

几何连通重建规则（与 KiCad 导入器语义对齐）：导线端点/T 型相接、**零长度网络点**、
引脚直接对碰、**多部件元件只激活 `OWNERPARTID==CURRENTPARTID` 的引脚**、
多显示模式取当前模式、Altium 网络名大小写不敏感、拼板实例归并。

---

## .epro → KiCad 管道（早期 MVP）

原始能力保留：`migrate` / `diff` / `report` / `rollback`，面向嘉立创专业版 `.epro` 的
可验证 KiCad 迁移（无 KiCad 时 dry-run 全通）：

```bash
migraeda migrate <input.epro> -o <outdir> [--dry-run]
migraeda diff <source.epro> <kicad_or_stats.json> -o report.md
migraeda report <diff.json> -o report.md|--html
migraeda rollback <migration_id>
```

### diff_v0 分级

| 等级 | 条件（摘要） |
|------|----------------|
| **PASS** | 元件数、网络名集合、过孔数均一致 |
| **WARN** | 网络对称差 ≤2，或过孔差 1（元件数须一致） |
| **FAIL** | 元件数不等，或网络对称差 >2，或过孔差 >1 |

---

## 限制与边界（诚实版）

- **符号/封装图形不转**：转换后的符号是按引脚位置合成的方框（引脚编号/位置/连通精确），
  库图形不在范围；封装保留名称引用与焊盘几何。
- **PCB 写出为 ASCII .PcbDoc**：AD 可直接打开；二进制 PcbDoc 只读。
- **库写出目前仅嘉立创侧**：AD 库（SchLib/PcbLib）写出待真实样本校准。
- 生成的 `.eprj` 已按真实 schema 复刻并通过自家解析器回读验证，客户端打开情况以实测为准。

---

## Fixtures

`fixtures/golden/*.epro` 是 **合成 ZIP + JSON**，字段名贴近公开资料，**不是**官方完整 schema。
重建：`python scripts/build_fixtures.py`。

## 许可

核心 **MIT**。不要静态链接 GPL EasyKiConverter。

## 联系

仓库与产品名：**MigraEDA**。问题请开 Issue 或改本 README。
