import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useAuth } from "@/components/auth-provider";
import { AutomationForm } from "@/components/automations/automation-form";
import { DryRunPanel } from "@/components/automations/dry-run-panel";
import type { Automation, DryRunResult } from "@/lib/automation-types";
import AutomationsPage from "./page";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  useParams: () => ({ automationId: "a1" }),
}));
vi.mock("@/components/auth-provider", () => ({ useAuth: vi.fn() }));

const workspace = { id: "ws-1", name: "WS", slug: "ws", role: "OWNER" };

const catalog = {
  triggers: [
    {
      type: "CONTENT_SUBMITTED_FOR_APPROVAL",
      label: "Content submitted for approval",
      description: "A content post was submitted for review.",
      category: "content",
      entity_type: "content_project",
      fields: [
        { name: "title", type: "string", label: "Title", ref: null, choices: null, description: "", operators: ["equals", "contains", "is_empty"] },
        { name: "platforms", type: "list", label: "Selected platforms", ref: null, choices: null, description: "", operators: ["contains", "not_contains", "is_empty", "is_not_empty"] },
      ],
      sample_payload: { title: "Spring launch", platforms: ["facebook"] },
      configuration_fields: [],
    },
    {
      type: "APPROVAL_REMINDER_DUE",
      label: "Approval reminder due",
      description: "Waiting too long.",
      category: "team",
      entity_type: "content_approval",
      fields: [{ name: "pending_hours", type: "number", label: "Hours waiting", ref: null, choices: null, description: "", operators: ["greater_than"] }],
      sample_payload: { pending_hours: 26 },
      configuration_fields: [{ name: "deadline_hours", type: "number", label: "Deadline (hours)", required: true, min: 1, max: 720 }],
    },
  ],
  actions: [
    {
      type: "notify_admins",
      label: "Notify workspace administrators",
      description: "Send an in-app notification to every Owner and Admin.",
      category: "notification",
      required_role: "MEMBER",
      allowed_triggers: null,
      required_fields: [],
      configuration_schema: { properties: { title: { anyOf: [{ type: "string" }, { type: "null" }] }, message: { type: "string", maxLength: 500 } }, required: ["message"] },
    },
    {
      type: "record_publishing_incident",
      label: "Record a publishing incident",
      description: "Only for failed publications.",
      category: "publishing",
      required_role: "MEMBER",
      allowed_triggers: ["POST_PUBLISH_FAILED"],
      required_fields: ["publication_id"],
      configuration_schema: { properties: { severity: { enum: ["low", "medium", "high"], default: "medium" } } },
    },
  ],
  limits: { max_actions: 10, max_conditions: 20, max_executions_per_hour: 60, workspace_max_executions_per_day: 1000 },
};

const automation: Automation = {
  id: "a1",
  workspace_id: "ws-1",
  brand_id: null,
  brand_name: null,
  name: "Notify reviewers",
  description: "Tell admins.",
  status: "enabled",
  trigger_type: "CONTENT_SUBMITTED_FOR_APPROVAL",
  trigger_label: "Content submitted for approval",
  trigger_configuration: {},
  conditions: { logic: "and", rules: [] },
  max_executions: null,
  cooldown_seconds: 0,
  execution_count: 3,
  success_count: 2,
  failure_count: 1,
  last_executed_at: "2026-11-12T10:00:00Z",
  last_execution: {
    id: "e1", automation_id: "a1", automation_name: "Notify reviewers", workspace_id: "ws-1", trigger_event_id: null,
    trigger_type: "CONTENT_SUBMITTED_FOR_APPROVAL", status: "failed", retry_count: 0, max_retries: 3, next_attempt_at: null,
    started_at: null, completed_at: null, error_message: "Step 1 failed", chain_depth: 0, created_at: "2026-11-12T10:00:00Z",
    can_retry: true, execution_context: {}, steps: [],
  },
  created_by: "u1",
  created_by_name: "Owner One",
  updated_by: "u1",
  created_at: "2026-11-11T10:00:00Z",
  updated_at: "2026-11-12T10:00:00Z",
  enabled_at: "2026-11-11T11:00:00Z",
  paused_at: null,
  archived_at: null,
  actions: [{ id: "x1", action_type: "notify_admins", label: "Notify workspace administrators", action_configuration: { message: "hi" }, execution_order: 1 }],
  issues: [],
  can_enable: false,
};

const dryRun: DryRunResult = {
  simulated: true,
  generated_at: "2026-11-12T10:00:00Z",
  trigger_type: "CONTENT_SUBMITTED_FOR_APPROVAL",
  payload_source: "sample",
  event_id: null,
  payload: { title: "Spring launch" },
  conditions_passed: false,
  condition_results: {
    path: "conditions", passed: false, logic: "and",
    children: [{ path: "conditions.rules[0]", passed: false, field: "title", operator: "contains", expected: "winter", actual: "Spring launch" }],
  },
  would_execute: false,
  actions: [{ order: 1, action_type: "notify_admins", label: "Notify workspace administrators", status: "would_run", detail: "Would notify 1 administrator (Owner One): “hi”", errors: [] }],
  errors: [],
  notice: "Simulated result. Nothing was executed.",
};

