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
