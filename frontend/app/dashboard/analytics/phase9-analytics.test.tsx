import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useAuth } from "@/components/auth-provider";
import { LineChart } from "@/components/analytics/charts";
import AnalyticsLayout from "./layout";
import AnalyticsOverviewPage from "./page";
import AnalyticsPostsPage from "./posts/page";
import AnalyticsReportsPage from "./reports/page";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/dashboard/analytics",
}));
vi.mock("@/components/auth-provider", () => ({ useAuth: vi.fn() }));

const workspace = { id: "ws-1", name: "WS", slug: "ws", role: "OWNER" };
const fbAccount = { id: "fb-1", workspace_id: "ws-1", brand_id: "b-1", platform: "facebook_page", platform_account_id: "page-1", username: "autowok", display_name: "Autowok Page", profile_image_url: null, account_type: "PAGE", parent_account_id: null, connection_status: "connected", granted_scopes: ["read_insights"], connected_by: "u", connected_at: "2026-11-01T00:00:00Z", last_verified_at: null, last_error_code: null, created_at: "2026-11-01T00:00:00Z", updated_at: "2026-11-01T00:00:00Z" };
const igAccount = { ...fbAccount, id: "ig-1", platform: "instagram", platform_account_id: "ig", display_name: "autowok", account_type: "BUSINESS" };

function platformEntry(platform: string, value: number | null, extra: Record<string, unknown> = {}) {
  return {
    platform,
    platform_label: platform === "instagram" ? "Instagram" : "Facebook Page",
    value,
    previous_value: value === null ? null : value / 2,
    change_percent: value === null ? null : 100,
    availability: value === null ? "unavailable" : "available",
    reason: value === null ? "The read_insights permission was not granted when the account was connected. Reconnect Meta to collect insights." : null,
    definition: "Definition text",
    source_metric: platform === "instagram" ? "reach" : "page_total_media_view_unique",
    unit: "count",
    aggregation: "sum",
    collected_at: "2026-11-10T06:00:00Z",
    accounts_with_data: value === null ? 0 : 1,
    accounts_total: 1,
    days_with_data: 28,
    ...extra,
  };
}

const post = {
  id: "post-1", workspace_id: "ws-1", brand_id: "b-1", social_account_id: "ig-1", account_name: "autowok", platform: "instagram", platform_label: "Instagram",
  publication_id: "pub-1", project_id: "proj-1", project_title: "Launch post", draft_id: "d-1", external_post_id: "ig-media-1", permalink: "https://www.instagram.com/p/x/",
  published_at: "2026-11-05T10:00:00Z", content_format: "image", content_format_label: "Image", caption_preview: "Big launch", thumbnail_url: null,
  metrics: { reach: 900, views: 1500, engagements: 66, likes: 40, comments: 6, shares: 9, saves: 11, clicks: null, video_views: null },
  extra_metrics: {}, metric_availability: { clicks: "not_supported_on_platform", video_views: "not_supported_on_platform" },
  engagement_rate: 7.33, engagement_rate_note: null, engagement_definition: "total_interactions", reach_definition: "reach", source: "autowok",
  collected_at: "2026-11-10T06:00:00Z", api_version: "v26.0",
};

