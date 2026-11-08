export type ExternalUse = { tool: string; purpose: string; scope: string; used_at: string; note: string };
export type DisclosureRevision = {
  number: number; text: string; external_uses: ExternalUse[]; verified: boolean;
  facts_token: string; created_by: number; created_at: string;
};
export type Counts = Record<"tasks" | "calls" | "successful_calls" | "published_tasks" | "reading_records" | "review_findings" | "expression_suggestions" | "notes" | "accepted" | "rejected" | "feedback_candidates" | "confirmed_tasks" | "completed_tasks" | "impact_candidates", number>;
export type DisclosureState = {
  summary: Counts; purposes: Record<string, Counts>; manuscript_version: number;
  facts_token: string; draft: string; current: DisclosureRevision | null; stale: boolean;
};
export type Usage = {
  id: string; kind: string; purpose: string; status: string; created_at: string; policy_version: number;
  model: { model?: string; runtime?: string; prompt_version?: string };
  embedding: { model_name?: string; runtime?: string; pipeline_version?: string };
  input: { impact_run_id: string | null; feedback_id: string | null; feedback_source_chunk_id: string | null; version_ids: string[]; source_count: number; manuscript_version: number | null; blocks: { block_id: string; version_id: string; position: number }[] };
  calls: { generation: number; number: number; model: string; prompt_version: string; status: string; usage: Record<string, number> | null; elapsed_ms: number | null; started_at: string; error_code: string }[];
  reading: { id: string; author_revision: number } | null;
  review: { id: string; findings: { id: string; status: string; revision: number }[] } | null;
  suggestions: { id: string; manuscript_version: number; decision: { action: "accepted" | "edited" | "rejected"; manuscript_version: number | null } | null }[];
  impact_candidates: { id: string; run_id: string; block_version_id: string; decisions: { number: number; state: string; created_by: number }[] }[];
  notes: number;
  feedback_candidates: { id: string; decision: string | null; task_id: string | null; task_version: number | null; status: string | null }[];
  sources?: { chunk_id?: string; id?: string; source_version_id?: string; source_scope?: string }[];
};
export const purposeLabels: Record<string, string> = { impact: "材料变更补查", note: "阅读摘记", reading: "文献阅读", comparison: "文献比较", review: "原稿诊断", expression: "表达建议", feedback: "反馈拆分", index: "向量索引" };
export const statusLabels: Record<string, string> = { queued: "等待执行", running: "执行中", succeeded: "成功", failed: "失败", cancelled: "已取消" };
