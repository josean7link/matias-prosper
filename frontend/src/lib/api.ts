/**
 * Tiny typed fetch wrapper. Same-origin paths only (proxied to backend via
 * next.config.js rewrites in dev; via kubernetes ingress in production).
 */
export async function api<T = unknown>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const url = path.startsWith("http") ? path : `/api${path.startsWith("/") ? path : "/" + path}`;
  const { headers: extraHeaders, ...rest } = init;
  // Don't force Content-Type when the body is FormData — the browser must set
  // the multipart boundary itself.
  const isFormData = typeof FormData !== "undefined" && rest.body instanceof FormData;
  const baseHeaders: Record<string, string> = isFormData
    ? {}
    : { "Content-Type": "application/json" };
  const res = await fetch(url, {
    credentials: "include",
    ...rest,
    headers: { ...baseHeaders, ...(extraHeaders || {}) },
  });
  if (!res.ok) {
    let detail: unknown = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? body.error ?? body.message ?? detail;
    } catch {}
    // FastAPI returns array-of-errors for validation failures; flatten to text
    if (Array.isArray(detail)) {
      detail = detail.map((d: any) => d?.msg || d?.message || JSON.stringify(d)).join("; ");
    } else if (detail && typeof detail === "object") {
      detail = JSON.stringify(detail);
    }
    throw new ApiError(res.status, String(detail));
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}
