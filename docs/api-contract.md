# Kaizen Cross-Check — local API contract (for the reviewer UI)

Base URL when running `kaizen serve`: `http://127.0.0.1:8765`. All endpoints are local. JSON unless stated.
Errors: 400 (invalid input), 401 (no approved review session, or bad credentials), 403 (insufficient
permission), 404 (unknown or inaccessible id), 409 (account exists or stale review revision),
422 (malformed request), 429 (rate limited), 500 (unexpected error, with a server-log reference),
503 (account provider unavailable).

The current HTTP interface uses one shared decision per row and explicit approval. The legacy
two-reviewer CLI store is separate. `/api/health` reports `api_contract: 3` and `restart_required`;
the UI requires a matching contract and a server running the current source.

## Signing in (email and password)
A session can only be opened by someone holding an account on an allowed email address. Reviewers sign
themselves up. Accounts live in one of two places (see `kaizen auth show`):

- **local** (default, works offline): in the workspace database, passwords as salted scrypt.
- **Supabase**: in a Supabase project, so one account works on every laptop. Only the email and password
  go to Supabase; the session, slot, blind mode and all review data stay in the local workspace. No email
  is sent (BD mail blocks external senders), so the project runs with "Confirm email" off.

| Method | Path | Body | Returns |
|---|---|---|---|
| POST | `/api/auth/signup` | `{email, password}` | Account registration with `status: "pending"`; administrator approval is required. |
| POST | `/api/auth/signin` | `{email, password}` | `{reviewer, slot:1, blind:false, is_admin, created_at, blind_review_policy}` + `Set-Cookie` |

If the Supabase project still has "Confirm email" on, sign-up is **503** with an explanation (the
confirmation email would never arrive), and an account created that way signs in with **403** until an
admin confirms it in the dashboard.

The address must end in a whole allowed domain — `bd.com` by default, so `user@gmail.com` and
`user@bd.com.evil.io` are both **400** `Only BD email addresses can sign in.` A password shorter than 10
characters is **400**; an address that already has an account is **409**.

Sign-in returns **401** `That email address and password do not match an account.` for both a wrong
password and an unknown address — the difference would report which BD addresses have accounts here.
With local accounts, after 10 consecutive failures the account is refused with **429** for 15 minutes;
the lockout expires on its own, so nobody has to unlock it. With Supabase, its own rate limits apply
(also **429**). The verified address becomes the reviewer's identity: it is what
decisions, exports, certificates and the audit trail are recorded against.

### Forgotten passwords
There is no reset email. With Supabase accounts the admin sets a new password in the Supabase dashboard
(README, "Forgotten passwords") and tells the reviewer. With local accounts an administrator clears the
account from the command line and the reviewer signs up again with a password of their own choosing:

```
kaizen users list
kaizen users reset dharma.reddy@bd.com
```

Clearing an account does not touch decisions already recorded: those carry the address, not a row in the
accounts table.

### Environment
| Variable | Purpose |
|---|---|
| `KAIZEN_ALLOWED_DOMAINS` | Comma-separated domains that may sign in. Default `bd.com`. |
| `KAIZEN_SUPABASE_URL`, `KAIZEN_SUPABASE_KEY` | Check accounts with this Supabase project (anon / publishable key only). Overrides `kaizen auth supabase`. Set both or neither. |

## Reviewer sessions
Reviewer identity, slot and blind mode are held by the server, not by the client. The session token is
returned in an HttpOnly cookie (`kaizen_session`), so page scripts cannot read or forge it, and the
`viewer` / `blind` query parameters below are **ignored whenever a session is present**.

| Method | Path | Body | Returns |
|---|---|---|---|
| POST | `/api/sessions` | | **403** `Use /api/auth/signin`. Superseded by the sign-in flow above; there is no bypass. |
| GET | `/api/sessions/current` | | `{session: {...}\|null, blind_review_policy, accounts: "local"\|"supabase"}` |
| DELETE | `/api/sessions/current` | | `{ended: bool}` and clears the cookie |

HTTP sessions use `slot: 1` and `blind: false`; changes and approvals are shared with collaborators
who have access to the run. Accounts require administrator approval. Run creation and every run-data
endpoint require an approved session. Health is public. Owners can share a run with edit or view
access; viewers cannot mutate or download review exports. Inaccessible run IDs return 404.

