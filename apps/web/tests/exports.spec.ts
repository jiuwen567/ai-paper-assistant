import { expect } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { test, login, mutate, activate, select } from "./fixtures/accounts";

test("固定快照 Word 导出、改稿隔离与下载记录", async ({ page, accounts }, testInfo) => {
  await page.goto("/"); await login(page, accounts.owner, accounts.password);
  await page.getByRole("button", { name: "创建项目" }).click();
  await page.getByLabel("项目名称", { exact: true }).fill("自制导出验收");
  const [created] = await Promise.all([
    page.waitForResponse(response => response.url().endsWith("/api/v1/projects/") && response.request().method() === "POST"),
    page.getByRole("button", { name: "创建", exact: true }).click(),
  ]);
  const project = await created.json(), base = `projects/${project.id}/`;
  const draft = { version: 0, request_key: randomUUID(), research: { question: "作者研究问题", method: "作者研究方法", result: "作者观察结果" }, blocks: [
    { id: randomUUID(), text: "第一章 自制正文", heading_level: 1 },
    { id: randomUUID(), text: "这是作者确认的导出正文。", heading_level: 0 },
    { id: randomUUID(), text: "自制图题", heading_level: 0 },
  ] };
  expect((await mutate(page.request, base + "manuscript/", "PUT", draft)).status()).toBe(200);
  const disclosure = await (await page.request.get(`/api/v1/${base}disclosure/`)).json();
  expect((await mutate(page.request, base + "disclosure/", "POST", { version: 0, request_key: randomUUID(), facts_token: disclosure.facts_token, text: "作者确认本样例未调用生成模型。", external_uses: [], verified: true })).status()).toBe(201);
  const panel = page.getByRole("region", { name: "Word 导出", exact: true });
  await activate(page, 'Word 导出');
  await panel.getByRole("button", { name: "刷新导出资料" }).click();
  await panel.getByLabel("署名", { exact: true }).fill("自制样例作者");
  await panel.locator(".n-collapse-item__header-main").filter({ hasText: "图表题注" }).click();
  await select(page, panel.locator(".caption-option").filter({ hasText: "自制图题" }).getByRole("combobox"), "figure");
  await panel.getByRole("button", { name: "预览导出", exact: true }).click();
  await panel.getByRole("article", { name: "导出内容", exact: true }).locator(".n-collapse-item__header-main").filter({ hasText: "正文与引用" }).click();
  await expect(panel).toContainText("图 1 自制图题");
  await panel.getByLabel("已核对正文、引用、模板和 AI 使用说明").check();
  await panel.getByRole("button", { name: "确认并生成 Word", exact: true }).click();
  await expect(panel).toContainText("导出快照已保存");
  expect((await mutate(page.request, base + "manuscript/", "PUT", { ...draft, version: 1, request_key: randomUUID(), blocks: draft.blocks.map((block, i) => i === 1 ? { ...block, text: "导出之后的新稿，不应进入旧文件。" } : block) })).status()).toBe(200);
  const detail = panel.getByRole("article", { name: "导出记录详情", exact: true });
  await expect(detail.getByRole("button", { name: "下载 Word", exact: true })).toBeVisible();
  await detail.locator(".n-collapse-item__header-main").filter({ hasText: "正文与引用" }).click();
  await expect(detail).toContainText("这是作者确认的导出正文。");
  await expect(detail).not.toContainText("导出之后的新稿");
  const [download] = await Promise.all([page.waitForEvent("download"), detail.getByRole("button", { name: "下载 Word", exact: true }).click()]);
  expect(download.suggestedFilename()).toMatch(/^稿件-v1-.*\.docx$/);
  await download.saveAs(testInfo.outputPath("self-authored-export.docx"));
  await detail.locator(".n-collapse-item__header-main").filter({ hasText: "版本与下载记录" }).click();
  await expect(detail).toContainText("用户 ");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await detail.screenshot({ path: testInfo.outputPath("word-export.png") });
});
