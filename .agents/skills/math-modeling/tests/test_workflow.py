from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile
import zlib
from datetime import date
from pathlib import Path
from unittest.mock import patch


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_DIR / "scripts"
SCHEMAS = SKILL_DIR / "schemas"
TEMPLATES = SKILL_DIR / "templates"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from _json_schema import load_and_validate


def load_preflight_module():
    spec = importlib.util.spec_from_file_location(
        "math_modeling_preflight", SCRIPTS / "preflight.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load preflight.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_pipeline_module():
    spec = importlib.util.spec_from_file_location(
        "math_modeling_pipeline", SCRIPTS / "run_pipeline.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load run_pipeline.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_submission_audit_module():
    spec = importlib.util.spec_from_file_location(
        "math_modeling_submission_audit",
        SCRIPTS / "audit_submission_compliance.py",
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load audit_submission_compliance.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_markdown_builder_module():
    spec = importlib.util.spec_from_file_location(
        "math_modeling_markdown_builder",
        TEMPLATES / "build_markdown_paper.py",
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load build_markdown_paper.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_formula_injector_module():
    path = SKILL_DIR.parents[2] / "tools" / "doc-export-enhanced" / "inject_formulas.py"
    spec = importlib.util.spec_from_file_location(
        "math_modeling_formula_injector", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load inject_formulas.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def run_script(name: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / name), *arguments],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def write_minimal_docx(path: Path, text: str) -> None:
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/'
        'wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>'
        f"{text}"
        "</w:t></w:r></w:p></w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w") as package:
        package.writestr("word/document.xml", xml)


def write_minimal_png(path: Path) -> None:
    def chunk(name: bytes, payload: bytes) -> bytes:
        checksum = zlib.crc32(name + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + name + payload + struct.pack(">I", checksum)

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    pixels = b"\x00\x00\x00\x00\xff"
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(pixels))
        + chunk(b"IEND", b"")
    )


class WorkflowTests(unittest.TestCase):
    def test_paper_expression_quick_card_carries_diagnosis_to_model_disposition_contract(self) -> None:
        quick = (
            SKILL_DIR / "references" / "paper-expression-quick-card.md"
        ).read_text(encoding="utf-8")
        for phrase in (
            "诊断到模型处置",
            "检查对象与期望关系/阈值",
            "限域接受、限制保留、修订或拒绝",
            "重跑受影响验证并重新冻结依赖的数字、表图和结论",
            "无下游处置的诊断图、残差图或检验罗列删除或下沉",
            "单项检验通过不证明模型正确、唯一最优、外部有效或部署安全",
            "单项失败也不自动否定与其无关的全部主张",
        ):
            self.assertIn(phrase, quick)

    def test_paper_expression_quick_card_carries_data_evidence_to_action_handoff(self) -> None:
        quick = (
            SKILL_DIR / "references" / "paper-expression-quick-card.md"
        ).read_text(encoding="utf-8")
        for phrase in (
            "数据证据到建模动作",
            "分析单位→可见模式→下游动作→禁止推出的更强结论",
            "无下游作用的探索图表删除或下沉",
            "不强制 EDA",
            "不把观察相关写成因果",
        ):
            self.assertIn(phrase, quick)

    def test_paper_expression_quick_card_covers_cross_question_recomputation(self) -> None:
        card = (
            SKILL_DIR / "references" / "paper-expression-quick-card.md"
        ).read_text(encoding="utf-8")
        for phrase in (
            "多问依赖与重算接口",
            "上游资产/定义",
            "实际传递量与风险类型",
            "受影响的下游主张",
            "失效范围与重算触发",
            "定义/测量、样本结构/因果边界、预测不确定性、决策触发",
            "上游点估计不能无条件传成下游确定输入",
            "下游检验不能修复上游定义错误",
            "若传播幅度无法量化",
            "不强制新增表或图",
        ):
            self.assertIn(phrase, card)
    def test_algorithm_execution_card_covers_code_mapping_and_solver_state(self) -> None:
        card = (
            SKILL_DIR / "references" / "paper-claim-figure-innovation-card.md"
        ).read_text(encoding="utf-8")
        quick = (
            SKILL_DIR / "references" / "paper-expression-quick-card.md"
        ).read_text(encoding="utf-8")
        for phrase in (
            "算法可执行叙事、求解状态与代码映射",
            "输入与数据状态",
            "停止、筛选或选择条件",
            "有限候选或有限折的确定性枚举",
            "success/status/message",
            "步骤 | 实际执行与判据 | 源码与产出映射",
        ):
            self.assertIn(phrase, card)
        self.assertIn("算法执行：输入/状态", quick)

    def test_sensitivity_robustness_cards_require_evidence_levels_and_recompute_boundaries(self) -> None:
        card = (
            SKILL_DIR / "references" / "paper-claim-figure-innovation-card.md"
        ).read_text(encoding="utf-8")
        quick = (
            SKILL_DIR / "references" / "paper-expression-quick-card.md"
        ).read_text(encoding="utf-8")
        for phrase in (
            "敏感性/稳健性证据的分层表达与边界闭环",
            "扰动对象",
            "扰动范围或替代口径",
            "响应指标",
            "稳定性判据",
            "失败边界或重算触发",
            "已量化敏感性",
            "已识别但未量化风险",
            "未建立的敏感性",
            "对象 | 扰动/替代口径 | 响应指标与稳定性判断 | 未证明边界/重算触发",
        ):
            self.assertIn(phrase, card)
        for phrase in (
            "敏感性/稳健性（材料性时）",
            "证据状态（已量化/已识别未量化/未建立）",
            "失败边界/重算触发",
        ):
            self.assertIn(phrase, quick)

    def test_parameter_provenance_contract_distinguishes_roles_and_boundaries(self) -> None:
        card = (
            SKILL_DIR / "references" / "paper-claim-figure-innovation-card.md"
        ).read_text(encoding="utf-8")
        quick = (
            SKILL_DIR / "references" / "paper-expression-quick-card.md"
        ).read_text(encoding="utf-8")
        for phrase in (
            "参数、阈值、超参数与情景旋钮的来源合同",
            "数值设置",
            "角色分类",
            "来源或估计方式",
            "选择或标定口径",
            "已完成的验证",
            "未证明的边界",
            "观测输入/元数据",
            "训练折内估计量",
            "固定操作性阈值",
            "固定超参数",
            "报告水平",
            "情景旋钮",
            "固定不等于由数据估计",
            "默认值不等于最优",
            "嵌套验证或等价的独立选择—评估结构",
            "对象与设置角色 | 来源/选择口径 | 已完成的核验 | 未证明边界/重算触发",
        ):
            self.assertIn(phrase, card)
        for phrase in (
            "数值设置与来源合同（材料性时）",
            "观测输入/折内估计量/拟合参数/固定阈值/固定超参数/报告水平/情景旋钮",
            "默认写成最优",
            "报告水平写成覆盖保证",
            "情景旋钮写成因果效应",
        ):
            self.assertIn(phrase, quick)
    def test_material_assumption_contract_requires_diagnosis_degradation_and_relaxation(self) -> None:
        card = (
            SKILL_DIR / "references" / "paper-claim-figure-innovation-card.md"
        ).read_text(encoding="utf-8")
        quick = (
            SKILL_DIR / "references" / "paper-expression-quick-card.md"
        ).read_text(encoding="utf-8")
        for phrase in (
            "材料性假设的诊断、违反后果与放宽路径合同",
            "material_assumption",
            "operational_definition",
            "validation_design",
            "scenario_condition",
            "可直接检查",
            "可间接诊断",
            "当前数据不可检验",
            "诊断未拒绝或暂未出现反例，不等于假设已被证明",
            "违反后的结论降级",
            "放宽路径或替代模型",
            "材料性假设及其作用 | 当前依据/可检查信号 | 违反后的结论降级 | 放宽路径/重算范围",
        ):
            self.assertIn(phrase, card)
        for phrase in (
            "类型（材料性假设/操作性定义/验证设计/情景条件）",
            "可检查信号（直接/间接/当前不可检验）",
            "违反后降级",
            "放宽路径/重算",
            "没有把“未拒绝”写成“已证明”",
        ):
            self.assertIn(phrase, quick)
    def test_conclusion_authority_contract_binds_evidence_verbs_and_actions(self) -> None:
        card = (
            SKILL_DIR / "references" / "paper-claim-figure-innovation-card.md"
        ).read_text(encoding="utf-8")
        quick = (
            SKILL_DIR / "references" / "paper-expression-quick-card.md"
        ).read_text(encoding="utf-8")
        for phrase in (
            "结论的证据等级、动词强度与行动权限合同",
            "direct_measurement_or_computation",
            "descriptive_or_associational_finding",
            "internally_validated_conditional_prediction",
            "scenario_or_planning_reference",
            "operational_recommendation_with_guardrails",
            "formal_decision_or_deployment",
            "证据等级限制动词，动词限制行动",
            "结论能被复算 ≠ 行动已经被验证",
            "模型内部最优 ≠ 现实最优",
            "安全规则被写出 ≠ 安全性已得到验证",
            "条件推荐 ≠ 正式决策",
        ):
            self.assertIn(phrase, card)
        for phrase in (
            "结论的证据等级与行动权限",
            "冻结答案 → 证据等级/验证范围 → 允许动词 → 允许行动 → 禁止升级/人工闸门",
            "不写因果或训练有效",
            "不写实测值、任意新对象保证或总体泛化",
            "不写训练反应、可达上限或承诺值",
            "责任人人工拍板",
        ):
            self.assertIn(phrase, quick)
    def test_numeric_display_precision_contract_matches_evidence_and_decision_use(self) -> None:
        card = (
            SKILL_DIR / "references" / "paper-claim-figure-innovation-card.md"
        ).read_text(encoding="utf-8")
        quick = (
            SKILL_DIR / "references" / "paper-expression-quick-card.md"
        ).read_text(encoding="utf-8")
        for phrase in (
            "数值显示精度、证据分辨率与决策阈值合同",
            "机器精度不等于测量精度",
            "测量/采样分辨率",
            "验证误差尺度",
            "决策用途",
            "未舍入冻结值",
            "并列、反转或跨阈值",
            "保护位",
            "临界状态",
        ):
            self.assertIn(phrase, card)
        for phrase in (
            "数值显示精度",
            "未舍入冻结值",
            "测量/采样分辨率",
            "验证误差/不确定性尺度",
            "决策用途/阈值间隔",
            "舍入临界保护",
            "使用未舍入冻结值",
        ):
            self.assertIn(phrase, quick)
    def test_material_formula_verification_witness_contract_is_explicit(self) -> None:
        card = (
            SKILL_DIR / "references" / "paper-claim-figure-innovation-card.md"
        ).read_text(encoding="utf-8")
        quick = (
            SKILL_DIR / "references" / "paper-expression-quick-card.md"
        ).read_text(encoding="utf-8")
        for phrase in (
            "材料性公式的局部验证见证",
            "检查对象",
            "期望关系",
            "实际结果",
            "允许范围/容差",
            "失败后的拒绝、降级或重算动作",
            "同一代码成功运行不等于独立验证",
            "单位一致不等于模型正确",
            "一个代表性代入不等于全域证明",
            "求解器成功不等于方程、边界、可行性或结果正确",
            "witness_type",
            "failure_action",
        ):
            self.assertIn(phrase, card)
        for phrase in (
            "材料性公式见证",
            "不只是同路径回算",
            "期望关系",
            "实际结果",
            "允许范围",
            "失败动作",
        ):
            self.assertIn(phrase, quick)

    def test_material_derivation_stopping_point_contract_is_explicit(self) -> None:
        card = (
            SKILL_DIR / "references" / "paper-claim-figure-innovation-card.md"
        ).read_text(encoding="utf-8")
        quick = (
            SKILL_DIR / "references" / "paper-expression-quick-card.md"
        ).read_text(encoding="utf-8")
        for phrase in (
            "关键推导的材料性步骤与正文停点合同",
            "分母、权重、方向、单位",
            "索引/数据层级",
            "损失/约束",
            "可计算式",
            "冻结结果或选择",
            "复核入口",
            "机械代数",
            "使用 MATLAB 计算",
            "达到正文停点",
        ):
            self.assertIn(phrase, card)
        for phrase in (
            "推导正文停点",
            "材料性步骤",
            "可计算式→冻结结果/选择→复核入口",
            "教材证明、机械代数和库内部步骤下沉",
            "不因‘充实’继续加公式",
        ):
            self.assertIn(phrase, quick)

    def test_figure_evidence_encoding_contract_is_explicit(self) -> None:
        card = (
            SKILL_DIR / "references" / "paper-claim-figure-innovation-card.md"
        ).read_text(encoding="utf-8")
        quick = (
            SKILL_DIR / "references" / "paper-expression-quick-card.md"
        ).read_text(encoding="utf-8")
        for phrase in (
            "图表证据编码真实性、离散节点与非颜色冗余合同",
            "原始观测、汇总统计、模型输出和条件情景",
            "完整连续响应",
            "已计算四个情景节点 ≠ 已验证全区间响应曲线",
            "颜色不能是唯一材料性通道",
            "缺失、零值、删失和排除",
            "经验误差带不能称为总体覆盖保证",
            "灰度或等价预览",
        ):
            self.assertIn(phrase, card)
        for phrase in (
            "图形编码真实性",
            "有限登记节点",
            "完整响应函数",
            "观测、汇总量、模型输出还是条件情景",
            "非颜色冗余",
            "区间与缺失职责可查",
        ):
            self.assertIn(phrase, quick)
    def test_figure_language_and_panel_identity_contract_is_explicit(self) -> None:
        card = (
            SKILL_DIR / "references" / "paper-claim-figure-innovation-card.md"
        ).read_text(encoding="utf-8")
        quick = (
            SKILL_DIR / "references" / "paper-expression-quick-card.md"
        ).read_text(encoding="utf-8")
        for phrase in (
            "图内主语言、术语与多面板身份一致性合同",
            "与正文一致的主语言",
            "MAE",
            "稳定的 `(a)(b)…`",
            "不得只靠“左图、右图、左上、其他面板”",
            "来源未解释的图内字符不得擅自赋义",
            "不承担的证据角色",
            "翻译、术语统一和面板编号",
        ):
            self.assertIn(phrase, card)
        for phrase in (
            "图内语言与面板身份",
            "图内术语与面板",
            "来源未解释的图内字符不得擅自赋义",
            "稳定 `(a)(b)…`",
            "不靠位置词唯一定位",
            "源图中无法核实的数字",
        ):
            self.assertIn(phrase, quick)
    def test_selected_object_diagnostic_panel_handoff_contract_is_explicit(self) -> None:
        card = (
            SKILL_DIR / "references" / "paper-claim-figure-innovation-card.md"
        ).read_text(encoding="utf-8")
        quick = (
            SKILL_DIR / "references" / "paper-expression-quick-card.md"
        ).read_text(encoding="utf-8")
        for phrase in (
            "上游选择对象与下游诊断面板的身份交接合同",
            "入选状态",
            "下游诊断面板",
            "重复入选对象身份",
            "来自冻结",
            "不得只靠颜色、面板邻接或读者记忆",
            "不证明模型选择正确",
        ):
            self.assertIn(phrase, card)
        for phrase in (
            "选择—诊断对象交接",
            "非颜色标记",
            "重复入选对象身份",
            "来自冻结结果",
            "不得只靠颜色、面板邻接或读者记忆",
            "不证明模型选择正确",
        ):
            self.assertIn(phrase, quick)
    def test_final_physical_size_and_local_legibility_contract_is_explicit(self) -> None:
        card = (
            SKILL_DIR / "references" / "paper-claim-figure-innovation-card.md"
        ).read_text(encoding="utf-8")
        quick = (
            SKILL_DIR / "references" / "paper-expression-quick-card.md"
        ).read_text(encoding="utf-8")
        for phrase in (
            "最终物理尺寸、信息密度与局部可读性合同",
            "目标嵌入宽度",
            "源字号、源画布英寸或 DPI 都不等于最终可读性证明",
            "最终有效字号 ≈ 源字号 × 最终嵌入宽度 / 源原生物理宽度",
            "直接标签减少图例往返",
            "改变方向、分面或面板结构",
            "拆图，或把非核心明细移入附录",
            "整页",
            "100% 或实际阅读比例",
            "下游分页",
            "PPI/DPI 只描述栅格采样",
        ):
            self.assertIn(phrase, card)
        for phrase in (
            "最终尺寸与局部可读性",
            "最终嵌入宽度和允许图高",
            "源字号、源画布与 DPI/PPI 不等于最终可读",
            "直接标签→改变方向/分面→拆图或移附录",
            "整页、100% 或实际阅读比例局部",
            "下游分页",
        ):
            self.assertIn(phrase, quick)
        self.assertNotIn("固定 6 pt", card)
        self.assertNotIn("固定 8 pt", card)

    def test_evidence_carrier_addressability_contract_is_explicit(self) -> None:
        card = (
            SKILL_DIR / "references" / "paper-claim-figure-innovation-card.md"
        ).read_text(encoding="utf-8")
        quick = (
            SKILL_DIR / "references" / "paper-expression-quick-card.md"
        ).read_text(encoding="utf-8")
        for phrase in (
            "证据载体稳定编号、首次引用与跨页导航合同",
            "编号是证据地址",
            "稳定、唯一、可搜索",
            "首次引用必须说明用途",
            "下表、上图",
            "前置符号表",
            "编号断裂",
            "图 1：图 1",
            "跨页表",
            "选择性编号",
        ):
            self.assertIn(phrase, card)
        for phrase in (
            "证据载体地址",
            "首次引用写清用途",
            "下表/上图/本表",
            "正文从表 3 起跳",
            "图 1：图 1",
            "跨页后仍可恢复",
        ):
            self.assertIn(phrase, quick)

    def test_contribution_claim_card_covers_full_paper_placement(self) -> None:
        card = (
            SKILL_DIR / "references" / "paper-claim-figure-innovation-card.md"
        ).read_text(encoding="utf-8")
        for phrase in (
            "贡献主张的全文落位与证据分工",
            "first_proof_location",
            "技术路线只预告",
            "正文首次证明位置负责定义和证据",
            "验证节负责证据强度和失败",
            "结论只回收",
            "贡献类型与证据类型必须匹配",
            "性能归因与消融闸门",
            "普通实现不自动构成贡献",
            "没有材料性贡献时",
            "它不证明贡献具有学术新颖性",
        ):
            self.assertIn(phrase, card)

        quick = (
            SKILL_DIR / "references" / "paper-expression-quick-card.md"
        ).read_text(encoding="utf-8")
        for phrase in (
            "贡献主张的全文落位",
            "正文首次证明位置",
            "没有逐组件消融时",
            "不强制制造创新点",
        ):
            self.assertIn(phrase, quick)
    def test_pipeline_parses_large_json_before_log_truncation(self) -> None:
        pipeline = load_pipeline_module()
        with tempfile.TemporaryDirectory() as temporary:
            script = Path(temporary) / "large_json.py"
            script.write_text(
                "import json\nprint(json.dumps({'payload': 'x' * 20000}))\n",
                encoding="utf-8",
            )
            payload, result = pipeline.run_json_script(script, [], Path(temporary))
            self.assertEqual(result["exit_code"], 0)
            self.assertEqual(len(payload["payload"]), 20000)

    def test_preflight_rejects_cli_that_fails_startup(self) -> None:
        preflight = load_preflight_module()
        working, error = preflight.probe_executable(
            sys.executable, "-c", "raise SystemExit(7)"
        )
        self.assertFalse(working)
        self.assertEqual(error, "exit code 7")

    def test_preflight_checks_existing_controlled_files_without_writing(self) -> None:
        preflight = load_preflight_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / ".agents" / "skills"
            root.mkdir(parents=True)
            target = root / "skill.md"
            original = "controlled content\n"
            target.write_text(original, encoding="utf-8")

            report = preflight.check_existing_files_writable(root)

            self.assertTrue(report["applicable"])
            self.assertTrue(report["checked"])
            self.assertTrue(report["writable"])
            self.assertEqual(report["total_files"], 1)
            self.assertEqual(report["writable_files"], 1)
            self.assertEqual(report["blocked_files"], 0)
            self.assertEqual(target.read_text(encoding="utf-8"), original)
            self.assertFalse(any(root.rglob("__pycache__")))

    def test_preflight_blocks_when_an_existing_file_cannot_open_for_update(self) -> None:
        preflight = load_preflight_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / ".agents" / "skills"
            root.mkdir(parents=True)
            allowed = root / "allowed.md"
            blocked = root / "blocked.md"
            allowed.write_text("allowed\n", encoding="utf-8")
            blocked.write_text("blocked\n", encoding="utf-8")
            original_open = Path.open

            def fake_open(path, *args, **kwargs):
                mode = args[0] if args else kwargs.get("mode")
                if path.resolve() == blocked.resolve() and mode == "r+b":
                    raise PermissionError("simulated Access is denied")
                return original_open(path, *args, **kwargs)

            with patch.object(Path, "open", new=fake_open):
                report = preflight.check_existing_files_writable(root)

            self.assertFalse(report["writable"])
            self.assertEqual(report["total_files"], 2)
            self.assertEqual(report["writable_files"], 1)
            self.assertEqual(report["blocked_files"], 1)
            self.assertIn("simulated Access is denied", report["error"])
            self.assertEqual(
                report["sample_blocked"][0]["path"], str(blocked.resolve())
            )

    def test_preflight_marks_missing_controlled_directory_not_applicable(self) -> None:
        preflight = load_preflight_module()
        with tempfile.TemporaryDirectory() as temporary:
            report = preflight.check_existing_files_writable(
                Path(temporary) / ".agents" / "skills"
            )

        self.assertFalse(report["applicable"])
        self.assertFalse(report["checked"])
        self.assertTrue(report["writable"])
        self.assertEqual(report["total_files"], 0)

    def test_preflight_prefers_libreoffice_console_launcher_on_windows(self) -> None:
        preflight = load_preflight_module()
        with (
            patch.object(preflight.os, "name", "nt"),
            patch.object(
                preflight,
                "find_executable",
                return_value=r"C:\Program Files\LibreOffice\program\soffice.com",
            ) as find_executable,
        ):
            found = preflight.find_libreoffice()

        self.assertEqual(
            found, r"C:\Program Files\LibreOffice\program\soffice.com"
        )
        find_executable.assert_called_once_with("soffice.com", "libreoffice.com")

    def test_preflight_upgrades_known_libreoffice_exe_to_console_launcher(self) -> None:
        preflight = load_preflight_module()
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "soffice.exe"
            console = Path(temporary) / "soffice.com"
            executable.write_bytes(b"exe")
            console.write_bytes(b"com")
            with (
                patch.object(preflight.os, "name", "nt"),
                patch.object(preflight, "find_executable", return_value=None),
                patch.object(preflight, "find_known_file", return_value=str(executable)),
            ):
                found = preflight.find_libreoffice()
            self.assertEqual(found, str(console.resolve()))

    def test_libreoffice_export_uses_isolated_user_profile(self) -> None:
        pipeline = load_pipeline_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            docx = root / "paper.docx"
            pdf = root / "paper.pdf"
            docx.write_bytes(b"docx")
            observed = {}

            def run(command, cwd, timeout):
                observed["command"] = command
                observed["cwd"] = cwd
                observed["timeout"] = timeout
                pdf.write_bytes(b"%PDF-test")
                return {"ok": True, "exit_code": 0, "stdout": "", "stderr": ""}

            with patch.object(pipeline, "run_command", side_effect=run):
                result = pipeline.export_with_libreoffice(
                    "soffice.com", docx, pdf, root
                )

            self.assertTrue(result["ok"])
            self.assertEqual(observed["command"][0], "soffice.com")
            self.assertTrue(
                observed["command"][1].startswith("-env:UserInstallation=file:")
            )
            self.assertIn("--headless", observed["command"])
            self.assertIn("--convert-to", observed["command"])
            self.assertFalse(any(root.glob(".libreoffice-profile-*")))

    def test_word_export_refreshes_document_fields_before_pdf(self) -> None:
        pipeline = load_pipeline_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            docx = root / "paper.docx"
            pdf = root / "paper.pdf"
            with (
                patch.object(pipeline.shutil, "which", return_value="powershell.exe"),
                patch.object(
                    pipeline,
                    "run_command",
                    return_value={
                        "ok": True,
                        "exit_code": 0,
                        "stdout": "",
                        "stderr": "",
                    },
                ) as run_command,
            ):
                result = pipeline.export_with_word(docx, pdf, root)

            self.assertTrue(result["ok"])
            command = run_command.call_args.args[0]
            script = command[-1]
            self.assertIn("$doc.Fields.Update()", script)
            self.assertIn("$doc.TablesOfContents", script)
            self.assertIn("$footer.Range.Fields.Update()", script)
            self.assertLess(
                script.index("$doc.Fields.Update()"),
                script.index("$doc.ExportAsFixedFormat"),
            )

    def test_render_pdf_normalizes_zero_padded_page_names(self) -> None:
        pipeline = load_pipeline_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pdf = root / "paper.pdf"
            pdf.write_bytes(b"%PDF-1.4 fixture")
            render_dir = root / "rendered-pages"
            preflight = {
                "backends": {
                    "pdf_to_images": {
                        "primary": {
                            "name": "pdftocairo",
                            "path": "pdftocairo",
                            "usable": True,
                        }
                    }
                }
            }

            def run(command, cwd, timeout):
                prefix = Path(command[-1])
                write_minimal_png(prefix.with_name("page-01.png"))
                write_minimal_png(prefix.with_name("page-02.png"))
                return {"ok": True, "exit_code": 0, "stdout": "", "stderr": ""}

            with patch.object(pipeline, "run_command", side_effect=run):
                result = pipeline.render_pdf(pdf, render_dir, preflight, 150, root)

            self.assertTrue(result["ok"])
            self.assertEqual(result["page_count"], 2)
            self.assertEqual(
                [path.name for path in sorted(render_dir.glob("*.png"))],
                ["page-1.png", "page-2.png"],
            )

    def test_replace_render_directory_does_not_commit_secure_staging_acl(self) -> None:
        pipeline = load_pipeline_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            staging = root / "secure-staging"
            destination = root / "rendered-pages"
            staging.mkdir(mode=0o700)
            destination.mkdir()
            (staging / "page-1.png").write_bytes(b"new")
            (destination / "page-1.png").write_bytes(b"old")

            pipeline.replace_render_directory(staging, destination)

            self.assertTrue(staging.is_dir())
            self.assertEqual((staging / "page-1.png").read_bytes(), b"new")
            self.assertEqual((destination / "page-1.png").read_bytes(), b"new")
            self.assertFalse(any(root.glob(".render-backup-*")))
            self.assertFalse(any(root.glob(".render-commit-*")))

    def test_audit_resolves_localized_heading_style_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            docx = Path(temporary) / "paper.docx"
            document_xml = (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/'
                'wordprocessingml/2006/main"><w:body><w:p><w:pPr>'
                '<w:pStyle w:val="21"/></w:pPr><w:r><w:t>Section</w:t>'
                '</w:r></w:p></w:body></w:document>'
            )
            styles_xml = (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:styles xmlns:w="http://schemas.openxmlformats.org/'
                'wordprocessingml/2006/main"><w:style w:type="paragraph" '
                'w:styleId="21"><w:name w:val="Heading 2"/></w:style>'
                '</w:styles>'
            )
            with zipfile.ZipFile(docx, "w") as package:
                package.writestr("word/document.xml", document_xml)
                package.writestr("word/styles.xml", styles_xml)

            completed = run_script(
                "audit_paper.py", "--docx", str(docx), "--json"
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            report = json.loads(completed.stdout)
            self.assertEqual(report["docx"]["headings"], {"Heading 2": 1})
            self.assertNotIn("docx: no Heading styles found", report["warnings"])

    def test_audit_rejects_unrefreshed_table_of_contents(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            docx = Path(temporary) / "paper.docx"
            write_minimal_docx(docx, "目录将在 Word 中自动更新")

            completed = run_script("audit_paper.py", "--docx", str(docx), "--json")

            self.assertEqual(completed.returncode, 2)
            report = json.loads(completed.stdout)
            self.assertEqual(
                report["docx"]["unrefreshed_toc_markers"],
                ["目录将在 Word 中自动更新"],
            )
            self.assertIn(
                "unresolved table-of-contents placeholder",
                "\n".join(report["errors"]),
            )
    def test_preflight_blocks_matlab_batch_when_servicehost_is_running(self) -> None:
        preflight = load_preflight_module()
        status = preflight.assess_matlab_batch(
            r"X:\SyntheticTools\Matlab\bin\matlab.exe",
            ["explorer.exe", "MathWorksServiceHost.exe"],
            windows=True,
        )
        self.assertFalse(status["safe_to_start"])
        self.assertEqual(status["blocking_processes"], ["MathWorksServiceHost.exe"])
        self.assertIn("use mcp-evidence", status["reason"])

    def test_preflight_allows_matlab_batch_without_mathworks_processes(self) -> None:
        preflight = load_preflight_module()
        status = preflight.assess_matlab_batch(
            r"X:\SyntheticTools\Matlab\bin\matlab.exe",
            ["explorer.exe"],
            windows=True,
        )
        self.assertTrue(status["safe_to_start"])
        self.assertEqual(status["blocking_processes"], [])
        self.assertIsNone(status["reason"])

    def test_pipeline_refuses_batch_when_preflight_detects_servicehost(self) -> None:
        pipeline = load_pipeline_module()
        preflight = {
            "ready": True,
            "tools": {"matlab": r"X:\SyntheticTools\Matlab\bin\matlab.exe"},
            "matlab_batch": {
                "safe_to_start": False,
                "reason": "running MATLAB/MathWorks ServiceHost process blocks batch",
            },
        }
        manifest = {
            "steps": [
                {
                    "name": "solve",
                    "type": "matlab",
                    "runner": "batch",
                    "script": Path("solve.m"),
                    "test": None,
                    "outputs": [],
                }
            ]
        }
        with tempfile.TemporaryDirectory() as temporary:
            with (
                patch.object(
                    pipeline,
                    "run_json_script",
                    side_effect=[(preflight, {}), ({"passed": True, "errors": []}, {})],
                ),
                patch.object(pipeline, "run_matlab_step") as run_matlab_step,
            ):
                report = pipeline.build_phase(
                    Path(temporary), manifest, Path(temporary)
                )
        self.assertFalse(report["steps"][0]["ok"])
        self.assertIn("ServiceHost", report["steps"][0]["stderr"])
        run_matlab_step.assert_not_called()

    def test_scaffold_is_non_destructive_and_adds_json_register(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = run_script("scaffold_case.py", "case-a", "--root", str(root))
            self.assertEqual(first.returncode, 0, first.stderr)
            register = root / "case-a" / "results" / "result-register.json"
            self.assertEqual(
                json.loads(register.read_text(encoding="utf-8")),
                {"schema_version": 1, "results": []},
            )
            visual_review = root / "case-a" / "paper" / "visual-review.json"
            self.assertEqual(
                json.loads(visual_review.read_text(encoding="utf-8"))["status"],
                "pending",
            )
            workflow = root / "case-a" / "workflow.json"
            workflow_data = json.loads(workflow.read_text(encoding="utf-8"))
            self.assertEqual(workflow_data["schema_version"], 2)
            self.assertEqual(workflow_data["profile"], "practice")
            build_step = workflow_data["steps"][1]
            self.assertEqual(build_step["script"], "src/build_markdown_paper.py")
            self.assertEqual(
                build_step["args"],
                [
                    "--case-dir",
                    ".",
                    "--source",
                    "paper/full-paper.md",
                    "--output",
                    "paper/paper.docx",
                    "--spec",
                    "cumcm-cn.yaml",
                ],
            )
            self.assertEqual(
                build_step["inputs"],
                ["paper/full-paper.md", "src/build_markdown_paper.py"],
            )
            self.assertEqual(build_step["outputs"], ["paper/paper.docx"])
            builder = root / "case-a" / "src" / "build_markdown_paper.py"
            analysis = root / "case-a" / "src" / "analyze.py"
            paper_source = root / "case-a" / "paper" / "full-paper.md"
            self.assertTrue(builder.is_file())
            self.assertTrue(analysis.is_file())
            self.assertTrue(paper_source.is_file())
            paper_text = paper_source.read_text(encoding="utf-8")
            for heading in (
                "## Problem Analysis And Technical Route",
                "### Symbols And Units",
                "## Data Audit And Preprocessing",
                "distinguish record rows, independent objects, pairs/groups, and validation units",
                "bind each core claim to its effective denominator",
                "three or more material transitions",
                "do not add the same source data across subproblems",
                "## Subproblem 1: Model, Solution, Result, And Validation",
                "## Cross-Model Validation, Sensitivity, And Robustness",
                "## Appendix B: Complete Runnable Source Code",
                "Begin with a one- or two-sentence direct answer",
                "For each core formula, state its calculation purpose",
                "Before a key table or figure, state the comparison purpose",
                "For mechanistic or dynamic subproblems",
                "external driver to state variable",
                "initial/boundary conditions",
                "parameter source or calibration objective",
                "numerical propagation and event extraction",
                "effective calibrated parameters",
                "which constraints or bounds shape the selected candidate",
                "what changed definition or preference would require reoptimization",
                "For statistical prediction, repeated-measure, or time-forecast subproblems",
                "failure structure by object, group, period, or tail event",
                "a future coverage guarantee",
                "For probability classification or scoring",
                "An AUC or accuracy result is not calibration evidence",
                "For clustering or grouping",
                "natural class, stable optimum, actual route, or collaboration guarantee",
                "For evaluation or composite-scoring subproblems",
                "indicator direction, unit, and time window",
                "A composite score is not a probability",
                "changed candidates, windows, indicators, eligibility rules, or preferences",
                "Synthesize only evidence that adds information across subproblems",
                "For every material dependency, record upstream asset or definition",
                "invalidation scope and recomputation trigger",
                "definition or measurement, sample structure or causal boundary",
                "Do not pass an upstream point estimate as an unconditional downstream input",
                "claim that a downstream check repairs an upstream definition error",
                "If propagation magnitude cannot be quantified",
                "Use a dependency figure only when its nodes, transferred items, risks, and actions remain readable",
                "do not turn this section into a second subproblem-by-subproblem result summary",
                "Recover only contributions that were first proved in the body",
                "first proof location",
                "Without component-level ablation",
                "are not algorithmic innovations",
                "Do not force an innovation claim",
                "Verify author, title, venue or publisher, year",
                "same frozen source version",
            ):
                self.assertIn(heading, paper_text)
            qa_text = (root / "case-a" / "paper" / "qa-register.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("Symbols and units table complete", qa_text)
            self.assertIn("Analysis units, effective denominators", qa_text)
            self.assertIn("exclusion/missingness reasons", qa_text)
            self.assertIn("validation units reconciled", qa_text)
            self.assertIn("derivation / baseline / result / validation chain", qa_text)
            self.assertIn("Figure and table numbering", qa_text)
            self.assertIn("Main-text completeness reviewed by subproblem", qa_text)
            self.assertIn("recorded separately", qa_text)
            self.assertIn("Results frozen before abstract", qa_text)
            self.assertIn("opens with a direct answer", qa_text)
            self.assertIn("Core formulas have purpose", qa_text)
            self.assertIn("Reference metadata verified", qa_text)
            self.assertIn("one authoritative paper source", qa_text)
            current_state = root / "case-a" / "CURRENT-STATE.md"
            current_state_text = current_state.read_text(encoding="utf-8")
            self.assertIn("only case-local resume pointer", current_state_text)
            self.assertIn("`INITIALIZING`", current_state_text)
            self.assertIn("`NOT_FROZEN`", current_state_text)
            self.assertIn("F1 candidate", current_state_text)
            self.assertIn("F1 accepted manifest", current_state_text)
            self.assertIn("F1 verification", current_state_text)
            self.assertIn("Paper authoritative", current_state_text)
            self.assertIn("F1_THAW Rule", current_state_text)
            self.assertIn("`NOT_FORMAL_F2`", current_state_text)
            self.assertIn("AUTHORITY_UNRESOLVED", current_state_text)
            self.assertIn("NOT_RUN_OR_NOT_REQUIRED", current_state_text)
            start_here = root / "case-a" / "START-HERE.md"
            start_text = start_here.read_text(encoding="utf-8")
            self.assertIn("--validate-only", start_text)
            self.assertIn("result-register.json", start_text)
            self.assertIn("Resume An Existing Case Safely", start_text)
            self.assertIn("CURRENT-STATE.md", start_text)
            self.assertIn("AUTHORITY_UNRESOLVED", start_text)
            self.assertIn("STALE_CONTROL_FILE", start_text)
            self.assertIn("NOT_RUN_OR_NOT_REQUIRED", start_text)
            f1_plan = root / "case-a" / "results" / "f1-freeze-plan.json"
            f1_card = root / "case-a" / "results" / "F1-review-card.md"
            self.assertEqual(
                json.loads(f1_plan.read_text(encoding="utf-8"))["freeze_id"],
                "REPLACE_BEFORE_PREPARE",
            )
            self.assertIn("cannot sign", f1_card.read_text(encoding="utf-8"))
            submission = root / "case-a" / "compliance" / "submission.json"
            self.assertIn(
                "TODO",
                json.loads(submission.read_text(encoding="utf-8"))["competition"],
            )
            definition_register = (
                root / "case-a" / "problem" / "model-definition-register.json"
            )
            self.assertEqual(
                json.loads(definition_register.read_text(encoding="utf-8"))[
                    "assessment_status"
                ],
                "pending",
            )
            register.write_text('{"preserved": true}\n', encoding="utf-8")
            workflow.write_text('{"preserved": true}\n', encoding="utf-8")
            builder.write_text("# preserved builder\n", encoding="utf-8")
            analysis.write_text("# preserved analysis\n", encoding="utf-8")
            paper_source.write_text("# Preserved paper\n", encoding="utf-8")
            current_state.write_text("# Preserved current state\n", encoding="utf-8")
            second = run_script("scaffold_case.py", "case-a", "--root", str(root))
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(register.read_text(encoding="utf-8"), '{"preserved": true}\n')
            self.assertEqual(workflow.read_text(encoding="utf-8"), '{"preserved": true}\n')
            self.assertEqual(builder.read_text(encoding="utf-8"), "# preserved builder\n")
            self.assertEqual(
                analysis.read_text(encoding="utf-8"), "# preserved analysis\n"
            )
            self.assertEqual(
                paper_source.read_text(encoding="utf-8"), "# Preserved paper\n"
            )
            self.assertEqual(
                current_state.read_text(encoding="utf-8"),
                "# Preserved current state\n",
            )

            invalid = run_script("scaffold_case.py", "bad:name", "--root", str(root))
            self.assertNotEqual(invalid.returncode, 0)
            self.assertFalse((root / "bad:name").exists())

            occupied = root / "case-b" / "results" / "result-register.json"
            occupied.mkdir(parents=True)
            conflict = run_script("scaffold_case.py", "case-b", "--root", str(root))
            self.assertNotEqual(conflict.returncode, 0)
            self.assertIn("expected a file", conflict.stderr)

            explore = run_script(
                "scaffold_case.py",
                "case-explore",
                "--root",
                str(root),
                "--profile",
                "explore",
            )
            self.assertEqual(explore.returncode, 0, explore.stderr)
            explore_workflow = json.loads(
                (root / "case-explore" / "workflow.json").read_text(encoding="utf-8")
            )
            self.assertEqual(explore_workflow["profile"], "explore")
            self.assertNotIn("artifacts", explore_workflow)
            submission_only = (
                "compliance/m6-plan.json",
                "compliance/official-rules-snapshot.md",
                "compliance/source-register.json",
                "compliance/M6-review-card.md",
                "submission-package-plan.json",
                "support-smoke-plan.json",
                "m7-f2-plan.json",
                "submission/M7-review-card.md",
            )
            for relative in submission_only:
                self.assertFalse((root / "case-a" / relative).exists())
                self.assertFalse((root / "case-explore" / relative).exists())

            submission_result = run_script(
                "scaffold_case.py",
                "case-submission",
                "--root",
                str(root),
                "--profile",
                "submission",
            )
            self.assertEqual(submission_result.returncode, 0, submission_result.stderr)
            submission_workflow = json.loads(
                (root / "case-submission" / "workflow.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(submission_workflow["profile"], "submission")
            self.assertEqual(
                submission_workflow["compliance"], "compliance/submission.json"
            )
            self.assertEqual(
                submission_workflow["m6_compliance_plan"],
                "compliance/m6-plan.json",
            )
            self.assertEqual(
                submission_workflow["m7_f2_plan"],
                "m7-f2-plan.json",
            )
            submission_case = root / "case-submission"
            for relative in submission_only:
                self.assertTrue((submission_case / relative).is_file(), relative)
            snapshot = submission_case / "compliance" / "official-rules-snapshot.md"
            m6_plan = json.loads(
                (submission_case / "compliance" / "m6-plan.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                m6_plan["official_rules"]["snapshot_sha256"],
                hashlib.sha256(snapshot.read_bytes()).hexdigest(),
            )
            source_register = json.loads(
                (submission_case / "compliance" / "source-register.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(source_register["status"], "pending")
            review_card = (
                submission_case / "compliance" / "M6-review-card.md"
            ).read_text(encoding="utf-8")
            self.assertIn("Codex", review_card)
            self.assertIn("cannot sign M6", review_card)
            package_plan = json.loads(
                (submission_case / "submission-package-plan.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                package_plan["finalization_report"],
                "paper/finalization-report.json",
            )
            self.assertEqual(package_plan["support"]["output_name"], "support-materials.zip")

            smoke_plan = json.loads(
                (submission_case / "support-smoke-plan.json").read_text(encoding="utf-8")
            )
            self.assertEqual(smoke_plan["package"], package_plan["support"]["output_name"])
            self.assertEqual(smoke_plan["tests"][0]["name"], "main-analysis")
            self.assertEqual(
                smoke_plan["tests"][0]["command"],
                ["python", "src/analyze.py", "--case-dir", "."],
            )
            self.assertEqual(
                smoke_plan["tests"][0]["expected_outputs"],
                ["results/result-register.json"],
            )

            m7_plan = json.loads(
                (submission_case / "m7-f2-plan.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                m7_plan["human_gate"]["f2_manifest"],
                "submission/F2-submission.json",
            )
            self.assertEqual(m7_plan["required_smoke_tests"], ["main-analysis"])
            self.assertFalse(
                (submission_case / m7_plan["official_upload"]["receipt"]).exists()
            )
            m7_card = (
                submission_case / "submission" / "M7-review-card.md"
            ).read_text(encoding="utf-8")
            self.assertIn("NOT_FORMAL_F2", m7_card)
            self.assertIn("single_operator_review", m7_card)
            self.assertIn("cannot sign", m7_card)
    def test_scaffolded_analysis_template_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scaffold = run_script("scaffold_case.py", "case-a", "--root", str(root))
            self.assertEqual(scaffold.returncode, 0, scaffold.stderr)

            case_dir = root / "case-a"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(case_dir / "src" / "analyze.py"),
                    "--case-dir",
                    str(case_dir),
                ],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )

            self.assertEqual(completed.returncode, 2)
            self.assertIn("analysis_not_implemented", completed.stderr)
            self.assertIn("deterministic analysis", completed.stderr)

    def test_markdown_builder_invokes_enhanced_exporter(self) -> None:
        builder = load_markdown_builder_module()
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            case_dir = workspace / "cases" / "case-a"
            source = case_dir / "paper" / "full-paper.md"
            source.parent.mkdir(parents=True)
            source.write_text("# Test paper\n", encoding="utf-8")

            tool_dir = workspace / "tools" / "doc-export-enhanced"
            exporter = tool_dir / "exporter.py"
            python = tool_dir / ".venv" / "Scripts" / "python.exe"
            spec = workspace / "doc-export-specs" / "cumcm-cn.yaml"
            exporter.parent.mkdir(parents=True)
            python.parent.mkdir(parents=True)
            spec.parent.mkdir(parents=True)
            exporter.write_text("# fake exporter\n", encoding="utf-8")
            python.write_bytes(b"fake python")
            spec.write_text("page: {}\n", encoding="utf-8")

            argv = [
                "build_markdown_paper.py",
                "--case-dir",
                str(case_dir),
                "--source",
                "paper/full-paper.md",
                "--output",
                "paper/paper.docx",
                "--spec",
                "cumcm-cn.yaml",
            ]
            completed = subprocess.CompletedProcess([], 0)
            with (
                patch.object(sys, "argv", argv),
                patch.object(
                    builder.subprocess, "run", return_value=completed
                ) as run_exporter,
            ):
                return_code = builder.main()

            self.assertEqual(return_code, 0)
            command = run_exporter.call_args.args[0]
            self.assertEqual(
                command[:2], [str(python.resolve()), str(exporter.resolve())]
            )
            self.assertIn(str(source.resolve()), command)
            self.assertIn(str(spec.resolve()), command)
            self.assertIn(str((case_dir / "paper" / "paper.docx").resolve()), command)
            for flag in ("--formulas", "--page-numbers", "--refresh-fields"):
                self.assertIn(flag, command)
            self.assertNotIn("--toc", command)
            self.assertEqual(run_exporter.call_args.kwargs["cwd"], case_dir.resolve())
            self.assertFalse(run_exporter.call_args.kwargs["check"])

    def test_markdown_builder_includes_toc_only_when_explicitly_requested(self) -> None:
        builder = load_markdown_builder_module()
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            case_dir = workspace / "cases" / "case-a"
            source = case_dir / "paper" / "full-paper.md"
            source.parent.mkdir(parents=True)
            source.write_text("# Test paper\n", encoding="utf-8")
            tool_dir = workspace / "tools" / "doc-export-enhanced"
            exporter = tool_dir / "exporter.py"
            python = tool_dir / ".venv" / "Scripts" / "python.exe"
            spec = workspace / "doc-export-specs" / "other-contest.yaml"
            exporter.parent.mkdir(parents=True)
            python.parent.mkdir(parents=True)
            spec.parent.mkdir(parents=True)
            exporter.write_text("# fake exporter\n", encoding="utf-8")
            python.write_bytes(b"fake python")
            spec.write_text("page: {}\n", encoding="utf-8")
            argv = [
                "build_markdown_paper.py", "--case-dir", str(case_dir),
                "--spec", "other-contest.yaml", "--include-toc",
            ]
            with (
                patch.object(sys, "argv", argv),
                patch.object(
                    builder.subprocess,
                    "run",
                    return_value=subprocess.CompletedProcess([], 0),
                ) as run_exporter,
            ):
                self.assertEqual(builder.main(), 0)
            self.assertIn("--toc", run_exporter.call_args.args[0])

    @unittest.skipUnless((SKILL_DIR.parents[2] / "tools" / "doc-export-enhanced").exists(), "Public candidate: formula exporter not bundled; integration NOT VERIFIED")
    def test_multiple_inline_formulas_preserve_paragraph_order(self) -> None:
        injector = load_formula_injector_module()
        paragraph = injector.etree.fromstring(
            (
                '<w:p xmlns:w="http://schemas.openxmlformats.org/'
                'wordprocessingml/2006/main"><w:r><w:t>'
                '集合 $I$ 中成本 $c_i$、收益 $b_i$ 与决策 $x_i$ 保持原顺序。'
                '</w:t></w:r></w:p>'
            ).encode("utf-8")
        )

        def math_node(value: str):
            node = injector.etree.Element(injector.M_OMATH)
            run = injector.etree.SubElement(node, f"{{{injector.M_NS}}}r")
            text = injector.etree.SubElement(run, f"{{{injector.M_NS}}}t")
            text.text = value
            return node

        replacements = [
            ("$I$", math_node("I")),
            ("$c_i$", math_node("c_i")),
            ("$b_i$", math_node("b_i")),
            ("$x_i$", math_node("x_i")),
        ]
        self.assertTrue(injector.replace_inline_many(paragraph, replacements))

        sequence = []
        for child in paragraph:
            if child.tag == injector.W_R:
                value = "".join(
                    child.xpath(".//w:t/text()", namespaces=injector.NSMAP)
                )
                sequence.append(("text", value))
            elif child.tag == injector.M_OMATH:
                value = "".join(
                    child.xpath(".//m:t/text()", namespaces=injector.NSMAP)
                )
                sequence.append(("math", value))

        self.assertEqual(
            sequence,
            [
                ("text", "集合 "),
                ("math", "I"),
                ("text", " 中成本 "),
                ("math", "c_i"),
                ("text", "、收益 "),
                ("math", "b_i"),
                ("text", " 与决策 "),
                ("math", "x_i"),
                ("text", " 保持原顺序。"),
            ],
        )
    @unittest.skipUnless((SKILL_DIR.parents[2] / "tools" / "doc-export-enhanced").exists(), "Public candidate: Word exporter not bundled; integration NOT VERIFIED")
    def test_enhanced_exporter_avoids_docx2pdf_wrapper(self) -> None:
        source = (
            SKILL_DIR.parents[2] / "tools" / "doc-export-enhanced" / "exporter.py"
        ).read_text(encoding="utf-8")
        self.assertIn("def _export_pdf_with_word", source)
        self.assertIn("document.ExportAsFixedFormat", source)
        self.assertNotIn("from docx2pdf import", source)
    def test_markdown_builder_rejects_case_and_spec_path_escape(self) -> None:
        builder = load_markdown_builder_module()
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            case_dir = workspace / "case-a"
            source = case_dir / "paper" / "full-paper.md"
            source.parent.mkdir(parents=True)
            source.write_text("# Test paper\n", encoding="utf-8")

            tool_dir = workspace / "tools" / "doc-export-enhanced"
            (tool_dir / ".venv" / "bin").mkdir(parents=True)
            (tool_dir / "exporter.py").write_text("# fake\n", encoding="utf-8")
            (tool_dir / ".venv" / "bin" / "python").write_bytes(b"fake")
            (workspace / "doc-export-specs").mkdir()

            with self.assertRaisesRegex(ValueError, "paper source must stay inside"):
                builder.resolve_inside(case_dir, "../outside.md", "paper source")

            argv = [
                "build_markdown_paper.py",
                "--case-dir",
                str(case_dir),
                "--spec",
                "../outside.yaml",
            ]
            with (
                patch.object(sys, "argv", argv),
                patch.object(builder.subprocess, "run") as run_exporter,
                self.assertRaisesRegex(ValueError, "export spec must stay inside"),
            ):
                builder.main()
            run_exporter.assert_not_called()

    def test_model_definition_gate_handles_none_and_material_ambiguities(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = Path(temporary)
            problem_dir = case_dir / "problem"
            results_dir = case_dir / "results"
            paper_dir = case_dir / "paper"
            problem_dir.mkdir()
            results_dir.mkdir()
            paper_dir.mkdir()
            register_path = problem_dir / "model-definition-register.json"

            no_ambiguity = {
                "schema_version": 1,
                "assessment_status": "completed",
                "assessment_evidence": "Reviewed objectives, constraints, units, time origin, aggregation, and boundary conventions.",
                "no_material_ambiguity_rationale": "The statement defines every output and convention explicitly, and alternate readings do not change feasibility or conclusions.",
                "ambiguities": [],
            }
            register_path.write_text(json.dumps(no_ambiguity), encoding="utf-8")
            passed = run_script(
                "audit_model_definitions.py", "--case-dir", str(case_dir), "--json"
            )
            self.assertEqual(passed.returncode, 0, passed.stderr)
            self.assertTrue(json.loads(passed.stdout)["passed"])

            (results_dir / "comparison.json").write_text("{}\n", encoding="utf-8")
            material = {
                "schema_version": 1,
                "assessment_status": "completed",
                "assessment_evidence": "Compared representative-point and complete-target definitions.",
                "no_material_ambiguity_rationale": "",
                "ambiguities": [
                    {
                        "id": "target-geometry",
                        "question": "What must be fully obscured?",
                        "primary_definition": "Block the representative-point sight line.",
                        "alternative_definition": "Block all sampled sight lines to the complete target.",
                        "comparison": {
                            "status": "completed",
                            "material_difference": True,
                            "materiality_rationale": "The objective changes beyond reported precision.",
                            "evidence_files": ["results/comparison.json"],
                        },
                        "alternative_reoptimization": {
                            "status": "not-required",
                            "evidence_files": [],
                        },
                        "paper_disclosure": {
                            "status": "not-required",
                            "paper_text": "",
                        },
                    }
                ],
            }
            register_path.write_text(json.dumps(material), encoding="utf-8")
            blocked = run_script(
                "audit_model_definitions.py", "--case-dir", str(case_dir), "--json"
            )
            self.assertEqual(blocked.returncode, 2)
            blocked_errors = "\n".join(json.loads(blocked.stdout)["errors"])
            self.assertIn("alternative_reoptimization.status must be completed", blocked_errors)
            self.assertIn("paper_disclosure.status must be completed", blocked_errors)

            (results_dir / "reoptimized.json").write_text("{}\n", encoding="utf-8")
            disclosure = "Definition sensitivity materially changes the reported objective."
            material["ambiguities"][0]["alternative_reoptimization"] = {
                "status": "completed",
                "evidence_files": ["results/reoptimized.json"],
            }
            material["ambiguities"][0]["paper_disclosure"] = {
                "status": "completed",
                "paper_text": disclosure,
            }
            register_path.write_text(json.dumps(material), encoding="utf-8")
            docx = paper_dir / "paper.docx"
            write_minimal_docx(docx, disclosure)
            missing_pdf = run_script(
                "audit_model_definitions.py",
                "--case-dir", str(case_dir),
                "--docx", str(docx),
                "--json",
            )
            self.assertEqual(missing_pdf.returncode, 0, missing_pdf.stderr)
            self.assertEqual(
                json.loads(missing_pdf.stdout)["ambiguities"][0]["paper_occurrences"]["docx"],
                1,
            )

    def test_model_definition_structure_only_allows_generated_evidence_to_be_absent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = Path(temporary)
            problem_dir = case_dir / "problem"
            problem_dir.mkdir()
            register = {
                "schema_version": 1,
                "assessment_status": "completed",
                "assessment_evidence": "Compared two coordinate conventions before selecting the primary definition.",
                "no_material_ambiguity_rationale": "",
                "ambiguities": [
                    {
                        "id": "coordinate-system",
                        "question": "Which image coordinate convention is authoritative?",
                        "primary_definition": "Use pixel coordinates with a top-left origin.",
                        "alternative_definition": "Use normalized coordinates with a bottom-left origin.",
                        "comparison": {
                            "status": "completed",
                            "material_difference": False,
                            "materiality_rationale": "The converted values agree after the coordinate transform.",
                            "evidence_files": ["results/generated-comparison.json"],
                        },
                        "alternative_reoptimization": {
                            "status": "not-required",
                            "evidence_files": [],
                        },
                        "paper_disclosure": {
                            "status": "not-required",
                            "paper_text": "",
                        },
                    }
                ],
            }
            (problem_dir / "model-definition-register.json").write_text(
                json.dumps(register), encoding="utf-8"
            )

            full = run_script(
                "audit_model_definitions.py", "--case-dir", str(case_dir), "--json"
            )
            self.assertEqual(full.returncode, 2)
            self.assertIn("comparison evidence is missing", full.stdout)

            structure = run_script(
                "audit_model_definitions.py",
                "--case-dir", str(case_dir),
                "--structure-only",
                "--json",
            )
            self.assertEqual(structure.returncode, 0, structure.stderr)
            report = json.loads(structure.stdout)
            self.assertTrue(report["passed"])
            self.assertEqual(report["scope"], "structure-only")
    def test_preflight_supports_machine_readable_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            completed = run_script(
                "preflight.py",
                "--project-root",
                temporary,
                "--output-dir",
                temporary,
                "--writable-dir",
                str(Path(temporary) / "new" / "nested"),
                "--module",
                "json",
                "--json",
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            report = json.loads(completed.stdout)
            self.assertTrue(report["ready"])
            self.assertTrue(report["modules"]["json"])
            self.assertIn("pdf_to_images", report["backends"])
            self.assertIn("existing_files", report["paths"])
            self.assertFalse(report["paths"]["existing_files"]["applicable"])
            self.assertTrue(report["paths"]["writable_dirs"][0]["writable"])
            self.assertFalse((Path(temporary) / "new").exists())
            if os.name == "nt":
                invalid = run_script(
                    "preflight.py",
                    "--project-root",
                    temporary,
                    "--output-dir",
                    str(Path(temporary) / "bad:name"),
                    "--module",
                    "json",
                    "--json",
                )
                self.assertEqual(invalid.returncode, 2)
                self.assertFalse(json.loads(invalid.stdout)["ready"])

    def test_preflight_checks_declared_existing_files_without_writing(self) -> None:
        preflight = load_preflight_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            writable = root / "writable.pdf"
            blocked = root / "blocked.pdf"
            missing = root / "missing.pdf"
            writable.write_bytes(b"writable")
            blocked.write_bytes(b"blocked")
            original_open = Path.open

            def guarded_open(path: Path, *args, **kwargs):
                if path.resolve() == blocked.resolve() and args and args[0] == "r+b":
                    raise PermissionError("simulated access denied")
                return original_open(path, *args, **kwargs)

            with patch.object(Path, "open", new=guarded_open):
                report = preflight.check_declared_files_writable(
                    [writable, blocked, missing, writable]
                )

            self.assertFalse(report["writable"])
            self.assertEqual(report["declared_paths"], 3)
            self.assertEqual(report["existing_files"], 2)
            self.assertEqual(report["missing_files"], 1)
            self.assertEqual(report["writable_files"], 1)
            self.assertEqual(report["blocked_files"], 1)
            self.assertIn(str(blocked.resolve()), report["error"])
            self.assertEqual(writable.read_bytes(), b"writable")
            self.assertEqual(blocked.read_bytes(), b"blocked")

    def test_pipeline_preflight_targets_are_declared_and_bounded(self) -> None:
        pipeline = load_pipeline_module()
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = Path(temporary).resolve()
            paper = case_dir / "paper"
            results = case_dir / "results"
            manifest = {
                "profile": "practice",
                "artifacts": {
                    "docx": paper / "paper.docx",
                    "pdf": paper / "paper-rebuilt.pdf",
                    "render_dir": paper / "rendered-pages-rebuilt",
                    "visual_review": paper / "visual-review-rebuilt.json",
                },
            }
            selected_steps = [
                {
                    "name": "solve",
                    "type": "python",
                    "outputs": [results / "output.json"],
                }
            ]

            writable_dirs, exact_files, output_roots = (
                pipeline.collect_build_preflight_targets(
                    case_dir, manifest, selected_steps, True
                )
            )

            self.assertIn(paper / "paper.docx", exact_files)
            self.assertIn(paper / "paper-rebuilt.pdf", exact_files)
            self.assertIn(results / "output.json", exact_files)
            self.assertIn(paper / "pipeline-report.json", exact_files)
            self.assertIn(case_dir / ".workflow" / "state.json", exact_files)
            self.assertNotIn(paper / "legacy.pdf", exact_files)
            self.assertNotIn(paper / "visual-review-rebuilt.json", exact_files)
            self.assertEqual(output_roots, [paper / "rendered-pages-rebuilt"])
            self.assertIn(results, writable_dirs)
            self.assertIn(paper, writable_dirs)

    def test_preflight_writable_probe_fails_fast_on_access_denied(self) -> None:
        preflight = load_preflight_module()
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)
            with patch.object(
                preflight.os,
                "open",
                side_effect=PermissionError("simulated access denied"),
            ):
                report = preflight.check_writable(target, True)
            self.assertFalse(report["writable"])
            self.assertIn("simulated access denied", report["error"])

    def test_reconciliation_detects_stale_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = Path(temporary)
            (case_dir / "results").mkdir()
            (case_dir / "results" / "q1.json").write_text(
                '{"duration_s": 1.410197}\n', encoding="utf-8"
            )
            register = {
                "schema_version": 1,
                "results": [
                    {
                        "id": "q1.duration_s",
                        "value": "1.410197",
                        "source_file": "results/q1.json",
                        "source_key": "duration_s",
                        "paper_required": True,
                    }
                ],
            }
            register_path = case_dir / "results" / "result-register.json"
            register_path.write_text(json.dumps(register), encoding="utf-8")
            docx = case_dir / "paper.docx"
            write_minimal_docx(docx, "Duration: 1.410197 s")

            passed = run_script(
                "reconcile_results.py",
                "--case-dir",
                str(case_dir),
                "--docx",
                str(docx),
                "--json",
            )
            self.assertEqual(passed.returncode, 0, passed.stderr)
            self.assertTrue(json.loads(passed.stdout)["reconciled"])

            register["results"][0]["value"] = "1.5"
            register_path.write_text(json.dumps(register), encoding="utf-8")
            failed = run_script(
                "reconcile_results.py",
                "--case-dir",
                str(case_dir),
                "--docx",
                str(docx),
                "--json",
            )
            self.assertEqual(failed.returncode, 2)
            self.assertFalse(json.loads(failed.stdout)["reconciled"])

            register["results"] = []
            register_path.write_text(json.dumps(register), encoding="utf-8")
            empty = run_script(
                "reconcile_results.py",
                "--case-dir",
                str(case_dir),
                "--docx",
                str(docx),
                "--json",
            )
            self.assertEqual(empty.returncode, 2)
            self.assertIn(
                "result register contains no results",
                json.loads(empty.stdout)["errors"],
            )

            register["results"] = [
                {
                    "id": "q1.duration_s",
                    "value": "1.410197",
                    "source_file": "results/q1.json",
                    "source_key": "duration_s",
                    "paper_required": True,
                    "paper_text": "",
                }
            ]
            register_path.write_text(json.dumps(register), encoding="utf-8")
            empty_paper_text = run_script(
                "reconcile_results.py",
                "--case-dir",
                str(case_dir),
                "--docx",
                str(docx),
                "--json",
            )
            self.assertEqual(empty_paper_text.returncode, 2)
            self.assertIn(
                "paper_text must be non-empty",
                "\n".join(json.loads(empty_paper_text.stdout)["errors"]),
            )

            (case_dir / "results" / "q1.json").write_text(
                '{"duration_s": [1, 2]}\n', encoding="utf-8"
            )
            register["results"][0].update(
                {"value": "[1, 2]", "paper_required": False}
            )
            register["results"][0].pop("paper_text")
            register_path.write_text(json.dumps(register), encoding="utf-8")
            non_scalar = run_script(
                "reconcile_results.py",
                "--case-dir",
                str(case_dir),
                "--json",
            )
            self.assertEqual(non_scalar.returncode, 2)
            self.assertIn(
                "generated source value must be a scalar",
                "\n".join(json.loads(non_scalar.stdout)["errors"]),
            )

            (case_dir / "results" / "q1.json").write_text(
                '{"duration_s": Infinity}\n', encoding="utf-8"
            )
            register["results"][0]["value"] = float("inf")
            register_path.write_text(json.dumps(register), encoding="utf-8")
            non_finite = run_script(
                "reconcile_results.py",
                "--case-dir",
                str(case_dir),
                "--json",
            )
            self.assertEqual(non_finite.returncode, 2)
            self.assertIn(
                "non-finite JSON constant",
                "\n".join(json.loads(non_finite.stdout)["errors"]),
            )

            (case_dir / "results" / "q1.json").write_text(
                '{"duration_s": 1.23}\n', encoding="utf-8"
            )
            register["results"][0].update(
                {"value": "1.23", "paper_required": True, "paper_text": "1.23"}
            )
            register_path.write_text(json.dumps(register), encoding="utf-8")
            write_minimal_docx(docx, "Only 11.230 appears here")
            embedded_number = run_script(
                "reconcile_results.py",
                "--case-dir",
                str(case_dir),
                "--docx",
                str(docx),
                "--json",
            )
            self.assertEqual(embedded_number.returncode, 2)
            self.assertIn(
                "missing from docx",
                "\n".join(json.loads(embedded_number.stdout)["errors"]),
            )

            write_minimal_docx(docx, "中位误差降至1.23米")
            adjacent_cjk = run_script(
                "reconcile_results.py",
                "--case-dir",
                str(case_dir),
                "--docx",
                str(docx),
                "--json",
            )
            self.assertEqual(adjacent_cjk.returncode, 0, adjacent_cjk.stderr)
            self.assertTrue(json.loads(adjacent_cjk.stdout)["reconciled"])

    def test_reconciliation_reads_numeric_values_from_docx_table_cells(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = Path(temporary)
            results_dir = case_dir / "results"
            results_dir.mkdir()
            (results_dir / "q1.json").write_text(
                json.dumps({"revenue": 30, "remaining": 14}), encoding="utf-8"
            )
            (results_dir / "result-register.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "results": [
                            {
                                "id": "q1.revenue",
                                "value": 30,
                                "source_file": "results/q1.json",
                                "source_key": "revenue",
                                "paper_required": True,
                            },
                            {
                                "id": "q1.remaining",
                                "value": 14,
                                "source_file": "results/q1.json",
                                "source_key": "remaining",
                                "paper_required": True,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            docx = case_dir / "paper.docx"
            document_xml = (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/'
                'wordprocessingml/2006/main"><w:body><w:tbl>'
                '<w:tr><w:tc><w:p><w:r><w:t>项目</w:t></w:r></w:p></w:tc>'
                '<w:tc><w:p><w:r><w:t>成本</w:t></w:r></w:p></w:tc>'
                '<w:tc><w:p><w:r><w:t>收益</w:t></w:r></w:p></w:tc></w:tr>'
                '<w:tr><w:tc><w:p><w:r><w:t>A</w:t></w:r></w:p></w:tc>'
                '<w:tc><w:p><w:r><w:t>6</w:t></w:r></w:p></w:tc>'
                '<w:tc><w:p><w:r><w:t>30</w:t></w:r></w:p></w:tc></w:tr>'
                '<w:tr><w:tc><w:p><w:r><w:t>B</w:t></w:r></w:p></w:tc>'
                '<w:tc><w:p><w:r><w:t>4</w:t></w:r></w:p></w:tc>'
                '<w:tc><w:p><w:r><w:t>14</w:t></w:r></w:p></w:tc></w:tr>'
                '</w:tbl></w:body></w:document>'
            )
            with zipfile.ZipFile(docx, "w") as package:
                package.writestr("word/document.xml", document_xml)

            completed = run_script(
                "reconcile_results.py",
                "--case-dir",
                str(case_dir),
                "--docx",
                str(docx),
                "--json",
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            report = json.loads(completed.stdout)
            self.assertTrue(report["reconciled"])
            self.assertEqual(
                [item["paper_occurrences"]["docx"] for item in report["results"]],
                [1, 1],
            )
    def test_pipeline_manifest_validation_rejects_path_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = Path(temporary) / "case"
            (case_dir / "src").mkdir(parents=True)
            (case_dir / "paper").mkdir()
            (case_dir / "src" / "analyze.py").write_text("print('ok')\n", encoding="utf-8")
            manifest = {
                "schema_version": 1,
                "steps": [
                    {"name": "analyze", "script": "src/analyze.py", "args": []}
                ],
                "artifacts": {
                    "docx": "paper/paper.docx",
                    "pdf": "paper/paper.pdf",
                    "render_dir": "paper/rendered-pages",
                    "visual_review": "paper/visual-review.json",
                },
                "audit": {"page_size": "a4", "orientation": "portrait"},
            }
            manifest_path = case_dir / "workflow.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            valid = run_script(
                "run_pipeline.py",
                "--case-dir",
                str(case_dir),
                "--validate-only",
                "--json",
            )
            self.assertEqual(valid.returncode, 0, valid.stderr)
            self.assertTrue(json.loads(valid.stdout)["valid"])

            manifest["steps"][0]["script"] = "../outside.py"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            escaped = run_script(
                "run_pipeline.py",
                "--case-dir",
                str(case_dir),
                "--validate-only",
                "--json",
            )
            self.assertEqual(escaped.returncode, 2)
            self.assertIn("escapes the case directory", escaped.stdout)

    def test_pipeline_profiles_preserve_v1_and_validate_submission_contract(self) -> None:
        pipeline = load_pipeline_module()
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = Path(temporary)
            (case_dir / "src").mkdir()
            (case_dir / "paper").mkdir()
            (case_dir / "compliance").mkdir()
            (case_dir / "src" / "analyze.py").write_text(
                "print('ok')\n", encoding="utf-8"
            )
            manifest = {
                "schema_version": 1,
                "steps": [{"name": "analyze", "script": "src/analyze.py"}],
                "artifacts": {
                    "docx": "paper/paper.docx",
                    "pdf": "paper/paper.pdf",
                    "render_dir": "paper/rendered-pages",
                    "visual_review": "paper/visual-review.json",
                },
            }
            manifest_path = case_dir / "workflow.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            self.assertEqual(
                pipeline.load_manifest(case_dir, manifest_path)["profile"], "practice"
            )

            manifest["profile"] = "explore"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "requires schema_version 2"):
                pipeline.load_manifest(case_dir, manifest_path)
            manifest.pop("profile")
            manifest["compliance"] = "compliance/submission.json"
            manifest["m7_f2_plan"] = "m7-f2-plan.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "requires schema_version 2"):
                pipeline.load_manifest(case_dir, manifest_path)

            manifest["schema_version"] = 2
            manifest.pop("compliance")
            manifest["profile"] = "invalid"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "explore, practice, or submission"):
                pipeline.load_manifest(case_dir, manifest_path)

            manifest["profile"] = "submission"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "requires a compliance JSON path"):
                pipeline.load_manifest(case_dir, manifest_path)

            manifest["compliance"] = "../submission.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "escapes the case directory"):
                pipeline.load_manifest(case_dir, manifest_path)

            manifest["compliance"] = "compliance/submission.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            normalized = pipeline.load_manifest(case_dir, manifest_path)
            self.assertEqual(normalized["profile"], "submission")
            self.assertEqual(
                normalized["compliance"],
                (case_dir / "compliance" / "submission.json").resolve(),
            )
            self.assertEqual(
                normalized["m7_f2_plan"],
                (case_dir / "m7-f2-plan.json").resolve(),
            )

    def test_explore_profile_skips_postprocessing_and_cannot_finalize(self) -> None:
        pipeline = load_pipeline_module()
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = Path(temporary)
            script = case_dir / "analyze.py"
            script.write_text("print('ok')\n", encoding="utf-8")
            manifest = {
                "schema_version": 2,
                "profile": "explore",
                "steps": [
                    {
                        "name": "analyze",
                        "type": "python",
                        "script": script,
                        "args": [],
                        "inputs": [],
                        "outputs": [],
                        "timeout_seconds": 30,
                        "cache": False,
                    }
                ],
            }
            with patch.object(pipeline, "run_json_script") as run_json:
                build = pipeline.build_phase(case_dir, manifest, case_dir)
            run_json.assert_not_called()
            self.assertTrue(build["steps_completed"])
            self.assertTrue(build["postprocessing_skipped"])
            self.assertEqual(build["completion_scope"], "configured_steps_only")
            self.assertFalse(build["ready_for_visual_review"])
            self.assertTrue(build["preflight"]["skipped"])
            self.assertFalse(build["model_definition_audit"]["required"])

            finalized = pipeline.finalize_phase(case_dir, manifest, case_dir)
            self.assertFalse(finalized["ready_for_submission"])
            self.assertIn("cannot be finalized", finalized["errors"][0])

    def test_explore_manifest_can_omit_paper_configuration(self) -> None:
        pipeline = load_pipeline_module()
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = Path(temporary)
            (case_dir / "analyze.py").write_text("print('ok')\n", encoding="utf-8")
            manifest_path = case_dir / "workflow.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "profile": "explore",
                        "steps": [{"name": "analyze", "script": "analyze.py"}],
                    }
                ),
                encoding="utf-8",
            )
            manifest = pipeline.load_manifest(case_dir, manifest_path)
            self.assertEqual(manifest["artifacts"], {})
            self.assertEqual(manifest["audit"]["page_size"], "a4")

            completed = run_script(
                "run_pipeline.py",
                "--case-dir",
                str(case_dir),
                "--phase",
                "build",
                "--json",
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            report = json.loads(completed.stdout)
            self.assertEqual(report["completion_scope"], "configured_steps_only")
            self.assertTrue(report["preflight"]["skipped"])
            self.assertTrue((case_dir / ".workflow" / "pipeline-report.json").is_file())
            self.assertFalse((case_dir / "paper").exists())

    @unittest.skipUnless(
        __import__("importlib").util.find_spec("pypdf"), "pypdf is unavailable"
    )
    def test_submission_compliance_audit_checks_freshness_and_ai_evidence(self) -> None:
        from pypdf import PdfWriter
        from pypdf.generic import (
            DecodedStreamObject,
            DictionaryObject,
            NameObject,
        )

        def write_text_pdf(path: Path, text: str) -> None:
            writer = PdfWriter()
            page = writer.add_blank_page(width=595.28, height=841.89)
            font = DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/Type1"),
                    NameObject("/BaseFont"): NameObject("/Helvetica"),
                }
            )
            page[NameObject("/Resources")] = DictionaryObject(
                {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
            )
            stream = DecodedStreamObject()
            escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            stream.set_data(f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("ascii"))
            page[NameObject("/Contents")] = writer._add_object(stream)
            with path.open("wb") as output:
                writer.write(output)

        with tempfile.TemporaryDirectory() as temporary:
            case_dir = Path(temporary)
            (case_dir / "paper").mkdir()
            (case_dir / "ai").mkdir()
            (case_dir / "compliance").mkdir()
            statement = "AI use statement reviewed"
            docx = case_dir / "paper" / "paper.docx"
            pdf = case_dir / "paper" / "paper.pdf"
            detail_pdf = case_dir / "paper" / "AI-use-detail.pdf"
            write_minimal_docx(docx, statement)
            write_text_pdf(pdf, statement)
            write_text_pdf(detail_pdf, "Reviewed AI usage details")
            (case_dir / "ai" / "ai-usage.md").write_text(
                "# AI Use Register\n\nStatus: used\n\n"
                "## Entries\n\n2026-08-10: Used a named model for editing; "
                "the team checked every adopted sentence against source evidence.\n",
                encoding="utf-8",
            )
            compliance_path = case_dir / "compliance" / "submission.json"
            compliance = {
                "schema_version": 1,
                "competition": "CUMCM 2026",
                "year": 2026,
                "rules": {
                    "verified_at": "2026-08-10",
                    "max_age_days": 30,
                    "sources": ["https://www.mcm.edu.cn/rules"],
                },
                "ai": {
                    "status": "used",
                    "usage_log": "ai/ai-usage.md",
                    "paper_statement": statement,
                    "detail_pdf": "paper/AI-use-detail.pdf",
                },
            }
            compliance_path.write_text(json.dumps(compliance), encoding="utf-8")
            common = (
                "--case-dir", str(case_dir),
                "--compliance", "compliance/submission.json",
                "--docx", "paper/paper.docx",
                "--pdf", "paper/paper.pdf",
                "--as-of", "2026-08-13",
                "--json",
            )
            passed = run_script("audit_submission_compliance.py", *common)
            self.assertEqual(passed.returncode, 0, passed.stderr)
            passed_report = json.loads(passed.stdout)
            self.assertTrue(passed_report["passed"])
            self.assertEqual(
                set(passed_report["evidence_sha256"]),
                {"compliance", "docx", "pdf", "ai_usage_log", "ai_detail_pdf"},
            )
            from _workflow_common import verify_evidence_hashes

            self.assertEqual(verify_evidence_hashes(passed_report["evidence_sha256"]), [])

            audit_module = load_submission_audit_module()

            class LocalNextDay(date):
                @classmethod
                def today(cls):
                    return cls(2026, 8, 16)

            compliance["rules"]["verified_at"] = "2026-08-16"
            compliance_path.write_text(json.dumps(compliance), encoding="utf-8")
            with patch.object(audit_module, "date", LocalNextDay):
                local_day_report = audit_module.audit(
                    case_dir,
                    Path("compliance/submission.json"),
                    Path("paper/paper.docx"),
                    Path("paper/paper.pdf"),
                )
            self.assertTrue(local_day_report["passed"])
            self.assertEqual(local_day_report["as_of"], "2026-08-16")

            compliance["rules"]["verified_at"] = "2026-08-17"
            compliance_path.write_text(json.dumps(compliance), encoding="utf-8")
            with patch.object(audit_module, "date", LocalNextDay):
                future_day_report = audit_module.audit(
                    case_dir,
                    Path("compliance/submission.json"),
                    Path("paper/paper.docx"),
                    Path("paper/paper.pdf"),
                )
            self.assertFalse(future_day_report["passed"])
            self.assertIn(
                "rules verification age is -1 days",
                "\n".join(future_day_report["errors"]),
            )

            compliance["rules"]["verified_at"] = "2026-08-10"
            compliance_path.write_text(json.dumps(compliance), encoding="utf-8")
            usage_log = case_dir / "ai" / "ai-usage.md"
            original_usage = usage_log.read_text(encoding="utf-8")
            usage_log.write_text(original_usage + "Changed after audit.\n", encoding="utf-8")
            self.assertIn(
                "changed after compliance audit",
                "\n".join(verify_evidence_hashes(passed_report["evidence_sha256"])),
            )
            usage_log.write_text(original_usage, encoding="utf-8")

            compliance["rules"]["verified_at"] = "2026-01-01"
            compliance_path.write_text(json.dumps(compliance), encoding="utf-8")
            stale = run_script("audit_submission_compliance.py", *common)
            self.assertEqual(stale.returncode, 2)
            self.assertIn(
                "verification age", "\n".join(json.loads(stale.stdout)["errors"])
            )

            compliance["rules"]["verified_at"] = "2026-08-10"
            detail_pdf.unlink()
            compliance_path.write_text(json.dumps(compliance), encoding="utf-8")
            missing_detail = run_script("audit_submission_compliance.py", *common)
            self.assertEqual(missing_detail.returncode, 2)
            self.assertIn(
                "detail_pdf", "\n".join(json.loads(missing_detail.stdout)["errors"])
            )

    def test_pipeline_v2_validates_python_execution_metadata(self) -> None:
        pipeline = load_pipeline_module()
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = Path(temporary)
            (case_dir / "src").mkdir()
            (case_dir / "data").mkdir()
            (case_dir / "paper").mkdir()
            (case_dir / "src" / "analyze.py").write_text(
                "print('ok')\n", encoding="utf-8"
            )
            (case_dir / "data" / "input.json").write_text(
                "{}\n", encoding="utf-8"
            )
            manifest = {
                "schema_version": 2,
                "steps": [
                    {
                        "name": "analyze",
                        "script": "src/analyze.py",
                        "inputs": ["data/input.json"],
                        "outputs": ["results/output.json"],
                        "timeout_seconds": 42,
                        "cache": True,
                    }
                ],
                "artifacts": {
                    "docx": "paper/paper.docx",
                    "pdf": "paper/paper.pdf",
                    "render_dir": "paper/rendered-pages",
                    "visual_review": "paper/visual-review.json",
                },
                "audit": {},
            }
            manifest_path = case_dir / "workflow.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            normalized = pipeline.load_manifest(case_dir, manifest_path)
            step = normalized["steps"][0]
            self.assertEqual(normalized["schema_version"], 2)
            self.assertTrue(step["cache"])
            self.assertEqual(step["timeout_seconds"], 42)
            self.assertTrue(step["inputs"][0].is_absolute())

            manifest["schema_version"] = 1
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "requires schema_version 2"):
                pipeline.load_manifest(case_dir, manifest_path)

            manifest["schema_version"] = 2
            manifest["steps"].append(
                {
                    "name": "duplicate-output",
                    "script": "src/analyze.py",
                    "outputs": ["results/output.json"],
                }
            )
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "declare the same output"):
                pipeline.load_manifest(case_dir, manifest_path)

            manifest["steps"] = [
                {
                    "name": "reserved-output",
                    "script": "src/analyze.py",
                    "outputs": [".workflow/state.json"],
                }
            ]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "reserved by the workflow"):
                pipeline.load_manifest(case_dir, manifest_path)

    def test_pipeline_v2_caches_and_invalidates_python_steps(self) -> None:
        pipeline = load_pipeline_module()
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = Path(temporary)
            (case_dir / "src").mkdir()
            (case_dir / "data").mkdir()
            (case_dir / "paper").mkdir()
            input_path = case_dir / "data" / "input.txt"
            input_path.write_text("first\n", encoding="utf-8")
            script = case_dir / "src" / "build.py"
            script.write_text(
                "from pathlib import Path\n"
                "root=Path(__file__).resolve().parents[1]\n"
                "counter=root/'counter.txt'\n"
                "count=int(counter.read_text())+1 if counter.exists() else 1\n"
                "counter.write_text(str(count))\n"
                "out=root/'results'/'output.txt'\n"
                "out.parent.mkdir(exist_ok=True)\n"
                "out.write_text((root/'data'/'input.txt').read_text())\n",
                encoding="utf-8",
            )
            step = {
                "name": "build",
                "type": "python",
                "script": script,
                "args": [],
                "inputs": [input_path],
                "outputs": [case_dir / "results" / "output.txt"],
                "timeout_seconds": 30,
                "cache": True,
            }
            manifest = {"schema_version": 2, "steps": [step]}
            preflight = {"ready": True, "tools": {}, "matlab_batch": {}}
            definition = {"passed": True, "errors": []}

            def run(force: set[str] | None = None):
                with patch.object(
                    pipeline, "run_json_script", side_effect=[(preflight, {}), (definition, {})]
                ) as run_json:
                    report = pipeline.build_phase(
                        case_dir, manifest, case_dir, only={"build"}, force=force
                    )
                self.assertIn("--structure-only", run_json.call_args_list[1].args[1])
                return report

            first = run()
            self.assertEqual(first["steps"][0]["status"], "executed")
            second = run()
            self.assertEqual(second["steps"][0]["status"], "cache-hit")
            self.assertEqual((case_dir / "counter.txt").read_text(), "1")

            input_path.write_text("changed\n", encoding="utf-8")
            third = run()
            self.assertEqual(third["steps"][0]["status"], "executed")
            self.assertEqual((case_dir / "counter.txt").read_text(), "2")

            forced = run({"build"})
            self.assertEqual(forced["steps"][0]["status"], "executed")
            self.assertEqual((case_dir / "counter.txt").read_text(), "3")

    def test_pipeline_step_selection_and_docx_fallback(self) -> None:
        pipeline = load_pipeline_module()
        steps = [{"name": name} for name in ("one", "two", "three")]
        selected, postprocess = pipeline.select_steps(steps, from_step="two")
        self.assertEqual([step["name"] for step in selected], ["two", "three"])
        self.assertTrue(postprocess)
        selected, postprocess = pipeline.select_steps(steps, only={"one", "three"})
        self.assertEqual([step["name"] for step in selected], ["one", "three"])
        self.assertFalse(postprocess)
        with self.assertRaisesRegex(ValueError, "cannot be used together"):
            pipeline.select_steps(steps, from_step="one", only={"two"})

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            docx = root / "paper.docx"
            pdf = root / "paper.pdf"
            docx.write_bytes(b"docx")
            preflight = {
                "backends": {
                    "docx_to_pdf": {
                        "primary": {"name": "Microsoft Word", "path": "word"},
                        "fallbacks": [
                            {"name": "LibreOffice", "path": "soffice"}
                        ],
                    }
                }
            }

            def libreoffice(_executable, _docx, target_pdf, _cwd):
                from pypdf import PdfWriter

                writer = PdfWriter()
                writer.add_blank_page(width=595.28, height=841.89)
                with target_pdf.open("wb") as stream:
                    writer.write(stream)
                return {"ok": True, "exit_code": 0, "stdout": "", "stderr": ""}

            with (
                patch.object(
                    pipeline,
                    "export_with_word",
                    return_value={
                        "ok": False,
                        "exit_code": 1,
                        "stdout": "",
                        "stderr": "Word COM failed",
                    },
                ),
                patch.object(pipeline, "export_with_libreoffice", side_effect=libreoffice),
            ):
                report = pipeline.export_docx(docx, pdf, preflight, root)
            self.assertTrue(report["ok"])
            self.assertEqual(report["backend"], "LibreOffice")
            self.assertEqual(len(report["attempts"]), 2)
            self.assertTrue(pdf.read_bytes().startswith(b"%PDF-"))

            pdf.write_bytes(b"stale")
            with (
                patch.object(
                    pipeline,
                    "export_with_word",
                    return_value={
                        "ok": True,
                        "exit_code": 0,
                        "stdout": "",
                        "stderr": "",
                    },
                ),
                patch.object(
                    pipeline,
                    "export_with_libreoffice",
                    return_value={
                        "ok": False,
                        "exit_code": 1,
                        "stdout": "",
                        "stderr": "fallback failed",
                    },
                ),
            ):
                stale = pipeline.export_docx(docx, pdf, preflight, root)
            self.assertFalse(stale["ok"])
            self.assertEqual(pdf.read_bytes(), b"stale")

    def test_pipeline_manifest_supports_matlab_steps(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = Path(temporary) / "case"
            (case_dir / "src").mkdir(parents=True)
            (case_dir / "tests").mkdir()
            (case_dir / "paper").mkdir()
            (case_dir / "src" / "solve.m").write_text("value = 42;\n", encoding="utf-8")
            (case_dir / "src" / "helper.m").write_text(
                "function value=helper\nvalue=42;\nend\n", encoding="utf-8"
            )
            (case_dir / "tests" / "test_solve.m").write_text(
                "function tests=test_solve\ntests=functiontests(localfunctions);\nend\n",
                encoding="utf-8",
            )
            manifest = {
                "schema_version": 1,
                "steps": [
                    {
                        "name": "solve",
                        "type": "matlab",
                        "script": "src/solve.m",
                        "test": "tests/test_solve.m",
                        "dependencies": ["src/helper.m"],
                        "outputs": ["results/result.json"],
                    }
                ],
                "artifacts": {
                    "docx": "paper/paper.docx",
                    "pdf": "paper/paper.pdf",
                    "render_dir": "paper/rendered-pages",
                    "visual_review": "paper/visual-review.json",
                },
                "audit": {"page_size": "a4", "orientation": "portrait"},
            }
            manifest_path = case_dir / "workflow.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            valid = run_script(
                "run_pipeline.py",
                "--case-dir",
                str(case_dir),
                "--validate-only",
                "--json",
            )
            self.assertEqual(valid.returncode, 0, valid.stderr)
            step = json.loads(valid.stdout)["manifest"]["steps"][0]
            self.assertEqual(step["type"], "matlab")
            self.assertEqual(step["runner"], "mcp-evidence")
            self.assertTrue(step["test"].endswith("test_solve.m"))
            self.assertTrue(step["dependencies"][0].endswith("helper.m"))
            self.assertTrue(step["outputs"][0].endswith("result.json"))
            self.assertTrue(step["evidence"].endswith("matlab-validation-solve.json"))

            manifest["steps"][0]["args"] = ["unsupported"]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            invalid_args = run_script(
                "run_pipeline.py",
                "--case-dir",
                str(case_dir),
                "--validate-only",
                "--json",
            )
            self.assertEqual(invalid_args.returncode, 2)
            self.assertIn("do not accept args", invalid_args.stdout)

            manifest["steps"][0].pop("args")
            manifest["steps"][0]["type"] = "shell"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            invalid_type = run_script(
                "run_pipeline.py",
                "--case-dir",
                str(case_dir),
                "--validate-only",
                "--json",
            )
            self.assertEqual(invalid_type.returncode, 2)
            self.assertIn("type must be python or matlab", invalid_type.stdout)

            manifest["steps"][0]["type"] = "matlab"
            manifest["steps"][0]["evidence"] = "results/result.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            evidence_conflict = run_script(
                "run_pipeline.py",
                "--case-dir",
                str(case_dir),
                "--validate-only",
                "--json",
            )
            self.assertEqual(evidence_conflict.returncode, 2)
            self.assertIn("must not overwrite", evidence_conflict.stdout)

    def test_matlab_mcp_evidence_is_explicit_and_hash_bound(self) -> None:
        pipeline = load_pipeline_module()
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = Path(temporary)
            (case_dir / "src").mkdir()
            (case_dir / "tests").mkdir()
            (case_dir / "results").mkdir()
            script = case_dir / "src" / "solve.m"
            test = case_dir / "tests" / "test_solve.m"
            dependency = case_dir / "src" / "helper.m"
            output = case_dir / "results" / "result.json"
            script.write_text("value = 42;\n", encoding="utf-8")
            test.write_text("assert(true);\n", encoding="utf-8")
            dependency.write_text(
                "function value=helper\nvalue=42;\nend\n", encoding="utf-8"
            )
            output.write_text('{"value": 42}\n', encoding="utf-8")

            missing_confirmation = run_script(
                "record_matlab_validation.py",
                "--case-dir", str(case_dir),
                "--step-name", "solve",
                "--script", "src/solve.m",
                "--test", "tests/test_solve.m",
                "--dependency", "src/helper.m",
                "--output", "results/result.json",
                "--json",
            )
            self.assertEqual(missing_confirmation.returncode, 2)
            self.assertFalse(json.loads(missing_confirmation.stdout)["recorded"])

            recorded = run_script(
                "record_matlab_validation.py",
                "--case-dir", str(case_dir),
                "--step-name", "solve",
                "--script", "src/solve.m",
                "--test", "tests/test_solve.m",
                "--dependency", "src/helper.m",
                "--output", "results/result.json",
                "--confirm-code-analyzer-passed",
                "--confirm-script-execution-passed",
                "--confirm-unit-tests-passed",
                "--json",
            )
            self.assertEqual(recorded.returncode, 0, recorded.stderr)
            evidence = json.loads(recorded.stdout)["evidence"]
            load_and_validate(
                evidence,
                SCHEMAS / "matlab-validation.schema.json",
                "MATLAB validation evidence",
            )
            step = {
                "name": "solve",
                "type": "matlab",
                "runner": "mcp-evidence",
                "script": script,
                "test": test,
                "dependencies": [dependency],
                "outputs": [output],
                "evidence": case_dir / "results" / "matlab-validation-solve.json",
            }
            verified = pipeline.verify_matlab_evidence(step, case_dir)
            self.assertTrue(verified["ok"], verified["errors"])

            output.write_text('{"value": 43}\n', encoding="utf-8")
            stale = pipeline.verify_matlab_evidence(step, case_dir)
            self.assertFalse(stale["ok"])
            self.assertIn("hashes do not match", "\n".join(stale["errors"]))

            output.write_text('{"value": 42}\n', encoding="utf-8")
            dependency.write_text(
                "function value=helper\nvalue=43;\nend\n", encoding="utf-8"
            )
            stale_dependency = pipeline.verify_matlab_evidence(step, case_dir)
            self.assertFalse(stale_dependency["ok"])
            self.assertIn(
                "hashes do not match", "\n".join(stale_dependency["errors"])
            )

    @unittest.skipUnless(
        __import__("importlib").util.find_spec("pypdf"), "pypdf is unavailable"
    )
    def test_visual_review_record_requires_explicit_confirmation(self) -> None:
        from pypdf import PdfWriter

        with tempfile.TemporaryDirectory() as temporary:
            case_dir = Path(temporary)
            paper_dir = case_dir / "paper"
            render_dir = paper_dir / "rendered-pages"
            render_dir.mkdir(parents=True)
            pdf = paper_dir / "paper.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=595.28, height=841.89)
            with pdf.open("wb") as stream:
                writer.write(stream)
            write_minimal_png(render_dir / "page-1.png")

            unconfirmed = run_script(
                "record_visual_review.py",
                "--case-dir",
                str(case_dir),
                "--reviewer",
                "tester",
                "--json",
            )
            self.assertEqual(unconfirmed.returncode, 2)
            self.assertFalse(json.loads(unconfirmed.stdout)["recorded"])

            confirmed = run_script(
                "record_visual_review.py",
                "--case-dir",
                str(case_dir),
                "--reviewer",
                "tester",
                "--confirm-all-pages-reviewed",
                "--json",
            )
            self.assertEqual(confirmed.returncode, 0, confirmed.stderr)
            report = json.loads(confirmed.stdout)
            self.assertTrue(report["recorded"])
            record = json.loads(
                (paper_dir / "visual-review.json").read_text(encoding="utf-8")
            )
            self.assertEqual(record["reviewed_pages"], [1])
            self.assertEqual(record["reviewer"], "tester")
            load_and_validate(
                record, SCHEMAS / "visual-review.schema.json", "visual review record"
            )

            custom_output = run_script(
                "record_visual_review.py",
                "--case-dir",
                str(case_dir),
                "--output",
                "paper/visual-review-rebuilt.json",
                "--reviewer",
                "tester",
                "--confirm-all-pages-reviewed",
                "--json",
            )
            self.assertEqual(custom_output.returncode, 0, custom_output.stderr)
            custom_report = json.loads(custom_output.stdout)
            self.assertTrue(custom_report["recorded"])
            self.assertTrue(
                (paper_dir / "visual-review-rebuilt.json").is_file()
            )

    @unittest.skipUnless(
        __import__("importlib").util.find_spec("pypdf"), "pypdf is unavailable"
    )
    def test_finalizer_requires_matching_visual_review_record(self) -> None:
        from pypdf import PdfWriter

        with tempfile.TemporaryDirectory() as temporary:
            case_dir = Path(temporary)
            (case_dir / "results").mkdir(parents=True)
            (case_dir / "paper").mkdir()
            (case_dir / "rendered").mkdir()
            (case_dir / "results" / "q1.json").write_text(
                '{"score": 0.95}\n', encoding="utf-8"
            )
            (case_dir / "results" / "result-register.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "results": [
                            {
                                "id": "q1.score",
                                "value": 0.95,
                                "source_file": "results/q1.json",
                                "source_key": "score",
                                "paper_required": False,
                            }
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (case_dir / "problem").mkdir()
            (case_dir / "problem" / "model-definition-register.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "assessment_status": "completed",
                        "assessment_evidence": "Reviewed objective, constraints, units, time origin, aggregation, and boundary conventions.",
                        "no_material_ambiguity_rationale": "The test fixture defines every convention explicitly and has no alternate interpretation that changes its single scalar result.",
                        "ambiguities": [],
                    }
                ),
                encoding="utf-8",
            )
            docx = case_dir / "paper" / "paper.docx"
            pdf = case_dir / "paper" / "paper.pdf"
            write_minimal_docx(docx, "Test paper")
            writer = PdfWriter()
            writer.add_blank_page(width=595.28, height=841.89)
            with pdf.open("wb") as stream:
                writer.write(stream)
            rendered_page = case_dir / "rendered" / "page-1.png"
            rendered_page.write_bytes(b"not-empty")
            invalid_render = run_script(
                "audit_paper.py",
                "--pdf",
                str(pdf),
                "--render-dir",
                str(case_dir / "rendered"),
                "--json",
            )
            self.assertEqual(invalid_render.returncode, 2)
            self.assertIn("invalid PNG", "\n".join(json.loads(invalid_render.stdout)["errors"]))
            write_minimal_png(rendered_page)

            common = (
                "--case-dir",
                str(case_dir),
                "--docx",
                str(docx),
                "--pdf",
                str(pdf),
                "--render-dir",
                str(case_dir / "rendered"),
                "--page-size",
                "a4",
                "--orientation",
                "portrait",
                "--json",
            )
            pending = run_script("finalize_case.py", *common)
            self.assertEqual(pending.returncode, 2)
            self.assertEqual(
                json.loads(pending.stdout)["visual_review"]["status"],
                "not_performed",
            )

            (case_dir / "compliance").mkdir()
            (case_dir / "ai").mkdir()
            (case_dir / "ai" / "ai-usage.md").write_text(
                "# AI Use Register\n\nStatus: undecided\n\nNo entries yet.\n",
                encoding="utf-8",
            )
            compliance_path = case_dir / "compliance" / "submission.json"
            compliance_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "competition": "CUMCM 2026",
                        "year": 2026,
                        "rules": {
                            "verified_at": "2026-08-10",
                            "max_age_days": 30,
                            "sources": ["https://www.mcm.edu.cn/rules"],
                        },
                        "ai": {
                            "status": "used",
                            "usage_log": "ai/ai-usage.md",
                            "paper_statement": "AI use statement",
                            "detail_pdf": "paper/AI-use-detail.pdf",
                        },
                    }
                ),
                encoding="utf-8",
            )
            compliance_failed = run_script(
                "finalize_case.py",
                *common[:-1],
                "--submission-compliance",
                str(compliance_path),
                "--json",
            )
            self.assertEqual(compliance_failed.returncode, 2)
            compliance_report = json.loads(compliance_failed.stdout)
            self.assertTrue(compliance_report["submission_compliance"]["required"])
            self.assertFalse(compliance_report["submission_compliance"]["passed"])
            self.assertFalse(compliance_report["ready_for_submission"])

            original_pdf_hash = hashlib.sha256(pdf.read_bytes()).hexdigest()
            conflict = run_script(
                "finalize_case.py",
                *common[:-1],
                "--report",
                str(pdf),
                "--json",
            )
            self.assertEqual(conflict.returncode, 2)
            self.assertFalse(json.loads(conflict.stdout)["ready_for_submission"])
            self.assertEqual(hashlib.sha256(pdf.read_bytes()).hexdigest(), original_pdf_hash)

            report_path = case_dir / "paper" / "finalization-report.json"
            report_path.unlink()
            original_page_hash = hashlib.sha256(rendered_page.read_bytes()).hexdigest()
            try:
                os.link(rendered_page, report_path)
            except OSError:
                pass
            else:
                hardlink_conflict = run_script("finalize_case.py", *common)
                self.assertEqual(hardlink_conflict.returncode, 2)
                self.assertEqual(
                    hashlib.sha256(rendered_page.read_bytes()).hexdigest(),
                    original_page_hash,
                )
                report_path.unlink()

            review = {
                "schema_version": 1,
                "status": "passed",
                "reviewed_at": "2026-08-11T00:00:00+00:00",
                "reviewer": "workflow-test",
                "pdf_sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
                "page_count": 1,
                "reviewed_pages": [1],
                "rendered_pages_sha256": {
                    "page-1.png": hashlib.sha256(rendered_page.read_bytes()).hexdigest()
                },
                "notes": "All pages inspected.",
            }
            review_path = case_dir / "paper" / "visual-review.json"
            review_path.write_text(json.dumps(review), encoding="utf-8")
            completed = run_script(
                "finalize_case.py",
                *common[:-1],
                "--visual-review-record",
                str(review_path),
                "--json",
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            report = json.loads(completed.stdout)
            self.assertTrue(report["ready_for_submission"])
            qa_text = (case_dir / "paper" / "qa-register.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("Every final page inspected", qa_text)
            self.assertIn("| passed |", qa_text)


    def test_directory_inputs_are_hashed_deterministically(self) -> None:
        from _workflow_common import sha256_path

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "raw"
            root.mkdir()
            (root / "b.txt").write_text("b", encoding="utf-8")
            (root / "nested").mkdir()
            (root / "nested" / "a.txt").write_text("a", encoding="utf-8")
            first = sha256_path(root)
            second = sha256_path(root)
            self.assertEqual(first, second)
            (root / "nested" / "a.txt").write_text("changed", encoding="utf-8")
            self.assertNotEqual(first, sha256_path(root))

    def test_paper_audit_rejects_template_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            docx = Path(temporary) / "paper.docx"
            write_minimal_docx(docx, "Paper Title")
            completed = run_script("audit_paper.py", "--docx", str(docx), "--json")
            self.assertEqual(completed.returncode, 2)
            report = json.loads(completed.stdout)
            self.assertFalse(report["structural_ok"])
            self.assertTrue(any("template placeholder" in error for error in report["errors"]))

    def test_paper_audit_rejects_stable_finalization_sentinel(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            docx = Path(temporary) / "paper.docx"
            write_minimal_docx(docx, "MMFINALIZE-ABSTRACT")
            completed = run_script("audit_paper.py", "--docx", str(docx), "--json")
            self.assertEqual(completed.returncode, 2)
            report = json.loads(completed.stdout)
            self.assertFalse(report["structural_ok"])
            self.assertIn("MMFINALIZE", report["docx"]["template_placeholders"])

    @unittest.skipUnless((SKILL_DIR / "templates" / "cumcm-2026-latex").exists(), "Public candidate: downloaded LaTeX asset not bundled; integration NOT VERIFIED")
    def test_cumcm_latex_template_isolates_authoring_guidance(self) -> None:
        template = SKILL_DIR / "templates" / "cumcm-2026-latex"
        section_paths = [
            template / "sections" / "00-abstract.tex",
            template / "sections" / "01-problem-analysis.tex",
            template / "sections" / "02-assumptions-symbols-data.tex",
            template / "sections" / "03-models-results.tex",
            template / "sections" / "04-validation-conclusions.tex",
        ]
        combined = "\n".join(path.read_text(encoding="utf-8") for path in section_paths)
        for phrase in (
            "结果冻结后再完成摘要",
            "用可计算的语言逐项说明输入、输出、变量、约束",
            "只保留影响模型闭合的假设",
            "先用一至两句给出本问的直接答案",
            "逐项直接回收正文已经冻结并验证的答案",
        ):
            matching_lines = [line for line in combined.splitlines() if phrase in line]
            self.assertTrue(matching_lines, phrase)
            self.assertTrue(
                all(line.startswith("% AUTHORING-GUIDANCE:") for line in matching_lines),
                phrase,
            )
        self.assertGreaterEqual(combined.count(r"\FinalizationRequired{"), 12)
        config = (template / "paper-config.tex").read_text(encoding="utf-8")
        self.assertIn(r"\newcommand{\FinalizationRequired}[1]", config)
        self.assertIn(r"\title{\FinalizationRequired{TITLE}}", config)
        self.assertIn(r"\FinalizationRequired{AI-DECLARATION}", config)
    def test_paper_audit_rejects_current_latex_template_examples(self) -> None:
        markers = (
            "终稿前必须替换或删除本示例条目",
            "表中仅列可替换的导航示例",
            "最小可运行示例（终稿前替换或删除）",
        )
        with tempfile.TemporaryDirectory() as temporary:
            for index, marker in enumerate(markers):
                docx = Path(temporary) / f"paper-{index}.docx"
                write_minimal_docx(docx, marker)
                completed = run_script(
                    "audit_paper.py", "--docx", str(docx), "--json"
                )
                self.assertEqual(completed.returncode, 2, marker)
                report = json.loads(completed.stdout)
                self.assertFalse(report["structural_ok"], marker)
                self.assertIn(marker, report["docx"]["template_placeholders"])

    def test_paper_audit_matches_chinese_template_marker_across_whitespace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            docx = Path(temporary) / "paper.docx"
            write_minimal_docx(
                docx,
                "终稿前必须替换或删除本示例条\n目",
            )
            completed = run_script("audit_paper.py", "--docx", str(docx), "--json")
            self.assertEqual(completed.returncode, 2)
            report = json.loads(completed.stdout)
            self.assertFalse(report["structural_ok"])
            self.assertIn(
                "终稿前必须替换或删除本示例条目",
                report["docx"]["template_placeholders"],
            )

    def test_paper_audit_rejects_literal_inline_latex_marker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            docx = Path(temporary) / "paper.docx"
            write_minimal_docx(docx, "feature $D_x^*$")
            completed = run_script("audit_paper.py", "--docx", str(docx), "--json")
            self.assertEqual(completed.returncode, 2)
            report = json.loads(completed.stdout)
            self.assertFalse(report["structural_ok"])
            self.assertTrue(
                any("unrendered LaTeX marker" in error for error in report["errors"])
            )

    def test_paper_audit_rejects_plain_text_sqrt_formula(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            docx = Path(temporary) / "paper.docx"
            write_minimal_docx(docx, "J(w) = sqrt{(1/N) sum(error^2)}")
            completed = run_script("audit_paper.py", "--docx", str(docx), "--json")
            self.assertEqual(completed.returncode, 2)
            report = json.loads(completed.stdout)
            self.assertFalse(report["structural_ok"])
            self.assertTrue(
                any("unrendered LaTeX marker" in error for error in report["errors"])
            )

    def test_failure_event_log_is_append_only_and_bounded(self) -> None:
        from _workflow_common import append_failure_event

        with tempfile.TemporaryDirectory() as temporary:
            log_path = Path(temporary) / "rehearsal" / "failure-events.jsonl"
            report = {
                "phase": "build",
                "errors": ["Access is denied"],
                "failure": {
                    "failed_stage": "preflight",
                    "cause_code": "environment_not_ready",
                    "retryable": True,
                    "remediation": ["Check the declared output directory ACL."],
                },
            }
            self.assertTrue(
                append_failure_event(
                    log_path,
                    source="test",
                    report=report,
                    command=["run_pipeline.py", "--phase", "build"],
                )
            )
            self.assertTrue(append_failure_event(log_path, source="test", report=report))
            events = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(events), 2)
            self.assertEqual(events[0]["cause_code"], "environment_not_ready")
            self.assertEqual(events[0]["errors"], ["Access is denied"])
            self.assertEqual(events[0]["command"], ["run_pipeline.py", "--phase", "build"])
            self.assertEqual(events[1]["source"], "test")


if __name__ == "__main__":
    unittest.main()











