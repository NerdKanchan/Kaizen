# Closed testing and continuous learning

Closed testing collects evidence while testers do their normal review. It does not assume that accepting
a recommendation makes it correct. Review decisions, changes, approvals and plausible review timing are
already recorded. The new **Ground truth** form captures the true counterpart, genuine discrepancies,
structured attributes and assembly quantities; another application administrator verifies that evidence.

## Start the test

1. Upload the four SKU sets into one run and share Edit access with the testers and verifying administrator.
2. The owner opens **Closed testing** and selects **Enable closed testing** before anyone creates learned
   terminology from these examples. The first four distinct SKU identities reserve one SKU for evaluation.
3. Confirm the correct released drawing for each SKU using the drawing selector, released revision, release
   record reference and evidence note. A different administrator verifies the applicability record. If the
   supplied drawing does not apply, record that and upload a new run with the correct released drawing.
4. Testers inspect the documents, save their normal decisions, and annotate component rows. Start with the
   balanced worklist on Closed testing: it includes all SKUs and available checks, both flagged and
   auto-cleared rows. Keep unresolved cases explicit until the source owner supplies evidence.
5. The administrator inspects each saved annotation and verifies or rejects it. An administrator who wrote
   an annotation needs another administrator to verify it. Existing review self-approval remains separate
   from independent verification of ground truth.

## What testers should record

| Priority | Tester action | Collected evidence |
|---|---|---|
| Real ground truth | Identify correct pairings, correct wrong or missing counterparts, and name genuine discrepancy types. | Expected source IDs and complete item evidence, engine output, SKU/check, source document hashes, reviewer identity, version, timestamps and reason. |
| Terminology | Verify repeated wording; administrators approve training-SKU worklist pairs or import a readable authorized workbook export through Terminology. | Versioned synonyms, document types, provenance and rule usage. Held-out SKUs are excluded from worklist learning and saving a relationship from a row. |
| Attributes | Check component type, dimensions in mm, gauge, concentration in percent and pack quantity against each source. | Explicit verified values separate from suggestions. Empty means unspecified or unreadable. |
| Assemblies | Select several active physical BOM components and one label entry; allocate each member's quantity per label unit. | Source membership, item numbers, descriptions and positive quantity allocations. |
| Drawing applicability | Confirm the actual released file and revision for the SKU, with a release record reference. | Versioned file identity/hash, applicability, release revision/reference, author and independent verifier. |

Pairing annotations currently cover component rows in BOM–Label, BOM–Drawing and Label–Drawing checks.
PCO, revision, header and exempt rows retain normal review history; extending their curated ground-truth
schema requires representative source documents. Reviewer notes are not automatically transformed into facts.

## What happens automatically

Verification queues an offline candidate rebuild. The durable SQLite job coalesces additional approvals
that arrive during a rebuild, runs again on the latest verified examples, and resumes queued/running work
after an application restart. Failures appear in Closed testing and can be retried with **Rebuild and
evaluate**. Replacing an approved annotation or changing its review decision removes the old label from
eligible data and schedules another rebuild. A normal approval of the unchanged decision keeps the label valid.

The candidate learns explainable terminology rules from verified positive pairings, negative pair rules
from verified incorrect pairings, reusable corrected attribute patterns and approved assembly membership.
A quantity discrepancy can still establish component identity; quantity checking remains independent.
Structured extraction adds conservative proposals for short descriptions such as Mask, compares explicit
dimensions across units, and guards against incompatible gauge, concentration, component type and pack
quantity. Approximate dimensional equivalents remain review-required. Conflicting attribute patterns
are not reused. Assemblies check each member's allocation and flag missing, changed or wrongly quantified members.

Candidate changes are saved separately and evaluated against the original run on identical parsed sources.
They do not change live recommendations, reviewer decisions or shared terminology. This is local rule
learning, not fine-tuning an external language model. No source descriptions or documents are sent to an
external training service by this workflow.

## Dataset protection and measurement

SKU assignments are immutable in the workspace. Numeric identity variants, repeated uploads and copies
keep their assignment. Identical BOM/label content cannot cross training/evaluation splits, even under a
renamed SKU. Shared packaging drawings are governed by per-SKU applicability; they are not an independent
held-out document corpus. A first run with just one SKU has training data only; accuracy is unmeasured until
another distinct SKU is reserved. With small deliveries, the 20% allocation is rounded up. Enable testing
before learned terminology is created, and keep the same workspace across deployments.

Only the latest independently verified annotation is eligible. Unresolved, rejected, stale and unverified
records stay out of both datasets. Drawing examples also require independently verified released
applicability to the exact document being compared. Duplicate true pair corrections are counted once;
conflicting labels are excluded and prevent passing the sample evaluation gate.

The dashboard reports the number of scored samples, pairing/classification accuracy, discrepancy
precision/recall, false-clear counts/rate and results by SKU/check in the saved report. A false clear means
an automatically cleared result whose pairing is wrong or whose verified truth contains a discrepancy.
Metrics without a denominator show **Not measured**, not a perfect score. Training-fit measurements are
labelled separately and are not held-out accuracy.

The initial sample gate requires at least 20 independently verified held-out examples, available check
coverage, genuine discrepancies and some originally auto-cleared rows, zero candidate false clears and
no aggregate or SKU/check pairing/classification regression or aggregate discrepancy regression. Passing
this small-sample gate does not promote the candidate or establish product-wide accuracy. Before shipping
an improved matcher, inspect the saved failures, broaden representative evaluation coverage, run the golden
and real-data regressions, and make an explicit reviewed code/rule release. Authorized external terminology
imports may change candidate results; the baseline and candidate terminology versions are both retained.

## Exports and deployment

Administrators with Edit access can download separate **Training dataset**, **Evaluation dataset**, and
**Raw observations** JSON files. Never concatenate evaluation samples into training data. Raw observations
include normal decision histories and timing and are not ground truth. Training exports are also suitable
as input to a future locally managed embedding/ranking model; external model training is not configured.

Each evaluation writes frozen `train.json`, `evaluation.json`, `candidate.json`, `candidate-config.json`,
`assemblies.json` and `report.json` under the workspace's `runs/<run-id>/learning/<evaluation-id>/` folder.
Datasets have content versions; configurations include the terminology snapshot, structured matching,
negative pairs, attribute overrides and assembly rules. Annotation versions remain in SQLite.

The existing hosted deployment uses one server worker and a persistent disk. Back up the full workspace,
including `kaizen.db`, source files and candidate artifacts. The new tables are created idempotently when
the workspace opens. Closed testing is disabled per run until its owner enables it. Learning artifacts stay
in the workspace and its backups; an administrator exports them explicitly. Retention and deletion remain
operator-managed through workspace backups/storage; there is no new automatic deletion policy.
