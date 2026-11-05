import { randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { expect, test as base, type APIRequestContext, type Page } from "@playwright/test";

type Accounts = { prefix: string; owner: string; reviewer: string; reviewerId: number; password: string; otherId: string };
const root = fileURLToPath(new URL("../../..", import.meta.url));
function fixtureData(action: "create" | "cleanup" | "binding" | "ai" | "reading" | "review" | "expression", prefix: string, options: Record<string, unknown> = {}) {
  return execFileSync("uv", ["run", "python", "services/backend/core/tests/browser_data.py"], {
    cwd: root, input: JSON.stringify({ action, prefix, ...options }), encoding: "utf-8",
    env: { ...process.env, PYTHONPATH: "services/backend" },
  });
}
const test = base.extend<{ accounts: Accounts }>({
  accounts: async ({}, use) => {
    const prefix = `e2e-${randomUUID().replaceAll("-", "")}`;
    const accounts = JSON.parse(fixtureData("create", prefix)) as Accounts;
    accounts.prefix = prefix;
    try { await use(accounts); } finally { fixtureData("cleanup", prefix); }
  },
});
async function login(page: Page, username: string, password: string) {
  await page.getByLabel("用户名", { exact: true }).fill(username);
  await page.getByLabel("密码", { exact: true }).fill(password);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page.getByRole("button", { name: "创建项目" })).toBeVisible();
}
async function mutate(api: APIRequestContext, path: string, method: string, data: unknown) {
  const session = await (await api.get("/api/v1/auth/session/")).json();
  return api.fetch(`/api/v1/${path}`, { method, data, headers: { "X-CSRFToken": session.csrf_token } });
}

test("表达建议差异、编辑采纳、引用和旧稿冲突", async ({ page, accounts }, testInfo) => {
  test.setTimeout(90000);
  await page.goto("/"); await login(page, accounts.owner, accounts.password);
  await page.getByRole("button", { name: "创建项目" }).click();
  await page.getByLabel("项目名称", { exact: true }).fill("表达验收");
  await page.getByRole("button", { name: "创建", exact: true }).click();
  await page.getByLabel("规则来源", { exact: true }).fill("自制规则");
  await page.getByLabel("来源版本", { exact: true }).fill("v1");
  await page.getByLabel("已核对学校或课程规则").check();
  await page.getByRole("checkbox", { name: "表达建议", exact: true }).check();
  await page.getByRole("button", { name: "保存规则新版本" }).click();
  await expect(page.getByRole("heading", { name: "AI 辅助规则 · v2" })).toBeVisible();
  const manuscript = page.getByRole("region", { name: "作者原稿", exact: true });
  await manuscript.getByRole("button", { name: "添加章节", exact: true }).click();
  await manuscript.getByLabel("标题 1", { exact: true }).fill("方法");
  await manuscript.getByRole("button", { name: "添加正文块", exact: true }).click();
  await manuscript.getByLabel("正文块 2", { exact: true }).fill("本研究对样本进行了观察。");
  await manuscript.getByRole("button", { name: "保存原稿新版本", exact: true }).click();
  await expect(manuscript.getByRole("heading", { name: "作者原稿 · v1", exact: true })).toBeVisible();
  const materials = page.getByRole("region", { name: "材料", exact: true });
  await materials.getByLabel("材料名称", { exact: true }).fill("表达自制依据");
  await materials.locator('input[type="file"]').setInputFiles({ name: "expression.txt", mimeType: "text/plain", buffer: Buffer.from("软件验收用记录：观察样本，未外推结论。") });
  await materials.getByRole("button", { name: "上传材料", exact: true }).click();
  await materials.getByRole("button", { name: "查看原文 v1", exact: true }).click();
  const reader = materials.getByRole("region", { name: "原文定位", exact: true });
  await reader.getByRole("button", { name: "解析材料", exact: true }).click();
  await expect(reader.getByRole("button", { name: "解析 #1 · 解析成功", exact: true })).toBeVisible();
  const panel = page.getByRole("region", { name: "表达建议", exact: true });
  await panel.getByRole("button", { name: "刷新表达区" }).click();
  await panel.getByLabel("建议原稿块", { exact: true }).selectOption({ label: "块 2：本研究对样本进行了观察。" });
  await panel.locator("summary").filter({ hasText: "选择表达依据" }).click();
  await panel.getByRole("checkbox", { name: /表达自制依据/ }).check();
  await panel.getByRole("button", { name: "生成表达建议", exact: true }).click();
  await expect(panel.getByRole("alert")).toContainText("配置生成模型");
  await page.route("**/expressions/tasks/", async route => {
    const created = JSON.parse(fixtureData("expression", accounts.prefix, { payload: route.request().postDataJSON() }));
    await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify(created.task) });
  });
  await panel.getByRole("button", { name: "生成表达建议", exact: true }).click();
  const card = panel.getByRole("article", { name: "表达建议：本研究对样本进行了观察。", exact: true });
  await expect(card).toBeVisible();
  await expect(card.getByLabel("文字差异").locator("del").first()).toBeVisible();
  await expect(card.getByRole("button", { name: "接受建议", exact: true })).toBeDisabled();
  await card.locator("summary").filter({ hasText: "相关依据" }).click();
  await card.getByRole("button", { name: "回查表达依据 1" }).click();
  await expect(card.getByRole("region", { name: "原文上下文" })).toContainText("未外推结论");
  await card.getByRole("button", { name: "编辑建议", exact: true }).click();
  await card.getByLabel("作者编辑", { exact: true }).fill("本研究已观察样本。");
  await card.getByRole("button", { name: "查看编辑差异" }).click();
  await card.getByRole("checkbox", { name: "已核对原意、数据、条件和依据，确认只是表达修改" }).check();
  await card.getByRole("button", { name: "编辑后接受", exact: true }).click();
  await expect(card.getByRole("heading", { name: "原稿 v1 · 编辑后接受", exact: true })).toBeVisible();
  await expect(card).toContainText("已生成原稿 v2");
  await manuscript.getByRole("button", { name: "加载最新原稿" }).click();
  await expect(manuscript.getByLabel("正文块 2", { exact: true })).toHaveValue("本研究已观察样本。");
  await panel.getByRole("button", { name: "生成表达建议", exact: true }).click();
  const stale = panel.getByRole("article", { name: "表达建议：本研究已观察样本。", exact: true });
  await expect(stale).toBeVisible();
  const project = (await (await page.request.get("/api/v1/projects/")).json()).results[0];
  const current = await (await page.request.get(`/api/v1/projects/${project.id}/manuscript/`)).json();
  expect((await mutate(page.request, `projects/${project.id}/manuscript/`, "PUT", { version: current.version, request_key: randomUUID(), research: current.research,
    blocks: current.blocks.map((block: { id: string; text: string; heading_level: number }) => ({ id: block.id, heading_level: block.heading_level, text: block.heading_level ? block.text : "作者在另一端保存的新稿。" })),
  })).status()).toBe(200);
  await stale.getByLabel("决定原因", { exact: true }).fill("当前窗口的处理草稿");
  await stale.getByRole("checkbox", { name: "已核对原意、数据、条件和依据，确认只是表达修改" }).check();
  await stale.getByRole("button", { name: "接受建议", exact: true }).click();
  await expect(stale.getByRole("alert")).toContainText("旧建议不能覆盖新稿");
  await expect(stale.getByLabel("决定原因", { exact: true })).toHaveValue("当前窗口的处理草稿");
  await stale.getByRole("button", { name: "重新加载建议", exact: true }).click();
  await expect(stale.getByRole("button", { name: "接受建议", exact: true })).toBeDisabled();
  await stale.getByRole("button", { name: "拒绝建议", exact: true }).click();
  await expect(stale.getByRole("heading", { name: "原稿 v2 · 已拒绝", exact: true })).toBeVisible();
  const final = await (await page.request.get(`/api/v1/projects/${project.id}/manuscript/`)).json();
  expect(final.version).toBe(3); expect(final.blocks[1].text).toBe("作者在另一端保存的新稿。");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await card.screenshot({ path: testInfo.outputPath("expression-decision.png") });
});

