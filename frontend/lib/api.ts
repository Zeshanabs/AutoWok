const API_BASE_URL =
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
