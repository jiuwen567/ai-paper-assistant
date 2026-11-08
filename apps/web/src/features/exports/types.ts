import type { Block } from "@/features/manuscripts/types";
import type { DisclosureRevision } from "@/features/disclosures/types";
export type ExportTemplate = { id: string; code: string; number: number; name: string; source_label: string; rights_note: string; digest: string; layout: Record<string, unknown> };
export type ExportContent = {
  title: string; author: string; manuscript_version: number; template: ExportTemplate;
  blocks: (Block & { caption: { kind: "figure" | "table"; number: number } | null; references: { number: number }[] })[];
  references: { number: number; text: string; bibliography_number: number; bibliography_revision_id: string | null }[];
  disclosure: DisclosureRevision; warnings: string[];
};
export type ExportRecord = {
  id: string; title: string; created_at: string; manuscript_version: number; disclosure_version: number;
  template: ExportTemplate; digest: string; renderer_version: string; downloadable: boolean; sources_changed: boolean;
  file: { id: number; sha256: string; size: number } | null;
  job: { id: string; status: string; generation: number; retryable: boolean; error_code: string; error_message: string; progress: number };
  content?: ExportContent;
  downloads?: { id: number; file_id: number; created_by_id: number; created_at: string }[];
};