test("原稿诊断固定位置、来源范围、作者判断与修改后复查", async ({ page, accounts }, testInfo) => {
  test.setTimeout(90000);
  await page.goto("/"); await login(page, accounts.owner, accounts.password);
  await page.getByRole("button", { name: "创建项目" }).click();
  await page.getByLabel("项目名称", { exact: true }).fill("诊断验收");
  await page.getByRole("button", { name: "创建", exact: true }).click();
  await page.getByLabel("规则来源", { exact: true }).fill("自制规则");
  await page.getByLabel("来源版本", { exact: true }).fill("v1");
  await page.getByLabel("已核对学校或课程规则").check();
  await page.getByRole("checkbox", { name: "原稿诊断", exact: true }).check();
  await page.getByRole("button", { name: "保存规则新版本" }).click();
  await expect(page.getByRole("heading", { name: "AI 辅助规则 · v2" })).toBeVisible();
  const manuscript = page.getByRole("region", { name: "作者原稿", exact: true });
  await manuscript.getByRole("button", { name: "添加章节", exact: true }).click();
  await manuscript.getByLabel("标题 1", { exact: true }).fill("结论");
  await manuscript.getByRole("button", { name: "添加正文块", exact: true }).click();
  await manuscript.getByLabel("正文块 2", { exact: true }).fill("所有条件下均有效。另一个待核对的句子。");
  await manuscript.getByRole("button", { name: "保存原稿新版本", exact: true }).click();
  await expect(manuscript.getByRole("heading", { name: "作者原稿 · v1", exact: true })).toBeVisible();
  const materials = page.getByRole("region", { name: "材料", exact: true });
  await materials.getByLabel("材料名称", { exact: true }).fill("诊断自制摘要");
  await materials.locator('input[type="file"]').setInputFiles({ name: "review.txt", mimeType: "text/plain", buffer: Buffer.from("仅在指定模拟条件观察到效果，不能外推到实际装置。") });
  await materials.getByRole("button", { name: "上传材料", exact: true }).click();
  await materials.getByRole("button", { name: "查看原文 v1", exact: true }).click();
  const reader = materials.getByRole("region", { name: "原文定位", exact: true });
  await reader.getByRole("button", { name: "解析材料", exact: true }).click();
  await expect(reader.getByRole("button", { name: "解析 #1 · 解析成功", exact: true })).toBeVisible();
  const project = (await (await page.request.get("/api/v1/projects/")).json()).results[0];
  const versions = (await (await page.request.get(`/api/v1/projects/${project.id}/reading/sources/`)).json()).results;
  const bibliography = await (await page.request.get(`/api/v1/projects/${project.id}/files/${versions[0].id}/bibliography/`)).json();
  expect((await mutate(page.request, `projects/${project.id}/files/${versions[0].id}/bibliography/`, "PUT", { version: bibliography.version, snapshot: { ...bibliography.snapshot, source_scope: "abstract" } })).status()).toBe(200);
  const panel = page.getByRole("region", { name: "原稿诊断", exact: true });
  await panel.getByRole("button", { name: "刷新审阅区" }).click();
  await panel.locator("summary").filter({ hasText: "选择原稿" }).click();
  await panel.getByRole("checkbox", { name: /块 2/ }).check();
  await panel.locator("summary").filter({ hasText: "选择依据" }).click();
  await panel.getByRole("checkbox", { name: /诊断自制摘要/ }).check();
  await panel.getByRole("button", { name: "开始诊断", exact: true }).click();
  await expect(panel.getByRole("alert")).toContainText("配置生成模型");
  let recheck = false;
  // 控制的供应商协议，经真实 Pi/业务任务发布；不把此样例算作模型效果。
  await page.route("**/reviews/tasks/", async route => {
    const created = JSON.parse(fixtureData("review", accounts.prefix, { payload: route.request().postDataJSON(), recheck }));
    await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify(created.task) });
  });
  await panel.getByRole("button", { name: "开始诊断", exact: true }).click();
  const result = panel.getByRole("article", { name: "诊断结果", exact: true });
  const card = result.getByRole("article", { name: /问题：所有条件下均有效/ });
  await expect(card).toBeVisible();
  await card.locator("summary").filter({ hasText: "查看固定版本原稿" }).click();
  await expect(card.locator("mark")).toHaveText("所有条件下均有效。");
  await result.locator("summary").filter({ hasText: "资料与全文范围" }).click();
  await expect(result).toContainText("出版真实性未核验");
  await expect(result).toContainText("未提供全文");
  await card.locator("summary").filter({ hasText: "材料原文依据" }).click();
  await card.getByRole("button", { name: "回查依据 1", exact: true }).click();
  await expect(card.getByRole("region", { name: "原文上下文" })).toContainText("不能外推到实际装置");
  await card.getByLabel("作者处理", { exact: true }).selectOption("ignored");
  await card.getByLabel("处理原因", { exact: true }).fill("作者认为已有其他限定，记录忽略原因。");
  await card.getByRole("button", { name: "保存作者判断", exact: true }).click();
  await expect(card.getByRole("heading", { name: "结论越界 · 已忽略" })).toBeVisible();
  await result.getByLabel("处理状态", { exact: true }).selectOption("ignored");
  await result.getByRole("button", { name: "筛选问题" }).click();
  await expect(card).toBeVisible();
  await manuscript.getByLabel("正文块 2", { exact: true }).fill("仅在指定模拟条件下观察到效果，不外推到实际装置。");
  await manuscript.getByRole("button", { name: "保存原稿新版本", exact: true }).click();
  await expect(manuscript.getByRole("heading", { name: "作者原稿 · v2", exact: true })).toBeVisible();
  await result.getByRole("button", { name: "重新加载诊断" }).click();
  await expect(result).toContainText("原稿或依据已变化");
  await result.getByRole("button", { name: "按当前原稿复查" }).click();
  recheck = true;
  await panel.getByRole("button", { name: "开始复查", exact: true }).click();
  await expect(result.getByRole("heading", { name: "原稿 v2 · 模型建议", exact: true })).toBeVisible();
  await expect(result).toContainText("当前范围没有问题卡");
  await result.getByRole("button", { name: "查看前次诊断" }).click();
  await expect(card.getByLabel("处理原因", { exact: true })).toHaveValue("作者认为已有其他限定，记录忽略原因。");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await result.screenshot({ path: testInfo.outputPath("manuscript-review.png") });
});

