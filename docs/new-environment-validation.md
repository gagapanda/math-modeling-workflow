# 新环境依赖与最小导出验证（C2）

## 验证范围

这次验证的是**同一 Windows 机器上的隔离 Python 环境、新路径副本和精简 PATH**，不是一台全新电脑/全新操作系统。基础解释器为文档 bundled Python 3.12.14；新 venv 不继承 system-site-packages，用户 site 禁用，空环境已确认缺少导出库。

五个导出 wheel 重新从官方 PyPI 下载，逐个匹配其官方 SHA256，再从本地 wheel 目录离线 hash-locked 安装；`pip check` 无断裂依赖。实际导入文件均来自该新 venv，没有修改原项目 Python 环境。

Pandoc 3.9 使用重新下载的官方 Windows x86_64 ZIP；直连失败后官方 asset API 成功，ZIP SHA256 为 `edccdaa95b5a33b3320187f0e291d58a232e21318a8081750bd31f847e598d18`，与 GitHub release digest 一致。不在本仓库分发下载包或 exe。LibreOffice 26.2.5.2、Poppler 26.07.0 和字体仍为同机既有前提。

## 可复用最小入口（PowerShell，从仓库根执行）

以下为用户在自己的新环境中安装的命令；脚本本身不会安装、改 PATH 或搜索私人目录。先自行核验 Python、Pandoc、LibreOffice、Poppler 的来源与安装位置，不需要复制作者的环境。

```powershell
python -c "import sys; print(sys.executable)"
python -m venv .venv
$python = (Resolve-Path .venv/Scripts/python.exe).Path
& $python -m pip install --index-url https://pypi.org/simple --require-hashes --only-binary=:all: -r tools/paper-export/requirements-win-py312.lock
& $python -m pip check

# 自行替换以下占位值，必须是本机真实原生可执行文件的绝对路径。
$pandoc = '<Pandoc 的绝对路径>'
$soffice = '<LibreOffice soffice.com 或 soffice.exe 的绝对路径>'
$pdftoppm = '<Poppler pdftoppm.exe 的绝对路径>'
& $python -I -B tools/paper-export/doctor.py --pdf --pandoc $pandoc --soffice $soffice --pdftoppm $pdftoppm
& $python -I -B examples/paper-export/make_figure.py
& $python -I -B tools/paper-export/export_paper.py --md examples/paper-export/paper.md --asset-root examples/paper-export --spec doc-export-specs/paper-default.json --out local-work/export-v1/paper.docx --pdf --pandoc $pandoc --soffice $soffice --pdftoppm $pdftoppm
```

锁文件仅实测 **CPython 3.12 / Windows x86_64** 对应 wheel；不是多平台锁。其他平台的 requirements.txt 只是版本清单，需重新解析、锁定和验证，不保证安装成功。不要为匹配本示例更改已有项目解释器。每次导出使用新的版本输出路径；现有 bundle 会被拒绝覆盖。

只需要 DOCX 时，doctor 和 exporter 都去掉 `--pdf`，不需要 LibreOffice/Poppler，但仍需导出 Python 库及 Pandoc。doctor 可用仅代表可以尝试，不等于导出、页检或提交通过。缺依赖/工具退出 2，不能吞掉错误继续打包。

## 本次实测结果

- 新副本路径含中文和空格；导出时 PATH 仅保留 Windows 系统目录，原生工具由参数指定，清除继承的 PYTHONPATH/PYTHONHOME，使用 `-I -B`。
- doctor 正向成功；空环境缺库、缺原生工具均按预期退出 2。缺库的 exporter 给出诊断提示，不输出成功产物。
- direct exporter 与公开 Skill 构建适配器均生成 DOCX、PDF、全部三页 PNG 和绑定哈希的 export manifest。
- 新环境的独立专项回归：导出 20/20、依赖及来源清单检查 12/12 通过。它们不是完整数学建模库在空环境中的验证。
- 全三页进行了 AI 实际视觉查看：行内公式顺序、求和、矩阵、分式、根式、编号、五行符号表、图文、代码字面美元符号与页码可读；第三页较多留白是合成回归样例的已知特征，不作为竞赛终稿排版样板。

结构计数与页面通过不能替代真实论文的结果对账、符号覆盖、评委重建、官方规则、匿名、引用、AI 披露及人类验收。新环境最小样例不是可参赛论文，也不是完整比赛链一键验证。

## 页面验收与发布检查

按 [paper-export.md](paper-export.md) 填写实际逐页观察记录，然后运行 review_pages.py；禁止预填 all-pass 或伪造 human reviewer。只更改字体/工具/正文也可能改变分页，旧页检不能沿用。

```powershell
& $python -I -B -m unittest discover -s tests -p test_new_environment_release.py -v
& $python -I -B scripts/check_release_inventory.py
& $python -I -B scripts/check_release_inventory.py --require-release
```

C2 历史检查因许可未定预期退出 2；C4 实施 MIT 并登记授权后，当前完整性及严格许可声明检查均应通过。严格检查通过仍不等于完成上传前隐私/历史检查或远程发布授权。依赖清单见 [dependency-licenses.json](dependency-licenses.json)，发布前权利确认见 [release-sources.md](release-sources.md)。

## 尚未验证

全新 OS/独立电脑、Linux/macOS、Microsoft Word 原生渲染与 LibreOffice 一致性、实际竞赛稿、全比赛提交链、全传递依赖 SBOM/漏洞、Poppler 具体发行包许可及字体 EULA/再分发权。所有 wheel、原生工具、venv、实际渲染件和含本机路径的证据只保留在私人验证目录，不进入公开候选。
