const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");
const automator = require("miniprogram-automator");

const outputDir = path.resolve(__dirname, "../test-results");
const checks = [];
let miniProgram;
let requestMocked = false;

async function waitForStatus(page, expected, timeout = 15000) {
  const started = Date.now();
  while (Date.now() - started < timeout) {
    const data = await page.data();
    if (!data.loading && data.status === expected) return data;
    if (!data.loading && ["连接失败", "API 返回异常"].includes(data.status)) {
      throw new Error(`预期「${expected}」，实际「${data.status}」：${data.detail}`);
    }
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new Error(`等待「${expected}」超时`);
}

async function main() {
  await fs.mkdir(outputDir, { recursive: true });
  miniProgram = await automator.connect({
    wsEndpoint: process.env.MINIAPP_WS_ENDPOINT || "ws://127.0.0.1:9420",
  });

  const page = await miniProgram.reLaunch("/pages/index/index");
  assert.ok(page, "开发者工具应编译并打开首页");
  assert.equal(page.path, "pages/index/index");
  assert.equal(await page.data("status"), "尚未连接");
  const button = await page.$("button");
  assert.ok(button, "首页应包含连接检查按钮");
  checks.push("开发者工具编译、首页渲染与初始状态");

  // 正常连接必须走真实 wx.request，不用模拟结果代替双端联调。
  await button.tap();
  await waitForStatus(page, "API 已连接");
  const statusElement = await page.$(".status");
  assert.ok(statusElement);
  assert.equal(await statusElement.text(), "API 已连接");
  await miniProgram.screenshot({ path: path.join(outputDir, "connected.png") });
  checks.push("真实 wx.request → Django API → 成功反馈");

  // 后续两项只模拟请求结果，验证页面状态；报告明确区分真实与模拟。
  await miniProgram.mockWxMethod("request", async () => {
    await new Promise((resolve) => setTimeout(resolve, 2000));
    return { errMsg: "request:fail acceptance-test" };
  });
  requestMocked = true;
  await page.callMethod("checkConnection");
  assert.equal(await page.data("loading"), true);
  await waitForStatus(page, "连接失败");
  checks.push("模拟网络失败：加载状态、失败提示和按钮恢复");

  await miniProgram.mockWxMethod("request", {
    errMsg: "request:ok",
    statusCode: 503,
    data: { status: "degraded" },
  });
  await button.tap();
  const failure = await waitForStatus(page, "API 返回异常");
  assert.match(failure.detail, /HTTP 503/);
  checks.push("模拟 HTTP 503：异常响应提示");

  await miniProgram.restoreWxMethod("request");
  requestMocked = false;
  await button.tap();
  await waitForStatus(page, "API 已连接");
  checks.push("解除模拟后，真实 API 重试恢复");

  const system = await miniProgram.systemInfo();
  const { libVersion } = require("../project.config.json");
  assert.equal(system.SDKVersion, libVersion, "模拟器基础库与工程配置应一致");
  const report = {
    status: "passed",
    checkedAt: new Date().toISOString(),
    runtime: { SDKVersion: system.SDKVersion, platform: system.platform },
    checks,
    limitations: ["未执行真机预览、微信账号绑定或公众号授权"],
  };
  await fs.writeFile(path.join(outputDir, "acceptance.json"), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
}

const watchdog = setTimeout(() => {
  console.error("小程序验收超时，请检查工具登录、服务端口及项目编译状态。");
  process.exit(1);
}, 150000);
watchdog.unref();

main()
  .catch(async (error) => {
    console.error(`小程序验收失败：${error.message}`);
    await fs.writeFile(
      path.join(outputDir, "acceptance.json"),
      JSON.stringify({ status: "failed", checks, error: error.message }, null, 2),
    );
    process.exitCode = 1;
  })
  .finally(async () => {
    if (miniProgram) {
      if (requestMocked) await miniProgram.restoreWxMethod("request");
      await miniProgram.disconnect();
    }
    clearTimeout(watchdog);
  });
