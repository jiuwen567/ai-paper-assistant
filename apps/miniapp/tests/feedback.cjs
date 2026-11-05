const { test } = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const fs = require("node:fs");
const ts = require("typescript");
class RequestError extends Error { constructor(status, message) { super(message); this.status = status; } }
function screen(request, controls = {}) {
  let definition;
  const source = fs.readFileSync(new URL("../miniprogram/pages/feedback/feedback.ts", `file://${__filename}`), "utf8");
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  vm.runInNewContext(code, { Error, exports: {}, require: () => ({ request, RequestError }), Component: value => { definition = value; }, wx: { navigateBack() {}, enableAlertBeforeUnload() {}, disableAlertBeforeUnload() {}, ...controls } });
  const view = { data: JSON.parse(JSON.stringify(definition.data)), setData(values) { Object.assign(this.data, values); } };
  for (const [name, method] of Object.entries(definition.methods)) view[name] = method.bind(view);
  return view;
}
const project = { id: "project", role: "author", name: "自制项目" };
const item = { id: "task", feedback_id: "feedback", original_location: null, current: { number: 2, title: "核对样本条件", instruction: "作者检查原始记录", status: "todo", note: "", result_kind: "pending", location: null, mentor_reports: [] } };
const manuscript = { version: 3, blocks: [{ id: "block", version_id: "version", text: "作者补充的说明。" }] };
const pick = value => ({ detail: { value } });
async function idle(view) { while (view.data.loading) await new Promise(resolve => setImmediate(resolve)); }

test("未保存说明在切换任务和返回前确认，取消时保留草稿", async () => {
  let prompts = 0, reads = 0, backs = 0, confirm = false, guarded = false;
  const view = screen(async () => { reads++; return item; }, {
    showModal(options) { prompts++; options.success({ confirm }); },
    enableAlertBeforeUnload() { guarded = true; },
    disableAlertBeforeUnload() { guarded = false; },
    navigateBack() { backs++; },
  });
  view.changeNote(pick("尚未保存的处理说明"));
  view.select({ currentTarget: { dataset: { id: "another" } } });
  view.back(); await idle(view);
  assert.equal(prompts, 2); assert.equal(reads, 0); assert.equal(backs, 0);
  assert.equal(guarded, true); assert.equal(view.data.note, "尚未保存的处理说明");
  confirm = true; view.back();
  assert.equal(backs, 1); assert.equal(guarded, false);
});

test("小程序进度走 POST，冲突保留说明与幂等键，作者完成不发送导师确认", async () => {
  let conflict = true, firstKey, submitted = 0;
  const view = screen(async (path, method, body) => {
    if (path === "projects/project/") return project;
    if (path.includes("feedback-tasks/?")) return { results: [item], next: null, previous: null };
    if (path.endsWith("manuscript/")) return manuscript;
    if (path.endsWith("feedback/feedback/")) return { text: "请核对条件。", source_label: "作者转录", source_chunk_id: null };
    if (method === "POST") {
      submitted++; assert.equal(body.version, 2); assert.equal(body.manuscript_version, 3);
      assert.equal(body.block_id, "block"); assert.equal(body.status, "completed"); assert.equal(body.result_kind, "modified");
      assert.equal(body.mentor_status, undefined); assert.equal(body.mentor_reports, undefined);
      if (!firstKey) firstKey = body.request_key; else assert.equal(firstKey, body.request_key);
      if (conflict) throw new RequestError(409, "处理记录已变化");
      return { ...item, current: { ...item.current, number: 3, status: "completed", note: body.note, mentor_reports: [] } };
    }
    return item;
  });
  view.onLoad({ project: "project" }); await idle(view); await view.open("task");
  view.changeNote(pick("已根据原始记录补充条件")); view.changeStatus(pick("2")); view.changeResult(pick("1")); view.changeBlock(pick("1")); view.relink();
  view.save(); view.save(); await idle(view);
  assert.equal(submitted, 1); assert.equal(view.data.note, "已根据原始记录补充条件"); assert.equal(view.data.error, "处理记录已变化");
  conflict = false; view.save(); await idle(view);
  assert.equal(view.data.version, 3); assert.match(view.data.message, /不代表导师确认/);
});

test("刷新不会自动升级处理基准或改挂原稿，撤权清空旧内容", async () => {
  let latest = item, revoked = false;
  const view = screen(async path => {
    if (revoked) throw new RequestError(404, "项目不存在");
    if (path === "projects/project/") return project;
    if (path.includes("feedback-tasks/?")) return { results: [latest], next: null, previous: null };
    if (path.endsWith("manuscript/")) return manuscript;
    if (path.endsWith("feedback/feedback/")) return { text: "原始意见", source_label: "作者转录" };
    return latest;
  });
  view.onLoad({ project: "project" }); await idle(view); await view.open("task");
  view.changeNote(pick("当前手机草稿")); latest = { ...item, current: { ...item.current, number: 3, note: "电脑新说明" } };
  view.refreshSelected(); await idle(view);
  assert.equal(view.data.version, 2); assert.equal(view.data.selected.current.number, 3); assert.equal(view.data.note, "当前手机草稿"); assert.equal(view.data.linked, null);
  view.adoptVersion(); assert.equal(view.data.version, 3);
  revoked = true; view.refresh(); await idle(view);
  assert.equal(view.data.selected, null); assert.equal(view.data.feedback, null); assert.equal(view.data.note, ""); assert.equal(view.data.manuscript, null);
});
