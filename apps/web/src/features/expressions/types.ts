import type { Citation } from "@/features/reading/types";
export type DiffPart = { kind: "equal" | "replace" | "insert" | "delete"; before: string; after: string };
export type Suggestion = {
  id: string; job_id: string; manuscript_version: number; manuscript_text: string; input_changed: boolean;
  model_output: { block_version_id: string; block_id: string; quote: string; start: number; end: number;
    replacement: string; reason: string; kind: "expression" | "substantive"; guard_reasons: string[]; citations: Citation[] };
  diff: DiffPart[];
  decision: { action: "accepted" | "edited" | "rejected"; text: string; reason: string; meaning_confirmed: boolean; policy_version: number; manuscript_version: number | null; created_by: number; created_at: string } | null;
};
export const decisionLabels = { accepted: "已接受", edited: "编辑后接受", rejected: "已拒绝" } as const;
