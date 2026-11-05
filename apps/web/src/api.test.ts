import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchHealth } from "./api";

const checks = {
  postgresql: "ok",
  neo4j: "ok",
  seaweedfs: "ok",
  redis: "ok",
  worker: "ok",
};
afterEach(() => vi.unstubAllGlobals());
function respond(body: unknown, status = 200) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status })),
  );
}

describe("健康检查协议", () => {
  it("展示真实就绪结果", async () => {
    respond({ status: "ok", checks });
    expect((await fetchHealth()).status).toBe("ok");
  });
  it("保留 503 中的服务故障状态", async () => {
    respond(
      { status: "degraded", checks: { ...checks, worker: "unavailable" } },
      503,
    );
    expect((await fetchHealth()).checks.worker).toBe("unavailable");
  });
  it("不将网关错误当作依赖故障", async () => {
    respond({}, 502);
    await expect(fetchHealth()).rejects.toThrow("API 返回异常");
  });
  it("拒绝缺失服务的响应", async () => {
    respond({ status: "ok", checks: {} });
    await expect(fetchHealth()).rejects.toThrow("不完整");
  });
  it("拒绝状态与服务详情不一致的响应", async () => {
    respond({ status: "ok", checks: { ...checks, worker: "unavailable" } });
    await expect(fetchHealth()).rejects.toThrow("不一致");
  });
  it("网络中断时交由页面显示错误", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("网络中断")),
    );
    await expect(fetchHealth()).rejects.toThrow("网络中断");
  });
});
