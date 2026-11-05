import { Type } from "typebox";

const citation = Type.Object({ chunk_id: Type.String({ format: "uuid" }), quote: Type.String({ minLength: 1, maxLength: 600 }) }, { additionalProperties: false });
const field = Type.Object({
  status: Type.Union([Type.Literal("reported"), Type.Literal("not_mentioned"), Type.Literal("unavailable")]),
  text: Type.String({ maxLength: 800 }), citations: Type.Array(citation, { maxItems: 3 }),
}, { additionalProperties: false });
export const readingSchema = (versionIds: string[], comparison: boolean) => Type.Object({
  documents: Type.Array(Type.Object({
    version_id: Type.Union(versionIds.map(id => Type.Literal(id))),
    fields: Type.Object({ subject: field, method: field, result: field, limitations: field, conditions: field, applicability: field }, { additionalProperties: false }),
  }, { additionalProperties: false }), { minItems: versionIds.length, maxItems: versionIds.length }),
  comparison: comparison ? Type.Object({
    status: Type.Union([Type.Literal("comparable"), Type.Literal("not_comparable"), Type.Literal("uncertain")]),
    reason: Type.String({ minLength: 1, maxLength: 1000 }), citations: Type.Array(citation, { maxItems: 10 }),
  }, { additionalProperties: false }) : Type.Null(),
}, { additionalProperties: false });
