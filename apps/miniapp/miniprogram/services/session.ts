import { API_BASE_URL } from "../config/api";
export type User = { id: number; username: string };
type Session = { token: string; expires_at: string; user: User };
export type LoginResult = Partial<Session> & { bound: boolean; binding_code?: string; expires_at: string };
const storageKey = "paper-session";
export class RequestError extends Error {
  constructor(public status: number, message: string) { super(message); }
}
export function clearSession() { wx.removeStorageSync(storageKey); }
export function savedSession(): Session | null {
  const saved = wx.getStorageSync(storageKey) as Session | undefined;
  if (!saved?.token || !Number.isFinite(Date.parse(saved.expires_at)) || Date.parse(saved.expires_at) <= Date.now()) {
    clearSession();
    return null;
  }
  return saved;
}
function errorMessage(data: unknown): string {
  if (typeof data === "string") return data;
  if (Array.isArray(data)) return data.map(errorMessage).join("；");
  if (data && typeof data === "object") return Object.values(data).map(errorMessage).join("；");
  return "请求失败，请重试。";
}
export function request<T extends object = Record<string, unknown>>(path: string, method: "GET" | "POST" | "PUT" | "DELETE" = "GET", data?: object): Promise<T> {
  const token = savedSession()?.token;
  return new Promise((resolve, reject) => wx.request<T>({
    url: `${API_BASE_URL}/api/v1/${path}`, method, data, timeout: 10000,
    header: { "content-type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    success(response) {
      if (response.statusCode >= 200 && response.statusCode < 300) resolve(response.data);
      else {
        if ([401, 403].includes(response.statusCode)) clearSession();
        reject(new RequestError(response.statusCode, errorMessage(response.data)));
      }
    },
    fail: () => reject(new Error("连接失败，请检查网络后重试。")),
  }));
}
export async function login(): Promise<LoginResult> {
  clearSession();
  const code = await new Promise<string>((resolve, reject) => wx.login({
    success: result => result.code ? resolve(result.code) : reject(new Error("微信登录失败，请重试。")),
    fail: () => reject(new Error("微信登录失败，请重试。")),
  }));
  const result = await request<LoginResult>("auth/wechat/login/", "POST", { code });
  if (result.bound && result.token && result.user) {
    wx.setStorageSync(storageKey, { token: result.token, expires_at: result.expires_at, user: result.user });
  }
  return result;
}

export function uploadFile<T extends object>(path: string, filePath: string): Promise<T> {
  return new Promise((resolve, reject) => wx.uploadFile({
    url: `${API_BASE_URL}/api/v1/${path}`, filePath, name: "file", timeout: 60000,
    header: { Authorization: `Bearer ${savedSession()?.token ?? ''}` },
    success(response) {
      let data: T;
      try { data = JSON.parse(response.data) as T; }
      catch { reject(new Error("上传响应异常，请刷新版本状态后重试。")); return; }
      if (response.statusCode >= 200 && response.statusCode < 300) resolve(data);
      else {
        if ([401, 403].includes(response.statusCode)) clearSession();
        reject(new RequestError(response.statusCode, errorMessage(data)));
      }
    },
    fail: () => reject(new Error("上传中断，可重试同一文件。")),
  }));
}

export function downloadDocument(path: string, fileType: "pdf" | "docx"): Promise<void> {
  return new Promise((resolve, reject) => wx.downloadFile({
    url: `${API_BASE_URL}/api/v1/${path}`, timeout: 60000,
    header: { Authorization: `Bearer ${savedSession()?.token ?? ''}` },
    success(response) {
      if (response.statusCode !== 200) {
        if ([401, 403].includes(response.statusCode)) clearSession();
        reject(new RequestError(response.statusCode, "文件不可用或访问权限已变化。")); return;
      }
      wx.openDocument({ filePath: response.tempFilePath, fileType, showMenu: true,
        success: () => resolve(), fail: () => reject(new Error("文件已下载，但微信无法预览此文档。")) });
    },
    fail: () => reject(new Error("下载失败，请检查网络后重试。")),
  }));
}
