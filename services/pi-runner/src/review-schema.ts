import { Type } from "typebox";

export function reviewSchema(blockIds: string[]) {
  const quote = {
    block_version_id: Type.Union(blockIds.map(id => Type.Literal(id)), { description: "read_manuscript.blocks 中的 block_version_id" }),
    quote: Type.String({ minLength: 1, maxLength: 1200, description: "仅从该原稿块的 text 逐字复制问题句，不能填文献原文或研究说明" }), occurrence: Type.Integer({ minimum: 1, maximum: 10000 }),
  };
  return Type.Object({
    findings: Type.Array(Type.Object({
      ...quote,
      category: Type.Union(["evidence_missing", "overclaim", "contradiction", "citation", "other"].map(value => Type.Literal(value))),
      support: Type.Union(["contradicts", "insufficient", "uncertain"].map(value => Type.Literal(value))),
      reason: Type.String({ minLength: 1, maxLength: 1000 }), action: Type.String({ minLength: 1, maxLength: 1000 }),
      citations: Type.Array(Type.Object({ chunk_id: Type.String({ format: "uuid" }), quote: Type.String({ minLength: 1, maxLength: 600 }) }, { additionalProperties: false }), { maxItems: 3, description: "仅引用 read_evidence 返回的文献片段；没有外部材料时必须为空，不填原稿编号" }),
      related_blocks: Type.Array(Type.Object(quote, { additionalProperties: false }), { maxItems: 3, description: "另一处作者正文的依据，只来自 read_manuscript.blocks；不能称为研究说明" }),
      research_evidence: Type.Array(Type.Object({ field: Type.Union(["question", "method", "result"].map(value => Type.Literal(value))), quote: Type.String({ minLength: 1, maxLength: 600 }) }, { additionalProperties: false }), { maxItems: 3, description: "只来自 read_manuscript.author_research 对应字段；字段为空则不能引用，不填其他正文或资料" }),
    }, { additionalProperties: false }), { maxItems: 10 }),
  }, { additionalProperties: false });
}
