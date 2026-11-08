import { expect } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { test, login, mutate, activate, select } from "./fixtures/accounts";

test("材料永久删除阻断旧访问、保留其他正文并跟踪项目清理", async ({ page, accounts }, testInfo) => {
  test.setTimeout(120000);
  await page.goto("/"); await login(page, accounts.owner, accounts.password);
  await page.getByRole("button", { name: "创建项目" }).click();
  await page.getByLabel("项目名称", { exact: true }).fill("自制删除验收");
  const [created] = await Promise.all([
    page.waitForResponse(response => response.url().endsWith("/api/v1/projects/") && response.request().method() === "POST"),
    page.getByRole("button", { name: "创建", exact: true }).click(),
  ]);
  const project = await created.json(), base = `projects/${project.id}/`;
  const draft = { version: 0, request_key: randomUUID(), research: { question: "作者问题", method: "作者方法", result: "作者结果" }, blocks: [{ id: randomUUID(), text: "与删除材料无关的作者正文。", heading_level: 0 }] };
  expect((await mutate(page.request, base + "manuscript/", "PUT", draft)).status()).toBe(200);
  const materials = page.getByRole("region", { name: "材料", exact: true });
  await activate(page, '材料');
  await materials.getByLabel("材料名称", { exact: true }).fill("待删除的自制记录");
  await materials.locator('input[type="file"]').setInputFiles({ name: "cleanup-sample.txt", mimeType: "text/plain", buffer: Buffer.from("自制待删除材料，不包含实际论文。") });
  await materials.getByRole("button", { name: "上传材料", exact: true }).click();
  await materials.getByRole("button", { name: "查看原文 v1", exact: true }).click();
  const material = (await (await page.request.get(`/api/v1/${base}materials/`)).json()).results[0];
  const panel = page.getByRole("region", { name: "删除与清理", exact: true });
  await activate(page, '删除与清理');
  await panel.locator(".n-collapse-item__header-main").filter({ hasText: /^删除与清理$/ }).click();
  await panel.getByRole("button", { name: "加载可选材料" }).click();
  await select(page, panel.getByRole("combobox", { name: "待删除材料", exact: true }), material.id);
  await panel.getByRole("button", { name: "预览删除影响" }).click();
  await expect(panel.getByLabel("删除影响预览", { exact: true })).toContainText("原文件版本：1");
  await panel.getByLabel("已核对影响范围，确认永久删除，无法撤销").check();
  await panel.getByRole("button", { name: "确认永久删除" }).click();
  const detail = panel.getByRole("article", { name: "清理记录详情" });
  await expect(detail.getByRole("status")).toContainText("在线清理完成");
  expect((await page.request.get(`/api/v1/${base}files/${material.latest_version.id}/`)).status()).toBe(404);
  const current = await (await page.request.get(`/api/v1/${base}manuscript/`)).json();
  expect(current.blocks[0].text).toBe(draft.blocks[0].text);
  await activate(page, '材料');
  await expect(materials).not.toContainText("待删除的自制记录");
  await activate(page, '删除与清理');
  await select(page, panel.getByRole("combobox", { name: "删除范围", exact: true }), "project");
  await panel.getByRole("button", { name: "预览删除影响" }).click();
  await panel.getByLabel("已核对影响范围，确认永久删除，无法撤销").check();
  await panel.getByRole("button", { name: "确认永久删除" }).click();
  await expect(page.getByRole("button", { name: "创建项目", exact: true })).toBeVisible();
  await expect(detail.getByRole("status")).toContainText("在线清理完成");
  expect((await page.request.get(`/api/v1/${base}`)).status()).toBe(404);
  await detail.locator(".n-collapse-item__header-main").filter({ hasText: "执行记录" }).click();
  await expect(detail).toContainText("第 1 次");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await panel.screenshot({ path: testInfo.outputPath("cleanup-progress.png") });
});
