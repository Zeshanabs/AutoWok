import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { FinalDeliverable } from "@/components/agents/result-views";
import { useAuth } from "@/components/auth-provider";
import type { Agent, AgentWorkflow, AgentWorkflowDetail, Catalog, FinalOutput } from "@/lib/agent-types";
import { formatDuration, reviewLabel } from "@/lib/agent-types";
import AiAgentsDashboardPage from "./page";
import AgentSettingsPage from "./settings/page";
import WorkflowHistoryPage from "./history/page";
import WorkflowBuilderPage from "./workflows/page";
import WorkflowExecutionPage from "./workflows/[workflowId]/page";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push }),
  useParams: () => ({ workflowId: "wf-1" }),
}));
vi.mock("@/components/auth-provider", () => ({ useAuth: vi.fn() }));

const workspace = { id: "ws-1", name: "WS", slug: "ws", role: "OWNER" };

function agent(key: string, name: string, enabled = true): Agent {
  return {
    key, name, enabled,
    description: `${name} description`,
    responsibility: `${name} responsibility`,
    version: "1.0.0",
    required_role: "MEMBER",
    tools: key === "content_writer" ? [{ name: "get_brand_profile", description: "Brand", access: "read" }] : [],
    model: { provider: "groq", temperature: 0.4, max_tokens: 1500 },
    limits: { timeout_seconds: null, max_attempts: null },
  };
}

const socialSteps = [
  ["brand_context", "context", "orchestrator", "Orchestrator", "Retrieve brand context", null],
  ["plan", "agent", "content_planner", "Content Planner Agent", "Plan the content", null],
  ["writer", "agent", "content_writer", "Content Writer Agent", "Write the draft", null],
  ["brand_review", "agent", "brand_guardian", "Brand Guardian Agent", "Review brand consistency", "review"],
  ["compile", "compile", "orchestrator", "Orchestrator", "Compile results", null],
].map(([step_key, kind, agent_key, agent_name, label, parallel_group], index) => ({
  step_order: index + 1, step_key, base_key: step_key, kind, agent_key, agent_name, label, depends_on: [], parallel_group,
}));

const catalog = {
  workflows: [
    {
      key: "social_content", name: "Create high-quality social content", description: "Plan, write and review a post.",
      deliverables: ["Content draft", "Brand review"], requires: ["brand"], optional: ["research", "platforms"],
      agents: ["content_planner", "content_writer", "brand_guardian"], supports_revision: true, accept_mode: "draft",
      steps: socialSteps, disabled_agents: [],
    },
    {
      key: "performance_analysis", name: "Performance analysis", description: "Interpret measured analytics.",
      deliverables: ["Performance summary"], requires: [], optional: ["brand", "days"],
      agents: ["analytics_strategist"], supports_revision: false, accept_mode: null, steps: [], disabled_agents: ["analytics_strategist"],
    },
  ],
  agents: [agent("content_writer", "Content Writer Agent"), agent("analytics_strategist", "Analytics Strategist Agent", false)],
  limits: {
    enabled: true, max_calls_per_workflow: 24, max_workflow_seconds: 900, step_timeout_seconds: 90, max_step_attempts: 3,
    max_auto_revisions: 1, max_revisions: 3, max_parallel_calls: 1, max_active_workflows: 3, max_workflows_per_hour: 20,
  },
  groq: { provider: "groq", enabled: true, configured: true, source: "environment", model_name: "configured-model", agent_model_override: false, search_provider_configured: false },
} as unknown as Catalog;

const summary: AgentWorkflow = {
  id: "wf-1", workspace_id: "ws-1", brand_id: "b1", brand_name: "Bean & Co", workflow_type: "social_content",
  workflow_name: "Create high-quality social content", name: "Launch post", task: "Promote the brewing guide", status: "succeeded",
  error_message: null, cancel_requested: false, agent_call_count: 5, revision_count: 1, total_tokens: 750, prompt_tokens: 500,
  completion_tokens: 250, review_status: "pending", review_note: null, accepted_project_id: null, created_by: "u1",
  created_by_name: "Owner One", created_at: "2026-11-13T10:00:00Z", started_at: "2026-11-13T10:00:01Z", completed_at: "2026-11-13T10:01:00Z",
  next_attempt_at: null, steps_total: 2, steps_done: 2, can_cancel: false, can_accept: true, can_revise: true, can_reject: true,
  supports_revision: true, accept_mode: "draft",
};

