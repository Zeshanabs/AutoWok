import { API_BASE_URL } from "@/lib/api";

const MAX_REPORTS_PER_PAGE = 10;
const seen = new Set<string>();
let sent = 0;

export type ClientErrorReport = {
  message: string;
  stack?: string;
  source: "error-boundary" | "window-error" | "unhandled-rejection";
  digest?: string;
};

/**
 * Sends a runtime error to the backend error-reporting endpoint. Reports are
 * de-duplicated and capped per page load, never include form values or
 * cookies, and failures are ignored (reporting must never break the page).
 */
export function reportClientError(report: ClientErrorReport): void {
  if (typeof window === "undefined") return;
  const key = `${report.source}:${report.message}`;
  if (seen.has(key) || sent >= MAX_REPORTS_PER_PAGE) return;
  seen.add(key);
  sent += 1;
  const body = JSON.stringify({
    message: report.message.slice(0, 500),
    stack: report.stack?.slice(0, 4000),
    source: report.source,
    digest: report.digest?.slice(0, 100),
    path: window.location.pathname.slice(0, 300),
    user_agent: navigator.userAgent.slice(0, 300),
  });
  try {
    void fetch(`${API_BASE_URL}/api/v1/client-errors`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF-Protection": "1" },
      credentials: "include",
      keepalive: true,
      body,
    }).catch(() => undefined);
  } catch {
    // Ignore: reporting is best effort.
  }
}

/** Test helper. */
export function resetClientErrorReporting(): void {
  seen.clear();
  sent = 0;
}
