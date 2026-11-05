import { Type } from "typebox";

export const feedbackSchema = Type.Object({
  candidates: Type.Array(Type.Object({
    title: Type.String({ minLength: 1, maxLength: 200, description: "一个可独立处理的要求，不将多个独立要求合成一项" }),
    instruction: Type.String({ minLength: 1, maxLength: 2000, description: "仅描述本项由作者处理的要求，细节不明保留原要求，不编造细节或执行它" }),
    quote: Type.String({ minLength: 1, maxLength: 2000, description: "read_feedback.text 中对应本项要求的连续原话，不引用整个复合意见代替分项" }),
    occurrence: Type.Integer({ minimum: 1, maximum: 1000, description: "quote 在原始意见中第几次出现，不是任务编号。只出现一次时填1。" }),
  }, { additionalProperties: false }), { maxItems: 10 }),
}, { additionalProperties: false });