const output: FinalOutput = {
  type: "social_content",
  decision: "final",
  human_review: "AI-generated output for human review. Nothing was saved to the content studio, approved, scheduled or published.",
  warnings: ["fact_checker: 1 claim(s) were downgraded to UNVERIFIABLE because their evidence could not be confirmed."],
  evidence: [
    { type: "research_source", source_id: "s1", research_id: "r1", title: "Coffee report", url: "https://example.org/coffee", domain: "example.org" },
    { type: "research_source", source_id: "s2", research_id: "r1", title: "Suspicious link", url: "javascript:alert(1)", domain: null },
  ],
  open_issues: ["Brand (prohibited_phrase): The draft uses a prohibited phrase."],
  revision_limit_reached: true,
  revision_rounds: 1,
  content_draft: {
    title: "Three brewing mistakes",
    versions: [
      { platform: "facebook", hook: "Still getting bitter coffee?", body: "Three simple fixes.", cta: "Tell us which one.", hashtags: ["#coffee"] },
      { platform: "instagram", hook: "Bitter coffee? Fix it.", body: "A smoother cup at home.", cta: "Save this.", hashtags: ["#homebrew"] },
    ],
  },
  alternative_hooks: ["Your coffee deserves better."],
  cta_recommendations: ["Ask a question."],
  improvement_suggestions: ["Shorten the second sentence."],
  brand_review: {
    assessment: "major_issues", summary: "One prohibited phrase.",
    issues: [{ category: "prohibited_phrase", severity: "high", platform: "facebook", excerpt: "best coffee in the world", explanation: "The brand profile prohibits it.", suggestion: "Remove it.", detected_by: "rule" }],
    approval_note: "This review is advisory. Only an authorized workspace reviewer can approve content.",
  },
  fact_check: {
    summary: "One claim supported.",
    claims: [
      { claim: "Interest in home brewing is growing.", classification: "SUPPORTED", reasoning: "Stated in S1.", source_refs: ["S1"], source_ids: ["s1"] },
      { claim: "We are number one.", classification: "UNVERIFIABLE", reasoning: "No source.", source_refs: [], source_ids: [] },
    ],
    citation_coverage: { factual_claims: 2, claims_with_evidence: 1, sources_available: 1 },
  },
  quality_assessment: {
    overall_score: 7.5,
    scores: { clarity: { score: 8, explanation: "Clear." }, hook_strength: { score: 7, explanation: "Decent hook." } },
    disclaimer: "Scores are editorial assessments by an AI reviewer. They are not predictions of reach, engagement or any other performance result.",
  },
};

const detail: AgentWorkflowDetail = {
  ...summary,
  input_data: {},
  agents: ["content_planner", "content_writer"],
  final_output: output,
  steps: [
    {
      id: "st-1", step_order: 1, step_key: "writer", base_key: "writer", revision_round: 0, kind: "agent", agent_key: "content_writer",
      agent_name: "Content Writer Agent", label: "Write the draft", depends_on: ["plan"], parallel_group: null, status: "succeeded",
      attempt_count: 1, error_message: null,
      execution: {
        id: "ex-1", step_key: "writer", agent_key: "content_writer", agent_version: "1.0.0", attempt_number: 2, status: "succeeded",
        model_name: "configured-model", token_usage: { prompt_tokens: 100, completion_tokens: 50, total_tokens: 150 }, execution_duration_ms: 1840,
        error_message: null, started_at: "2026-11-13T10:00:05Z", completed_at: "2026-11-13T10:00:07Z",
        warnings: ["facebook: uses prohibited phrase(s): best coffee in the world."], evidence: [], result: { title: "Three brewing mistakes" },
      },
    },
    {
      id: "st-2", step_order: 2, step_key: "compile", base_key: "compile", revision_round: 0, kind: "compile", agent_key: "orchestrator",
      agent_name: "Orchestrator", label: "Compile results", depends_on: ["writer"], parallel_group: null, status: "succeeded",
      attempt_count: 0, error_message: null, execution: null,
    },
  ],
};