function overviewResponse(url: URL) {
  const platform = url.searchParams.get("platform");
  const platforms = platform ? [platform] : ["facebook_page", "instagram"];
  const accounts = [fbAccount, igAccount].filter((account) => platforms.includes(account.platform));
  return {
    filters: { start: url.searchParams.get("start"), end: url.searchParams.get("end"), days: 28, previous_start: "2026-09-16", previous_end: "2026-10-13", brand_id: null, platform, social_account_id: null, account_ids: accounts.map((a) => a.id), timezone_note: "Daily values follow Meta's reporting day." },
    accounts: accounts.map((account) => ({ social_account_id: account.id, account_name: account.display_name, platform: account.platform, connection_status: "connected", last_synced_at: "2026-11-10T06:00:00Z", last_sync_status: "succeeded", last_error: null, last_error_category: null, next_attempt_at: null, active_job_id: null, insights_available: true, can_sync: true, missing_permissions: [], notes: [] })),
    metrics: [
      { key: "followers", label: "Followers", comparable: true, combined_value: platforms.length === 2 ? 2000 : null, combined_note: platforms.length === 2 ? "Sum of the platform values above" : null, platforms: platforms.map((p) => platformEntry(p, p === "instagram" ? 800 : 1200, { aggregation: "last" })) },
      { key: "reach", label: "Reach / unique viewers", comparable: true, combined_value: null, combined_note: null, platforms: platforms.map((p) => platformEntry(p, p === "instagram" ? 2800 : null)) },
      { key: "engagements", label: "Engagements (platform definitions differ)", comparable: false, combined_value: null, combined_note: null, platforms: platforms.map((p) => platformEntry(p, 420)) },
    ],
    follower_growth: accounts.map((account) => ({ social_account_id: account.id, account_name: account.display_name, platform: account.platform, change: null, snapshots: 1, latest: 800, note: "At least two daily follower snapshots are needed to calculate growth." })),
    published_posts: { total: 5, by_platform: { facebook_page: 3, instagram: 2 }, from_autowok: 1, previous_total: 4, change_percent: 25 },
    top_posts: [post],
    freshness: { newest_collected_at: "2026-11-10T06:00:00Z", oldest_collected_at: "2026-11-10T06:00:00Z" },
    notes: ["Totals are shown per platform."],
  };
}

function timeseriesResponse(url: URL) {
  const metric = url.searchParams.get("metric");
  return {
    metric, group_by: "platform", start: "2026-10-14", end: "2026-11-10",
    series: [
      { key: "facebook_page", label: "Facebook Page", platform: "facebook_page", metric_label: "Unique viewers", definition: "FB def", source_metric: "page_total_media_view_unique", unit: "count", supported: metric !== "saves", has_data: metric === "reach", points: [{ date: "2026-11-09", value: metric === "reach" ? 80 : null }, { date: "2026-11-10", value: metric === "reach" ? 90 : null }] },
      { key: "instagram", label: "Instagram", platform: "instagram", metric_label: "Reach", definition: "IG def", source_metric: "reach", unit: "count", supported: true, has_data: metric === "reach", points: [{ date: "2026-11-09", value: metric === "reach" ? 100 : null }, { date: "2026-11-10", value: metric === "reach" ? 120 : null }] },
    ],
  };
}

const syncStatus = { accounts: [{ social_account_id: "fb-1", account_name: "Autowok Page", platform: "facebook_page", connection_status: "connected", last_synced_at: null, last_sync_status: null, last_error: null, last_error_category: null, next_attempt_at: null, active_job_id: null, insights_available: false, can_sync: true, missing_permissions: ["read_insights"], notes: ["Insights need the read_insights permission. Reconnect Meta and grant it; follower and like counts are still collected."] }], active_jobs: 0, sync_interval_hours: 12 };

