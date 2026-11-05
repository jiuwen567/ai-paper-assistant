import type { Citation } from "./reading";
export const reviewCategories = { evidence_missing: "证据缺口", overclaim: "结论越界", contradiction: "前后矛盾", citation: "引用问题", other: "其他核对项" } as const;
export const decisionLabels = { pending: "待核对", confirmed: "作者确认", ignored: "已忽略" } as const;
export const supportLabels = { contradicts: "依据与表述矛盾（待核对）", insufficient: "现有依据不足", uncertain: "支持关系不确定" } as const;
export type SourceCheck = { version_id: string; file_name: string; title: string; source_number: number; material_exists: boolean; bibliography_registered: boolean; publication_status: "unverified"; source_scope: string };
export type ReviewRecord = {
  id: string; job_id: string; manuscript_version: number; block_ids: string[]; version_ids: string[];
  question: string; summary: string; source_checks: SourceCheck[]; input_changed: boolean;
  findings_count: number; research_limited: boolean; previous_review_id: string | null;
  recheck_tasks: { id: string; status: string; output: { review_id?: string } | null }[];
};
export type ManuscriptQuote = { block_version_id: string; block_id: string; quote: string; start: number; end: number };
export type ReviewFinding = {
  id: string; category: keyof typeof reviewCategories; status: keyof typeof decisionLabels; revision: number;
  model_output: ManuscriptQuote & { support: keyof typeof supportLabels; reason: string; action: string; citations: Citation[]; related_blocks: ManuscriptQuote[]; research_evidence: { field: "question" | "method" | "result"; quote: string }[] };
  manuscript_text: string; manuscript_version: number;
  author_decision: { number: number; status: keyof typeof decisionLabels; reason: string; created_by: number; created_at: string } | null;
};
