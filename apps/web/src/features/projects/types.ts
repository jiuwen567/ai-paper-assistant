export const aiActions = {
  reading: "文献阅读",
  comparison: "文献比较",
  review: "原稿诊断",
  expression: "表达建议",
  feedback: "反馈拆解",
} as const;
export type AIAction = keyof typeof aiActions;
export type Policy = {
  id: number;
  version: number;
  source: string;
  source_version: string;
  notes: string;
  verified: boolean;
  allowed_actions: AIAction[];
  created_by: string;
  created_at: string;
};
export type ProjectFields = {
  name: string; paper_type: string; requirements: string; template: string;
};
export type Project = ProjectFields & {
  id: string;
  version: number;
  role: "author" | "reviewer";
  is_owner: boolean;
  owner_name: string;
  policy: Policy;
};
export type Member = { user_id: number; username: string; role: "author" | "reviewer" };
