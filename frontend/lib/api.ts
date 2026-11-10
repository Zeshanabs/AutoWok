export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function apiRequest<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const method = (options.method ?? "GET").toUpperCase();
  const headers = new Headers(options.headers);
  if (options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    headers.set("X-CSRF-Protection", "1");
  }

  const response = await fetch(`${API_BASE_URL}/api/v1${path}`, {
    ...options,
    method,
    headers,
    credentials: "include",
  });
  if (response.status === 204) {
    return undefined as T;
  }

  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    if (
      response.status === 401 &&
      typeof window !== "undefined" &&
      !/^\/auth\/(me|login|register|logout|logout-all)$/.test(path)
    ) {
      window.dispatchEvent(new Event("autowok:session-expired"));
    }
    let message = "The request could not be completed.";
    if (typeof body === "object" && body !== null && "detail" in body) {
      const detail = body.detail;
      message =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((item) => item.msg).filter(Boolean).join(" ")
            : message;
    }
    throw new ApiError(message, response.status);
  }
  return body as T;
}

function extractDetail(body: unknown, fallback: string): string {
  if (typeof body === "object" && body !== null && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail.map((item: { msg?: string }) => item?.msg).filter(Boolean).join(" ") || fallback;
    }
  }
  return fallback;
}

/** Multipart upload with progress reporting (fetch cannot report upload progress). */
export function uploadWithProgress<T>(
  path: string,
  form: FormData,
  onProgress?: (fraction: number) => void,
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", `${API_BASE_URL}/api/v1${path}`);
    request.withCredentials = true;
    request.setRequestHeader("X-CSRF-Protection", "1");
    request.upload.onprogress = (event) => {
      if (event.lengthComputable && onProgress) onProgress(event.loaded / event.total);
    };
    request.onerror = () => reject(new ApiError("The upload failed. Check your connection and try again.", 0));
    request.onload = () => {
      let body: unknown = null;
      try {
        body = JSON.parse(request.responseText);
      } catch {
        body = null;
      }
      if (request.status >= 200 && request.status < 300) {
        resolve(body as T);
      } else {
        if (request.status === 401 && typeof window !== "undefined") {
          window.dispatchEvent(new Event("autowok:session-expired"));
        }
        reject(new ApiError(extractDetail(body, "The upload could not be completed."), request.status));
      }
    };
    request.send(form);
  });
}

export function newIdempotencyKey(prefix = "req"): string {
  const random =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  return `${prefix}-${random}`;
}
