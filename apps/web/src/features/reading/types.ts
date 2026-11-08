export const readingFields = {
  subject: "研究对象", method: "方法", result: "结果", limitations: "局限",
  conditions: "实验条件", applicability: "适用范围",
};
export type ReadingField = keyof typeof readingFields;
export type Citation = { chunk_id: string; quote: string; source_version_id: string };
export type ReadingDocument = {
  version_id: string; title: string; file_name: string; source_number: number; source_scope: string;
  fields: Record<ReadingField, { status: string; text: string; citations: Citation[] }>;
};
export type ReadingRecord = {
  id: string; job_id: string; purpose: string; question: string; revision: number; sources_changed: boolean;
  model_output: { documents: ReadingDocument[]; comparison: { status: string; reason: string; citations: Citation[] } | null };
  author_revision: { number: number; edits: { version_id: string; field: ReadingField; text: string }[]; note: string; verified: boolean } | null;
};