test("作者原稿保存、历史对照、冲突保护与 DOCX 导入", async ({ page, accounts }, testInfo) => {
  test.setTimeout(90000);
  await page.goto("/"); await login(page, accounts.owner, accounts.password);
  await page.getByRole("button", { name: "创建项目" }).click();
  await page.getByLabel("项目名称", { exact: true }).fill("原稿版本验收");
  await page.getByRole("button", { name: "创建", exact: true }).click();
  const panel = page.getByRole("region", { name: "作者原稿", exact: true });
  await expect(panel.getByRole("heading", { name: "作者原稿 · v0", exact: true })).toBeVisible();
  await panel.getByLabel("研究问题", { exact: true }).fill("作者提出的自制问题");
  await panel.getByLabel("研究方法", { exact: true }).fill("作者描述的方法");
  await panel.getByRole("button", { name: "添加章节", exact: true }).click();
  await panel.getByLabel("标题 1", { exact: true }).fill("第一章 研究背景");
  await panel.getByRole("button", { name: "添加正文块", exact: true }).click();
  await panel.getByLabel("正文块 2", { exact: true }).fill("作者自己写的第一版正文。");
  await panel.getByRole("button", { name: "保存原稿新版本", exact: true }).click();
  await expect(panel.getByRole("heading", { name: "作者原稿 · v1", exact: true })).toBeVisible();
  await expect(panel.getByRole("navigation", { name: "章节树" })).toContainText("第一章 研究背景");
  await panel.getByLabel("正文块 2", { exact: true }).fill("作者自己修订的第二版正文。");
  await panel.getByRole("button", { name: "保存原稿新版本", exact: true }).click();
  await expect(panel.getByRole("heading", { name: "作者原稿 · v2", exact: true })).toBeVisible();
  await panel.locator("summary").filter({ hasText: "历史版本与对照" }).click();
  await panel.getByRole("button", { name: "查看原稿 v1 · 作者编辑", exact: true }).click();
  await panel.getByRole("button", { name: "查看原稿差异", exact: true }).click();
  const diff = panel.getByLabel("原稿差异", { exact: true });
  await expect(diff).toContainText("作者自己写的第一版正文。");
  await expect(diff).toContainText("作者自己修订的第二版正文。");
  await panel.getByRole("button", { name: "恢复此稿为新版本", exact: true }).click();
  await expect(panel.getByRole("heading", { name: "作者原稿 · v3", exact: true })).toBeVisible();
  await expect(panel.getByLabel("正文块 2", { exact: true })).toHaveValue("作者自己写的第一版正文。");
  const project = (await (await page.request.get("/api/v1/projects/")).json()).results[0];
  const current = await (await page.request.get(`/api/v1/projects/${project.id}/manuscript/`)).json();
  const saved = await mutate(page.request, `projects/${project.id}/manuscript/`, "PUT", {
    version: current.version, request_key: randomUUID(), research: current.research,
    blocks: current.blocks.map((block: { id: string; text: string; heading_level: number }) => ({ id: block.id, text: block.heading_level ? block.text : "另一个窗口保存的第四版。", heading_level: block.heading_level })),
  });
  expect(saved.status()).toBe(200);
  await panel.getByLabel("正文块 2", { exact: true }).fill("当前窗口未保存草稿。");
  await panel.getByRole("button", { name: "保存原稿新版本", exact: true }).click();
  await expect(panel.getByRole("alert")).toContainText("原稿已更新");
  await expect(panel.getByLabel("正文块 2", { exact: true })).toHaveValue("当前窗口未保存草稿。");
  page.once("dialog", dialog => dialog.dismiss());
  await page.getByRole("button", { name: "返回列表", exact: true }).click();
  await expect(panel.getByLabel("正文块 2", { exact: true })).toHaveValue("当前窗口未保存草稿。");
  page.once("dialog", dialog => dialog.accept());
  await panel.getByRole("button", { name: "加载最新原稿", exact: true }).click();
  await expect(panel.getByLabel("正文块 2", { exact: true })).toHaveValue("另一个窗口保存的第四版。");
  const docx = execFileSync("uv", ["run", "python", "-c", "import sys; from core.tests.parse_samples import docx_sample; sys.stdout.buffer.write(docx_sample())"], { cwd: root, env: { ...process.env, PYTHONPATH: "services/backend" } });
  const materials = page.getByRole("region", { name: "材料", exact: true });
  await materials.getByLabel("材料名称", { exact: true }).fill("作者 DOCX");
  await materials.locator('input[type="file"]').setInputFiles({ name: "author.docx", mimeType: "application/octet-stream", buffer: docx });
  await materials.getByRole("button", { name: "上传材料", exact: true }).click();
  await materials.getByRole("button", { name: "查看原文 v1", exact: true }).click();
  const reader = materials.getByRole("region", { name: "原文定位", exact: true });
  await reader.getByRole("button", { name: "解析材料", exact: true }).click();
  await expect(reader.getByRole("button", { name: "解析 #1 · 解析成功", exact: true })).toBeVisible();
  await panel.locator("summary").filter({ hasText: "导入 DOCX 正文" }).click();
  await panel.getByRole("button", { name: "选择已解析 DOCX", exact: true }).click();
  await panel.getByRole("button", { name: "预览 author.docx · v1 · 解析 1", exact: true }).click();
  await expect(panel.getByLabel("DOCX 导入预览")).toContainText("表格、图片、公式");
  await panel.getByLabel("导入方式", { exact: true }).selectOption("replace");
  await panel.getByRole("button", { name: "确认导入并保存新版本", exact: true }).click();
  await expect(panel.getByRole("heading", { name: "作者原稿 · v5", exact: true })).toBeVisible();
  await expect(panel.getByLabel("标题 1", { exact: true })).toHaveValue("自制标题");
  await expect(panel.getByLabel("正文块 2", { exact: true })).toHaveValue("自制正文\t尾部");
  await expect(panel.getByLabel("研究问题", { exact: true })).toHaveValue("作者提出的自制问题");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await panel.locator("form").first().screenshot({ path: testInfo.outputPath("manuscript-editor.png") });
  await diff.screenshot({ path: testInfo.outputPath("manuscript-diff.png") });
});

