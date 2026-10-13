# samples/ — 用户设计样本投递目录

把需要验证/转换的设计文件按下面的规范放进来，工具命令（`migraeda samples`、`verify`、`convert`、
`pcbdiff`、`libdiff`、`libconvert`）即可直接引用。**本目录内容默认不入库**（`.gitignore` 已覆盖，
只有本 README 被跟踪），设计文件属商业机密也不会外泄。

## 目录结构

```
samples/
  <项目名>/            # 一块板/一个产品的全部相关文件，例如 G318/
    *.eprj             # 嘉立创EDA 工程（含原理图；带 PCB 请确认客户端里有 PCB 页再导出）
    *.epro             # 嘉立创专业版工程包（旧 migrate 流程）
    *.epcb             # 嘉立创 PCB 单文件（如有）
    *.SchDoc           # Altium 原理图（二进制或 ASCII 均可）
    *.PcbDoc           # Altium PCB
    *.SchLib           # Altium 符号库（可选）
    *.PcbLib           # Altium 封装库（可选）
    *.PrjPcb           # Altium 工程文件（可选）
    out/               # 工具输出（转换结果/验证报告），不入库、可随便删
```

## 规则

1. **一个项目一个子目录**，目录名即项目名（`migraeda samples` 按此列出）。
2. 文件**平铺**在项目目录下即可，工具按扩展名自动归类，不依赖文件名。
3. 同类文件可放多个（如两版 `.SchDoc` 对比），建议文件名能看出角色/版本。
4. 没有的文件不用凑——每个工具只用它需要的类型：
   - `verify`：任意两份 `.eprj / .SchDoc / .PcbDoc`
   - `convert`：`.eprj` 或 `.SchDoc`
   - `pcbdiff`：两份 `.PcbDoc`（嘉立创 PCB 解析需要**含 PCB 数据**的 `.eprj`）
   - `libdiff` / `libconvert`：`.eprj / .SchLib / .PcbLib / .PcbDoc`
5. 生成的报告/转换结果请写到项目内的 `out/`（保持源文件目录干净）。

## 私有文件与路径

- **所有命令都接受任意绝对/相对路径**——`samples/` 只是便利约定，不是必须的。
  私有库（如 `.SchLib / .PcbLib`）不必放进 samples，也不必共享给任何人：
  ```bash
  migraeda libinspect "D:\libs\我的封装库.PcbLib"   # 结构自检（仅元数据，可安全外发）
  migraeda libdiff "D:\libs\Schlib1.SchLib" "D:\libs\我的封装库.PcbLib"
  ```
- 如果某个解析器在你的文件上报错，运行 `migraeda libinspect <文件>` 并把输出
  （目录树 + traceback，**不含图形/网络数据**）发给开发者即可定位修复。

## 当前缺失与用途

| 样本 | 用途 | 状态 |
|---|---|---|
| 含 PCB 的 `.eprj`（SME-IOT-1） | 嘉立创 PCB 解析（T1.1） | ✅ 已投递并解锁 |
| `.SchLib` / `.PcbLib` | 验证 AD 库解析器、开工 AD 库写出（T3.3） | ⏳ 待投递（可用 `migraeda libinspect` 自检） |
