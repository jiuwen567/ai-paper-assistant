import { request, setCsrfToken } from "@/api/client";

export type User = { id: number; username: string };
export type Session = { user: User | null; csrf_token: string };
export async function session(method = "GET", body?: unknown): Promise<Session> {
  const result = await request<Session>("auth/session/", method, body);
  setCsrfToken(result.csrf_token);
  return result;
}

export async function logout(): Promise<void> {
  const result = await request<Session>("auth/logout/", "POST");
  setCsrfToken(result.csrf_token);
}
