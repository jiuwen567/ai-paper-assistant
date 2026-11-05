const { test } = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const fs = require("node:fs");
const ts = require("typescript");

class RequestError extends Error { constructor(status, message) { super(message); this.status = status; } }
function screen(request) {
  let definition;
  const source = fs.readFileSync(new URL("../miniprogram/pages/library/library.ts", `file://${__filename}`), "utf8");
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  vm.runInNewContext(code, { Error, exports: {}, require: () => ({ request, RequestError, downloadDocument: async () => {} }), Component: value => { definition = value; }, wx: { navigateBack() {} } });
  const instance = { data: JSON.parse(JSON.stringify(definition.data)), setData(values) { Object.assign(this.data, values); } };
  for (const [name, method] of Object.entries(definition.methods)) instance[name] = method.bind(instance);
  return instance;
}
const card = { id: "card", chunk: "chunk", revision: 1, quote: "不可修改的原文摘录", bibliography: { title: "自制摘要", source_scope: "abstract" }, source: { id: "file", number: 1, file_name: "abstract.pdf", access_state: "active" }, note: { text: "作者笔记", tags: ["实验"] } };

async function idle(view) { while (view.data.loading) await new Promise(resolve => setImmediate(resolve)); }

test("小程序查看摘要证据并以原版本提交笔记，冲突保留草稿", async () => {
  let conflict = false;
  const view = screen(async (path, method, payload) => {
    if (path === "projects/project/") return { id: "project", role: "author", name: "自制项目" };
    if (path.includes("evidence/?")) return { results: [card], next: null, previous: null };
    if (method === "PUT") {
      assert.equal(payload.version, 1);
      assert.equal(payload.note, "手机短笔记");
      assert.equal(payload.tags[0], "实验");
      if (conflict) throw new RequestError(409, "笔记已更新");
      return { ...card, revision: 2, note: { text: payload.note, tags: payload.tags } };
    }
    return card;
  });
  view.onLoad({ project: "project" }); await idle(view);
  assert.equal(view.data.cards[0].scopeLabel, "仅摘要");
  await view.open("card");
  view.changeNote({ detail: { value: "手机短笔记" } });
  conflict = true; view.save(); await idle(view);
  assert.equal(view.data.note, "手机短笔记"); assert.equal(view.data.error, "笔记已更新");
  assert.equal(view.data.selected.quote, card.quote);
  conflict = false; view.save(); await idle(view);
  assert.equal(view.data.selected.revision, 2); assert.equal(view.data.message, "笔记已保存。");
});

test("小程序撤权时清除证据与草稿", async () => {
  const view = screen(async () => { throw new RequestError(404, "项目不存在"); });
  view.setData({ selected: card, note: "自制私人草稿", cards: [card], projectId: "project" });
  view.refresh(); await idle(view);
  assert.equal(view.data.selected, null); assert.equal(view.data.note, ""); assert.equal(view.data.cards.length, 0);
});