## Runs
| Method | Path | Body / params | Returns |
|---|---|---|---|
| GET | `/api/health` | | `{status, version, api_contract, restart_required, hosted}` |
| GET | `/api/runs` | | Accessible run records with ownership and permissions; `summary` has `rows`, `reviewable_rows`, `skus`, `documents`, original `needs_validation`/`auto_cleared`, flat classification keys over reviewable rows, and live `review_progress`. A missing saved run is marked `unavailable: true`. |
| POST | `/api/runs/from-path` | `{path}` (local folder) | run summary (below) |
| POST | `/api/runs/upload` | multipart `files[]`; each filename may include a relative path such as `sku-001/bom.pdf` (use `webkitRelativePath` for folder drops) | run summary |
| POST | `/api/demo/load` | | run summary (golden dataset) |
| GET | `/api/runs/{run_id}` | | run summary |

Run summary: `{run_id, timestamp, input_root, tool_version, skus, documents, documents_by_type:{BOM,LABEL,DRAWING,PCO}, unrecognised_files[], rows (all result rows), reviewable_rows (roles item + change), exempt_rows, header_rows_needing_validation (header/reference/coverage rows that need validation, e.g. REF mismatch or missing BOM), counts:{EXACT,EQUIVALENT,POTENTIAL,MISMATCH,MISSING} (reviewable rows), needs_validation and auto_cleared (original engine counts over reviewable rows), per_check:{BOM_LABEL,BOM_DRAWING,LABEL_DRAWING,PCO_BOM,LABEL_REVISION}, blockers, coverage:[{kind, sku, status: OK|MISSING_BOM|MISSING_LABEL, detail, source}], groups:[{sku, family, document_ids[], warnings[]}], warnings[], parser_warnings:[{document, doc_id, warnings[]}], low_confidence_rows, state_counts:{ENGINE_RECOMMENDED, REVIEWED, FINALIZED}, review_progress, terminology_version, terminology_count, relationships_used[], capabilities:{name: status}, thresholds, inputs:[{path, sha256, size_bytes, doc_type}]}`

`review_progress` is computed from a single current decision/approval snapshot across every result row:
`{pending, awaiting_review, awaiting_approval, approved, needs_information, unresolved_rows,
confirmed_discrepancies, blockers, low_confidence_rows, discrepancies:[{type, count, severity}]}`.
The discrepancy aggregation counts distinct rows per type, without a page limit. `state_counts`
counts the same snapshot. Original engine counts and evidence remain unchanged by review.

A saved decision awaits approval, including a decision on an originally clean row. An approved
Exact/Equivalent acceptance or override clears its current finding. Approving a confirmed discrepancy
completes review while retaining the finding. Needs-more-information decisions stay pending even
when approved. Editing an approved row reopens review.

## Results (review queue)
`GET /api/runs/{run_id}/results` params: `check` (BOM_LABEL|BOM_DRAWING|LABEL_DRAWING|PCO_BOM|LABEL_REVISION), `sku`, `classification` (current effective classification), `engine_classification` (original EXACT|EQUIVALENT|POTENTIAL|MISMATCH|MISSING), `unresolved` (true/false), `severity` (BLOCKER|MAJOR|MINOR|INFO), `discrepancy` (type name), `needs_validation` (true/false), `state`, `role` (item|header|reference|coverage|exempt|change), `search`, `limit` (default 500), `offset`. (`viewer` and `blind` are still accepted but ignored when a session is present.)
`needs_validation` filters current `pending_review`, and `severity` filters `current_severity`. With `unresolved=true`, `discrepancy` filters current findings; otherwise it filters original evidence. The UI defaults to pending rows; `nv=0` removes that filter.
Default order: blocker → major → ambiguous → potential → low-confidence → sku → row id.
Returns `{total, offset, limit, rows:[{row_id, sku, check, role, engine:{classification, match_level, score, relationship_id, requires_validation, severity, discrepancies[], explanation}, decisions:{"1": Decision|null, "2": Decision|null}, state, final, effective_classification, pending_review, unresolved, current_severity, current_discrepancies, a:{item_number, description, quantity, page, locator, file_name}|null, b:{...}|null, discrepancies:[{type, severity, detail, recommended_action}], action_items[]}]}`.
Also returns `viewer: {slot, blind, reviewer}` — the visibility actually applied.
Decision: `{slot, reviewer, decision, comment, override_classification, decided_at, blind}`.
`effective_classification` includes the saved shared override. Approval is recorded separately in
`final`, including `self_approved`, the approver, timestamp and note.

