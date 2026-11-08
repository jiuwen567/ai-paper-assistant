import { expect } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { execFileSync } from "node:child_process";
import { test, root, login, activate } from "./fixtures/accounts";

test("材料原件上传、新版本及授权下载", async ({ page, accounts }) => {
  await page.goto("/");
  await login(page, accounts.owner, accounts.password);
  await page.getByRole("button", { name: "创建项目" }).click();
  await page.getByLabel("项目名称", { exact: true }).fill("自制材料项目");
  await page.getByRole("button", { name: "创建", exact: true }).click();
  const panel = page.getByRole("region", { name: "材料", exact: true });
  await activate(page, '材料');
  await expect(panel.getByText("上传第一份文献或研究材料", { exact: true })).toBeVisible();
  await panel.getByLabel("材料名称", { exact: true }).fill("自制研究记录");
  const first = Buffer.from("自制材料第一版");
  const chooser = page.waitForEvent('filechooser');
  await panel.getByRole('button', { name: '选择文件', exact: true }).focus();
  await page.keyboard.press('Enter');
  await (await chooser).setFiles({ name: "self-authored.txt", mimeType: "text/plain", buffer: first });
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
  await activate(page, '材料');
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
