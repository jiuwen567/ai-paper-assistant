export const serviceNames = {
  postgresql: "PostgreSQL / pgvector",
  neo4j: "Neo4j",
  seaweedfs: "SeaweedFS S3",
  redis: "Redis",
  worker: "Celery Worker",
} as const;

export type Service = keyof typeof serviceNames;
export type Health = {
  status: "ok" | "degraded";
  checks: Record<Service, "ok" | "unavailable">;
};

export async function fetchHealth(): Promise<Health> {
  const response = await fetch("/api/v1/health/ready/", {
    signal: AbortSignal.timeout(30000),
  });
  if (response.status !== 200 && response.status !== 503)
    throw new Error("API 返回异常，请检查服务日志。");
  const data: unknown = await response.json();
  if (
    !data ||
    typeof data !== "object" ||
    !("status" in data) ||
    !("checks" in data)
  ) {
    throw new Error("API 返回了无法识别的健康检查结果。");
  }
  const { status, checks } = data;
  if (
    !["ok", "degraded"].includes(String(status)) ||
    !checks ||
    typeof checks !== "object" ||
    !Object.keys(serviceNames).every(
      (key) =>
        key in checks &&
        ["ok", "unavailable"].includes(String(Reflect.get(checks, key))),
    )
  ) {
    throw new Error("API 健康检查结果不完整。");
  }
  const allReady = Object.keys(serviceNames).every(
    (key) => Reflect.get(checks, key) === "ok",
  );
  if (
    (status === "ok") !== allReady ||
    (response.status === 200) !== allReady
  ) {
    throw new Error("API 健康检查状态不一致。");
  }
  return data as Health;
}