`GET /api/runs/{run_id}/results/{row_id}` → `{result: full CheckResult (source_a/source_b with evidence), evidence:{a: Evidence|null, b: Evidence|null}, decisions, state, final, effective_classification, revision, owner, permission, history:[{event: engine|change|approval, ...}], viewer, action_items[]}`.
Evidence: `{doc_id, doc_type, file, file_name, sha256, page, bbox:{x0,y0,x1,y1}|null, locator, raw_text, sheet, item_number, description, quantity, uom, oper_seq, category, category_reason, confidence, attributes, sub_quantity}`.

## Documents and evidence images
| GET | `/api/runs/{run_id}/documents` | `[{id, doc_type, file, file_name, sku, sha256, parser, parser_version, items, warnings[], header, pages}]` |
| GET | `/api/runs/{run_id}/documents/{doc_id}/items` | `{doc_id, doc_type, file_name, header, warnings, pages, items:[Evidence + {id, is_active}]}` (extraction verification view) |
| GET | `/api/runs/{run_id}/documents/{doc_id}/pages/{n}?highlight={row_id}&dpi=110` | `image/png` of page n (1-based); with `highlight`, the evidence box of that row on this document is outlined. Bbox coordinates in Evidence are PDF points at 72 dpi; the image is rendered at `dpi`, so scale = dpi/72. 404 for spreadsheet sources. |

## Decisions
| POST | `/api/runs/{run_id}/decisions` | `{row_id, decision: ACCEPT|OVERRIDE|CONFIRM_DISCREPANCY|NEEDS_MORE_INFORMATION, comment?, override_classification? (required for OVERRIDE), expected_revision}` → `{row_id, state, decisions, effective_classification}`. Actor comes from the session. Saving clears any previous approval and preserves its history. |
| POST | `/api/runs/{run_id}/finalize` | `{row_id, final_decision, expected_revision, confirm_self_approval?, note?}` → `{row_id, state}`. Requires a saved decision matching the current revision and kind; approving one's own decision or run requires explicit self-approval confirmation. |
| POST | `/api/runs/{run_id}/bulk-accept` | `{}` → `{accepted}` (only rows with no discrepancy and not needing validation) |
| POST | `/api/runs/{run_id}/relationships/from-row` | `{row_id, scope? (global|family:<prefix>|sku:<code>), anchor? (bind to the BOM item number), canonical?, aliases?, doc_types?, notes?}` → Relationship |

## Terminology worklist
`GET /api/runs/{run_id}/terminology-worklist` → `{needs_validation, potential_rows, items:[Suggestion + {would_clear, still_review, cumulative_clear, cumulative_pct}], top5:{n, rows, pct}, top10:{...}}`.
Unconfirmed fuzzy pairings ranked by the rows they would auto-clear once approved as relationships (rows carrying a discrepancy or an ambiguity are `still_review`). Approval goes through `mining/approve`; nothing is created automatically.

## Review effort (measured)
Opening a row (`GET .../results/{row_id}`) with a session records the time for that reviewer's slot; the next decision on that row by the same slot stores `seconds_spent` (only when the gap is between 5 seconds and 15 minutes; bulk accept and Excel imports are never timed). `GET .../business-case` uses the median of timed decisions once there are at least 10 (`effort_basis: "measured"`, `timed_decisions`, `measured_minutes_per_validation_row`, `minutes_per_validation_row_used`); below that it keeps the brief's assumption and says so.

## Closed testing

All paths below start with `/api/runs/{run_id}/learning`. Existing run permissions apply;
enrollment requires the owner, writes require Edit access, and verification, exports and candidate
evaluation require an application administrator with Edit access. Ground-truth verification requires
a different actor from the annotation author. See [the tester guide](closed-testing.md).

