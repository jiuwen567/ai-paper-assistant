export const aiActions = {
  reading: "文献阅读",
  comparison: "文献比较",
  review: "原稿诊断",
  expression: "表达建议",
  feedback: "反馈拆解",
} as const;
export type AIAction = keyof typeof aiActions;
export type User = { id: number; username: string };
export type Session = { user: User | null; csrf_token: string };
export type Policy = {
  id: number;
  version: number;
  source: string;
  source_version: string;
  notes: string;
  verified: boolean;
  allowed_actions: AIAction[];
  created_by: string;
  created_at: string;
};
export type ProjectFields = {
  name: string; paper_type: string; requirements: string; template: string;
};
export type Project = ProjectFields & {
  id: string;
  version: number;
  role: "author" | "reviewer";
  is_owner: boolean;
  owner_name: string;
  policy: Policy;
};
export type Member = { user_id: number; username: string; role: "author" | "reviewer" };
export type Page<T> = { count: number; next: string | null; previous: string | null; results: T[] };

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

export async function session(method = "GET", body?: unknown): Promise<Session> {
  const result = await request<Session>("auth/session/", method, body);
  csrfToken = result.csrf_token;
  return result;
}

export async function logout(): Promise<void> {
  const result = await request<Session>("auth/logout/", "POST");
  csrfToken = result.csrf_token;
}
