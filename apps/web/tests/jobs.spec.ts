import { expect } from "@playwright/test";
import { test, login, activate } from "./fixtures/accounts";

test("后台任务离开页面后可查回真实 Worker 结果", async ({ page, accounts }) => {
  await page.goto("/");
  await login(page, accounts.owner, accounts.password);
  await page.getByRole("button", { name: "创建项目" }).click();
  await page.getByLabel("项目名称", { exact: true }).fill("任务测试项目");
  await page.getByRole("button", { name: "创建", exact: true }).click();
  const panel = page.getByRole("region", { name: "后台任务" });
  await activate(page, '后台任务');
  await expect(panel.getByText("暂无任务。")).toBeVisible();
  await panel.getByLabel("字数统计样例").fill("自制测试");
  await panel.getByRole("button", { name: "开始统计" }).click();
  await expect(panel.locator(".n-collapse-item__header-main")).toHaveCount(1);
  await page.reload();
  await expect(page).toHaveURL(/\/projects\/[^/]+\/jobs$/);
  await activate(page, "后台任务");
  await expect(panel.locator(".n-collapse-item__header-main")).toContainText("成功");
  await panel.locator(".n-collapse-item__header-main").click();
  await expect(panel.getByText("4 字 · 输入版本 1")).toBeVisible();
  await expect(panel.getByText("第 1 次 · 成功")).toBeVisible();
});