function respond(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("analytics dashboard", () => {
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
    fetchMock.mockImplementation(async (input: string | URL, init?: RequestInit) => {
      const url = new URL(String(input));
      const path = url.pathname;
      if (path.endsWith("/brands")) return respond([{ id: "b-1", name: "Brand", status: "ACTIVE" }]);
      if (path.endsWith("/social-accounts")) return respond([fbAccount, igAccount]);
      if (path.endsWith("/analytics/sync/status")) return respond(syncStatus);
      if (path.endsWith("/analytics/sync") && init?.method === "POST") return respond({ jobs: [{ id: "j1" }], skipped: [] }, 202);
      if (path.endsWith("/analytics/overview")) return respond(overviewResponse(url));
      if (path.endsWith("/analytics/timeseries")) return respond(timeseriesResponse(url));
      if (path.endsWith("/analytics/platforms/compare")) return respond({ filters: {}, platforms: [{ key: "facebook_page", label: "Facebook Page", accounts: 1 }, { key: "instagram", label: "Instagram", accounts: 1 }], account_metrics: [], post_metrics: [{ key: "engagements", label: "Engagements", comparable: false, note: "Not directly comparable", platforms: [{ platform: "facebook_page", platform_label: "Facebook Page", total: 222, average_per_post: 74, posts_with_data: 3, posts_total: 3, definition: "FB", source_metric: "reactions + comments + shares + clicks", availability: "available" }, { platform: "instagram", platform_label: "Instagram", total: 132, average_per_post: 66, posts_with_data: 2, posts_total: 2, definition: "IG", source_metric: "total_interactions", availability: "available" }] }], engagement_rates: [], meaningful: true, note: "Only metrics marked comparable measure the same thing on both platforms." });
      if (path.endsWith("/analytics/posts")) return respond({ total: 1, offset: 0, limit: 25, items: [post] });
      if (path.endsWith("/analytics/reports")) return respond({ title: "Autowok analytics report", generated_at: "2026-11-10T06:00:00Z", period: { start: "2026-10-14", end: "2026-11-10", days: 28 }, previous_period: { start: "2026-09-16", end: "2026-10-13" }, brand: { id: null, name: null }, platform_filter: null, accounts: [{ id: "fb-1", display_name: "Autowok Page", username: null, platform: "facebook_page", platform_label: "Facebook Page", connection_status: "connected" }], key_metrics: [], follower_growth: [], published_posts: { total: 5, by_platform: {}, from_autowok: 1, previous_total: 4, change_percent: 25 }, account_insights: [], posts: [post], definitions: [{ key: "reach" }], missing_data: ["Facebook Page - Saves: not reported"], collection: { newest_collected_at: "2026-11-10T06:00:00Z", note: "Each value shows when it was retrieved from Meta." } });
      return respond({ detail: `No mock for ${path}` }, 404);
    });
    vi.stubGlobal("fetch", fetchMock);
    window.sessionStorage.clear();
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  const calledUrls = () => fetchMock.mock.calls.map(([url]) => String(url));

  it("shows per-platform values, marks unavailable metrics and keeps definitions", async () => {
    render(
      <AnalyticsLayout>
        <AnalyticsOverviewPage />
      </AnalyticsLayout>,
    );
    const followers = await screen.findByRole("article", { name: "Followers" });
    expect(within(followers).getByText("1,200")).toBeTruthy();
    expect(within(followers).getByText("800")).toBeTruthy();
    expect(within(followers).getByText(/Combined:/)).toBeTruthy();
    const reach = screen.getByRole("article", { name: "Reach / unique viewers" });
    expect(within(reach).getByText("Not available")).toBeTruthy();
    expect(within(reach).getByText(/read_insights permission was not granted/)).toBeTruthy();
    expect(within(reach).getByText("2,800")).toBeTruthy();
    expect(within(reach).queryByText("0")).toBeNull();
    const engagements = screen.getByRole("article", { name: "Engagements (platform definitions differ)" });
    expect(within(engagements).getByText(/Shown per platform only/)).toBeTruthy();
    expect(within(engagements).queryByText(/Combined:/)).toBeNull();
    expect(screen.getAllByText("Definition (page_total_media_view_unique)").length).toBeGreaterThan(0);
    expect(screen.getByText(/Insights need the read_insights permission/)).toBeTruthy();
    const overviewCall = calledUrls().find((url) => url.includes("/analytics/overview"));
    expect(overviewCall).toContain("start=");
    expect(overviewCall).not.toContain("platform=");
    await waitFor(() => expect(screen.getByRole("img", { name: /Reach over time/ })).toBeTruthy());
    expect(screen.getByText("Platform comparison")).toBeTruthy();
    expect(screen.getByText("Big launch")).toBeTruthy();
  });

  it("applies platform, account and date filters through the API and hides the cross-platform comparison", async () => {
    render(
      <AnalyticsLayout>
        <AnalyticsOverviewPage />
      </AnalyticsLayout>,
    );
    await screen.findByRole("article", { name: "Followers" });
    fireEvent.change(screen.getByLabelText("Filter by platform"), { target: { value: "instagram" } });
    await waitFor(() => {
      const last = calledUrls().filter((url) => url.includes("/analytics/overview")).at(-1) ?? "";
      expect(last).toContain("platform=instagram");
    });
    expect(screen.queryByText("Platform comparison")).toBeNull();
    const accountSelect = screen.getByLabelText("Filter by account") as HTMLSelectElement;
    expect([...accountSelect.options].map((option) => option.textContent)).toEqual(["All accounts", "autowok · Instagram"]);
    fireEvent.change(accountSelect, { target: { value: "ig-1" } });
    await waitFor(() => expect(calledUrls().filter((url) => url.includes("/analytics/overview")).at(-1)).toContain("social_account_id=ig-1"));
    fireEvent.click(screen.getByRole("button", { name: "Last 7 days" }));
    await waitFor(() => {
      const last = new URL(calledUrls().filter((url) => url.includes("/analytics/overview")).at(-1) ?? "http://x");
      const start = new Date(`${last.searchParams.get("start")}T00:00:00Z`).getTime();
      const end = new Date(`${last.searchParams.get("end")}T00:00:00Z`).getTime();
      expect((end - start) / 86_400_000).toBe(6);
    });
    expect(window.sessionStorage.getItem("autowok.analytics.filters")).toContain("instagram");
  });

  it("lets owners request a refresh and shows the queued result", async () => {
    render(
      <AnalyticsLayout>
        <AnalyticsOverviewPage />
      </AnalyticsLayout>,
    );
    const button = await screen.findByRole("button", { name: "Refresh now" });
    fireEvent.click(button);
    await screen.findByText(/1 synchronization queued/);
    const syncCall = fetchMock.mock.calls.find(([url, init]) => String(url).endsWith("/analytics/sync") && (init as RequestInit | undefined)?.method === "POST");
    expect(syncCall).toBeTruthy();
    const headers = new Headers((syncCall?.[1] as RequestInit).headers);
    expect(headers.get("X-CSRF-Protection")).toBe("1");
  });

  it("renders the post table with availability badges, content link and filters", async () => {
    render(
      <AnalyticsLayout>
        <AnalyticsPostsPage />
      </AnalyticsLayout>,
    );
    await screen.findByText("Big launch");
    expect(screen.getByRole("link", { name: "Launch post" }).getAttribute("href")).toBe("/dashboard/content/proj-1");
    expect(screen.getAllByText("Not reported by this platform").length).toBe(2);
    expect(screen.getByText("7.33%")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Filter by content type"), { target: { value: "reel" } });
    await waitFor(() => expect(calledUrls().filter((url) => url.includes("/analytics/posts")).at(-1)).toContain("content_format=reel"));
    fireEvent.change(screen.getByLabelText("Sort posts"), { target: { value: "reach" } });
    await waitFor(() => expect(calledUrls().filter((url) => url.includes("/analytics/posts")).at(-1)).toContain("sort=reach"));
  });

  it("links CSV and PDF exports that carry the active filters", async () => {
    render(
      <AnalyticsLayout>
        <AnalyticsReportsPage />
      </AnalyticsLayout>,
    );
    await screen.findByText(/Autowok analytics report · preview/);
    const csv = screen.getByRole("link", { name: "Download CSV" }).getAttribute("href") ?? "";
    const pdf = screen.getByRole("link", { name: "Download PDF" }).getAttribute("href") ?? "";
    expect(csv).toContain("/api/v1/workspaces/ws-1/analytics/reports/export?");
    expect(csv).toContain("format=csv");
    expect(pdf).toContain("format=pdf");
    expect(screen.getByText("Facebook Page - Saves: not reported")).toBeTruthy();
  });
});

describe("line chart", () => {
  afterEach(cleanup);

  it("renders a legend, breaks lines on missing values and exposes a table view", () => {
    const series = [
      { key: "fb", label: "Facebook Page", color: "#2a78d6", points: [{ date: "2026-11-01", value: 10 }, { date: "2026-11-02", value: null }, { date: "2026-11-03", value: 30 }] },
      { key: "ig", label: "Instagram", color: "#eb6834", points: [{ date: "2026-11-01", value: 5 }, { date: "2026-11-02", value: 8 }, { date: "2026-11-03", value: 9 }] },
    ];
    const { container } = render(<LineChart series={series} ariaLabel="Reach per day" />);
    expect(screen.getByRole("img", { name: "Reach per day" })).toBeTruthy();
    expect(screen.getByLabelText("Legend").textContent).toContain("Instagram");
    const paths = container.querySelectorAll("path");
    expect((paths[0].getAttribute("d") ?? "").trim().split("M").length - 1).toBe(2); // the gap starts a second segment
    fireEvent.click(screen.getByRole("button", { name: "Show table" }));
    const table = screen.getByRole("table");
    expect(within(table).getAllByText("Not available").length).toBe(1);
    expect(within(table).getByText("30")).toBeTruthy();
  });
});
