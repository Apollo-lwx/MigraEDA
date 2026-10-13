# MigraEDA 落地计划与当前状态

> 产品一句话：嘉立创 ↔ Altium 双向转换，每一步转换都有独立验证兜底。
> 本文档为**当前状态版**（2026-10-13），取代 MVP 时期旧计划。

## 1. 定位

**转换 + 验证闭环**：原理图 / PCB / 库三条链路。
不写"请相信转换器"的代码——每次转换自动重解析产物并做引脚级 LVS 比对。

差异化（对照嘉立创官方导入导出）：

| 嘉立创官方 | MigraEDA |
|------------|----------|
| 静默转换，丢失不报告 | 转换 + 引脚级闭环验证，错位精确到 `位号.引脚` |
| 无跨格式比对 | 自动 LVS（PASS/WARN/FAIL + 标准报告） |
| 仅原理图 | 原理图 + PCB + 库 |
| GUI 手工 | 全 CLI，可进 CI |

## 2. 当前架构

```
                ┌──────────── 读 ────────────┐
  .eprj(SQLite) │ eprj_sqlite / epcb         │  .SchDoc(OLE/ASCII)
       ───────► │ eprj_lib / schlib / pcblib │ ◄───────
                │ pcbdoc (PcbDoc OLE/ASCII)  │
                └─────────────┬──────────────┘
                              ▼
                    SchematicIR / PcbNetlist / Library
                              │
                ┌─────────────┼─────────────┐
                ▼             ▼             ▼
        adascii(SchDoc)  eprj_write   pcbascii(PcbDoc)
        eprj_pcb_write   libconvert        │
                └─────────────┬─────────────┘
                              ▼
        lvs(引脚级)   pcbdiff(几何级)   libdiff(库级)
                              │
                     roundtrip（A→B→A 自比对）
```

核心引擎 `schgeom.py`：导线端点/T 型相接、零长度网络点、引脚对碰、
并查集按名合并（Altium 大小写不敏感）、多部件/多显示模式过滤。

## 3. 已交付（里程碑）

| 里程碑 | 内容 | 状态 |
|--------|------|------|
| M0 | `.epro → KiCad` 可验证迁移管道（migrate/diff/report/rollback） | ✅ 保留 |
| M1 | 嘉立创 `.eprj` 解析（原理图 + 内嵌库） | ✅ |
| M2 | AD `.SchDoc` 解析（二进制+ASCII，多部件/多模式） | ✅ |
| M3 | AD `.PcbDoc` 解析（焊盘/过孔/走线/圆弧/铺铜/板框） | ✅ |
| M4 | 引脚级 LVS + 标准验证报告（verify --report） | ✅ |
| M5 | 原理图双向转换 + 闭环验证（eprj↔SchDoc，0 误差） | ✅ |
| M6 | 嘉立创 PCB 解析（epcb：PAD_NET/LINE/元件/过孔/板框） | ✅ |
| M7 | PCB 级 diff（pcbdiff：板框/元件/焊盘/过孔/铜皮，刚体对齐） | ✅ |
| M8 | 库提取/比对/转换（libdiff/libconvert，eprj 侧闭环） | ✅ |
| M9 | PCB 转换（eprj→ASCII PcbDoc，loop pcbdiff PASS） | ✅ |
| M10 | 往返自比对（roundtrip：原理图双 IDENTICAL + PCB PASS） | ✅ |
| M11 | samples/ 样本约定 + libinspect 结构自检 | ✅ |

实测基线（SME-IOT-1）：AD 内部一致性 376/376 引脚 0 差异；
原理图双向往返 IDENTICAL；PCB 往返 pcbdiff PASS；测试 40 项全绿。

## 4. 当前范围

**In scope**
- 嘉立创 `.eprj`（原理图/PCB/内嵌库）与 AD `.SchDoc/.PcbDoc`（二进制+ASCII）
- 2 层板为主；单 sheet；≤500 元件量级已实测
- 转换产物的**独立验证**为第一公民

**Out of scope（明确不做）**
- 重写 KiCad / 嘉立创原生导入引擎
- 库图形保真转换（符号/封装的图形外观）
- 多层（>2）板的专项处理、盲埋孔、完整 DRC 级保证
- 电气功能仿真（文件内无 SPICE 模型/激励，做了静态电气合理性检查替代）
- 账号体系、付费墙

**风险项（已知边界）**
- 生成的 `.eprj` / ASCII `.PcbDoc` 以格式规范 + 自研解析器回读验证，
  客户端打开兼容性以实测为准（样本验证通道已留：samples/ + libinspect）
- AD 库（SchLib/PcbLib）写出待真实样本校准

## 5. 后续方向（按价值排序）

1. **T3.3 AD 库写出**（等 SchLib/PcbLib 样本或 libinspect 自检输出）
2. 嘉立创 `.epcb` 独立 PCB 文件支持（格式同 docType=3，待样本）
3. 多 sheet 原理图
4. 验证报告 HTML 化 + CI Action 封装
5. P5 远期：KiCad 实机管道接通真实导入（原 M0 延伸）

## 6. 许可

核心 **MIT**。不静态链接 GPL EasyKiConverter。
