# 确定性数据清洗契约

## 目的

清洗位于只读数据审计之后、模型路由之前。`scripts/data_clean.py` 只执行经过人工声明的有限规则，不推断清洗策略，不接受任意表达式，也不原地覆盖输入。每次运行绑定输入 CSV 和规则计划的 SHA-256，并把单元格、删行和列名变化写入账本。

账本证明“哪些机械操作实际发生”，不证明删除、插补、截尾或单位换算在科学上合理。理由必须来自题意、数据字典、采集规则、业务约束或经过记录的人工判断。

## 使用顺序

1. 对原始 CSV 运行 `data_audit.py`，审阅 blocker、warning 和 review；
2. 创建符合 `schemas/data-cleaning-plan.schema.json` 的 JSON 计划，填写当前输入 SHA-256；
3. 为每条规则写唯一 `id`、非空 `reason` 和人工复核的 `expected_changes`；
4. 运行 `data_clean.py`，任何哈希、列、规则或变化计数不符时整次失败；
5. 对 `processed.csv` 重新运行 `data_audit.py`，确认问题变化和新数据角色；
6. 将原始审计、清洗计划、清洗账本和处理后审计一起保留。

## CLI

```powershell
python scripts/data_clean.py `
  --input <source.csv> `
  --plan <cleaning-plan.json> `
  --output <new-cleaning-directory>
```

输出目录不能含有本工具管理的同名文件。失败发生在写出之前，不生成部分成功的处理结果。需要修改规则时使用新的输出目录，保留旧计划和证据用于比较。

## 计划示例

```json
{
  "version": 1,
  "input_sha256": "<64位小写SHA-256>",
  "row_id_columns": ["sample_id"],
  "rules": [
    {
      "id": "normalize_missing",
      "operation": "replace_values",
      "columns": ["temperature"],
      "replacements": [{"from": "NA*", "to": null}],
      "reason": "数据字典将 NA* 定义为缺测",
      "expected_changes": 3
    },
    {
      "id": "numeric_temperature",
      "operation": "convert_numeric",
      "columns": ["temperature"],
      "errors": "fail",
      "reason": "温度字段单位为摄氏度且必须为数值",
      "expected_changes": 97
    }
  ]
}
```

`expected_changes` 是保护条件，不是运行后的自动回填值。它必须由预览、查询或人工复核得到；原始数据发生漂移时，旧计划应失败而不是静默适配。

## 支持的操作

| operation | 必需参数 | 变化计数含义 |
|---|---|---|
| `trim_whitespace` | `columns` | 实际改变的单元格数 |
| `replace_values` | `columns`, `replacements` | 实际替换的单元格数 |
| `convert_numeric` | `columns`, `errors` | 从文本转换为数值或缺失的单元格数 |
| `fill_missing` | `columns`, `value` | 实际填补的单元格数 |
| `clip_numeric` | `columns`, `minimum`, `maximum` | 实际越界并被截尾的单元格数 |
| `unit_transform` | `columns`, `factor`, `offset` | 经过 `x * factor + offset` 且值发生改变的单元格数 |
| `swap_columns_by_row_key` | `columns`（恰两列）, `row_keys` | 每个精确行键匹配唯一一行后交换两列，变化计数为实际改变的单元格数 |
| `drop_missing_rows` | `columns`, `how` | 删除的行数，`how` 为 `any` 或 `all` |
| `drop_duplicate_rows` | `subset`, `keep` | 删除的行数，`keep` 为 `first` 或 `last` |
| `rename_columns` | `mapping` | 实际改变名称的列数 |

规则严格按数组顺序执行。后续规则引用当前列名和当前数据值；列重命名后的旧列名不能继续使用。数值截尾和单位换算要求先通过 `convert_numeric` 获得有限数值。

## 输出证据

- `processed.csv`：处理后的数据，不覆盖输入；
- `changes.csv`：每个单元格变化的规则、原始 CSV 行号、声明行键、列名和前后 JSON 值；
- `dropped_rows.csv`：删行规则、原始 CSV 行号、行键、原始行 SHA-256 和删除前整行 JSON；
- `schema_changes.csv`：列名变化；
- `rule_summary.csv`：规则顺序、预期/实际变化数及每步后的数据形状；
- `plan.json`：经验证、规范化保存的执行计划；
- `run.json`：输入/计划哈希、前后形状、变化总数、输出文件哈希和解释边界；
- `summary.md`：供人快速阅读的摘要。

## 边界

- 不支持任意 Python、SQL、正则表达式、条件表达式或外部命令；复杂清洗必须写独立脚本并增加同等级测试和证据；
- `fill_missing` 只支持显式常量，不自动使用均值、中位数、前向填充或模型插补；
- `replace_values` 是精确、类型敏感匹配，不做模糊映射；
- `swap_columns_by_row_key` 必须声明非空 `row_id_columns`，每个 `row_keys` 对象必须精确包含这些键且在当前数据中只匹配一行；它不接受范围、正则或任意条件，也不能交换行键列；
- 截尾必须有可辩护的物理、仪器或规则边界，不能仅凭 IQR 异常候选执行；
- 去重必须显式写出判重列和保留方向，并确认重复是否真的是冗余记录；
- 删除行会造成信息损失，必须在论文中披露规则、数量及可能偏差；
- 清洗完成后仍须重新审计；清洗账本不能替代训练/测试隔离或模型验证。
