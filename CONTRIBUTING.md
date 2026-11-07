# Contributing to MigraEDA

感谢你愿意为 MigraEDA 做贡献。/ Thanks for contributing to MigraEDA.

## 提交 Issue

转换类问题请附上：

1. `migraeda libinspect <文件>` 的输出（只含结构元数据，不含设计内容，可安全外发）
2. `migraeda verify` / `pcbdiff` 生成的 Markdown 报告
3. 不需要附上整份原理图或 PCB

## 开发环境

```bash
git clone https://github.com/Apollo-lwx/MigraEDA.git
cd MigraEDA
pip install -e ".[dev]"
pytest -q
```

所有测试通过后再提交 PR。CI 会在 Python 3.10–3.13 × Ubuntu/Windows 上重跑完整测试套件。

## 贡献者许可协议（CLA）

**提交 Pull Request 即表示你确认并同意以下条款：**

1. 你提交的贡献是你自己的原创工作，你有权按本协议授权；
2. 你同意你的贡献以本项目的 [MIT 协议](LICENSE) 授权；
3. 你授予项目维护者（dan luo / MigraEDA maintainers）一项永久的、全球范围的、不可撤销的权利：**在未来的版本中，以其他许可条款（包括商业许可）对你的贡献进行再授权**。

第 3 条是为了保留项目未来提供商业版本的可能性（open core 模式）。已经以 MIT 协议发布的历史版本，其许可条款不会追溯改变——这是 MIT 协议本身的保证，任何 CLA 都改变不了这一点。

如果你不同意第 3 条，仍然欢迎通过 Issue 提交 bug 报告、复现样本和功能建议——这些不涉及代码版权，不受 CLA 约束。

---

*English summary: By submitting a pull request, you confirm the contribution is your original work, license it under the project's MIT license, and grant the maintainers a perpetual, worldwide, irrevocable right to relicense your contribution — including under commercial terms — in future releases. Past MIT-licensed releases remain MIT forever. If you disagree with the relicensing clause, bug reports and feature requests via Issues are still very welcome.*
