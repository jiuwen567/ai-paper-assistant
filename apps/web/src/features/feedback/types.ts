export type FeedbackLocation = {
  manuscript_version: number; block_id: string; block_version_id: string; position: number; text: string;
  stale: boolean; current_version: number; current_position: number | null;
};
export type Feedback = { id: string; text: string; source_label: string; source_chunk_id: string | null;
  location: FeedbackLocation | null; recording: "author_transcription"; created_by: number; created_at: string };
export type FeedbackCandidate = { id: string; feedback_id: string; job_id: string; input_changed: boolean;
  model_output: { title: string; instruction: string; quote: string; start: number; end: number };
  decision: { action: "accepted" | "rejected"; reason: string; task_id: string | null } | null };
export type MentorReport = { id: number; task_version: number; status: "confirmed" | "changes_requested"; text: string; source_label: string; recording: "author_transcription"; created_by: number; created_at: string };
export type TaskProgress = { number: number; title: string; instruction: string; status: "todo" | "doing" | "completed" | "dropped";
  note: string; result_kind: "pending" | "modified" | "no_change"; location: FeedbackLocation | null;
  mentor_reports: MentorReport[]; created_by: number; created_at: string };
export type FeedbackTask = { id: string; feedback_id: string; candidate_id: string | null; current: TaskProgress; original_location: FeedbackLocation | null };
export const progressLabels = { todo: "待处理", doing: "处理中", completed: "作者已完成", dropped: "不再处理" };
export const mentorLabels = { confirmed: "确认本次处理", changes_requested: "仍需修改" };
