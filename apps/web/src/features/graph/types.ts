import type { FeedbackLocation } from "@/features/feedback/types";
import type { Anchor } from "@/features/materials/types";
export type EvidenceLink = {
  id: string; claim: string; evidence_quote: string; chunk_id: string; location: FeedbackLocation;
  source_available: boolean; needs_review: boolean; current: LinkDecision;
};
export type LinkDecision = { number: number; state: "confirmed" | "withdrawn"; kind: string; note: string; created_by: number; created_at: string };
export type GraphPath = {
  id: string; origin: "author" | "model" | "citation"; kind: string; state: string; claim: string;
  evidence_quote: string; location: FeedbackLocation; chunk_id: string; material_id: string;
  material_title: string; source_number: number; source_version_id: string; parse_id: string; anchor: Anchor;
  link_id?: string; finding_id?: string; finding_status?: string; model_support?: string;
  citation_id?: string; decision_version?: number; needs_review?: boolean;
};
export type GraphResult = {
  revision: number; applied_revision: number; projected_revision?: number | null; pending_events: number;
  error_code: string; status: "synced" | "pending" | "missing" | "unavailable" | "inconsistent";
  count: number | null; results: GraphPath[]; page: number; next: boolean; previous: boolean;
};
export const graphLabels = { synced: "依据关系已同步", pending: "依据关系同步中，暂不显示旧路径", missing: "依据关系投影尚未建立或已丢失，请等待同步或重建", unavailable: "依据关系暂时无法查询，请稍后重试", inconsistent: "依据关系投影与业务记录不一致，请重建后重试" };
export const relationLabels: Record<string, string> = { supports: "支持", contradicts: "矛盾", context: "背景材料", diagnostic: "诊断依据", cites: "正文引用" };
export const linkStateLabels: Record<string, string> = { confirmed: "作者已核对", withdrawn: "作者已撤回", needs_review: "需要重新核对", candidate: "模型候选", citation: "作者采纳时保存的引用" };
