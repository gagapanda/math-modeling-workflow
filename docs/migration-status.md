# Public Distribution Scope

This repository is a source-only public edition of the mathematical-modeling workflow. It is not a readiness certificate, a complete competition environment, or an official-rules snapshot.

## Included

- The `math-modeling` Skill, general references, scripts, JSON Schemas and generic templates.
- Model baselines and synthetic regression tests.
- Candidate-lineage management, authority heartbeat and the `mm` command entry point.
- Paper integration, evidence binding, closeout and post-contest harvesting controls.
- The separately reviewed public Markdown-to-Word/PDF adapter and its synthetic tests.

## Excluded

- Private cases, papers, competition attachments, audit evidence and local libraries.
- Downloaded course material, third-party LaTeX classes and fonts without redistribution clearance.
- Virtual environments, dependencies, caches, build logs and generated documents.
- Human approvals, official submission receipts and historical local-machine readiness claims.

## Validation Boundary

Run the source inventory gate and Skill checks from the repository root:

```powershell
python -B scripts/check_release_inventory.py --root . --require-release
python -B .agents/skills/math-modeling/scripts/check_skill.py --workspace-root . --skip-historical --json
python -B -m unittest discover -s tests -p "test_*.py"
```

Passing these checks proves only the recorded source, structure and synthetic regression contracts. It does not prove model correctness for a new problem, document rendering on an untested machine, compliance with current rules, human acceptance, or official submission.
