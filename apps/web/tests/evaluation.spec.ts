import { test, expect } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

test("离线评测复核表保留草稿、计时、导出并隔离模型文本", async ({ page }) => {
  const directory = mkdtempSync(join(tmpdir(), "paper-review-"));
  const root = resolve(import.meta.dirname, "../../..");
  try {
    const run = { status: "completed", suite: { cases: [{ id: "fixture", purpose: "review", sources: [], blocks: [], targets: [{ id: "one", expected: "自制预期" }] }] }, records: [
      { id: "fixture/system", case: "fixture", arm: "system", status: "succeeded", error_code: "", items: [{ id: "item-1", content: "</script><script>window.attacked=true</script>自制模型输出" }] },
      { id: "fixture/direct", case: "fixture", arm: "direct", status: "failed", error_code: "fixture_failure", raw: "自制失败原文", items: [] },
    ] };
    const input = join(directory, "run.json"), output = join(directory, "review.html");
    writeFileSync(input, JSON.stringify(run));
    execFileSync("uv", ["run", "python", "-c", "import json,sys; from pathlib import Path; from core.tests.evaluation_review import render; Path(sys.argv[2]).write_text(render(json.loads(Path(sys.argv[1]).read_text())))", input, output], { cwd: root, env: { ...process.env, PYTHONPATH: join(root, "services/backend") } });
    await page.goto(pathToFileURL(output).href);
    await expect(page.getByRole("heading", { name: "自制样例人工复核" })).toBeVisible();
    expect(await page.evaluate(() => (window as Window & { attacked?: boolean }).attacked)).toBeUndefined();
    await page.getByLabel("复核者代号").fill("browser-fixture");
    await page.getByLabel("本表由我人工复核").check();
    await page.getByLabel("我已核对全部样例预期", { exact: false }).check();
    const article = page.locator("article").first();
    await article.getByRole("button", { name: /开始\/继续计时/ }).click();
    await article.getByRole("combobox", { name: "判断", exact: true }).selectOption("correct");
    await article.getByRole("combobox", { name: "对应预期", exact: true }).selectOption("one");
    await article.getByLabel("判断理由", { exact: true }).fill("仅用于浏览器自动化验证，并非人类实测。");
    await article.getByRole("checkbox").check();
    await article.getByRole("button", { name: "暂停计时", exact: true }).click();
    await page.locator("article").last().getByRole("checkbox").check();
    await page.reload();
    await expect(article.getByLabel("判断理由", { exact: true })).toHaveValue("仅用于浏览器自动化验证，并非人类实测。");
    const [download] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "导出复核 JSON" }).click()]);
    const saved = join(directory, "saved.json"); await download.saveAs(saved);
    const review = JSON.parse(readFileSync(saved, "utf8"));
    expect(review.reviewer).toBe("browser-fixture");
    expect(review.records[0].review_seconds).toBeGreaterThan(0);
    expect(review.records[0].human_operations).toBeGreaterThanOrEqual(3);
    expect(review.records[1].review_seconds).toBeNull();
    expect(review.records[0].items[0].target).toBe("one");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  } finally { rmSync(directory, { recursive: true, force: true }); }
});
