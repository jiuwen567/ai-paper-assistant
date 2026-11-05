const { test } = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const fs = require("node:fs");
const ts = require("typescript");
class RequestError extends Error { constructor(status, message) { super(message); this.status = status; } }
function screen(request) {
  let definition;
  const source = fs.readFileSync(new URL("../miniprogram/pages/suggestions/suggestions.ts", `file://${__filename}`), "utf8");
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  vm.runInNewContext(code, { Error, exports: {}, require: () => ({ request, RequestError }), Component: value => { definition = value; }, wx: { navigateBack() {} } });
  const view = { data: JSON.parse(JSON.stringify(definition.data)), setData(values) { Object.assign(this.data, values); } };
  for (const [name, method] of Object.entries(definition.methods)) view[name] = method.bind(view);
  return view;
}
const project = { id: "project", role: "author", policy: { version: 3, allowed_actions: ["expression"] } };
const item = { id: "suggestion", manuscript_version: 7, manuscript_text: "本研究对样本进行了观察。", input_changed: false,
  model_output: { quote: "本研究对样本进行了观察。", start: 0, end: 13, replacement: "本研究观察了样本。", reason: "简化表达", kind: "expression", guard_reasons: [], citations: [] },
  diff: [{ kind: "replace", before: "对样本进行了观察", after: "观察了样本" }], decision: null };
const event = action => ({ currentTarget: { dataset: { action } } });
async function idle(view) { while (view.data.loading) await new Promise(resolve => setImmediate(resolve)); }

test("小程序编辑后接受保留基准版本、规则与请求键，冲突保留编辑草稿", async () => {
  let conflict = true, firstKey, posted = 0;
  const view = screen(async (path, method, payload) => {
    if (path === "projects/project/") return project;
    if (path.includes("suggestions/?")) return { results: [item], next: null, previous: null };
    if (path.endsWith("preview/")) return { diff: item.diff, guard_reasons: [] };
    if (path.endsWith("decision/")) {
      posted++;
      assert.equal(payload.manuscript_version, 7); assert.equal(payload.policy_version, 3);
      assert.equal(payload.action, "edited"); assert.equal(payload.text, "本研究已观察样本。"); assert.equal(payload.meaning_confirmed, true);
      if (!firstKey) firstKey = payload.request_key; else assert.equal(payload.request_key, firstKey);
      if (conflict) throw new RequestError(409, "原稿或依据已变化");
      return { ...item, decision: { action: "edited", text: payload.text, reason: payload.reason, manuscript_version: 8 } };
    }
    return item;
  });
  view.onLoad({ project: "project" }); await idle(view); await view.open("suggestion");
  view.toggleEdit(); view.changeText({ detail: { value: "本研究已观察样本。" } });
  view.previewEdit(); await idle(view); assert.equal(view.data.preview.text, view.data.text);
  view.changeConfirmed({ detail: { value: ["confirmed"] } });
  view.decide(event("edited")); view.decide(event("edited")); await idle(view);
  assert.equal(posted, 1); assert.equal(view.data.text, "本研究已观察样本。"); assert.equal(view.data.error, "原稿或依据已变化");
  conflict = false; view.decide(event("edited")); await idle(view);
  assert.equal(view.data.selected.decision.manuscript_version, 8); assert.match(view.data.message, /Web/);
});

test("编辑变化撤销旧核对，拒绝不发送替换文字，撤权清空敏感内容", async () => {
  let revoked = false;
  const view = screen(async (path, method, payload) => {
    if (revoked) throw new RequestError(404, "项目不存在");
    if (path === "projects/project/") return project;
    if (path.includes("suggestions/?")) return { results: [item], next: null, previous: null };
    if (path.endsWith("decision/")) {
      assert.equal(payload.action, "rejected"); assert.equal(payload.meaning_confirmed, false); assert.equal(payload.text, undefined);
      return { ...item, decision: { action: "rejected", text: "", reason: "", manuscript_version: null } };
    }
    return item;
  });
  view.onLoad({ project: "project" }); await idle(view); await view.open("suggestion");
  view.changeConfirmed({ detail: { value: ["confirmed"] } }); view.changeText({ detail: { value: "作者的草稿" } });
  assert.equal(view.data.confirmed, false); assert.equal(view.data.preview, null);
  view.decide(event("rejected")); await idle(view); assert.match(view.data.message, /原稿未修改/);
  revoked = true; view.refresh(); await idle(view);
  assert.equal(view.data.selected, null); assert.equal(view.data.text, ""); assert.equal(view.data.canAccept, false);
});
