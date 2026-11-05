import { Type } from "typebox";
export function expressionSchema(blockIds: string[]) {
  return Type.Object({
    summary: Type.String({ minLength: 1, maxLength: 1000 }),
    suggestions: Type.Array(Type.Object({
      block_version_id: Type.Union(blockIds.map(id => Type.Literal(id))),
      quote: Type.String({ minLength: 1, maxLength: 1200, description: "逐字复制 read_manuscript 对应块的原句，不是文献原文" }),
      occurrence: Type.Integer({ minimum: 1, maximum: 10000 }),
      replacement: Type.String({ minLength: 1, maxLength: 1200, description: "仅改善已有文字表达；实质修改保留原句，由作者自行处理" }),
      reason: Type.String({ minLength: 1, maxLength: 1000 }),
      kind: Type.Union([Type.Literal("expression"), Type.Literal("substantive")]),
      citations: Type.Array(Type.Object({ chunk_id: Type.String({ format: "uuid" }), quote: Type.String({ minLength: 1, maxLength: 600 }) }, { additionalProperties: false }), { maxItems: 3, description: "实际读取的材料引文，无材料则为空" }),
    }, { additionalProperties: false }), { maxItems: 5 }),
  }, { additionalProperties: false });
}
