import { randomUUID } from "node:crypto";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { expect, test as base, type APIRequestContext, type Page, type Locator } from "@playwright/test";

type Accounts = { prefix: string; owner: string; reviewer: string; reviewerId: number; password: string; otherId: string };
export const root = fileURLToPath(new URL("../../../..", import.meta.url));
export function fixtureData(action: "create" | "cleanup" | "binding" | "ai" | "reading" | "review" | "expression" | "feedback" | "impact", prefix: string, options: Record<string, unknown> = {}) {
  return execFileSync("uv", ["run", "python", "services/backend/core/tests/browser_data.py"], {
    cwd: root, input: JSON.stringify({ action, prefix, ...options }), encoding: "utf-8",
    env: { ...process.env, PYTHONPATH: "services/backend" },
  });
}
export const test = base.extend<{ accounts: Accounts }>({
  accounts: async ({}, use) => {
    const prefix = `e2e-${randomUUID().replaceAll("-", "")}`;
    const accounts = JSON.parse(fixtureData("create", prefix)) as Accounts;
    accounts.prefix = prefix;
    try { await use(accounts); } finally { fixtureData("cleanup", prefix); }
  },
});
export async function login(page: Page, username: string, password: string) {
  await expect(page.getByLabel("密码", { exact: true })).toHaveAttribute("type", "password");
  await page.getByLabel("用户名", { exact: true }).fill(username);
  await page.getByLabel("密码", { exact: true }).fill(password);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page.getByRole("button", { name: "创建项目" })).toBeVisible();
}
export async function mutate(api: APIRequestContext, path: string, method: string, data: unknown) {
  const session = await (await api.get("/api/v1/auth/session/")).json();
  return api.fetch(`/api/v1/${path}`, { method, data, headers: { "X-CSRFToken": session.csrf_token } });
}


// 通过产品导航切换工作区；不强制点击隐藏控件。
const sections: Record<string, [string, string?]> = {
  '作者原稿': ['原稿写作'], '材料': ['材料与阅读', '文件材料'], '阅读与证据': ['材料与阅读', '检索与证据卡'],
  '阅读摘记与比较': ['材料与阅读', 'AI 阅读'], '原稿诊断': ['审阅与修订', '原稿诊断'], '表达建议': ['审阅与修订', '表达建议'],
  '导师反馈与修改待办': ['导师反馈'], '依据关系': ['依据与变更', '依据关系'], '材料变更与影响': ['依据与变更', '变更影响'],
  'Word 导出': ['导出与披露', '导出文档'], 'AI 使用与披露': ['导出与披露', 'AI 使用说明'], '后台任务': ['后台任务'], '删除与清理': ['项目设置'],
};
export async function activate(page: Page, section: string) {
  const [menu, tab] = sections[section] ?? [section];
  if (await page.getByRole('heading', { name: menu, exact: true }).count() === 0) {
    const mobile = page.getByRole('button', { name: '打开导航' });
    if (await mobile.isVisible()) await mobile.click();
    await page.getByRole('menuitem', { name: menu, exact: true }).filter({ visible: true }).click();
  }
  if (tab) await page.getByRole('tab', { name: tab, exact: true }).click();
}
export async function select(page: Page, field: Locator, value: string | { label: string }) {
  await field.click();
  const menu = page.locator(`[id="${await field.getAttribute('aria-controls')}"]`);
  if (typeof value === 'string') await menu.locator(`[data-option-value="${value}"]`).click();
  else await menu.getByText(value.label, { exact: true }).click();
}
export async function returnToList(page: Page) {
  const mobile = page.getByRole('button', { name: '打开导航' });
  if (await mobile.isVisible()) { await mobile.click(); await page.getByRole('button', { name: '返回列表', exact: true }).filter({ visible: true }).click(); }
  else await page.getByRole('button', { name: '我的论文', exact: true }).click();
}
