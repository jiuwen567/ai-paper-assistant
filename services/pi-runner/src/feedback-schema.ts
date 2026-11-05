import { Type } from "typebox";

export const feedbackSchema = Type.Object({
  summary: Type.String({ minLength: 1, maxLength: 1000 }),
  candidates: Type.Array(Type.Object({
    title: Type.String({ minLength: 1, maxLength: 200 }),
    instruction: Type.String({ minLength: 1, maxLength: 2000 }),
    quote: Type.String({ minLength: 1, maxLength: 2000 }),
    occurrence: Type.Integer({ minimum: 1, maximum: 1000, description: "quote 在原始意见中第几次出现，不是任务编号。只出现一次时填1。" }),
  }, { additionalProperties: false }), { maxItems: 10 }),
}, { additionalProperties: false });
