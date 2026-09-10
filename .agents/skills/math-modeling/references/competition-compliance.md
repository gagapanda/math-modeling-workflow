# Public-edition verification boundary

The dated source descriptions below are historical guidance, not current official verification. No official document or current-rule audit is supplied by this migration. Verify the actual contest requirements before use.

# Competition Compliance

Treat this file as a dated snapshot, not permanent authority. Verify current official rules before every live competition.

## 2026 CUMCM Snapshot

Verified on 2026-08-10 from the official CUMCM site:

- Contest: 2026 高教社杯全国大学生数学建模竞赛.
- Time: 2026-09-10 18:00 through 2026-09-13 20:00.
- Team: no more than three students from the same institution.
- Graduate students are not eligible.
- Official site: https://www.mcm.edu.cn
- 2026 rules: https://www.mcm.edu.cn/html_cn/node/9d8e511fe7a1447b35f53a82c908e2e0.html
- 2026 paper format: https://www.mcm.edu.cn/html_cn/node/4cd596519c9eb9fbd866398f6df0caa3.html
- 2026 AI rules: https://www.mcm.edu.cn/html_cn/node/fef94648f2836ab6cc81586f4c38512b.html

Key paper-format requirements in the 2026 revision include an official commitment page, numbering page, one-page abstract section, no table of contents,正文 no longer than 30 pages, and appendices containing the complete runnable source code and support-file list. Confirm details against the official documents and the team's contest area.

For the controlled LaTeX path, `templates/cumcm-2026-latex/paper.tex` is the electronic anonymous entrypoint and deliberately omits the two identity pages. `paper-print.tex` is only the paper-print wrapper. The required document order is `abstract -> main text -> AI declaration -> references -> appendices`; changing that order or enabling a table of contents is a compliance failure. A successful compilation does not establish page-limit, anonymity, AI-disclosure, or visual-layout compliance.

### AI Use

The 2026 trial rules allow AI assistance but require human leadership, review, and verification.

- Put an “AI工具使用声明” before the references, choosing the official used/not-used wording.
- When AI is used, include `AI工具使用详情.pdf` in support materials.
- Record tool name and version/model when known, purpose and stage, major prompting/use process, adopted output, human changes, and verification.
- Do not submit unverified AI output as core modeling or analysis.
- Concealment, false declarations, or missing necessary review can disqualify the entry.

Maintain `ai/ai-usage.md` throughout a live case. Do not reconstruct it from memory at the end.

## Complete M6 Evidence Boundary

For a new CUMCM submission case, `compliance/m6-plan.json` is the complete machine entry point. Its technical audit covers the current official-rules snapshot and SHA-256, anonymity, citations/external data/software and licenses, AI disclosure content, and the exact support allowlist. A technical pass is not M6 approval.

Use the following sequence:

```text
technical audit
-> prepare M6_PENDING_HUMAN candidate
-> actual single-operator human review
-> human records accepted / accepted_with_limitations / rejected
-> verify immutable manifest
-> full audit during finalization
```

Codex may prepare and verify every evidence item but cannot use `--confirm-human-reviewed`, sign as reviewer, or infer approval from earlier blanket consent. A one-person team records `single_operator_review`; it does not invent a second or independent reviewer. `accepted_with_limitations` requires real objections and a recorded resolution.

The source register must be `complete` when sources exist, or `not_applicable` with a substantive reason and review timestamp when none exist. `pending`, unknown/prohibited license status, missing local evidence where declared, or a required support file absent from the allowlist blocks M6. When AI use requires a detail PDF, include it explicitly in `submission-package-plan.json`.

The legacy `audit_submission_compliance.py` remains available for old cases. It proves only `rules_and_ai_technical_only`, always reports `full_m6_proven=false`, and cannot close complete M6.

## M7/F2 Official Submission Boundary

The local M7 gate selects and reviews the exact delivery candidate; it does not prove official submission. `ready_for_submission=true`, successful packaging, a clean support replay, `M7-PRECHECK-PASS`, and an accepted M7 manifest all remain `NOT_FORMAL_F2`.

Use `m7-f2-plan.json` and `audit_m7_f2.py` to bind the package report, finalization report, source and packaged paper, support ZIP, smoke report, every required replay, current competition/platform, future official receipt path, and immutable M7/F2 manifests. A one-person run records `single_operator_review`. Codex may prepare and verify the evidence but cannot use `--confirm-human-reviewed`, use `--confirm-official-upload`, name itself as reviewer/operator, fabricate a receipt, or infer a future upload from blanket consent.

Record `F2_COMPLETE` only after all of the following are true:

1. the accepted M7 manifest verifies;
2. the selected package and smoke evidence are unchanged;
3. the responsible human actually uploads that package through the current official platform;
4. a real non-empty official receipt with an allowlisted suffix is preserved;
5. substantive local and portal submission identifiers and ordered timestamps are recorded;
6. the immutable F2 manifest passes `verify-f2`.
## 2026 Graduate Contest Snapshot

- Contest: “华为杯”第二十三届中国研究生数学建模竞赛.
- Organizer platform: https://cpipc.acge.org.cn/cw/hp/4
- Contest time: 2026-09-23 08:00 through 2026-09-27 12:00.
- Team: three eligible graduate students; verify cross-institution rules for the entrant year.
- 2026 host: Xi'an Jiaotong University.

## Live-Competition Guardrails

- Confirm eligibility, registration, payment, official template, deadline, and upload mechanism before modeling begins.
- Do not contact instructors or external people about the active problem when prohibited.
- Do not browse or publish active-problem discussions on forums, social media, code hosts, or group chats.
- Cite all public data and prior work used.
- Keep identities and institution names out of anonymized paper sections.
- Preserve source files and a reproducible run path for support-material review.
