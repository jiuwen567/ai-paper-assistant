import { randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { expect, test as base, type APIRequestContext, type Page } from "@playwright/test";

type Accounts = { prefix: string; owner: string; reviewer: string; reviewerId: number; password: string; otherId: string };
const root = fileURLToPath(new URL("../../..", import.meta.url));
function fixtureData(action: "create" | "cleanup" | "binding", prefix: string) {
  return execFileSync("uv", ["run", "python", "services/backend/core/tests/browser_data.py"], {
    cwd: root, input: JSON.stringify({ action, prefix }), encoding: "utf-8",
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
