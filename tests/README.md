# 测试入口

测试权威位置为 `.agents/skills/math-modeling/tests/`。全量测试仍包含未迁移导出后端与私人集成环境的检查；报告须保留失败或明确排除的范围，不得称全量通过。

公开候选仅给缺失的外部 LaTeX、Word 导出与私人协议集成加了条件跳过；恢复对应组件后自动恢复检查。所有 skip 都是未验证，不是通过。核心测试不因公开化而跳过。


## C2 独立发布/环境回归

根目录 `tests/test_new_environment_release.py` 有 12 项独立检查，不包含在 Skill 门的 426 项计数内：

```powershell
python -I -B -m unittest discover -s tests -p test_new_environment_release.py -v
```

导出专项 20 项位于 Skill tests，已包含在其 426 项中，不重复累计。新环境只安装导出所需库，没有安装所有建模库；全 Skill 回归与隔离导出专项须分别报告。原生工具缺失导致的 skip 不算通过。
