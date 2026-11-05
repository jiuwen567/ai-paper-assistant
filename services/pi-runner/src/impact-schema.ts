import { Type } from "typebox";

export function impactSchema(blockIds: string[]) { return Type.Object({
  summary: Type.String({ minLength: 1, maxLength: 1000 }),
  candidates: Type.Array(Type.Object({
    block_version_id: Type.Union(blockIds.map(id => Type.Literal(id)), { description: "仅选择 read_impact.blocks 中尚未登记的原稿位置，不填材料片段编号" }),
    body_quote: Type.String({ minLength: 1, maxLength: 2000, description: "逐字引用所选正文块的 text，不填材料内容" }),
    reason: Type.String({ minLength: 1, maxLength: 2000 }),
    basis: Type.Union([Type.Literal("old"), Type.Literal("new"), Type.Literal("note")]),
    chunk_id: Type.Union([Type.String({ format: "uuid" }), Type.Null()]),
    change_quote: Type.String({ minLength: 1, maxLength: 2000 }),
  }, { additionalProperties: false }), { maxItems: 10 }),
}, { additionalProperties: false });

}