function authenticated(role = "OWNER") {
  vi.mocked(useAuth).mockReturnValue({
    user: { id: "u1", full_name: "Owner One", email: "o@example.com", is_active: true, is_verified: true },
    workspaces: [{ ...workspace, role }],
    selectedWorkspace: { ...workspace, role },
    status: "authenticated",
    error: null,
    refreshUser: vi.fn(),
    selectWorkspace: vi.fn(),
    login: vi.fn(),
    register: vi.fn(),
    logout: vi.fn(),
  } as unknown as ReturnType<typeof useAuth>);
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const fetchMock = vi.fn();
type Route = (url: string, init?: RequestInit) => unknown;

function serve(routes: Record<string, Route | unknown>) {
  fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
    const method = (init?.method ?? "GET").toUpperCase();
    const match = Object.keys(routes)
      .sort((a, b) => b.length - a.length)
      .find((key) => {
        const [routeMethod, fragment] = key.includes(" ") ? key.split(" ") : ["GET", key];
        return routeMethod === method && String(url).includes(fragment);
      });
    if (!match) return json([]);
    const route = routes[match];
    const body = typeof route === "function" ? (route as Route)(String(url), init) : route;
    return body instanceof Response ? body : json(body);
  });
}

function calls(fragment: string, method = "GET") {
  return fetchMock.mock.calls.filter(([url, init]) => String(url).includes(fragment) && ((init?.method ?? "GET") as string).toUpperCase() === method);
}

