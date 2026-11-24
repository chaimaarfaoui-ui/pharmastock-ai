const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type Role = "admin" | "manager" | "employee";
export interface User { id: number; email: string; full_name: string; role: Role; pharmacy_id: number; is_active: boolean }
interface Tokens { access_token: string; refresh_token: string }

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

// Tokens live in sessionStorage (cleared when the tab closes). An httpOnly-cookie flow is a
// planned hardening step; it needs a backend change and is not implemented yet.
const KEY = "pharmastock.tokens";
export const tokenStore = {
  get(): Tokens | null {
    if (typeof window === "undefined") return null;
    try { return JSON.parse(sessionStorage.getItem(KEY) ?? "null"); } catch { return null; }
  },
  set(t: Tokens) { sessionStorage.setItem(KEY, JSON.stringify(t)); },
  clear() { sessionStorage.removeItem(KEY); },
};

function errorMessage(body: unknown, fallback: string): string {
  const detail = (body as { detail?: unknown })?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((d) => d?.msg).filter(Boolean).join("; ") || fallback;
  return fallback;
}

async function raw(path: string, init: RequestInit & { token?: string; skipJson?: boolean } = {}) {
  const headers = new Headers(init.headers);
  if (init.body && !init.skipJson) headers.set("Content-Type", "application/json");
  if (init.token) headers.set("Authorization", `Bearer ${init.token}`);
  let res: Response;
  try { res = await fetch(`${BASE}/api/v1${path}`, { ...init, headers }); }
  catch { throw new ApiError(0, "Cannot reach the server. Is the backend running?"); }
  return res;
}

async function parse<T>(res: Response): Promise<T> {
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, errorMessage(body, `Request failed (${res.status})`));
  return body as T;
}

let refreshing: Promise<boolean> | null = null;
async function tryRefresh(): Promise<boolean> {
  const t = tokenStore.get();
  if (!t) return false;
  refreshing ??= (async () => {
    const res = await raw("/auth/refresh", { method: "POST", body: JSON.stringify({ refresh_token: t.refresh_token }) });
    if (!res.ok) { tokenStore.clear(); return false; }
    tokenStore.set(await res.json());
    return true;
  })().finally(() => { refreshing = null; });
  return refreshing;
}

/** Authenticated request: retries once after a token refresh on 401. */
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const go = () => raw(path, { ...init, token: tokenStore.get()?.access_token });
  let res = await go();
  if (res.status === 401 && (await tryRefresh())) res = await go();
  return parse<T>(res);
}

export const auth = {
  async login(email: string, password: string) {
    const res = await raw("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) });
    tokenStore.set(await parse<Tokens>(res));
  },
  async register(p: { pharmacy_name: string; full_name: string; email: string; password: string }) {
    await parse<User>(await raw("/auth/register", { method: "POST", body: JSON.stringify(p) }));
    await auth.login(p.email, p.password);
  },
  me: () => api<User>("/auth/me"),
  /** Revokes the refresh token on the server (best effort), then forgets the tokens locally. */
  logout: () => {
    const t = tokenStore.get();
    tokenStore.clear();
    if (t) void raw("/auth/logout", { method: "POST", body: JSON.stringify({ refresh_token: t.refresh_token }) }).catch(() => undefined);
  },
};

export const users = {
  list: () => api<User[]>("/users"),
  create: (b: { full_name: string; email: string; password: string; role: Role }) =>
    api<User>("/users", { method: "POST", body: JSON.stringify(b) }),
  deactivate: (id: number) => api<User>(`/users/${id}/deactivate`, { method: "PATCH" }),
};

// ---- helpers added for the operational / analytics pages
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type Row = Record<string, any>;
export interface Page<T> { items: T[]; total: number; limit: number; offset: number }

export const qs = (o: Record<string, string | number | boolean | null | undefined>) => {
  const p = new URLSearchParams();
  Object.entries(o).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== "" && v !== false) p.set(k, String(v)); });
  const s = p.toString();
  return s ? `?${s}` : "";
};
export const post = <T = Row>(path: string, body?: unknown) => api<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
export const patch = <T = Row>(path: string, body?: unknown) => api<T>(path, { method: "PATCH", body: body === undefined ? undefined : JSON.stringify(body) });
export const put = <T = Row>(path: string, body?: unknown) => api<T>(path, { method: "PUT", body: JSON.stringify(body) });

/** Starts a background job and polls /jobs/{id} until it finishes. */
export async function runJob(path: string, body: unknown, onProgress?: (p: number) => void): Promise<Row> {
  const { job_id } = await post<{ job_id: string }>(path, body);
  for (;;) {
    await new Promise((r) => setTimeout(r, 900));
    const j = await api<Row>(`/jobs/${job_id}`);
    onProgress?.(j.progress ?? 0);
    if (j.status === "succeeded") return j.result ?? {};
    if (j.status === "failed") throw new ApiError(500, j.error ?? "Job failed");
  }
}

/** Authenticated file download (the API needs the bearer token, so a plain link will not work). */
export async function downloadFile(path: string, filename: string) {
  const t = tokenStore.get();
  const res = await fetch(`${BASE}/api/v1${path}`, { headers: t ? { Authorization: `Bearer ${t.access_token}` } : {} });
  if (!res.ok) throw new ApiError(res.status, "Download failed");
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
}

/** Multipart upload (CSV import). Same login and one-time refresh retry as api(), but no JSON content type. */
export async function upload<T = Row>(path: string, form: FormData): Promise<T> {
  const go = () => raw(path, { method: "POST", body: form, token: tokenStore.get()?.access_token, skipJson: true });
  let res = await go();
  if (res.status === 401 && (await tryRefresh())) res = await go();
  return parse<T>(res);
}
