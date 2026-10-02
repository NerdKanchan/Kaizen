import type { CheckResultFull, Classification } from "./types";

export interface AttributeLabel {
  component_type: string | null;
  dimensions_mm: number[];
  gauge: number | null;
  concentration_pct: number | null;
  pack_quantity: number | null;
}
export type Verdict = "CORRECT_PAIR" | "INCORRECT_PAIR" | "GENUINE_DISCREPANCY" | "UNRESOLVED";
export interface GroundTruthBody {
  expected_version: number;
  review_revision: number;
  verdict: Verdict;
  classification: Classification;
  expected_a_ids: string[];
  expected_b_ids: string[];
  discrepancies: string[];
  attributes: Record<string, AttributeLabel>;
  assembly_quantities: Record<string, number>;
  note: string;
}
export interface Annotation {
  run_id: string;
  row_id: string;
  version: number;
  status: "pending" | "approved" | "rejected";
  annotated_by: string;
  annotated_at: string;
  approved_by: string;
  payload: GroundTruthBody & {sku: string; engine: CheckResultFull};
  eligible?: boolean;
  eligibility_note?: string;
  split?: "train" | "evaluation";
}
export interface LearningOption {
  id: string;
  doc_id: string;
  description: string;
  item_number: string | null;
  quantity: string | null;
  page: number | null;
  suggested_attributes: AttributeLabel;
}
export interface LearningRow {
  enabled: boolean;
  split: "train" | "evaluation" | null;
  annotation: Annotation | null;
  a_options: LearningOption[];
  b_options: LearningOption[];
}
export interface DrawingBody {
  expected_version: number;
  doc_id: string;
  applicability: "CONFIRMED_RELEASED" | "NOT_APPLICABLE" | "UNCONFIRMED";
  released_revision: string;
  release_reference: string;
  note: string;
}
export interface DrawingAnnotation {
  version: number;
  status: "pending" | "approved" | "rejected";
  annotated_by: string;
  payload: DrawingBody;
}
export interface LearningGroup {
  sku: string;
  split: "train" | "evaluation" | null;
  total_rows: number;
  reviewed_rows: number;
  annotated_rows: number;
  verified_rows: number;
  drawing: DrawingAnnotation | null;
  drawing_options: {id: string; number: string | null; revision: string | null; file_name: string}[];
}
export interface LearningMetrics {
  scored_samples: number;
  pairing_accuracy: number | null;
  classification_accuracy: number | null;
  discrepancy_precision: number | null;
  discrepancy_recall: number | null;
  false_clears: number;
  false_clear_rate: number | null;
}
export interface LearningReport {
  id: string;
  created_at: string;
  training_samples: number;
  evaluation_dataset_version: string;
  baseline: LearningMetrics;
  candidate: LearningMetrics;
  gate_passed: boolean;
  gate_reasons: string[];
  scope_note: string;
  stale?: boolean;
}
export interface LearningSummary {
  automatic_learning?: {state: "idle" | "queued" | "running" | "complete" | "failed"; error: string | null};
  enabled: boolean;
  review_events: number;
  groups: LearningGroup[];
  labels: Annotation[];
  counts: {annotated: number; pending: number; verified_train: number; verified_evaluation: number};
  tasks: {row_id: string; sku: string; check: string; classification: Classification; auto_cleared: boolean; description: string}[];
  latest_evaluation: LearningReport | null;
}

export const VERDICTS: [Verdict, string][] = [["UNRESOLVED", "Unresolved — more evidence needed"], ["CORRECT_PAIR", "Correct pairing"], ["INCORRECT_PAIR", "Incorrect pairing — select correction"], ["GENUINE_DISCREPANCY", "Genuine discrepancy"]];
