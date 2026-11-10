import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useAuth } from "@/components/auth-provider";
import { addDays, addMonths, formatInZone, splitLocal, todayInZone, weekdayIndex } from "@/lib/timezones";
import CalendarPage from "./page";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}));
vi.mock("@/components/auth-provider", () => ({ useAuth: vi.fn() }));

const workspace = { id: "ws-1", name: "WS", slug: "ws", role: "OWNER" };

function calendarResponse(view: string) {
  return {
    view,
    timezone: "Asia/Karachi",
    anchor_date: "2027-03-10",
    range_start: "2027-02-28T19:00:00Z",
    range_end: "2027-04-04T19:00:00Z",
    days: view === "month" ? Array.from({ length: 35 }, (_, i) => addDays("2027-03-01", i)) : ["2027-03-10"],
    items: [
      {
        kind: "scheduled", id: "s1", scheduled_post_id: "s1", publication_id: null, project_id: "p1", draft_id: "d1",
        title: "Launch day", caption_preview: "Big news", brand_id: null, brand_name: "Brand", platform: "instagram",
        social_account_id: "a1", account_name: "autowok", at: "2027-03-10T04:00:00Z", local_time: "09:00",
        local_date: "2027-03-10", timezone: "Asia/Karachi", status: "failed", approval_status: "approved",
        content_changed: false, last_error: "Token expired", permalink: null, can_edit: true, can_cancel: true,
      },
    ],
    unscheduled: [{ project_id: "p2", draft_id: "d2", title: "Ready one", caption_preview: null, platform: "facebook", brand_id: null, brand_name: null }],
  };
}

describe("timezone helpers", () => {
  it("does plain date arithmetic", () => {
    expect(addDays("2027-02-28", 1)).toBe("2027-03-01");
    expect(addDays("2027-03-01", -1)).toBe("2027-02-28");
    expect(addMonths("2027-01-31", 1)).toBe("2027-02-01");
    expect(weekdayIndex("2027-03-08")).toBe(0); // Monday
    expect(splitLocal("2027-03-10T09:30")).toEqual({ date: "2027-03-10", time: "09:30" });
  });

  it("formats instants in the requested zone", () => {
    expect(formatInZone("2027-03-10T04:00:00Z", "Asia/Karachi", { weekday: undefined, year: undefined, day: undefined, month: undefined, hourCycle: "h23" })).toContain("09:00");
    expect(todayInZone("UTC")).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });
});

describe("calendar page", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.mocked(useAuth).mockReturnValue({
      user: { id: "u", full_name: "U", email: "u@example.com", is_active: true, is_verified: true },
      workspaces: [workspace],
      selectedWorkspace: workspace,
      status: "authenticated",
      error: null,
      refreshUser: vi.fn(),
      selectWorkspace: vi.fn(),
      login: vi.fn(),
      register: vi.fn(),
      logout: vi.fn(),
    } as unknown as ReturnType<typeof useAuth>);
    fetchMock.mockImplementation(async (url: string) => {
      const body = url.includes("/me/preferences")
        ? { timezone: "Asia/Karachi", timezone_is_default: false, default_timezone: "UTC" }
        : url.includes("/calendar")
          ? calendarResponse(new URL(url).searchParams.get("view") ?? "month")
          : [];
      return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
    });
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("loads the month in the user's timezone and shows items, status, and unscheduled content", async () => {
    render(<CalendarPage />);
    await waitFor(() => expect(screen.getAllByText("Launch day").length).toBeGreaterThan(0));
    const calendarCall = fetchMock.mock.calls.map(([url]) => String(url)).find((url) => url.includes("/calendar"));
    expect(calendarCall).toContain("view=month");
    expect(calendarCall).toContain("timezone=Asia%2FKarachi");
    expect(screen.getByText("Ready one")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Schedule post" })).toBeTruthy();
    expect(screen.getAllByTitle(/Failed/).length).toBeGreaterThan(0);
  });

  it("switches views and applies filters through the API", async () => {
    render(<CalendarPage />);
    await waitFor(() => expect(screen.getAllByText("Launch day").length).toBeGreaterThan(0));
    fireEvent.click(screen.getByRole("button", { name: "list" }));
    fireEvent.change(screen.getByLabelText("Filter by platform"), { target: { value: "instagram" } });
    fireEvent.change(screen.getByLabelText("Filter by status"), { target: { value: "failed" } });
    await waitFor(() => {
      const last = String(fetchMock.mock.calls.filter(([url]) => String(url).includes("/calendar")).at(-1)?.[0]);
      expect(last).toContain("view=list");
      expect(last).toContain("platform=instagram");
      expect(last).toContain("status=failed");
    });
    expect(await screen.findByText("Token expired")).toBeTruthy();
  });
});
