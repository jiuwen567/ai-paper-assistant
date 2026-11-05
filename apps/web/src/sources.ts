export type Anchor = { kind: string; page?: number; page_label?: string; paragraph?: number; record?: number; line?: number };
export type Chunk = { id: string; ordinal: number; text: string; anchor: Anchor; heading_level: number };
export type SourceLocation = { chunk: Chunk; context: Chunk[]; source_version: { id: string; number: number; file_name: string }; download_url: string; preview_url: string | null };
export const anchorLabel = (a: Anchor) => a.kind === "pdf" ? `文件第 ${a.page} 页（页码标签 ${a.page_label}）` : a.kind === "docx" ? `第 ${a.paragraph} 段` : a.kind === "csv" ? `第 ${a.record} 条记录` : `第 ${a.line} 行`;
export const scopeLabels: Record<string, string> = { unknown: "范围未核对", abstract: "仅摘要", full_text: "全文（作者标记）", research: "研究记录" };