function authenticated() {
  vi.mocked(useAuth).mockReturnValue({
    user: { id: "u1", full_name: "Owner One", email: "o@example.com", is_active: true, is_verified: true },
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
}

describe("automations list", () => {
  const fetchMock = vi.fn();
  beforeEach(() => {
    authenticated();
    fetchMock.mockImplementation(async (url: string) => {
      const body = url.includes("/automations") ? [automation] : [];
      return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
    });
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("shows name, trigger, status, counts and last execution", async () => {
    render(<AutomationsPage />);
    expect(await screen.findByText("Notify reviewers")).toBeTruthy();
    expect(screen.getByText("Content submitted for approval")).toBeTruthy();
    expect(screen.getByText("Enabled")).toBeTruthy();
    expect(screen.getByText("2 / 1")).toBeTruthy();
    expect(screen.getAllByText("Owner One").length).toBeGreaterThan(0);
    expect(screen.getByText("Failed")).toBeTruthy();
    expect(screen.getByRole("link", { name: "New automation" })).toBeTruthy();
    const call = fetchMock.mock.calls.find(([url]) => String(url).includes("/workspaces/ws-1/automations"));
    expect(call).toBeTruthy();
  });

  it("hides creation for members", async () => {
    vi.mocked(useAuth).mockReturnValue({
      ...vi.mocked(useAuth)(),
      selectedWorkspace: { ...workspace, role: "MEMBER" },
    } as unknown as ReturnType<typeof useAuth>);
    render(<AutomationsPage />);
    await screen.findByText("Notify reviewers");
    expect(screen.queryByRole("link", { name: "New automation" })).toBeNull();
  });
});

describe("automation builder", () => {
  const fetchMock = vi.fn();
  beforeEach(() => {
    authenticated();
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      let body: unknown = [];
      if (url.includes("/automations/catalog")) body = catalog;
      else if (url.includes("/members")) body = [{ user_id: "u1", full_name: "Owner One", email: "o@example.com", role: "OWNER", joined_at: "2026-01-01T00:00:00Z" }];
      else if (url.includes("/brands")) body = [];
      else if (url.includes("/automations/dry-run")) body = dryRun;
      else if (url.includes("/automations/validate")) body = { valid: true, errors: [], warnings: ["No conditions: the automation runs for every event of this trigger in its scope."] };
      else if (url.endsWith("/automations") && init?.method === "POST") body = { ...automation, id: "new", status: "draft" };
      return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
    });
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("builds a definition, filters actions by trigger, tests and saves as draft", async () => {
    const onSaved = vi.fn();
    render(<AutomationForm workspaceId="ws-1" onSaved={onSaved} />);
    await screen.findByText("1. Name and trigger");
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Review reminder" } });
    fireEvent.change(screen.getByLabelText("Trigger"), { target: { value: "CONTENT_SUBMITTED_FOR_APPROVAL" } });
    expect(screen.getByText("A content post was submitted for review.")).toBeTruthy();

    // Actions not allowed for this trigger are not offered.
    const addAction = screen.getByLabelText("Add an action") as HTMLSelectElement;
    expect(Array.from(addAction.options).map((option) => option.value)).toEqual(["", "notify_admins"]);
    fireEvent.change(addAction, { target: { value: "notify_admins" } });
    fireEvent.change(screen.getByLabelText("message *"), { target: { value: "“{title}” needs review" } });

    fireEvent.click(screen.getByText("Add condition"));
    fireEvent.change(screen.getByLabelText("Condition 1 field"), { target: { value: "platforms" } });
    fireEvent.change(screen.getByLabelText("Condition 1 operator"), { target: { value: "contains" } });
    fireEvent.change(screen.getByLabelText("Condition 1 value"), { target: { value: "facebook" } });

    fireEvent.click(screen.getByText("Test (dry run)"));
    expect(await screen.findByText("Simulated result")).toBeTruthy();
    expect(screen.getByText("This automation would not run for this event.")).toBeTruthy();
    expect(screen.getByText(/SIMULATION/)).toBeTruthy();
    const testCall = fetchMock.mock.calls.find(([url]) => String(url).includes("/automations/dry-run"));
    const sent = JSON.parse(String((testCall?.[1] as RequestInit).body));
    expect(sent.automation.trigger_type).toBe("CONTENT_SUBMITTED_FOR_APPROVAL");
    expect(sent.automation.conditions).toEqual({ logic: "and", rules: [{ field: "platforms", operator: "contains", value: "facebook" }] });
    expect(sent.automation.actions).toEqual([{ action_type: "notify_admins", configuration: { message: "“{title}” needs review" } }]);

    fireEvent.click(screen.getByText("Save as draft"));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    const saveCall = fetchMock.mock.calls.find(([url, init]) => String(url).endsWith("/workspaces/ws-1/automations") && (init as RequestInit)?.method === "POST");
    expect(saveCall).toBeTruthy();
    expect(JSON.parse(String((saveCall?.[1] as RequestInit).body)).name).toBe("Review reminder");
  });

  it("asks for trigger configuration when the trigger needs it", async () => {
    render(<AutomationForm workspaceId="ws-1" onSaved={vi.fn()} />);
    await screen.findByText("1. Name and trigger");
    fireEvent.change(screen.getByLabelText("Trigger"), { target: { value: "APPROVAL_REMINDER_DUE" } });
    expect(screen.getByLabelText("Deadline (hours)")).toBeTruthy();
  });
});

describe("dry run panel", () => {
  afterEach(cleanup);
  it("labels the result as simulated and shows condition and action details", () => {
    render(<DryRunPanel result={dryRun} />);
    expect(screen.getAllByText(/nothing was executed/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/✗ title contains winter/)).toBeTruthy();
    expect(screen.getByText(/actual: Spring launch/)).toBeTruthy();
    expect(screen.getByText("would run")).toBeTruthy();
    expect(screen.getByText(/Would notify 1 administrator/)).toBeTruthy();
  });
});
