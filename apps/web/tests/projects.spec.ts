import { randomUUID } from "node:crypto";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { expect, test as base, type APIRequestContext, type Page } from "@playwright/test";

type Accounts = { owner: string; reviewer: string; reviewerId: number; password: string; otherId: string };
const root = fileURLToPath(new URL("../../..", import.meta.url));
function fixtureData(action: "create" | "cleanup", prefix: string) {
  return execFileSync("uv", ["run", "python", "services/backend/core/tests/browser_data.py"], {
    cwd: root, input: JSON.stringify({ action, prefix }), encoding: "utf-8",
    env: { ...process.env, PYTHONPATH: "services/backend" },
  });
}
const test = base.extend<{ accounts: Accounts }>({
  accounts: async ({}, use) => {
    const prefix = `e2e-${randomUUID().replaceAll("-", "")}`;
    const accounts = JSON.parse(fixtureData("create", prefix)) as Accounts;
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
  await expect(page.locator("details")).toHaveCount(2);
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
