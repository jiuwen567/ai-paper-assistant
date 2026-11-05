import { Type } from "typebox";

export function impactSchema(blockIds: string[]) {
  const fields = {
    block_version_id: Type.Union(blockIds.map(id => Type.Literal(id)), { description: "仅选择 read_impact.blocks 中尚未登记的原稿位置，不填材料片段编号" }),
    body_quote: Type.String({ minLength: 1, maxLength: 2000, description: "仅逐字引用 blocks.text 中实际使用变更事实的主张，不填材料内容或无关陈述" }),
    reason: Type.String({ minLength: 1, maxLength: 2000, description: "说明正文实际使用了哪项变更事实；不因主题相近就推测关联或补造交互关系" }),
    change_quote: Type.String({ minLength: 1, maxLength: 2000 }),
  };
  return Type.Object({
    candidates: Type.Array(Type.Union([
      Type.Object({
        ...fields,
        basis: Type.Union([Type.Literal("old"), Type.Literal("new")]),
        chunk_id: Type.String({ format: "uuid", description: "必须复制同一 side 的 sources.chunk_id，不能为 null" }),
      }, { additionalProperties: false }),
      Type.Object({
        ...fields,
        basis: Type.Literal("note"),
        chunk_id: Type.Null({ description: "仅 basis=note 才用 null，change_quote 须来自 change.note" }),
      }, { additionalProperties: false }),
    ]), { maxItems: 10 }),
  }, { additionalProperties: false });
}
