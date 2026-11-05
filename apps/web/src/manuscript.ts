export type Block = { id: string; text: string; heading_level: number; version_id?: string; number?: number };
export type Research = { question: string; method: string; result: string };
export const researchLabels = { question: "研究问题", method: "研究方法", result: "研究结果" } as const;
export type Manuscript = {
  version: number; current_version: number; research: Research; blocks: Block[];
  origin: "edit" | "import" | "restore"; source: { file_name?: string; warnings?: string[]; from_version?: number };
  created_at: string | null; created_by: number | null;
};
export type Revision = Pick<Manuscript, "version" | "origin" | "source" | "created_at" | "created_by">;
export type ImportSource = { id: string; file_name: string; source_number: number; number: number; coverage: string; warnings: string[] };
export type ImportPreview = { token: string; source: { parse_id: string; file_name: string; warnings: string[]; coverage: string }; blocks: Block[] };
export type ManuscriptDiff = {
  before: number; after: number;
  research: Partial<Record<keyof Research, { before: string; after: string }>>;
  blocks: { id: string; kinds: string[]; before: Block | null; after: Block | null; before_position: number | null; after_position: number | null }[];
};
export const editableBlocks = (blocks: Block[]) => blocks.map(({ id, text, heading_level }) => ({ id, text, heading_level }));
