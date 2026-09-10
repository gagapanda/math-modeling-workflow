# Word PDF 导出与全页检查

## 当前定位

公开候选现已提供新写的 Pandoc 编排后端；没有分发旧导出器源码、虚拟环境、可执行文件或字体。此入口支持论文导出，不替代结果对账、正文说服力审查、当届规则审查和真实人工提交确认。配置是通用排版起点，不是官方模板。

## 环境前提

使用已经配置好的 Python，具备 python-docx、Pillow、pypdf；python-docx 的传递依赖包含 lxml。外部需 Pandoc；要 PDF 和页面图还需 LibreOffice、Poppler 的 pdftoppm。脚本不安装依赖、不修改环境。Codex 管理的文档环境应先发现其 bundled 文档 Python，然后显式传入；普通用户使用自己的已核验解释器。

C1 在既有 Windows 环境实测，C2 又以隔离 Python、新路径副本和重新下载的 Pandoc 3.9 验证；LibreOffice 26.2.5.2、Poppler 和字体仍来自同机。未验证全新操作系统、Linux/macOS 或 Microsoft Word 原生渲染与 LibreOffice 的一致性。工具从 PATH 或显式参数发现，不保存本机位置。

字体仅按名称配置：宋体、黑体、Times New Roman、Cambria Math；代码使用 Consolas。不同机器的字体替换会改变分页，缺字不能通过换一份哈希报告解决，必须重新渲染查看。仓库不携带字体，不保证这些字体在目标机器可用。

## 最小合成例子

在仓库根目录执行，`python` 表示上面选定的文档解释器：

```text
python -B examples/paper-export/make_figure.py
python -B tools/paper-export/export_paper.py --md examples/paper-export/paper.md --asset-root examples/paper-export --spec doc-export-specs/paper-default.json --out local-work/export-v1/paper.docx --pdf
python -B tools/paper-export/review_pages.py local-work/export-v1/paper.export.json
```

LibreOffice 未在 PATH 时加 `--soffice "你的原生可执行文件绝对路径"`；其他工具同理使用 `--pandoc`、`--pdftoppm`。Windows 可以传 soffice.com。不要传 cmd/bat/ps1 包装器，不使用 shell 或执行策略绕过。

每次使用新版本输出目录/文件名。发现既有 DOCX、PDF、页面目录或清单时拒绝覆盖，避免把新结果与旧证据混合。中断后有部分文件也不能当作成功，选择新输出版本重建。产物提交前仍须映射到正式 workflow 的文件清单并执行原有门禁。

不加 `--pdf` 时只产生 DOCX 和构建清单；此时页面检查入口会拒绝认定全套证据完整。

## 作者输入约定

- 行内公式使用 `$x_i$`；独立公式使用单独段落的 `$$ ... $$`。
- 可见编号显式写在公式末尾，如 `$$y=ax+b\tag{1}$$`。支持数字及 `2.1`、`2-1`；不自动编号，不自动检查正文交叉引用。重复编号、行内编号、正文与编号公式共段、表格内编号公式会拒绝。
- 原生公式在普通正文和表格单元格内保留；不把公式重新替换成图片。代码块中的美元符号保留为字面值。
- 符号表必须由作者写入，至少区分含义、单位、范围。导出器不会猜测或自动补造符号定义。
- 图片只接受资产根目录内的 PNG/JPEG，解析后的路径必须仍在根目录内；拒绝远程图片、数据 URI 输入、路径越界和过大图片。不支持 SVG/PDF 图片导入。
- 图片替代文字和正文图注都需要作者提供。系统不自动证明图表与结论一致。
- 显式分页用空的 fenced div：

```markdown
::: page-break
:::
```

- 不支持原始 HTML/TeX 指令、宏、Lua 过滤器、外部参考 DOCX、Word 自动化。原始指令不会执行；不受支持的写法可能成为可见正文，应由结构和页面审查发现并修正。
- 默认无目录；只有规则和模板确实允许时显式加 `--toc`。本轮没有核验复杂目录、题注自动编号或域更新。

## 排版和公式边界

A4、可配置页边距和字号、中西文字体、标题层级、页码字段、表格重复表头与禁拆行、图片限宽；编号公式采用无边框三列布局，左右留编号位置。宽公式需要作者主动分行，超高表格行不能靠禁拆行解决。长表、复杂合并单元格、横向页面、浮动图以及大量脚注尚未验证。

导出会清除核心作者和最后修改者等字段，不等于完成匿名审查：正文身份、图中文字、图片 EXIF、引用身份以及 PDF 元数据仍须按主工作流审查。

