export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

let csrfToken = "";
function errorText(value: unknown): string {
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.map(errorText).join("；");
  if (value && typeof value === "object") return Object.values(value).map(errorText).join("；");
  return "请求失败，请稍后重试。";
}

export async function request<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const response = await fetch(`/api/v1/${path}`, {
    method,
    credentials: "same-origin",
    cache: "no-store",
    headers: body instanceof FormData ? { "X-CSRFToken": csrfToken } : { "Content-Type": "application/json", "X-CSRFToken": csrfToken },
    body: body instanceof FormData ? body : body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(body instanceof FormData ? 60000 : 15000),
  });
  const data: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    throw new ApiError(response.status, data ? errorText(data) : "请求失败，请刷新登录状态后重试。");
  }
  return data as T;
}

export function setCsrfToken(value: string) { csrfToken = value; }
