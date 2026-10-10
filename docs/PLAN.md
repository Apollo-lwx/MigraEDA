# MigraEDA 完整落地计划

> 产品一句话：KiCad 能打开你的嘉立创工程；我们告诉你哪里其实已经坏了，并能回滚。
> 自研重点：normalize → migrate → diff → report → audit/rollback（不是又一个库转换器）。

## 1. 目标与非目标

### 目标（MVP）
- 解析合成 `.epro` 金标 fixture（ZIP + 简化 JSON），无 KiCad 也可运行。
- CLI：`migrate` / `diff` / `report` / `rollback` 全通，exit 0。
- `diff_v0`：元件数、网络名集合、过孔数 → PASS / WARN / FAIL。
- 审计与回滚：每次迁移写入 `migration_id`、源/结果哈希、产物路径；`rollback` 可恢复。
- `pytest` 在无 KiCad 环境全绿；可选 KiCad/pcbnew 后端探测后启用。

### 非目标（本周不做）
- 重写完整 EasyEDA→KiCad 导入引擎。
- 官方完整 `.epro` schema 兼容（用合成 fixture + 文档声明）。
- 账号体系、付费墙、官网、Altium 导出。
- 静态链接 GPL EasyKiConverter。

## 2. 阶段与里程碑

| 阶段 | 时间 | 交付 | 成功标准 |
|------|------|------|----------|
| P0 计划与骨架 | Day 1 | `docs/PLAN.md`、包结构、MIT、gitignore | 仓可读、可安装 |
| P1 解析与规范化 | Day 1–2 | `epro_parse` + `normalize` + 2 个 golden fixture | 解析出元件/网络/过孔 |
| P2 diff_v0 + report | Day 2 | `diff` / `report`，MD + JSON | 分级正确；CLI 冒烟 |
| P3 migrate dry-run + audit | Day 2–3 | stub 迁移、审计库、rollback | `migrate --dry-run` 全绿 |
| P4 测试与推送 | Day 3 | pytest、README、推 Gitee | 成功标准 1–6 全满足 |
| P5（后续）KiCad 实机 | Week 2+ | 可选 pcbnew/CLI 后端 | 有 KiCad 时真导入仍可 diff |

## 3. 本周可交付（已落地范围）

1. **可安装包** `migraeda`（`pip install -e .`）。
2. **合成 fixture** ≥2：`simple.epro`、`bus_mismatch.epro`（故意网络差异供 WARN/FAIL）。
3. **管道**：parse → normalize → migrate(dry-run) → diff → report → audit。
4. **自动化测试**：parse / normalize / diff / report / cli / audit。
5. **文档**：PLAN + README（安装/运行/限制）。

## 4. 技术设计摘要

```
.epro (ZIP)
  project.json          # 工程元数据
  boards/*.epcb.json    # 简化 PCB：components / nets / vias
  sheets/*.esch.json    # 简化原理图（可选）
       │
       ▼
  epro_parse → ProjectModel
       │
       ▼
  normalize → ProjectStats (component_count, net_names, via_count, …)
       │
       ▼
  migrate
    ├─ dry-run / no KiCad: 写 kicad_stats.json + 占位 .kicad_pro/.kicad_pcb 文本
    └─ KiCad 可用（可选）: 调用 pcbnew 或外部 CLI（本 MVP 仅探测钩子）
       │
       ▼
  diff_v0 → DiffResult (PASS/WARN/FAIL) + diff.json
       │
       ▼
  report → report.md / report.html
       │
       ▼
  audit → ~/.migraeda/audit/<migration_id>/ 或 -o 下的 .migraeda/
```

### diff_v0 分级规则
- **PASS**：元件数相等；网络名集合相等；过孔数相等。
- **WARN**：元件数相等，但网络名有对称差 ≤2，或过孔数差 1。
- **FAIL**：元件数不等，或网络对称差 >2，或过孔差 >1。

### 回滚
- 迁移前快照输出目录（若已存在）与写入清单。
- `rollback <migration_id>` 删除本次产物或恢复快照。

## 5. 后续 KiCad 实机扩展

1. 探测 `pcbnew` Python 或 `kicad-cli`。
2. 将 dry-run 占位替换为真实导入（可包装 KiCad 原生 EasyEDA Pro import）。
3. 从真实 `.kicad_pcb` 抽取 stats，再进同一套 `diff`。
4. 金标扩展到 2 层、≤200 元件真实匿名样例（需用户授权）。

## 6. 风险与缓解

| 风险 | 缓解 |
|------|------|
| 真实 `.epro` schema 未知/变更 | 合成 fixture + 适配器接口；真实文件走 normalize 扩展点 |
| 无 KiCad 无法演示「能打开」 | dry-run 产出可打开的最小占位 + 明确文档 |
| 用户期望「完美转换」 | 对外话术锁定「可验证」，报告是产品 |

## 7. 许可

- 核心代码：**MIT**
- 不静态链接 GPL EasyKiConverter；可选外部进程调用需用户自行安装并自负许可责任（本仓不捆绑）。
