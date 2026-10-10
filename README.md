# MigraEDA

> KiCad 能打开你的嘉立创工程；我们告诉你哪里其实已经坏了，并能回滚。

**可验证迁移**：嘉立创 / EasyEDA 专业版 → KiCad（后续探索 Altium）  
不是「尽力转换」，而是 **规范化 → 转换 → 差异报告 → 审计 / 回滚**。

---

## 现状（为什么做）

| 路径 | 能力 | 缺口 |
|------|------|------|
| 库转换开源（easyeda2kicad.py / EasyKiConverter / JLC2KiCad_lib） | 符号 / 封装 / 3D | **不做整项目** |
| KiCad 原生 Import EasyEDA Pro | 原理图 + PCB 只读导入 | **无差异报告、无回滚** |
| 官方格式转换助手 | 迁**入**嘉立创强；导出到 KiCad **不支持** | 迁出免责、勿反复转 |
| epro2kicad（MIT） | `.epro` 修复 + 无头 PCB 导入 | 原理图仍需 GUI；无产品化差异层 |

空白：**工程级、可验证、可审计的无损迁出**。

---

## 产品范围（MVP）

### In scope（第一版）

- 来源：嘉立创 / EasyEDA **专业版** `.epro`
- 目标：KiCad 8/9/10 工程包（单向）
- 板型：以 **2 层**为主；≤200 元件；单 sheet 或浅层级
- 输出：转换结果 + **差异报告**（摘要免费 / 完整付费）+ 审计日志 + 可回滚快照

### Out of scope（0–6 月不做）

- Altium GA、双向同步、标准版完整 SLA
- ≥6 层 / HDI / 刚挠、「DRC 像素级保证」
- 爬取用户嘉立创账号、重写 KiCad 导入器

---

## 架构（草案）

```
.epro (ZIP / JSONL)
    → normalize/   # 换行、RULE、NET、版本指纹
    → engine/      # KiCad pcbnew（+ 原理图 GUI/IPC）
    → diff/        # 源统计 vs KiCad → diff.json
    → report/      # 摘要(Free) / 完整(Paid)
    → audit/       # migration_id、hash、回滚
```

自研重点在 **差异与审计**；转换引擎站在 KiCad 原生导入 + epro2kicad 式预处理上。

---

## 仓库状态

私有仓库，早期脚手架。近期计划：

1. 金标 `.epro` 样例（不含用户私密工程）
2. CLI：`migrate input.epro -o out/`
3. `diff_v0`：元件数 / 网络名集合 / 过孔数
4. 支持矩阵与已知限制文档

---

## 许可

待定（核心倾向 MIT / Apache-2.0；避免把 GPL 库转换器静态链进闭源发行版）。

---

## 联系

内部产品名：**MigraEDA**。对外叙事以 README 顶部一句话为准。