| Method | Suffix | Body / params | Returns |
|---|---|---|---|
| GET | (none) | | Enrollment, immutable SKU splits, annotation/drawing coverage, balanced tasks, latest evaluation and automatic job state. |
| POST | `/enable` | | Enroll the run and reserve evaluation SKU identities before learning. |
| GET | `/rows/{row_id}` | | Current annotation, split, source options, suggested attributes and review revision. |
| PUT | `/rows/{row_id}` | `{expected_version, review_revision, verdict, classification, expected_a_ids[], expected_b_ids[], discrepancies[], attributes, assembly_quantities, note}` | Versioned pending annotation. |
| POST | `/rows/{row_id}/approve` | `{expected_version, approve, note?}` | Verified or rejected annotation; queues an offline candidate rebuild. |
| PUT | `/drawings/{sku}` | `{expected_version, doc_id, applicability, released_revision, release_reference, note}` | Versioned pending applicability record. |
| POST | `/drawings/{sku}/approve` | `{expected_version, approve, note?}` | Verified or rejected applicability; queues a rebuild. |
| GET | `/export.json` | `split=train\|evaluation` | Separate verified dataset with source evidence and configuration metadata. |
| GET | `/observations.json` | | Normal review histories and timing, explicitly labelled as raw observations. |
| POST | `/shadow` | | Rebuild and score a local candidate; returns the frozen evaluation report. |

Verdicts are `CORRECT_PAIR`, `INCORRECT_PAIR`, `GENUINE_DISCREPANCY` or `UNRESOLVED`.
Attributes are keyed by selected source item ID and support `component_type`, `dimensions_mm[]`,
`gauge`, `concentration_pct` and `pack_quantity`. Assembly quantities map BOM item IDs to positive
quantities per label unit. Applicability is `CONFIRMED_RELEASED`, `NOT_APPLICABLE` or `UNCONFIRMED`;
confirmed release requires a revision and release reference. Stale annotation/review versions return 409.
Unresolved, stale and unverified labels are excluded from datasets. Drawing examples require verified
released applicability. Candidate evaluation uses saved parsed sources and never changes live results
or shared terminology. The durable background job resumes after restart; failed jobs can be retried.
Evaluation SKUs are excluded from relationship mining and relationship creation from a row.

## Certificate, run diff, optional Excel round-trip
| Method | Path | Body / params | Returns |
|---|---|---|---|
| GET | `/api/runs/{run_id}/certificate.pdf?sku=` | optional `sku` | One A4 page per SKU (or one SKU): run id, timestamp, terminology version, thresholds, every input file with its SHA-256, counts by classification, blockers, named reviewers with decision counts, finalized and disagreement counts, open action items, statement and signature lines. 403 for a blind session; 404 for an unknown SKU. |
| GET | `/api/runs/{run_id}/diff?against={earlier_run_id}` | | `{before_run_id, after_run_id, skus:{added,removed,common}, documents:{changed:[{path, before_sha256, after_sha256}], added, removed}, counts:{resolved,new,still_open,changed,unchanged,gone,not_covered}, rows:[{key, sku, check, status, before, after, note}]}`. Rows are matched by comparison key; `unchanged` rows are counted, not listed; `gone` means the comparison disappeared, which is not the same as fixed. |
| POST | `/api/runs/{run_id}/decisions/import` | multipart `file` (.xlsx exported by this tool), `dry_run` (default false), `force` (default false) | `RoundTripResult`: `{run_id, slot, reviewer, dry_run, force, exported_at, applied[], unchanged[], conflicts:[{row_id, sheet, workbook, database, database_decided_at, database_reviewer}], invalid:[{row_id, sheet, value, reason}], unknown_rows[], summary}`. Slot and reviewer come from the session. The workbook must carry this run's id (400 otherwise); only the session's own columns are read; a decision changed in the database after `Exported at` is a conflict and is skipped unless `force`. Optional feature. |

## Relationship mining
| GET | `/api/runs/{run_id}/mining?min_skus=2` | `[{a_text, b_text, a_key, b_key, pair_key, sku_count, skus[], check_types[], row_ids[], confirmed, contradicted, item_anchors[], relationship_id, evidence}]` |
| POST | `/api/runs/{run_id}/mining/approve` | `{a_key, b_key, by, scope?, anchor?, notes?}` → Relationship |
| POST | `/api/runs/{run_id}/mining/reject` | `{a_key, b_key, by, note?}` → `{rejected}` |