test("阅读比较保留原文、作者修订、核对状态及过期冲突", async ({ page, accounts }, testInfo) => {
  test.setTimeout(90000);
  await page.goto("/"); await login(page, accounts.owner, accounts.password);
  await page.getByRole("button", { name: "创建项目" }).click();
  await page.getByLabel("项目名称", { exact: true }).fill("阅读比较验收");
  await page.getByRole("button", { name: "创建", exact: true }).click();
  await page.getByLabel("规则来源", { exact: true }).fill("自制规则");
  await page.getByLabel("来源版本", { exact: true }).fill("v1");
  await page.getByLabel("已核对学校或课程规则").check();
  await page.getByLabel("文献阅读", { exact: true }).check();
  await page.getByLabel("文献比较", { exact: true }).check();
  await page.getByRole("button", { name: "保存规则新版本" }).click();
  await expect(page.getByRole("heading", { name: "AI 辅助规则 · v2" })).toBeVisible();
  const materials = page.getByRole("region", { name: "材料", exact: true });
  for (const title of ["自制资料甲", "自制资料乙"]) {
    await materials.getByLabel("材料名称", { exact: true }).fill(title);
    await materials.locator('input[type="file"]').setInputFiles({ name: title + ".txt", mimeType: "text/plain", buffer: Buffer.from(`${title}：软件验收模拟记录，条件为 25 摄氏度。\n局限：不能外推。`) });
    await materials.getByRole("button", { name: "上传材料", exact: true }).click();
    await materials.getByRole("button", { name: "查看原文 v1", exact: true }).click();
    const reader = materials.getByRole("region", { name: "原文定位", exact: true });
    await reader.getByRole("button", { name: "解析材料", exact: true }).click();
    await expect(reader.getByRole("button", { name: "解析 #1 · 解析成功", exact: true })).toBeVisible();
    if (title === "自制资料甲") await materials.getByRole("button", { name: "新增材料", exact: true }).click();
  }
  const reading = page.getByRole("region", { name: "阅读摘记与比较", exact: true });
  await reading.getByRole("button", { name: "刷新阅读区" }).click();
  await reading.locator("summary").filter({ hasText: "选择已解析资料" }).click();
  await reading.getByRole("checkbox", { name: /自制资料甲/ }).check();
  await reading.getByRole("checkbox", { name: /自制资料乙/ }).check();
  await reading.getByLabel("阅读问题", { exact: true }).fill("比较实验条件与局限");
  await reading.getByRole("button", { name: "开始比较" }).click();
  await expect(reading.getByRole("alert")).toContainText("请先由管理员配置生成模型");
  fixtureData("reading", accounts.prefix);
  await reading.getByRole("button", { name: "刷新阅读区" }).click();
  await reading.getByRole("button", { name: /自制资料甲.*自制资料乙.*待核对/ }).click();
  const result = reading.getByRole("article", { name: "阅读结果" });
  await expect(result.getByText("可比性不确定", { exact: true })).toBeVisible();
  const row = result.getByRole("row").filter({ has: page.getByRole("rowheader", { name: "结果", exact: true }) });
  const cell = row.getByRole("cell").first();
  await cell.locator("summary").filter({ hasText: "原文依据" }).click();
  await cell.getByRole("button", { name: "回查原文 1", exact: true }).click();
  await expect(result.getByRole("region", { name: "原文上下文" })).toContainText("软件验收模拟记录");
  await cell.locator("summary").filter({ hasText: "修订此项" }).click();
  await cell.getByRole("textbox").fill("作者修订后的比较理解");
  await result.getByLabel("作者理解", { exact: true }).fill("这是作者的理解，不是文献原文。");
  await result.getByLabel("已逐项核对原文", { exact: true }).check();
  await result.getByRole("button", { name: "保存作者修订与核对状态" }).click();
  await expect(reading.getByText("作者修订已保存。", { exact: true })).toBeVisible();
  await expect(reading.getByRole("button", { name: /作者已核对/ })).toBeVisible();
  const project = (await (await page.request.get("/api/v1/projects/")).json()).results[0];
  const record = (await (await page.request.get(`/api/v1/projects/${project.id}/reading/`)).json()).results[0];
  expect((await mutate(page.request, `projects/${project.id}/reading/${record.id}/`, "PATCH", { version: 1, edits: record.author_revision.edits, note: "另一窗口保存", verified: false })).ok()).toBeTruthy();
  await result.getByLabel("作者理解", { exact: true }).fill("保留这个旧窗口草稿");
  await result.getByRole("button", { name: "保存作者修订与核对状态" }).click();
  await expect(reading.getByRole("alert")).toContainText("阅读结果已被修改");
  await expect(result.getByLabel("作者理解", { exact: true })).toHaveValue("保留这个旧窗口草稿");
  await result.getByRole("button", { name: "重新加载结果" }).click();
  await expect(result.getByLabel("作者理解", { exact: true })).toHaveValue("另一窗口保存");
  await expect(reading.getByRole("button", { name: /自制资料甲.*自制资料乙.*待核对/ })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await reading.screenshot({ path: testInfo.outputPath("reading-comparison.png") });
});

test("真实登录、项目编辑、规则版本、审阅者限制与撤权", async ({ page, accounts, playwright }, testInfo) => {
  await page.goto("/");
  await page.getByLabel("用户名", { exact: true }).fill(accounts.owner);
  await page.getByLabel("密码", { exact: true }).fill("wrong-password");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("账号或密码不正确");
  await login(page, accounts.owner, accounts.password);
  await expect(page.getByText("还没有论文项目。")).toBeVisible();
  expect((await page.request.get(`/api/v1/projects/${accounts.otherId}/`)).status()).toBe(404);
  await page.getByRole("button", { name: "创建项目" }).click();
  await page.getByLabel("项目名称", { exact: true }).fill("自制论文验收");
  await page.getByLabel("论文类型").fill("课程论文");
  await page.getByLabel("写作要求").fill("只使用自制公开测试材料。");
  await page.getByRole("combobox", { name: "模板", exact: true }).selectOption("department-default");
  await page.getByRole("button", { name: "创建", exact: true }).click();
  await expect(page.getByText("项目已保存。")).toBeVisible();
  await expect(page.getByLabel("文献阅读", { exact: true })).toBeDisabled();
  const project = (await (await page.request.get("/api/v1/projects/")).json()).results[0];
  const projectPath = `projects/${project.id}/`;
  expect((await mutate(page.request, `${projectPath}ai-permissions/`, "POST", { action: "reading", policy_version: 1 })).status()).toBe(403);

  // 另一请求先保存，旧表单提交必须保留输入并提示冲突。
  expect((await mutate(page.request, projectPath, "PATCH", { version: 1, name: "另一窗口的标题" })).ok()).toBeTruthy();
  await page.getByLabel("项目名称", { exact: true }).fill("旧页面标题");
  await page.getByRole("button", { name: "保存项目", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("版本已更新");
  await expect(page.getByLabel("项目名称", { exact: true })).toHaveValue("旧页面标题");
  await page.getByRole("button", { name: "重新加载", exact: true }).click();
  await expect(page.getByLabel("项目名称", { exact: true })).toHaveValue("另一窗口的标题");
  await page.getByLabel("项目名称", { exact: true }).fill("自制论文验收");
  await page.getByRole("button", { name: "保存项目", exact: true }).click();
  await expect(page.getByText("项目已保存。")).toBeVisible();

  await page.getByLabel("规则来源", { exact: true }).fill("自制课程规则");
  await page.getByLabel("来源版本", { exact: true }).fill("2026-v1");
  await page.getByLabel("已核对学校或课程规则").check();
  await page.getByLabel("文献阅读", { exact: true }).check();
  await page.getByRole("button", { name: "保存规则新版本" }).click();
  await expect(page.getByRole("heading", { name: "AI 辅助规则 · v2" })).toBeVisible();
  expect((await mutate(page.request, `${projectPath}ai-permissions/`, "POST", { action: "reading", policy_version: 2 })).ok()).toBeTruthy();
  expect((await mutate(page.request, `${projectPath}ai-permissions/`, "POST", { action: "expression", policy_version: 2 })).status()).toBe(403);
  await expect(page.locator("details.history-item")).toHaveCount(2);
  await page.getByLabel("成员用户名").fill(accounts.reviewer);
  await page.getByRole("button", { name: "添加或更新成员" }).click();
  await expect(page.getByText("成员权限已保存。")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await page.screenshot({ path: testInfo.outputPath("project-settings.png"), fullPage: true });
  await page.reload();
  await page.getByRole("button", { name: "自制论文验收 作者" }).click();
  await expect(page.getByLabel("写作要求")).toHaveValue("只使用自制公开测试材料。");

  await page.getByRole("button", { name: "退出", exact: true }).click();
  await expect(page.getByRole("heading", { name: "登录", exact: true })).toBeVisible();
  expect((await page.request.get("/api/v1/projects/")).status()).toBe(403);
  await login(page, accounts.reviewer, accounts.password);
  await page.getByRole("button", { name: "自制论文验收 审阅者" }).click();
  await expect(page.getByLabel("项目名称", { exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "保存项目", exact: true })).toHaveCount(0);
  expect((await mutate(page.request, projectPath, "PATCH", { version: 4, name: "越权" })).status()).toBe(403);

  // 独立作者会话移除审阅者，原审阅者会话立即失去读取权限。
  const owner = await playwright.request.newContext({ baseURL: "http://127.0.0.1:5173" });
  try {
    expect((await mutate(owner, "auth/session/", "POST", { username: accounts.owner, password: accounts.password })).ok()).toBeTruthy();
    const latest = await (await owner.get(`/api/v1/${projectPath}`)).json();
    expect((await mutate(owner, `${projectPath}members/${accounts.reviewerId}/`, "DELETE", { version: latest.version })).ok()).toBeTruthy();
    await page.getByRole("button", { name: "重新加载", exact: true }).click();
    await expect(page.getByRole("alert")).toContainText("项目不存在");
    await expect(page.getByLabel("写作要求")).toHaveCount(0);
    await page.getByRole("button", { name: "刷新列表" }).click();
    await expect(page.getByText("还没有论文项目。")).toBeVisible();
  } finally { await owner.dispose(); }
});

test("登录连接失败可重试", async ({ page }) => {
  await page.route("**/api/v1/auth/session/", route => route.abort());
  await page.goto("/");
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(page.getByRole("button", { name: "重新连接" })).toBeEnabled();
  await page.unroute("**/api/v1/auth/session/");
  await page.getByRole("button", { name: "重新连接" }).click();
  await expect(page.getByRole("heading", { name: "登录", exact: true })).toBeVisible();
});

test("会话失效后重新登录不显示上一账号的创建草稿", async ({ page, accounts }) => {
  await page.goto("/");
  await login(page, accounts.owner, accounts.password);
  await page.getByRole("button", { name: "创建项目" }).click();
  await page.getByLabel("项目名称", { exact: true }).fill("上一账号的自制草稿");
  expect((await mutate(page.request, "auth/logout/", "POST", {})).ok()).toBeTruthy();
  await page.getByRole("button", { name: "创建", exact: true }).click();
  await expect(page.getByRole("heading", { name: "登录", exact: true })).toBeVisible();
  await login(page, accounts.reviewer, accounts.password);
  await expect(page.getByText("还没有论文项目。")).toBeVisible();
  await expect(page.getByLabel("项目名称", { exact: true })).toHaveCount(0);
});

test("后台任务离开页面后可查回真实 Worker 结果", async ({ page, accounts }) => {
  await page.goto("/");
  await login(page, accounts.owner, accounts.password);
  await page.getByRole("button", { name: "创建项目" }).click();
  await page.getByLabel("项目名称", { exact: true }).fill("任务测试项目");
  await page.getByRole("button", { name: "创建", exact: true }).click();
  const panel = page.getByRole("region", { name: "后台任务" });
  await expect(panel.getByText("暂无任务。")).toBeVisible();
  await panel.getByLabel("字数统计样例").fill("自制测试");
  await panel.getByRole("button", { name: "开始统计" }).click();
  await expect(panel.locator("summary")).toHaveCount(1);
  await page.reload();
  await page.getByRole("button", { name: "任务测试项目 作者" }).click();
  await expect(panel.locator("summary")).toContainText("成功");
  await panel.locator("summary").click();
  await expect(panel.getByText("4 字 · 输入版本 1")).toBeVisible();
  await expect(panel.getByText("第 1 次 · 成功")).toBeVisible();
});


test("Web 确认绑定并解除（自制微信身份）", async ({ page, accounts }) => {
  const binding = JSON.parse(fixtureData("binding", accounts.prefix));
  await page.goto("/");
  await login(page, accounts.owner, accounts.password);
  await page.locator("summary").filter({ hasText: "微信账号" }).click();
  await page.getByLabel("绑定码", { exact: true }).fill("A".repeat(24));
  await page.getByRole("button", { name: "确认绑定当前账号" }).click();
  await expect(page.getByRole("alert")).toContainText("绑定码无效");
  await page.getByLabel("绑定码", { exact: true }).fill(binding.binding_code);
  await page.getByRole("button", { name: "确认绑定当前账号" }).click();
  await expect(page.locator("summary").filter({ hasText: "微信账号" })).toContainText("已绑定");
  await page.getByRole("button", { name: "解除微信绑定" }).click();
  await expect(page.getByRole("button", { name: "确认绑定当前账号" })).toBeVisible();
  await page.getByLabel("绑定码", { exact: true }).fill(binding.binding_code);
  await page.getByRole("button", { name: "确认绑定当前账号" }).click();
  await expect(page.getByRole("alert")).toContainText("绑定码无效、过期或已使用");
});


test("材料原件上传、新版本及授权下载", async ({ page, accounts }) => {
  await page.goto("/");
  await login(page, accounts.owner, accounts.password);
  await page.getByRole("button", { name: "创建项目" }).click();
  await page.getByLabel("项目名称", { exact: true }).fill("自制材料项目");
  await page.getByRole("button", { name: "创建", exact: true }).click();
  const panel = page.getByRole("region", { name: "材料", exact: true });
  await expect(panel.getByText("暂无材料。")).toBeVisible();
  await panel.getByLabel("材料名称", { exact: true }).fill("自制研究记录");
  const first = Buffer.from("自制材料第一版");
  await panel.locator('input[type="file"]').setInputFiles({ name: "self-authored.txt", mimeType: "text/plain", buffer: first });
  await panel.getByRole("button", { name: "上传材料", exact: true }).click();
  await expect(panel.getByText("材料版本已保存。")).toBeVisible();
  await expect(panel.getByRole("link", { name: "下载 v1", exact: true })).toBeVisible();
  const second = Buffer.from("自制材料第二版，旧版保留。");
  await panel.locator('input[type="file"]').setInputFiles({ name: "self-authored-v2.txt", mimeType: "text/plain", buffer: second });
  await panel.getByRole("button", { name: "上传新版本", exact: true }).click();
  await expect(panel.getByRole("link", { name: "下载 v2", exact: true })).toBeVisible();
  for (const [number, content] of [[1, first], [2, second]] as const) {
    const downloaded = page.waitForEvent("download");
    await panel.getByRole("link", { name: `下载 v${number}`, exact: true }).click();
    const file = await downloaded;
    expect(await readFile((await file.path())!)).toEqual(content);
  }
  await panel.locator('input[type="file"]').setInputFiles({ name: "broken.pdf", mimeType: "application/pdf", buffer: Buffer.from("invalid PDF") });
  await panel.getByRole("button", { name: "上传新版本", exact: true }).click();
  await expect(panel.getByRole("alert")).toContainText("文件损坏");
  await panel.getByRole("button", { name: "刷新材料", exact: true }).click();
  await expect(panel.getByText("v3 · broken.pdf · 失败")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
});


test("真实 Worker 解析 PDF、DOCX、CSV 并定位固定文件版本", async ({ page, accounts }, testInfo) => {
  const samples = JSON.parse(execFileSync("uv", ["run", "python", "-c",
    "import json,base64; from core.tests.parse_samples import pdf_sample,docx_sample,CSV_SAMPLE; print(json.dumps({k:base64.b64encode(v).decode() for k,v in {'sample.pdf':pdf_sample(),'sample.docx':docx_sample(),'sample.csv':CSV_SAMPLE,'scan.pdf':pdf_sample(blank=True)}.items()}))",
  ], { cwd: root, encoding: "utf-8", env: { ...process.env, PYTHONPATH: "services/backend" } })) as Record<string, string>;
  await page.goto("/");
  await login(page, accounts.owner, accounts.password);
  await page.getByRole("button", { name: "创建项目" }).click();
  await page.getByLabel("项目名称", { exact: true }).fill("原文定位测试");
  await page.getByRole("button", { name: "创建", exact: true }).click();
  const panel = page.getByRole("region", { name: "材料", exact: true });
  const reader = page.getByRole("region", { name: "原文定位", exact: true });
  for (const name of ["sample.pdf", "sample.docx", "sample.csv", "scan.pdf"]) {
    await panel.getByRole("button", { name: "新增材料", exact: true }).click();
    await panel.getByLabel("材料名称", { exact: true }).fill(name);
    await panel.locator('input[type="file"]').setInputFiles({ name, mimeType: "application/octet-stream", buffer: Buffer.from(samples[name], "base64") });
    await panel.getByRole("button", { name: "上传材料", exact: true }).click();
    await panel.getByRole("button", { name: "查看原文 v1", exact: true }).click();
    await expect(reader.getByText("尚无解析记录。")).toBeVisible();
    await reader.getByRole("button", { name: "解析材料", exact: true }).click();
    if (name === "scan.pdf") {
      await expect(reader.getByRole("alert")).toContainText("未提取到可用文字");
      await expect(reader.locator(".source-chunks li")).toHaveCount(0);
      continue;
    }
    await expect(reader.getByRole("button", { name: "解析 #1 · 解析成功", exact: true })).toBeVisible();
    if (name === "sample.pdf") await page.route("**/files/*/preview/", route => route.abort());
    await reader.locator(".source-chunks button").last().click();
    const context = reader.getByRole("region", { name: "原文上下文" });
    await expect(context.getByRole("heading")).toContainText(`${name} · v1`);
    if (name === "sample.pdf") {
      await expect(context.getByRole("heading")).toContainText("文件第 2 页（页码标签 ii）");
      await expect(context.locator(".located-chunk")).toContainText("Self-authored result");
      const preview = context.getByRole("link", { name: "打开 PDF 定位页" });
      await expect(preview).toHaveAttribute("href", /preview\/#page=2$/);
      const response = await page.request.get((await preview.getAttribute("href"))!);
      expect(response.headers()["content-disposition"]).toMatch(/^inline/);
      expect(await response.body()).toEqual(Buffer.from(samples[name], "base64"));
      await expect(context.getByRole("alert")).toContainText("PDF 预览加载失败");
      await page.unroute("**/files/*/preview/");
      await context.getByRole("button", { name: "重试预览" }).click();
      await expect(context.getByRole("img", { name: "PDF 文件第 2 页" })).toHaveAttribute("data-rendered", "true");
      expect(await context.locator("canvas").evaluate((element: HTMLCanvasElement) => {
        const pixels = element.getContext("2d")!.getImageData(0, 0, element.width, element.height).data;
        return pixels.some((value, index) => index % 4 !== 3 && value < 100);
      })).toBeTruthy();
      await reader.screenshot({ path: testInfo.outputPath("pdf-source-location.png") });
      // 增加新文件版本后，再选旧版仍定位旧原件；重新解析保留原有解析记录。
      await panel.locator('input[type="file"]').setInputFiles({ name: "replacement.txt", mimeType: "text/plain", buffer: Buffer.from("Replacement self-authored text") });
      await panel.getByRole("button", { name: "上传新版本", exact: true }).click();
      await panel.getByRole("button", { name: "查看原文 v2", exact: true }).click();
      await reader.getByRole("button", { name: "解析材料", exact: true }).click();
      await expect(reader.getByRole("button", { name: "解析 #1 · 解析成功", exact: true })).toBeVisible();
      await reader.locator(".source-chunks button").last().click();
      await expect(reader.getByRole("region", { name: "原文上下文" })).toContainText("Replacement self-authored text");
      await panel.getByRole("button", { name: "查看原文 v1", exact: true }).click();
      await reader.getByRole("button", { name: "重新解析", exact: true }).click();
      await expect(reader.getByRole("button", { name: "解析 #2 · 解析成功", exact: true })).toBeVisible();
      await reader.getByRole("button", { name: "解析 #1 · 解析成功", exact: true }).click();
      await reader.locator(".source-chunks button").last().click();
      await expect(reader.getByRole("region", { name: "原文上下文" }).getByRole("heading")).toContainText("sample.pdf · v1");
    } else if (name === "sample.docx") {
      await expect(context.getByRole("heading")).toContainText("第 3 段");
      await expect(context.locator(".located-chunk")).toContainText("自制正文");
      await expect(reader.locator(".source-chunks")).toContainText("1 级标题");
      await expect(context.locator("canvas")).toHaveCount(0);
    } else {
      await expect(context.getByRole("heading")).toContainText("第 1 条记录");
      await expect(context.locator(".located-chunk")).toContainText("value: 0.9");
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  }
});


test("摘要证据、作者笔记、真实语义检索与材料撤回", async ({ page, accounts }, testInfo) => {
  test.setTimeout(90000);
  await page.goto("/"); await login(page, accounts.owner, accounts.password);
  await page.getByRole("button", { name: "创建项目" }).click();
  await page.getByLabel("项目名称", { exact: true }).fill("证据检索测试");
  await page.getByRole("button", { name: "创建", exact: true }).click();
  await page.getByLabel("规则来源", { exact: true }).fill("自制规则");
  await page.getByLabel("来源版本", { exact: true }).fill("v1");
  await page.getByLabel("已核对学校或课程规则").check();
  await page.getByLabel("文献阅读", { exact: true }).check();
  await page.getByRole("button", { name: "保存规则新版本" }).click();
  await expect(page.getByRole("heading", { name: "AI 辅助规则 · v2" })).toBeVisible();
  const materials = page.getByRole("region", { name: "材料", exact: true });
  await materials.getByLabel("材料名称", { exact: true }).fill("自制温度实验摘要");
  await materials.locator('input[type="file"]').setInputFiles({ name: "abstract.txt", mimeType: "text/plain", buffer: Buffer.from("自制实验记录：提高温度后反应速率增加。\n对照记录：光照保持不变。") });
  await materials.getByRole("button", { name: "上传材料", exact: true }).click();
  await materials.getByRole("button", { name: "查看原文 v1", exact: true }).click();
  const reader = materials.getByRole("region", { name: "原文定位", exact: true });
  await reader.locator("summary").filter({ hasText: "文献卡与作者笔记" }).click();
  await reader.getByRole("combobox", { name: "资料范围", exact: true }).selectOption("abstract");
  await reader.getByRole("button", { name: "保存题录", exact: true }).click();
  await expect(reader.getByText("题录已保存。")).toBeVisible();
  await reader.getByRole("button", { name: "解析材料", exact: true }).click();
  await expect(reader.getByRole("button", { name: "解析 #1 · 解析成功", exact: true })).toBeVisible();
  await reader.getByRole("button", { name: "AI 阅读", exact: true }).click();
  await expect(reader.getByRole("alert")).toContainText("请先由管理员配置生成模型");
  fixtureData("ai", accounts.prefix);
  const jobs = page.getByRole("region", { name: "后台任务", exact: true });
  await jobs.getByRole("button", { name: "刷新任务", exact: true }).click();
  await jobs.locator("summary").filter({ hasText: "AI 摘记 · 成功" }).click();
  await expect(jobs.getByText("待核对", { exact: true })).toBeVisible();
  await expect(jobs.getByText("协议样例摘记，等待作者核对。", { exact: true })).toBeVisible();
  await jobs.getByRole("button", { name: "调用记录", exact: true }).click();
  await expect(jobs.getByText(/第 1 次执行 \/ 调用 2/)).toContainText("输入 20 / 输出 10 token");
  await jobs.getByRole("button", { name: "来源 1 · 仅摘要", exact: true }).click();
  await expect(jobs.getByRole("region", { name: "原文上下文" })).toContainText("提高温度");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await jobs.screenshot({ path: testInfo.outputPath("ai-pending-result.png") });
  await reader.locator(".source-chunks button").first().click();
  const context = reader.getByRole("region", { name: "原文上下文" });
  await context.getByLabel("作者笔记", { exact: true }).fill("我的理解，仍需复核。");
  await context.getByLabel("标签（逗号分隔）", { exact: true }).fill("实验");
  await context.getByRole("button", { name: "保存当前片段为证据卡" }).click();
  await expect(context.getByText("证据卡已保存。")).toBeVisible();
  const library = page.getByRole("region", { name: "阅读与证据", exact: true });
  await library.getByRole("button", { name: "刷新证据卡", exact: true }).click();
  await library.getByRole("button", { name: /自制温度实验摘要 · v1/ }).click();
  const detail = library.getByRole("article", { name: "证据详情" });
  await expect(detail.getByRole("heading").first()).toContainText("仅摘要");
  await expect(detail.locator("pre")).toContainText("提高温度");
  await detail.getByLabel("证据笔记", { exact: true }).fill("作者修订后的笔记");
  await detail.getByRole("button", { name: "保存证据笔记" }).click();
  await expect(library.getByText("笔记已保存。")).toBeVisible();
  await detail.getByRole("button", { name: "回查原文" }).click();
  await expect(library.getByRole("region", { name: "原文上下文" }).getByRole("heading")).toContainText("abstract.txt · v1");
  await library.locator("summary").filter({ hasText: "检索索引" }).click();
  await library.getByRole("button", { name: "重建检索索引", exact: true }).click();
  await expect(library.getByText(/512 维 · 成功/)).toBeVisible({ timeout: 30000 });
  await library.getByLabel("项目内检索", { exact: true }).fill("升温与反应速率");
  await library.getByRole("combobox", { name: "检索方式", exact: true }).selectOption("semantic");
  await library.getByRole("button", { name: "检索材料", exact: true }).click();
  const results = library.getByLabel("检索结果", { exact: true });
  await expect(results).toContainText("提高温度");
  await expect(results).toContainText("仅摘要");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await library.screenshot({ path: testInfo.outputPath("evidence-search.png") });
  await materials.getByRole("button", { name: "从检索和新任务撤回材料" }).click();
  await expect(materials.getByRole("button", { name: "恢复材料使用" })).toBeVisible();
  await library.getByRole("button", { name: "检索材料", exact: true }).click();
  await expect(library.getByRole("alert")).toContainText("请先重建检索索引");
  await library.getByRole("combobox", { name: "检索方式", exact: true }).selectOption("keyword");
  await library.getByLabel("项目内检索", { exact: true }).fill("温度");
  await library.getByRole("button", { name: "检索材料", exact: true }).click();
  await expect(results).toContainText("没有匹配的有效资料");
  await expect(library.getByText("仅摘要 · 材料已撤回")).toBeVisible();
});
