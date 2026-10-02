# Repository review — 2 October 2026

Reviewed the project before pushing the closed-testing feedback and candidate-learning system to `main`.
The review covered application code, tests, build/deployment configuration and operator documentation.
This is a repository review with regression checks, not an independent penetration test or quality-system
validation. Live production infrastructure and an actual Docker deployment were not exercised.

## Findings resolved

| Priority | Finding and impact | Resolution and regression evidence |
|---|---|---|
| P1 | Excel exports treated comments/descriptions beginning with `=` as executable formulas. | Report, approval-history and terminology XLSX exports store values as literal text; CSV exports escape formula-like values. Workbook validation/formatting remains intact. Tests cover comments in both current state and history, terminology exports and failed-write cleanup. |
| P1 | Concurrent incorrect passwords could overwrite the failure counter, bypassing the intended lockout. | Password verification and failure-counter updates execute in one transaction. A concurrent-attempt regression reaches lockout without losing attempts. |
| P2 | Concurrent signup for the same address could raise a database error; public credentials had no upper input bounds. | Account existence and insertion are transactional, duplicate signup remains a normal conflict, and credential fields have size limits. Concurrent signup and input-validation tests pass. |
| P1 | Label-revision comparisons could clear uncertain extraction, ambiguous pairings or incompatible structured variants; PCO/BOM checks could clear low-confidence values. | Those rows require validation; strict PCO expectations honor assignment/conflict/confirmation guards. Checker versions increase to preserve run reproducibility. Tests cover unchanged lines, duplicate alternatives, inferred identity, PCO confidence and conflicting gauges. |
| P1 | XLSX terminology worklists could expose reserved evaluation examples as training suggestions. | Report worklists use only non-evaluation rows, matching the API worklist/mining restrictions. An export regression checks real worklist row IDs against the reserved SKU. |
| P2 | Bulk acceptance and Excel decision import could invalidate verified labels without rebuilding the candidate. | Both mutation paths enqueue a coalesced rebuild when verified evidence changes. HTTP regressions verify rebuilding, removal of invalidated training labels and dry-run isolation. Approval of an unchanged decision preserves verified evidence. |
| P2 | A candidate report could appear current after approved terminology changed. | Reports record their source terminology hash; the dashboard marks a comparison stale after terminology or verified-dataset changes. A rebuild clears the stale state. |
| P2 | The optional local embedding adapter could download a missing model despite its offline contract. | Model construction uses `local_files_only=True`. A constructor regression verifies this option without installing or downloading a model. See the [Sentence Transformers parameter documentation](https://sbert.net/docs/package_reference/sentence_transformer/model.html). |

Workbook writes also use temporary files and atomic replacement so an interrupted save does not replace
an existing valid workbook with an incomplete one. Spreadsheet safety escaping is documented for operators.

## Review coverage

| Area | Review focus |
|---|---|
| API and accounts | Same-origin writes, approved profiles, run ownership/grants, read/edit/admin boundaries, upload paths and limits, identity attribution, optimistic review revisions, export and import permissions, optional Supabase password authentication. |
| Storage and collaboration | Locked SQLite access, nested transactions, additive schema initialization, append-only review history, approval invalidation, independent copies, action-item scope and verification, saved-run reproducibility. |
| Ingestion | BOM PDF/table parsing, workbook detection, labels, drawings, PCO forms, OCR fallback/corrections, quantities, evidence geometry/hashes, grouping and extraction-failure reporting. |
| Matching and checks | Normalization, terminology scopes/anchors, global assignment/ambiguity, fuzzy/numeric guards, optional semantic/AI suggestions, all five check types, structured attributes and assembly allocation. |
| Learning and evaluation | Owner enrollment, immutable SKU/hash partitions, independent verification, source/review validation, corrected/negative pairs, candidate-only rules, frozen datasets, held-out metrics, false clears, restart recovery and stale-report detection. |
| Reporting and CLI | Workbook/import behavior, literal text, approval history, certificates and annotated BOMs, diffs/business estimates, operator commands, synthetic dataset/accuracy harness and real-source validation scripts. |
| UI | Routing/session guards, API error handling, asynchronous state, review queue/evidence/decisions, account/sharing controls, terminology import, closed-testing dashboard and ground-truth form. |
| Delivery | CI jobs, Python package metadata, UI lockfile, Dockerfile, Render manifest, single-worker entry point and persistent workspace requirements. |

## Verification

- Ruff checks pass across `src` and `tests`.
- The full Python unit, integration and golden suite passes all 742 collected tests. The final HTTP
  regression run passes all nine learning API tests, including an additional unchanged-approval invariant.
- All 55 UI tests pass; TypeScript checking and the Vite production build pass.
- The synthetic golden accuracy gate passes at `--fail-under 1.0`: 1,049 scored rows, 30 true positives,
  zero false positives, zero false negatives, no false-missing violations. These figures describe the
  synthetic fixture set, not real tester accuracy.
- `npm audit` reports zero known vulnerabilities in the UI lockfile. `pip-audit` reports zero known
  vulnerabilities for the 50 packages installed in the review environment. Future unconstrained Python
  dependency resolution and the deployed image were not audited by these checks.
- The closed-testing synthetic browser flow was exercised while implementing the feature: annotation,
  independent verification and automatic candidate reporting. No real tester ground truth was created.
- Git whitespace checks pass. Generated test workspaces and audit outputs are excluded from the commit.

Two upstream test-client deprecation warnings and Vite's current bundle-size warning remain non-failing.

## Remaining release limits

- Real-data pairing/discrepancy accuracy remains unmeasured until reviewers supply verified labels.
  The authorized terminology export and correct released drawings still need to come from source owners.
  Four SKUs provide an initial closed test; generalization requires more untouched, varied SKU sets.
- Candidate improvements are stored separately. Passing the held-out gate does not automatically promote
  rules into the live matcher and does not constitute external model fine-tuning.
- Deploy one instance/worker with the persistent workspace and consistent backups. Shared-database/object
  storage migration is required before horizontal scaling; no multi-instance load test was performed.
- Administrator approval limits account access but does not prove email ownership. Sessions persist
  until sign-out/revocation; company SSO and an expiry policy remain broader-deployment improvements.
- Report/PDF download routes still reuse run output paths. Atomic XLSX writes prevent partial saved files,
  but concurrent download generation/streaming was not load-tested; request-specific artifacts would
  further isolate exports at higher usage.

See [closed-testing instructions](closed-testing.md), [hosted deployment](hosted-collaboration.md) and
[known limitations](known-limitations.md) for the operating workflow.
