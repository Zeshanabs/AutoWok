import { afterEach, describe, expect, it, vi } from "vitest";

import { apiRequest } from "@/lib/api";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("cookie-based API client", () => {
  it("uses credentials and the CSRF header for state-changing requests", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await apiRequest("/auth/logout", { method: "POST" });

    const request = fetchMock.mock.calls[0][1] as RequestInit;
    expect(request.credentials).toBe("include");
    expect(new Headers(request.headers).get("X-CSRF-Protection")).toBe("1");
    expect(new Headers(request.headers).has("Authorization")).toBe(false);
  });

  it("notifies the session provider when an authenticated API call expires", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "Authentication required." }), {
        status: 401,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const expired = vi.fn();
    window.addEventListener("autowok:session-expired", expired);

    await expect(apiRequest("/workspaces")).rejects.toThrow(
      "Authentication required.",
    );
    expect(expired).toHaveBeenCalledOnce();
    window.removeEventListener("autowok:session-expired", expired);
  });
});
