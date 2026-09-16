# Evidence-Driven Math Modeling Workflow

面向数学建模竞赛的证据驱动 AI 建模工作流、论文表达框架与结果质量控制工具。

> 当前仓库是经过筛选、脱敏和回归验证的公开源码版，不包含私人案例、课程资料、优秀论文或未获再分发许可的资产。

## 项目目标

- 帮助团队完成题目拆解、数据审计、模型路由和验证；
- 建立代码、数据、结果、图表与论文之间的可追溯链条；
- 让论文正文呈现清晰的推导链、选择理由和结果边界；
- 明确 AI 执行与人工拍板的职责边界；
- 在比赛限时条件下保留可复现、可审计和合规的最小路径。

## 目录

- `.agents/skills/math-modeling/`：公开版数学建模 Skill、脚本、Schema、模板与测试候选；
- `docs/`：工作流、验证、论文表达和合规文档；
- `templates/`：数据血缘、结果冻结、符号表和提交检查模板；
- `scripts/`：通用检查与辅助脚本；
- `examples/`：经过许可或自造的最小示例；
- `tests/`：公开版回归检查。

## 当前状态

本仓库由私人工作区筛选而来。私人工作区不会整体复制到这里。

当前不包含：下载的课程资料、优秀论文和原始竞赛附件、未确认许可证的第三方代码或数据、个人比赛过程记录、本机环境、缓存、构建产物和凭据。

当前公开版已包含候选谱系管理、权威状态心跳、统一 `mm` 入口、论文章节接入审计和赛后工作流沉淀。它们约束证据与状态，不代替模型正确性、人工验收或官方提交。

在仓库根目录可运行：

```powershell
.\mm.ps1 --help
.\mm.ps1 status --case-dir <case-dir> --json
```

## 许可说明

本项目采用 [MIT License](LICENSE)，允许使用、修改、再分发和商用，须保留版权与许可声明；不提供担保。外部依赖保留各自许可证，详见 [第三方说明](THIRD_PARTY_NOTICES.md)。

## 通用核心已进入候选目录

Skill、脚本、Schema、通用模板与测试已做第一轮筛选迁移。请先阅读 `docs/migration-status.md`；Word/PDF 新可选后端已接入；下载的 LaTeX 模板、字体及旧导出器仍未纳入。此处不是已验收的可提交论文生产环境。

## Word PDF 公开候选入口

已接入原生公式、显式公式编号、符号表排版和哈希绑定的全页检查；使用方法及未验证范围见 [导出与页面检查](docs/paper-export.md)。这是经过同机隔离 Python 与新路径导出验证的可选后端，不是完整比赛提交链或许可证放行。

## 新环境与发布来源

- [隔离环境验证与最小安装/导出入口](docs/new-environment-validation.md)
- [发布来源和所有者确认事项](docs/release-sources.md)
- [逐文件来源与 SHA256](docs/source-inventory.json)
- [第三方依赖与许可边界](THIRD_PARTY_NOTICES.md)

当前是采用 MIT 的 source-only 公开版本。`scripts/check_release_inventory.py --require-release` 检查来源清单与许可声明，不代表完整法律审查、比赛规则核验或提交通过。
