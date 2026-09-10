from __future__ import annotations

import hashlib
import re
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
TEMPLATE = SKILL_DIR / "templates" / "cumcm-2026-latex"


def read(relative: str) -> str:
    return (TEMPLATE / relative).read_text(encoding="utf-8")


def active_tex(source: str) -> str:
    return "\n".join(line.split("%", 1)[0] for line in source.splitlines())


@unittest.skipUnless(TEMPLATE.exists(), "Public candidate: downloaded LaTeX asset not bundled; integration NOT VERIFIED")
class CumcmLatexTemplateTests(unittest.TestCase):
    def test_electronic_entrypoint_is_anonymous_and_has_no_toc(self) -> None:
        source = active_tex(read("paper.tex"))
        self.assertRegex(
            source,
            r"\\documentclass\[[^]]*\bwithoutpreface\b[^]]*\]\{cumcmthesis\}",
        )
        self.assertNotIn(r"\tableofcontents", source)

    def test_required_document_order_is_locked(self) -> None:
        source = active_tex(read("paper.tex"))
        ordered_inputs = [
            "sections/00-abstract.tex",
            "sections/01-problem-analysis.tex",
            "sections/02-assumptions-symbols-data.tex",
            "sections/03-models-results.tex",
            "sections/04-validation-conclusions.tex",
            "sections/05-ai-declaration.tex",
            "sections/06-references.tex",
            "sections/07-appendices.tex",
        ]
        positions = [source.index(rf"\input{{{item}}}") for item in ordered_inputs]
        self.assertEqual(positions, sorted(positions))

    def test_print_wrapper_disables_front_matter_page_anchors(self) -> None:
        source = active_tex(read("paper-print.tex"))
        disabled = source.index(r"\hypersetup{pageanchor=false}")
        title = source.index(r"\maketitle")
        enabled = source.index(r"\hypersetup{pageanchor=true}")
        abstract = source.index(r"\input{sections/00-abstract.tex}")
        self.assertLess(disabled, title)
        self.assertLess(title, enabled)
        self.assertLess(enabled, abstract)

    def test_ai_declaration_and_required_appendices_exist(self) -> None:
        declaration = active_tex(read("sections/05-ai-declaration.tex"))
        references = active_tex(read("sections/06-references.tex"))
        appendices = active_tex(read("sections/07-appendices.tex"))
        self.assertIn("AI 工具使用声明", declaration)
        self.assertIn(r"\AIUseStatement", declaration)
        self.assertIn(r"\begin{thebibliography}", references)
        self.assertIn("支撑材料文件列表", appendices)
        self.assertIn("完整可运行源程序", appendices)

    def test_symbols_section_covers_roles_units_domains_and_ranges(self) -> None:
        source = read("sections/02-assumptions-symbols-data.tex")
        self.assertIn("符号与单位", source)
        self.assertIn("单位或取值域", source)
        self.assertIn("索引范围或说明", source)
        for token in ("输入量", "决策变量", "状态变量", "模型参数", "评价指标"):
            self.assertIn(token, source)
        self.assertIn(r"$i=1,\ldots,n$", source)

    def test_symbols_section_carries_global_table_and_local_first_definition_contract(self) -> None:
        source = read("sections/02-assumptions-symbols-data.tex")
        for phrase in (
            "公式邻近处说明其数学身份与现实角色",
            "单位/定义域、索引层级、信息时点和标量/向量/集合身份",
            "全局表只收跨段复用或高歧义符号",
            "一次性局部量不得因追求表面完整而机械入表",
            "最终 PDF/DOCX 中确认定义与对应公式同一逻辑块且可读",
        ):
            self.assertIn(phrase, source)

    def test_data_audit_section_tracks_analysis_units_and_effective_denominators(self) -> None:
        source = read("sections/02-assumptions-symbols-data.tex")
        for token in (
            "记录行数、独立对象数、配对/群组数和验证组数",
            "分析单位、有效分母",
            "未进入或分母缩小原因",
            "同一原始数据不得跨问题相加",
            "局部特征缺失只缩小受影响指标的分母",
            "三个及以上材料性流转节点",
            "不强制制表",
            "数据审计只回答数据能否使用",
            "分析单位→可见模式→下游动作→禁止推出的更强结论",
            "无下游作用的探索图表删除或下沉",
            "不强制 EDA",
        ):
            self.assertIn(token, source)


    def test_model_section_carries_algorithm_execution_contract(self) -> None:
        models = read("sections/03-models-results.tex")
        for phrase in (
            "材料性循环、分支、多阶段搜索或折分",
            "输入/状态",
            "停止/选择条件",
            "有限确定性枚举不写成收敛或全局最优",
            "种子、多次运行和稳定性证据",
        ):
            self.assertIn(phrase, models)

    def test_model_section_carries_sensitivity_evidence_contract(self) -> None:
        models = read("sections/03-models-results.tex")
        for phrase in (
            "扰动对象、扰动范围或替代口径、响应指标、稳定性判据和失败边界/重算触发",
            "已量化敏感性",
            "已识别但未量化风险",
            "未建立",
            "内部候选一致、条件情景或训练残差不能写成外部验证、总体覆盖或因果保证",
            "对象—扰动/替代口径—响应指标与稳定性判断—未证明边界/重算触发",
        ):
            self.assertIn(phrase, models)

    def test_model_section_carries_parameter_provenance_contract(self) -> None:
        models = read("sections/03-models-results.tex")
        for phrase in (
            "观测输入/元数据、训练折内估计量、拟合参数、固定操作性阈值、固定超参数、报告水平和情景旋钮",
            "设置角色—来源或估计方式—选择或标定口径—已完成验证—未证明边界—重算触发",
            "固定不等于数据估计",
            "默认不等于最优",
            "无泄漏嵌套或独立选择—评估结构",
            "报告水平不能写成总体覆盖保证",
            "情景旋钮不能写成因果效应、生理上限或可达性保证",
            "对象与设置角色—来源/选择口径—已完成的核验—未证明边界/重算触发",
            "重复表头并保持语义行完整",
        ):
            self.assertIn(phrase, models)
    def test_model_section_carries_material_assumption_contract(self) -> None:
        models = read("sections/03-models-results.tex")
        for phrase in (
            "材料性假设须与操作性定义、验证设计和情景条件分开",
            "材料性假设—采用理由/模型作用—受影响主张—可检查信号（直接/间接/当前不可检验）—违反后的结论降级—放宽路径—重算范围",
            "诊断未拒绝或未见反例不等于假设已证明",
            "材料性假设及其作用—当前依据/可检查信号—违反后的结论降级—放宽路径/重算范围",
            "不得补造敏感性、实验、校准或因果证据",
        ):
            self.assertIn(phrase, models)
    def test_model_section_carries_numeric_display_precision_contract(self) -> None:
        models = read("sections/03-models-results.tex")
        for phrase in (
            "显示位数",
            "测量/采样分辨率",
            "验证误差尺度",
            "决策用途",
            "未舍入冻结值",
            "并列、反转或跨阈值",
            "保护位",
            "机器输出位数",
            "不构成精度证据",
        ):
            self.assertIn(phrase, models)
    def test_model_section_carries_material_formula_witness_contract(self) -> None:
        models = read("sections/03-models-results.tex")
        for phrase in (
            "材料性核心公式",
            "验证见证",
            "非同路径自证",
            "期望关系",
            "实际结果/容差",
            "不能证明什么",
            "拒绝或重算动作",
            "单位一致",
            "代表性代入",
            "求解器成功",
            "不能单独证明模型正确",
        ):
            self.assertIn(phrase, models)

    def test_model_section_carries_derivation_stopping_point_contract(self) -> None:
        models = read("sections/03-models-results.tex")
        for phrase in (
            "改变分母、权重、方向、单位",
            "索引/数据层级",
            "损失/约束",
            "材料性步骤",
            "可计算式",
            "冻结结果/选择",
            "复核入口",
            "教材证明、机械代数和库内部步骤可下沉",
            "达到正文停点后停止扩写",
        ):
            self.assertIn(phrase, models)

    def test_model_section_carries_figure_evidence_encoding_contract(self) -> None:
        models = read("sections/03-models-results.tex")
        for phrase in (
            "原始观测、汇总统计、模型输出和条件情景",
            "有限登记节点",
            "完整响应函数",
            "零基线",
            "断轴",
            "双轴",
            "缺失连接",
            "非颜色冗余",
            "灰度或等价预览",
        ):
            self.assertIn(phrase, models)
    def test_model_section_carries_parameter_domain_grid_and_node_count_contract(self) -> None:
        models = read("sections/03-models-results.tex")
        for phrase in (
            "参数域",
            "实际评估网格",
            "当前/基线节点",
            "非基线方案节点",
            "表题/行数",
            "图中节点",
            "基线节点不得",
            "完整连续响应",
        ):
            self.assertIn(phrase, models)

    def test_model_section_carries_figure_language_and_panel_identity_contract(self) -> None:
        models = read("sections/03-models-results.tex")
        for phrase in (
            "同一主语言和对象术语",
            "MAE/RMSE",
            "稳定 (a)(b)…",
            "不用左图、右图、左上或其他面板等位置词唯一定位",
            "来源未解释的图内字符不得擅自赋义",
            "不承担的证据角色",
        ):
            self.assertIn(phrase, models)
    def test_model_section_carries_selected_object_diagnostic_handoff_contract(self) -> None:
        models = read("sections/03-models-results.tex")
        for phrase in (
            "上游面板完成候选选择",
            "非颜色标记",
            "下游须重复入选对象身份",
            "来自冻结结果",
            "不得只靠颜色、面板邻接或读者记忆传递",
            "身份闭合不证明模型选择正确",
        ):
            self.assertIn(phrase, models)
    def test_model_section_carries_final_size_legibility_contract(self) -> None:
        models = read("sections/03-models-results.tex")
        for phrase in (
            "最终 PDF/DOCX 的嵌入宽度和允许图高",
            "源字号、源画布与 DPI/PPI 不等于最终可读",
            "固定 pt 门",
            "使用直接标签、改变方向/分面或拆图",
            "不得用继续缩小字号换取同页",
            "整页、实际阅读比例下的局部",
            "图注/正文邻接和下游分页",
            "后续章节漂移",
        ):
            self.assertIn(phrase, models)
        self.assertNotIn("固定 6 pt", models)
        self.assertNotIn("固定 8 pt", models)

    def test_model_section_carries_evidence_carrier_addressability_contract(self) -> None:
        models = read("sections/03-models-results.tex")
        for phrase in (
            "稳定、唯一、可搜索",
            "首次引用说明用途",
            "下表、上图、本表",
            "前置符号表或数据审计表可不编号",
            "编号连续",
            "重复图号",
            "表题与表头和首行同页",
            "跨页表重复表头",
        ):
            self.assertIn(phrase, models)

    def test_model_section_carries_selective_equation_numbering_contract(self) -> None:
        models = read("sections/03-models-results.tex")
        for phrase in (
            "只编号会被后文引用、用于验证、进入连续推导或被下游计算复用的核心公式",
            "一次性局部定义不强制编号",
            "跨段或跨问复用时按式号回指",
            "最终 PDF/DOCX 中编号必须真实可见",
            "与对应公式同一逻辑块",
        ):
            self.assertIn(phrase, models)

    def test_validation_section_carries_diagnosis_to_model_disposition_contract(self) -> None:
        validation = read("sections/04-validation-conclusions.tex")
        for phrase in (
            "检查对象与期望关系/阈值",
            "限域接受、限制保留、修订或拒绝",
            "重跑受影响验证",
            "重新冻结依赖数字、表图和结论",
            "无下游处置的诊断图、残差图或检验罗列删除或下沉",
            "单项通过不证明模型正确、唯一最优、外部有效或部署安全",
            "单项失败也不自动否定无关主张",
        ):
            self.assertIn(phrase, validation)

    def test_expression_contract_is_carried_by_default_sections(self) -> None:
        abstract = read("sections/00-abstract.tex")
        models = read("sections/03-models-results.tex")
        conclusions = read("sections/04-validation-conclusions.tex")
        references_raw = read("sections/06-references.tex")
        references_active = active_tex(references_raw)
        appendices = active_tex(read("sections/07-appendices.tex"))
        readme = read("README.md")

        self.assertIn("结果冻结后", abstract)
        self.assertIn("不承担完整定义和推导", abstract)
        self.assertIn("先用一至两句给出本问的直接答案", models)
        self.assertIn("透明基线", models)
        self.assertIn("同一口径模型选择", models)
        self.assertIn("每个核心公式", models)
        self.assertIn("关键表图前", models)
        self.assertIn("验证和适用边界", models)
        self.assertIn("现实对象与外部驱动", models)
        self.assertIn("初始/边界条件", models)
        self.assertIn("参数来源或标定目标", models)
        self.assertIn("数值推进与事件提取", models)
        self.assertIn("等效标定参数", models)
        self.assertIn("与方程逐项对应", models)
        self.assertIn("哪些约束或变量边界塑造当前候选", models)
        self.assertIn("目标函数隐含何种决策偏好", models)
        self.assertIn("必须触发重新优化", models)
        self.assertIn("预测对象与部署单位", models)
        self.assertIn("失败结构与偏差方向", models)
        self.assertIn("残差时序", models)
        self.assertIn("不能写成未来覆盖保证", models)
        self.assertIn("AUC 或准确率不是校准证据", models)
        self.assertIn("运营目标也不是统计置信水平", models)
        self.assertIn("簇数或容量来源", models)
        self.assertIn("自然类别、稳定最优、真实路线或协同保证", models)
        self.assertIn("评价目标与决策对象", models)
        self.assertIn("权重来自数据、专家、规则还是决策偏好", models)
        self.assertIn("综合得分不是概率、置信度或绝对价值", models)
        self.assertIn("候选集、时间窗、指标、门槛或偏好变化", models)
        self.assertIn("跨问题新增信息", conclusions)
        self.assertIn("依赖传递", conclusions)
        self.assertIn("共同失效模式", conclusions)
        self.assertIn("上游资产/定义", conclusions)
        self.assertIn("失效范围与重算触发", conclusions)
        self.assertIn("定义/测量、样本结构/因果边界、预测不确定性和决策触发", conclusions)
        self.assertIn("上游点估计不得无条件传成下游确定输入", conclusions)
        self.assertIn("下游检验不能修复上游定义错误", conclusions)
        self.assertIn("传播幅度无法量化", conclusions)
        self.assertIn("不强制新增表或图", conclusions)
        self.assertIn("第二份逐问结果摘要", conclusions)
        self.assertIn("正文首次证明位置", conclusions)
        self.assertIn("技术路线只预告", conclusions)
        self.assertIn("没有逐组件消融时", conclusions)
        self.assertIn("不得包装成算法创新", conclusions)
        self.assertIn("不强制制造创新点", conclusions)
        self.assertIn("结论不新增", conclusions)
        self.assertIn("逐问结论还须按证据等级限制动词和行动权限", conclusions)
        self.assertIn("直接计算只在冻结定义、单位和精度下报告", conclusions)
        self.assertIn("观察或关联只用于线索与复测", conclusions)
        self.assertIn("内部验证预测只在匹配模型、数据域和验证对象内表述", conclusions)
        self.assertIn("条件情景或规划参考", conclusions)
        self.assertIn("责任人人工拍板点", conclusions)
        self.assertIn("条件推荐写成正式决策", conclusions)
        self.assertIn("核验作者", references_raw)
        self.assertNotIn("作者.", references_active)
        self.assertNotIn("与本文模型直接相关的文献题目", references_active)
        self.assertIn("终稿前必须替换或删除本示例条目", references_active)
        self.assertIn("入口文件", appendices)
        self.assertIn("环境依赖", appendices)
        self.assertIn("同一冻结源版本", appendices)
        self.assertIn("single authoritative source", readme)

    def test_appendix_carries_evidence_navigation_and_review_sequence_contract(self) -> None:
        appendices = active_tex(read("sections/07-appendices.tex"))
        for phrase in (
            "证据类别",
            "路径或入口",
            "支撑范围",
            "复核用途",
            "运行入口",
            "处理数据",
            "逐问结果",
            "结果登记",
            "完整源码",
            "AI 披露",
            "提交清单",
            "最短复核顺序",
            "不存在的项目必须删除",
            "不得虚构路径",
        ):
            self.assertIn(phrase, appendices)
        self.assertLess(
            appendices.index("最短复核顺序"),
            appendices.index(r"\section{完整可运行源程序}"),
        )

    def test_retained_source_hashes_match_review_record(self) -> None:
        expected = {
            "cumcmthesis.cls": "70960E2F2B2242BD6D9F6D47F85BE7C5FCDEAC34D2742C58754BFEC68A4EE38F",
            "simkai.ttf": "99092CBB0DF301625F46509E85854DB8685556551742097AB3FBBC2E2CA0778B",
            "simsun.ttc": "7A368113C36D516AAC1A825ACC4BBBC9906C4D197F7C649E7FE0F6F31E7475DD",
        }
        for name, digest in expected.items():
            actual = hashlib.sha256((TEMPLATE / name).read_bytes()).hexdigest().upper()
            self.assertEqual(actual, digest, name)

    def test_stress_fixture_covers_page_regions_and_evidence_density(self) -> None:
        source = active_tex(read("validation/stress-test.tex"))
        markers = [
            r"\MainTextStart",
            r"\MainTextEnd",
            r"\DeclarationsStart",
            r"\AppendixStart",
        ]
        positions = [source.index(marker) for marker in markers]
        self.assertEqual(positions, sorted(positions))
        self.assertGreaterEqual(len(re.findall(r"\\begin\{table\}", source)), 12)
        self.assertGreaterEqual(len(re.findall(r"\\begin\{equation\}", source)), 10)
        self.assertIn("AI 工具使用详情.pdf", source)
        self.assertIn("完整可运行源程序示例", source)

    def test_template_contains_no_generated_build_artifacts(self) -> None:
        forbidden = {"build", "visual", "rendered-pages", "review-previews"}
        directories = {path.name for path in TEMPLATE.rglob("*") if path.is_dir()}
        self.assertTrue(forbidden.isdisjoint(directories))


if __name__ == "__main__":
    unittest.main()


















