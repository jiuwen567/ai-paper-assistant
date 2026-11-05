import { expect, test } from "@playwright/test";

test("Web 代理请求真实 Django API，并能从连接失败恢复", async ({
  page,
}, testInfo) => {
  const live = await page.request.get("/api/v1/health/live/");
  expect(live.ok()).toBeTruthy();
  expect((await live.json()).service).toBe("api");
  const responsePromise = page.waitForResponse("**/api/v1/health/ready/");
  await page.goto("/");
  const response = await responsePromise;
  expect([200, 503]).toContain(response.status());
  const report = await response.json();
  expect(Object.keys(report.checks)).toHaveLength(5);
  await expect(page.getByRole("button", { name: "重新检查" })).toBeEnabled();
  await expect(page.getByRole("heading", { name: "API 连接失败" })).toHaveCount(
    0,
  );
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: testInfo.outputPath("environment.png"),
    fullPage: true,
  });

  await page.route("**/api/v1/health/ready/", (route) => route.abort());
  await page.getByRole("button", { name: "重新检查" }).click();
  await expect(
    page.getByRole("heading", { name: "API 连接失败" }),
  ).toBeVisible();
  await expect(page.getByText("已就绪", { exact: true })).toHaveCount(0);
  await page.unroute("**/api/v1/health/ready/");
  await page.getByRole("button", { name: "重新检查" }).click();
  await expect(page.getByRole("button", { name: "重新检查" })).toBeEnabled();
  await expect(page.getByRole("heading", { name: "API 连接失败" })).toHaveCount(
    0,
  );
});

test("公众号说明页可直接打开并标明未接入能力", async ({ page }) => {
  await page.goto("/wechat");
  await expect(
    page.getByRole("heading", { name: "微信接入" }),
  ).toBeVisible();
  await expect(
    page.getByText("消息回调尚未接入。", { exact: false }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
});