## 证据与全页审查

`paper.export.json` 绑定 Markdown、配置、导出器、图片、DOCX、PDF 和每张页面图的 SHA256，并登记公式数量和显式编号。只有工具全部成功、PDF 存在且页数与渲染图数一致才写出清单。清单最后落盘，始终是 `pending_visual_review` 和 `submission_ready=false`。

`review_pages.py` 只证明清单引用的文件哈希与页面覆盖一致；**它不是渲染真实性鉴定器，也不替代 DOCX 结构审查、裁切检测或人工目视审查**。必须实际查看每页大图，检查：

1. 行内公式顺序、上下标、分数、矩阵、编号是否完整且与源文一致；
2. 符号表是否覆盖正文中的关键符号，单位有无混淆；
3. 图中文字、坐标轴、单位、图例是否可读，图与图注是否脱节；
4. 标题层级、推导步骤和选择理由是否能从正文连续读懂；
5. 表格跨页、孤立标题、附录分页、末尾空白页、页码、裁切和缺字。

AI 实际查看后可另建记录（不得预先生成全部通过）：

```json
{
  "manifest_sha256": "被审查构建清单的实际SHA256",
  "reviewer_kind": "ai",
  "pages": [
    {"page": 1, "sha256": "该页实际SHA256", "status": "pass", "notes": "本页实际观察内容，不是通用勾选语"}
  ]
}
```

每一页都需记录；`status` 为 `pass` 或 `fail`。运行：

```text
python -B tools/paper-export/review_pages.py local-work/export-v1/paper.export.json --review local-work/export-v1/ai-review.json
```

缺页、旧哈希、缺观察说明或冒用此格式作人工签字均拒绝；存在 `fail` 返回非零。即使得到 `ai_pass`，仍为 `submission_ready=false`、`human_acceptance=not_recorded`。结构合法的评论不证明真的看过，执行者须忠实记录。本记录不能直接充当既有 M6 Schema 的人工清单。主工作流的当前文件对账、匿名/引用/AI 披露、真实人工判定仍须完成。

## 接入现有模板

公开 Skill 的 Markdown 构建适配器优先发现 `tools/paper-export/export_paper.py`，已知旧默认 `cumcm-cn.yaml` 映射至 `paper-default.json`；任意自定义配置不存在时失败，不悄悄忽略。使用 `--document-python` 或本地环境变量 `PAPER_DOCUMENT_PYTHON` 选择文档运行时。

默认仍只构建 workflow 原来声明的 DOCX；通过适配器显式加 `--pdf` 获得新的 PDF/全页证据。已有工作流其他步骤的旧 PDF 后端、doctor、Schema 和真实提交门本轮没有重设计；**不能据此宣称任意 practice/submission 案例一键全链路可用**。不要静默把新的页面清单塞入旧验收 Schema。

没有新后端的历史环境仍保留旧接口兼容分支，但公开仓库不分发旧工具，其对应集成测试继续标为未验证。

## 回归入口

```text
python -B -m unittest discover -s .agents/skills/math-modeling/tests -p test_public_paper_export.py -v
python -B .agents/skills/math-modeling/scripts/check_skill.py --workspace-root . --skip-historical --json
```

完整 Skill 测试可用项目测试解释器；文档集成子进程使用 `PAPER_DOCUMENT_PYTHON` 指定的文档解释器。缺 Pandoc 的原生公式集成会显示 skip，不能算通过。全页视觉证据使用本地合成样例另行实测，不把单元测试的空白假 PDF 当作页面质量验证。

## 来源与分发决策

旧工具的本地上游记录没有发现明确 LICENSE，远端授权未完成确认；因此其源码、修改版和旧包装器均暂缓迁移。本轮脚本为新写的外部工具编排，不宣称法律意义的 clean-room 或已获得完整权利审核。JSON 配置只重新表达页边距、字号和系统字体名，不分发原 YAML、DOCX 样张或第三方字体。

外部工具只调用，不复制；发布前仍须审查本仓库作者权利、许可证、依赖和分发方式。根目录 LICENSE 现为 MIT，仅适用于项目内容；它不重新许可外部工具。实际上传仍需检查待发布集合，不能以导出通过代替来源、许可或隐私审查。

实现参考入口（不是随仓库分发的源码）：

```text
https://pandoc.org/MANUAL.html
https://help.libreoffice.org/latest/en-US/text/shared/guide/start_parameters.html
```

新环境诊断、依赖锁和实际最小入口见 [new-environment-validation.md](new-environment-validation.md)；完整发布来源与许可状态见 [release-sources.md](release-sources.md)。
