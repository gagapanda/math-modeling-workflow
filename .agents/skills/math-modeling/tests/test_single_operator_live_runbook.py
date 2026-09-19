from pathlib import Path
import unittest


SKILL_ROOT = Path(__file__).resolve().parents[1]


class SingleOperatorLiveRunbookTests(unittest.TestCase):
    def test_runbook_is_routed_from_skill_and_exposes_live_contracts(self) -> None:
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        runbook = (
            SKILL_ROOT / "references" / "single-operator-live-runbook.md"
        ).read_text(encoding="utf-8")

        self.assertIn("single-operator-live-runbook.md", skill)
        for contract in (
            "one canonical workspace",
            "must not sign a human gate",
            "single_operator_second_pass",
            "DO_NOT_FREEZE",
            "NON_AUTHORITATIVE REVIEW DRAFT",
            "paper_authoritative=false",
            "F1_THAW",
            "M7-PRECHECK-PASS",
            "NOT_FORMAL_F2",
            "120 minutes remaining",
            "60 minutes remaining",
            "30 minutes remaining",
            "AI Use Record",
            "CURRENT-STATE.md",
            "resume and authority summary",
            "AUTHORITY_UNRESOLVED",
            "STALE_CONTROL_FILE",
            "required=false",
            "NOT_RUN_OR_NOT_REQUIRED",
            "successful subset smoke test proves only that subset",
            "freeze_results.py prepare",
            "F1_PENDING_HUMAN",
            "actual responsible human operator",
            "verified accepted manifest",
            "candidate provenance",
            "Authority Heartbeat",
            "SUBMISSION_AUTHORITY_DRIFT",
            "TECHNICAL_ONLY_SUPPORT_PACKAGE",
            "AI_DETAILS_NOT_BOUND",
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, runbook)

        harvest = (
            SKILL_ROOT / "references" / "post-contest-harvest.md"
        ).read_text(encoding="utf-8")
        self.assertIn("post-contest-harvest.md", skill)
        for marker in (
            "observed facts",
            "human recollection",
            "inferred causes",
            "adopted controls",
            "NO_RETROACTIVE_GATE_CLAIM",
        ):
            with self.subTest(harvest_marker=marker):
                self.assertIn(marker, harvest)

        checklist = (
            SKILL_ROOT / "references" / "submission-checklist.md"
        ).read_text(encoding="utf-8")
        self.assertIn("TECHNICAL_ONLY_SUPPORT_PACKAGE", checklist)
        self.assertIn("AI-detail draft", checklist)

    def test_h4_data_lineage_and_lead_time_contracts_are_routed(self) -> None:
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        data_audit = (SKILL_ROOT / "references" / "data-audit.md").read_text(encoding="utf-8")
        routing = (SKILL_ROOT / "references" / "model-routing.md").read_text(encoding="utf-8")
        checklist = (SKILL_ROOT / "references" / "submission-checklist.md").read_text(encoding="utf-8")

        for marker in ("container path and SHA-256", "member path and SHA-256", "temporary extraction path"):
            with self.subTest(skill_marker=marker):
                self.assertIn(marker, skill)
        for marker in ("container_path", "container_sha256", "member_path", "member_sha256"):
            with self.subTest(lineage_marker=marker):
                self.assertIn(marker, data_audit)
        for marker in ("L=1", "L>=2", "DO_NOT_FREEZE", "future realized demand"):
            with self.subTest(routing_marker=marker):
                self.assertIn(marker, routing)
        for marker in ("case-relative", "support-smoke-plan.json", "M7 precheck"):
            with self.subTest(checklist_marker=marker):
                self.assertIn(marker, checklist)

    def test_h4_p1_controls_are_routed_without_reopening_closed_gates(self) -> None:
        paper = (SKILL_ROOT / "references" / "paper-production.md").read_text(encoding="utf-8")
        workflow = (SKILL_ROOT / "references" / "workflow-automation.md").read_text(encoding="utf-8")
        recovery = (SKILL_ROOT / "references" / "environment-and-recovery.md").read_text(encoding="utf-8")
        routing = (SKILL_ROOT / "references" / "model-routing.md").read_text(encoding="utf-8")
        checklist = (SKILL_ROOT / "references" / "submission-checklist.md").read_text(encoding="utf-8")

        for marker in ("must not add a table of contents by default", "--include-toc", "CUMCM"):
            with self.subTest(toc_marker=marker):
                self.assertIn(marker, paper)
        self.assertIn("omits a table of contents by default", workflow)
        for marker in ("DOCX-To-PDF Dual-Backend Recovery Card", "10 minutes", "visual inspection of every page"):
            with self.subTest(recovery_marker=marker):
                self.assertIn(marker, recovery)
        for marker in ("Aggregation Denominator And Weighting Gate", "macro/unweighted", "micro/volume-weighted", "definition sensitivity"):
            with self.subTest(aggregation_marker=marker):
                self.assertIn(marker, routing)
        for marker in ("support DOCX/PDF/OOXML/text payload", "local absolute paths", "manual-review limitation"):
            with self.subTest(scan_marker=marker):
                self.assertIn(marker, checklist)

    def test_single_operator_rehearsal_does_not_invent_reviewers(self) -> None:
        rehearsal = (
            SKILL_ROOT / "references" / "timed-rehearsal.md"
        ).read_text(encoding="utf-8")
        self.assertIn("single-operator rehearsal", rehearsal)
        self.assertIn("do not invent additional members or reviewers", rehearsal)
        self.assertIn("delayed adversarial second pass", rehearsal)
        self.assertNotIn("team lead before start", rehearsal)
        self.assertNotIn("team review after the last event", rehearsal)

    @unittest.skipUnless((SKILL_ROOT.parents[2] / "比赛版数学建模运行协议-2026国赛.md").exists(), "Public candidate: private protocol not distributed; historical integration NOT VERIFIED")
    def test_live_protocol_and_readiness_roadmap_match_single_operator_authority(self) -> None:
        workspace_root = SKILL_ROOT.parents[2]
        protocol = (workspace_root / "比赛版数学建模运行协议-2026国赛.md").read_text(
            encoding="utf-8"
        )
        roadmap = (
            SKILL_ROOT / "references" / "competition-readiness-roadmap-2026.md"
        ).read_text(encoding="utf-8")

        for marker in (
            "用户是唯一真实人工责任人",
            "single_operator_second_pass",
            "single_operator_review",
            "Codex 可以准备和验证证据，但不得代签",
            "用户完成最后一次错时、换视角复核",
        ):
            with self.subTest(protocol_marker=marker):
                self.assertIn(marker, protocol)
        for prohibited in (
            "双人复核",
            "至少两名队员",
            "队友审核/拍板人",
            "交队友拍板",
            "真实队员人工门",
        ):
            with self.subTest(protocol_prohibited=prohibited):
                self.assertNotIn(prohibited, protocol)

        for marker in (
            "单操作者执行效率",
            "唯一责任人操作 Codex Desktop",
            "### 单操作者节奏",
            "single_operator_second_pass",
            "唯一操作者能够借助 Codex Desktop",
        ):
            with self.subTest(roadmap_marker=marker):
                self.assertIn(marker, roadmap)
        self.assertNotIn("按真实团队分工", roadmap)
        self.assertNotIn("### 团队节奏", roadmap)
    def test_generic_failure_prevention_has_no_case_specific_reviewer(self) -> None:
        failure_prevention = (
            SKILL_ROOT / "references" / "failure-prevention.md"
        ).read_text(encoding="utf-8")
        self.assertNotIn("PRIVATE_REVIEWER_SENTINEL", failure_prevention)
        self.assertIn("actual responsible human reviewer/operator", failure_prevention)


if __name__ == "__main__":
    unittest.main()

