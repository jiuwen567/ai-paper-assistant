import { expect } from "@playwright/test";
import { test, fixtureData, login } from "./fixtures/accounts";

test("Web 确认绑定并解除（自制微信身份）", async ({ page, accounts }) => {
  const binding = JSON.parse(fixtureData("binding", accounts.prefix));
  await page.goto("/");
  await login(page, accounts.owner, accounts.password);
  await page.locator(".n-collapse-item__header-main").filter({ hasText: "微信账号" }).click();
  await page.getByLabel("绑定码", { exact: true }).fill("A".repeat(24));
  await page.getByRole("button", { name: "确认绑定当前账号" }).click();
  await expect(page.getByRole("alert")).toContainText("绑定码无效");
  await page.getByLabel("绑定码", { exact: true }).fill(binding.binding_code);
  await page.getByRole("button", { name: "确认绑定当前账号" }).click();
  await expect(page.locator(".n-collapse-item__header-main").filter({ hasText: "微信账号" })).toContainText("已绑定");
  await page.getByRole("button", { name: "解除微信绑定" }).click();
  await expect(page.getByRole("button", { name: "确认绑定当前账号" })).toBeVisible();
  await page.getByLabel("绑定码", { exact: true }).fill(binding.binding_code);
  await page.getByRole("button", { name: "确认绑定当前账号" }).click();
  await expect(page.getByRole("alert")).toContainText("绑定码无效、过期或已使用");
});