## Action items, verify & close, business case
| POST | `/api/runs/{run_id}/action-items` | `{row_id, reviewer, owner?}` → ActionItem |
| GET | `/api/action-items?status=&run_id=` | `[ActionItem]` |
| PATCH | `/api/action-items/{id}` | `{status? (OPEN|IN_PROGRESS|RESOLVED|CLOSED|REJECTED), owner?, by, note?}` → ActionItem |
| POST | `/api/runs/{run_id}/verify-and-close` | → `{run_id, resolved[], still_open[], not_covered[]}` |
| GET | `/api/runs/{run_id}/business-case` | params override assumptions: `baseline_minutes_per_sku, hourly_rate, skus_per_project, projects_per_year, reviewers, minutes_per_validation_row, minutes_per_cleared_row, target_reduction_pct` → `{skus, rows, auto_cleared, needs_validation, estimated_minutes_per_sku, minutes_saved_per_sku, reduction_pct, hours_saved_per_project, annual_savings, meets_target, assumptions[], per_sku, confirmable_rows, needs_validation_after_confirmation, estimated_minutes_per_sku_after_confirmation, reduction_pct_after_confirmation, hours_saved_per_project_after_confirmation, annual_savings_after_confirmation, meets_target_after_confirmation}` — the `*_after_confirmation` fields are a labelled projection (strong POTENTIAL pairings confirmed as relationships), not a measurement |

ActionItem: `{id, run_id, row_id, sku, check_type, discrepancy_type, severity, detail, recommended_action, owner, status, reviewer, created_at, updated_at, resolved_in_run, resolved_at, comparison_key}`.

## Exports
| GET | `/api/runs/{run_id}/export.xlsx` | workbook with reviewer decisions merged |
| GET | `/api/runs/{run_id}/annotated-bom/{doc_id}` | PDF; headers `X-Kaizen-Fallback` (true when the BOM had no page geometry) and `X-Kaizen-Marks` |

## Terminology
| GET | `/api/terminology?search=&scope=&all=` | `[Relationship + {usage}]` |
| POST | `/api/terminology` | `{canonical, aliases[], scope, doc_types[], item_anchors[], provenance?, by, notes}` |
| GET | `/api/terminology/{id}` · PUT `/api/terminology/{id}` `{canonical?, aliases?, scope?, doc_types?, item_anchors?, notes?, by, note}` · POST `/{id}/deactivate` `{by}` · POST `/{id}/activate` · DELETE `/{id}?by=` · GET `/{id}/history` |
| GET | `/api/terminology/export.xlsx` | Download the Kaizen column format. |
| POST | `/api/terminology/inspect` | Multipart `file`, optional `sheet`, `header_row` (default 1) → `{sheets[], sheet, header_row, columns[], row_count, sample:[{row, values}], column_map, sha256, header_error}`. Invalid headers still return the worksheet inventory so another table can be selected. |
| POST | `/api/terminology/import` | Multipart `file`, optional `sheet`, `header_row`, `column_map` (JSON object), `default_scope` (default global), `dry_run` (default false), `expected_version` (preview terminology snapshot). Returns `{summary, created, updated, unchanged, errors[], dry_run, applied, rows:[{row, action, id, canonical, aliases[], scope, item_anchors[], doc_types[], active}], source:{file, sha256, sheet, header_row, column_map, terminology_version}}`. |
| GET | `/api/audit?limit=200` | recent audit events |

Relationship: `{id, canonical, aliases[], scope, doc_types[], item_anchors[], provenance (manual|learned|imported), created_by, created_at, updated_at, active, notes, version}`.

Column mapping keys are `ID`, `Canonical`, `Aliases`, `Scope`, `Doc Types`, `Item Anchors`, `Provenance`,
`Created By`, `Active`, and `Notes`; values are source column names or arrays of names. Multiple columns
are supported for Aliases, Doc Types and Item Anchors. With no mapping, Kaizen column names are recognised
case-insensitively. The verified session supplies the author; uploaded `Created By` and form `by` never
override it. These POST endpoints require application administrator access.

Counts describe planned changes when `dry_run=true` or when errors block an import. Any invalid mapped row
blocks the entire import, with `applied=false`. IDs update existing rules and record a new version; no-ID
rows with the same terms, scope, document types and anchors are unchanged, including inactive rules.
Formula cells require a values-only export. Protected Excel containers return an actionable 400.
See [authorized relationship imports](relationship-import.md) for the local export and comparison workflow.