beforeEach(() => {
  authenticated();
  push.mockReset();
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("AI agent dashboard", () => {
  it("shows workflows, agents, usage and recent executions", async () => {
    serve({
      "/agent-workflows/catalog": catalog,
      "/agent-workflows/stats": { days: 30, counts: { pending: 0, running: 0, succeeded: 4, failed: 1, cancelled: 0 }, total: 5, active: 0, agent_calls: 21, total_tokens: 12345, limits: catalog.limits, recent: [summary] },
    });
    render(<AiAgentsDashboardPage />);
    expect(await screen.findByText("Launch post")).toBeTruthy();
    expect(screen.getAllByText("Create high-quality social content").length).toBeGreaterThan(0);
    expect(screen.getByText("Content Planner → Content Writer → Brand Guardian")).toBeTruthy();
    expect(screen.getByText("Unavailable: a required agent is disabled.")).toBeTruthy();
    expect(screen.getByText("12,345")).toBeTruthy();
    expect(screen.getByText("21")).toBeTruthy();
    expect(screen.getByText(/Awaiting your review/)).toBeTruthy();
    expect(screen.getByText("Content Writer Agent")).toBeTruthy();
    expect(screen.getByText(/cannot approve, schedule or publish/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Launch post" }).getAttribute("href")).toBe("/dashboard/ai-agents/workflows/wf-1");
    expect(calls("/workspaces/ws-1/agent-workflows/stats").length).toBe(1);
  });

  it("warns when Groq is not configured", async () => {
    serve({
      "/agent-workflows/catalog": { ...catalog, groq: { ...catalog.groq, configured: false } },
      "/agent-workflows/stats": { days: 30, counts: {}, total: 0, active: 0, agent_calls: 0, total_tokens: 0, limits: catalog.limits, recent: [] },
    });
    render(<AiAgentsDashboardPage />);
    expect(await screen.findByText(/Groq is not configured for this workspace/)).toBeTruthy();
    expect(screen.getByText(/No workflows yet/)).toBeTruthy();
  });
});

describe("workflow builder", () => {
  const routes = {
    "/agent-workflows/catalog": catalog,
    "/workspaces/ws-1/brands": [{ id: "b1", name: "Bean & Co", status: "ACTIVE" }, { id: "b2", name: "Old brand", status: "ARCHIVED" }],
    "/research?": [{ id: "r1", title: "Home coffee research", status: "COMPLETED" }],
    "/content/projects": [{ id: "c1", title: "Approved post", status: "approved" }, { id: "c2", title: "Draft post", status: "draft" }],
    "POST /agent-workflows/plan": {
      workflow: catalog.workflows[0],
      input_data: {},
      estimated_agent_calls: 3,
      notes: ["Agents produce drafts and recommendations only. Nothing is approved, scheduled or published."],
    },
    "POST /agent-workflows": { ...detail, id: "wf-new", status: "pending" },
  };

  it("requires a review of the planned execution before starting", async () => {
    serve(routes);
    render(<WorkflowBuilderPage />);
    const task = await screen.findByLabelText("Task");
    expect(screen.queryByRole("button", { name: "Start workflow" })).toBeNull();
    expect(screen.queryByRole("option", { name: "Old brand" })).toBeNull(); // archived brands are not offered

    fireEvent.click(screen.getByRole("button", { name: "Review planned execution" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Describe the task.");
    fireEvent.change(task, { target: { value: "Promote the brewing guide" } });
    fireEvent.click(screen.getByRole("button", { name: "Review planned execution" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Select a brand.");
    expect(calls("/agent-workflows/plan", "POST").length).toBe(0);

    fireEvent.change(screen.getByLabelText("Brand"), { target: { value: "b1" } });
    fireEvent.click(screen.getByLabelText(/Home coffee research/));
    fireEvent.click(screen.getByLabelText("Facebook"));
    fireEvent.click(screen.getByRole("button", { name: "Review planned execution" }));

    await screen.findByRole("button", { name: "Start workflow" });
    expect(screen.getByText("Write the draft")).toBeTruthy();
    expect(screen.getByText("Brand Guardian Agent · independent review")).toBeTruthy();
    expect(screen.getByText(/About 3 Groq requests, more if a revision is needed/)).toBeTruthy();
    const planned = JSON.parse(calls("/agent-workflows/plan", "POST")[0][1].body);
    expect(planned).toMatchObject({ workflow_type: "social_content", task: "Promote the brewing guide", brand_id: "b1", research_ids: ["r1"], platforms: ["instagram"], content_project_id: null });

    // Changing the form invalidates the reviewed plan.
    fireEvent.change(task, { target: { value: "Promote the brewing guide to beginners" } });
    expect(screen.queryByRole("button", { name: "Start workflow" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Review planned execution" }));
    fireEvent.click(await screen.findByRole("button", { name: "Start workflow" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/dashboard/ai-agents/workflows/wf-new"));
    const started = calls("/workspaces/ws-1/agent-workflows", "POST").find(([url]) => !String(url).includes("/plan"));
    expect(JSON.parse(started![1].body).task).toBe("Promote the brewing guide to beginners");
    expect(started![1].headers.get("X-CSRF-Protection")).toBe("1");
  });

  it("blocks starting while a required agent is disabled", async () => {
    serve({
      ...routes,
      "POST /agent-workflows/plan": { ...routes["POST /agent-workflows/plan"], workflow: { ...catalog.workflows[0], disabled_agents: ["brand_guardian"] } },
    });
    render(<WorkflowBuilderPage />);
    fireEvent.change(await screen.findByLabelText("Task"), { target: { value: "Promote the brewing guide" } });
    fireEvent.change(screen.getByLabelText("Brand"), { target: { value: "b1" } });
    fireEvent.click(screen.getByRole("button", { name: "Review planned execution" }));
    const start = (await screen.findByRole("button", { name: "Start workflow" })) as HTMLButtonElement;
    expect(start.disabled).toBe(true);
  });

  it("shows the server's reason when a workflow cannot start", async () => {
    serve({ ...routes, "POST /agent-workflows": (url: string) => (url.includes("/plan") ? routes["POST /agent-workflows/plan"] : json({ detail: "The hourly limit for AI agent workflows was reached. Try again later." }, 429)) });
    render(<WorkflowBuilderPage />);
    fireEvent.change(await screen.findByLabelText("Task"), { target: { value: "Promote the brewing guide" } });
    fireEvent.change(screen.getByLabelText("Brand"), { target: { value: "b1" } });
    fireEvent.click(screen.getByRole("button", { name: "Review planned execution" }));
    fireEvent.click(await screen.findByRole("button", { name: "Start workflow" }));
    expect((await screen.findByRole("alert")).textContent).toBe("The hourly limit for AI agent workflows was reached. Try again later.");
    expect(push).not.toHaveBeenCalled();
  });
});

describe("workflow execution view", () => {
  it("shows the timeline, warnings, evidence and the final deliverable", async () => {
    serve({ "/agent-workflows/wf-1": detail });
    render(<WorkflowExecutionPage />);
    expect(await screen.findByRole("heading", { name: "Launch post" })).toBeTruthy();
    expect(screen.getByText("Promote the brewing guide")).toBeTruthy();
    expect(screen.getByRole("progressbar").getAttribute("aria-valuenow")).toBe("2");
    expect(screen.getByText(/Content Writer Agent v1.0.0 · configured-model · 1.8 s · 150 tokens · 1 failed attempt before this/)).toBeTruthy();
    expect(screen.getByText("facebook: uses prohibited phrase(s): best coffee in the world.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Output" }));
    expect(screen.getByText(/"title": "Three brewing mistakes"/)).toBeTruthy();

    // Result review: draft, brand review, fact check, quality, evidence.
    expect(screen.getByText("Still getting bitter coffee?")).toBeTruthy();
    expect(screen.getByText("major issues")).toBeTruthy();
    expect(screen.getByText("found by rule check")).toBeTruthy();
    expect(screen.getByText("Supported")).toBeTruthy();
    expect(screen.getByText("Unverifiable")).toBeTruthy();
    expect(screen.getByText(/1 of 2 factual claims have a source/)).toBeTruthy();
    expect(screen.getByText("7.5")).toBeTruthy();
    expect(screen.getByText(/not predictions of reach/)).toBeTruthy();
    expect(screen.getByText(/automatic revision limit was reached/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Coffee report" }).getAttribute("href")).toBe("https://example.org/coffee");
    expect(screen.queryByRole("link", { name: "Suspicious link" })).toBeNull(); // non-http links are never clickable
    expect(screen.getByText(/Awaiting your review/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Cancel workflow" })).toBeNull();
  });

  it("accepts a draft only after confirmation", async () => {
    serve({
      "/agent-workflows/wf-1": detail,
      "POST /agent-workflows/wf-1/accept": { project_id: "p-9", draft_ids: { facebook: "d1" }, status: "draft", workflow: { ...summary, review_status: "accepted" } },
    });
    render(<WorkflowExecutionPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Accept draft into content studio" }));
    expect(calls("/accept", "POST").length).toBe(0);
    expect(screen.getByText(/It is not approved, scheduled or published/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Accept as draft" }));
    expect((await screen.findByRole("status")).textContent).toContain("It still needs approval before it can be published.");
    expect(screen.getByRole("link", { name: "Open the draft" }).getAttribute("href")).toBe("/dashboard/content/p-9");
    expect(JSON.parse(calls("/accept", "POST")[0][1].body)).toEqual({ idea_index: null });
  });

  it("requests a bounded revision with feedback and can reject", async () => {
    serve({
      "/agent-workflows/wf-1": detail,
      "POST /agent-workflows/wf-1/revise": { ...detail, status: "pending", review_status: null, final_output: null, can_accept: false, can_revise: false, can_reject: false, can_cancel: true },
    });
    render(<WorkflowExecutionPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Request revision" }));
    const dialog = screen.getByRole("dialog");
    const submit = within(dialog).getByRole("button", { name: "Request revision" }) as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    fireEvent.change(within(dialog).getByLabelText("What should change?"), { target: { value: "Make it shorter." } });
    fireEvent.click(submit);
    expect((await screen.findByRole("status")).textContent).toContain("Revision requested");
    expect(JSON.parse(calls("/revise", "POST")[0][1].body)).toEqual({ feedback: "Make it shorter." });
    expect(screen.queryByRole("button", { name: "Accept draft into content studio" })).toBeNull();
    expect(screen.getByRole("button", { name: "Cancel workflow" })).toBeTruthy();
  });

  it("shows a failed workflow with its error and no review actions", async () => {
    serve({
      "/agent-workflows/wf-1": {
        ...detail, status: "failed", review_status: null, final_output: null, can_accept: false, can_revise: false, can_reject: false,
        error_message: "Content Writer Agent failed: Groq rejected the API key or account permissions.",
        steps: [{ ...detail.steps[0], status: "failed", error_message: "Groq rejected the API key or account permissions.", execution: null }, { ...detail.steps[1], status: "skipped" }],
      },
    });
    render(<WorkflowExecutionPage />);
    expect(await screen.findByText("Content Writer Agent failed: Groq rejected the API key or account permissions.")).toBeTruthy();
    expect(screen.getByText("Skipped")).toBeTruthy();
    expect(screen.getByText(/did not finish, so there is no final output/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Accept draft into content studio" })).toBeNull();
  });

  it("explains a missing workflow", async () => {
    serve({ "/agent-workflows/wf-1": () => json({ detail: "Workflow not found." }, 404) });
    render(<WorkflowExecutionPage />);
    expect(await screen.findByText(/was not found in the selected workspace/)).toBeTruthy();
  });
});

describe("history and settings", () => {
  it("lists workflow history and filters by status", async () => {
    serve({ "/agent-workflows?": { items: [summary, { ...summary, id: "wf-2", name: "Failed run", status: "failed", review_status: null, error_message: "Timed out." }], total: 2, offset: 0, limit: 20 } });
    render(<WorkflowHistoryPage />);
    expect(await screen.findByText("Launch post")).toBeTruthy();
    expect(screen.getByText("Timed out.")).toBeTruthy();
    expect(screen.getByText("Awaiting your review")).toBeTruthy();
    expect(screen.getByText("1–2 of 2")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Filter by status"), { target: { value: "failed" } });
    await waitFor(() => expect(calls("status=failed").length).toBe(1));
  });

  it("lets admins switch agents and hides the control from members", async () => {
    serve({ "/agent-workflows/catalog": catalog, "PATCH /agents/content_writer": { ...catalog.agents[0], enabled: false } });
    render(<AgentSettingsPage />);
    expect(await screen.findByText("Content Writer Agent responsibility")).toBeTruthy();
    expect(screen.getByText("configured-model")).toBeTruthy();
    expect(screen.getByText("No search provider configured")).toBeTruthy();
    expect(screen.getByText("get_brand_profile (read)")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Disable Content Writer Agent" }));
    await waitFor(() => expect(calls("/workspaces/ws-1/agents/content_writer", "PATCH").length).toBe(1));
    expect(JSON.parse(calls("/agents/content_writer", "PATCH")[0][1].body)).toEqual({ enabled: false });
    expect(screen.getByRole("button", { name: "Enable Analytics Strategist Agent" })).toBeTruthy();

    cleanup();
    authenticated("MEMBER");
    render(<AgentSettingsPage />);
    expect(await screen.findByText("Workspace Owners and Admins can switch agents on or off.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Disable/ })).toBeNull();
  });
});

describe("deliverables and helpers", () => {
  it("separates sourced findings from assumptions in research output", () => {
    const accept = vi.fn();
    render(
      <FinalDeliverable
        output={{
          type: "content_research",
          warnings: [],
          evidence: [],
          research_findings: {
            summary: "Home baristas want simple guidance.",
            findings: [
              { claim: "Interest is growing.", explanation: "", category: "trend", verified: true, source_refs: ["S1"], source_ids: ["s1"] },
              { claim: "Buyers value subscriptions.", explanation: "", category: "audience", verified: false, source_refs: [], source_ids: [] },
            ],
          },
          strategic_recommendations: { strategy_summary: "Teach brewing.", supporting_evidence: [{ statement: "Tips resonate.", basis: "assumption", source_ids: [] }] },
          content_ideas: [{ title: "Three mistakes", description: "Explain mistakes.", content_angle: "", platform: "instagram", format: "educational", content_pillar: null, objective: "", suggested_hook: "", source_ids: [] }],
          suggested_publishing_frequency: { posts_per_week: 3, rationale: "" },
        }}
        renderIdeaAction={(index) => <button type="button" onClick={() => accept(index)}>Add to content studio</button>}
      />,
    );
    expect(screen.getByText("Sourced (S1)")).toBeTruthy();
    expect(screen.getByText("Assumption — no source")).toBeTruthy();
    expect(screen.getByText(/nothing is scheduled/)).toBeTruthy();
    expect(screen.getByText(/No source references/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Add to content studio" }));
    expect(accept).toHaveBeenCalledWith(0);
  });

  it("labels measured values and unverified numbers in performance output", () => {
    render(
      <FinalDeliverable
        output={{
          type: "performance_analysis",
          performance_summary: "The reel led with 120 engagements.",
          measured_data: { period: { start: "2026-10-14", end: "2026-11-13" }, post_count: 3 },
          content_patterns: [{ observation: "Reels lead.", metric_refs: [{ metric: "engagements", value: 120, scope: "reel" }] }, { observation: "Images lag.", metric_refs: [] }],
          unverified_numbers: ["250"],
          metric_references: [{ type: "metric", metric: "engagements", value: 120, scope: "reel" }],
          label: "Metric references are measured values. Everything else is AI interpretation.",
        }}
      />,
    );
    expect(screen.getByText("Measured: engagements 120 (reel)")).toBeTruthy();
    expect(screen.getByText("No measured value supports this observation.")).toBeTruthy();
    expect(screen.getByText(/Unverified numbers in the text/).textContent).toContain("250");
    expect(screen.getByText("Supporting metric references")).toBeTruthy();
    expect(screen.getByText(/2026-10-14 to 2026-11-13 · 3 measured posts/)).toBeTruthy();
  });

  it("formats durations and review labels", () => {
    expect(formatDuration(null)).toBe("—");
    expect(formatDuration(420)).toBe("420 ms");
    expect(formatDuration(1840)).toBe("1.8 s");
    expect(reviewLabel("pending")).toBe("Awaiting your review");
    expect(reviewLabel("accepted")).toBe("Accepted");
    expect(reviewLabel(null)).toBe("—");
  });
});
