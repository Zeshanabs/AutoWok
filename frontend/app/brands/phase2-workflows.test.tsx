import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useAuth } from "@/components/auth-provider";
import { apiRequest } from "@/lib/api";
import NewBrandPage from "@/app/brands/new/page";
import BrandSettingsPage from "@/app/brands/[brandId]/settings/page";
import { BrandSectionPage } from "@/components/brand-section";
import AISettingsPage from "@/app/settings/ai/page";
import SocialAccountsPage from "@/app/settings/social-accounts/page";

const push = vi.fn();

vi.mock("@/components/auth-provider", () => ({ useAuth: vi.fn() }));
vi.mock("@/components/route-guards", () => ({
  AppShell: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  ProtectedPage: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, apiRequest: vi.fn() };
});
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
  useParams: () => ({ brandId: "brand-1" }),
}));

const workspace = {
  id: "workspace-1",
  name: "Test workspace",
  slug: "test-workspace",
  role: "OWNER" as const,
};

const overview = {
  brand: {
    id: "brand-1",
    workspace_id: workspace.id,
    name: "Test brand",
    slug: "test-brand",
    description: null,
    website_url: null,
    industry: null,
    business_type: null,
    logo_url: null,
    primary_color: null,
    secondary_color: null,
    status: "ACTIVE" as const,
    created_by: "user-1",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  },
  voice: null,
  audiences: [],
  pillars: [
    {
      id: "pillar-1",
      brand_id: "brand-1",
      name: "Education",
      description: null,
      objective: null,
      suggested_topics: [],
      priority: 3,
      is_active: true,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    },
  ],
  goals: [],
  policies: [],
};

function setOwnerAuth() {
  vi.mocked(useAuth).mockReturnValue({
    user: null,
    workspaces: [workspace],
    selectedWorkspace: workspace,
    status: "authenticated",
    error: null,
    refreshUser: vi.fn(async () => {}),
    selectWorkspace: vi.fn(async () => {}),
    login: vi.fn(async () => {}),
    register: vi.fn(async () => {}),
    logout: vi.fn(async () => {}),
  } as ReturnType<typeof useAuth>);
}

describe("Phase 2 brand and AI workflows", () => {
  afterEach(cleanup);

  beforeEach(() => {
    setOwnerAuth();
    push.mockReset();
    vi.mocked(apiRequest).mockReset();
  });

  it("creates a brand through the two-step setup wizard", async () => {
    vi.mocked(apiRequest).mockResolvedValue({
      ...overview.brand,
      id: "created-brand",
    } as never);
    render(<NewBrandPage />);

    fireEvent.change(screen.getByLabelText("Brand name"), {
      target: { value: "Sample brand" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(screen.getByLabelText("Brand identity")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Website URL"), {
      target: { value: "https://sample.example" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create brand" }));

    await waitFor(() => {
      expect(apiRequest).toHaveBeenCalledWith(
        `/workspaces/${workspace.id}/brands`,
        expect.objectContaining({ method: "POST" }),
      );
      expect(push).toHaveBeenCalledWith("/brands/created-brand");
    });
    const request = vi.mocked(apiRequest).mock.calls[0][1] as RequestInit;
    expect(JSON.parse(String(request.body))).toMatchObject({
      name: "Sample brand",
      website_url: "https://sample.example",
    });
  });

  it("updates brand identity in the settings route", async () => {
    vi.mocked(apiRequest)
      .mockResolvedValueOnce(overview as never)
      .mockResolvedValueOnce(overview.brand as never)
      .mockResolvedValueOnce(overview as never);
    render(<BrandSettingsPage />);

    const nameInput = await screen.findByLabelText("Brand name");
    fireEvent.change(nameInput, { target: { value: "Updated brand" } });
    fireEvent.click(screen.getByRole("button", { name: "Save settings" }));

    await waitFor(() => {
      expect(apiRequest).toHaveBeenCalledWith(
        "/brands/brand-1",
        expect.objectContaining({
          method: "PATCH",
          body: expect.stringContaining('"name":"Updated brand"'),
        }),
      );
      expect(screen.getByRole("status").textContent).toContain(
        "Brand settings saved.",
      );
    });
  });

  it("toggles active state for a content pillar", async () => {
    vi.mocked(apiRequest)
      .mockResolvedValueOnce(overview as never)
      .mockResolvedValueOnce({ ...overview.pillars[0], is_active: false } as never);
    render(<BrandSectionPage brandId="brand-1" section="pillars" />);

    fireEvent.click(await screen.findByRole("button", { name: "Deactivate Education" }));

    await waitFor(() => {
      expect(apiRequest).toHaveBeenLastCalledWith(
        "/brands/brand-1/pillars/pillar-1",
        expect.objectContaining({
          method: "PATCH",
          body: JSON.stringify({ is_active: false }),
        }),
      );
      expect(screen.getByText("Inactive")).toBeTruthy();
    });
  });

  it("saves AI provider credentials through the settings form", async () => {
    const provider = {
      id: "provider-1",
      workspace_id: workspace.id,
      provider_name: "openai",
      display_name: "Primary OpenAI",
      model_name: "gpt-4o-mini",
      base_url: null,
      api_key_configured: true,
      masked_api_key: "********",
      is_active: true,
      is_default: true,
      configuration: {},
      created_by: "user-1",
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
      last_tested_at: null,
      last_test_status: null,
    };
    vi.mocked(apiRequest)
      .mockResolvedValueOnce([] as never)
      .mockResolvedValueOnce({
        enabled: true,
        configured: false,
        source: "missing",
        model_name: null,
        api_key_configured: false,
      } as never)
      .mockResolvedValueOnce(provider as never);
    render(<AISettingsPage />);

    fireEvent.change(await screen.findByLabelText("Display name"), {
      target: { value: "Primary OpenAI" },
    });
    fireEvent.change(screen.getByLabelText("Model name"), {
      target: { value: "gpt-4o-mini" },
    });
    fireEvent.change(screen.getByLabelText("API key", { exact: false }), {
      target: { value: "secret-test-key" },
    });
    fireEvent.click(screen.getByLabelText("Use as workspace default"));
    fireEvent.click(screen.getByRole("button", { name: "Save provider" }));

    await waitFor(() => {
      expect(apiRequest).toHaveBeenLastCalledWith(
        `/workspaces/${workspace.id}/ai-providers`,
        expect.objectContaining({ method: "POST" }),
      );
      expect(screen.getByRole("status").textContent).toContain(
        "Provider saved.",
      );
      expect(document.body.textContent).not.toContain("secret-test-key");
    });
    const request = vi.mocked(apiRequest).mock.calls[2][1] as RequestInit;
    expect(JSON.parse(String(request.body))).toMatchObject({
      provider_name: "openai",
      display_name: "Primary OpenAI",
      api_key: "secret-test-key",
      is_default: true,
    });
  });

  it("edits an AI provider and replaces its key only when supplied", async () => {
    const provider = {
      id: "provider-1",
      workspace_id: workspace.id,
      provider_name: "openai",
      display_name: "Primary OpenAI",
      model_name: "gpt-4o-mini",
      base_url: null,
      api_key_configured: true,
      masked_api_key: "********",
      is_active: true,
      is_default: true,
      configuration: {},
      created_by: "user-1",
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
      last_tested_at: null,
      last_test_status: null,
    };
    vi.mocked(apiRequest)
      .mockResolvedValueOnce([provider] as never)
      .mockResolvedValueOnce({
        enabled: true,
        configured: false,
        source: "missing",
        model_name: null,
        api_key_configured: false,
      } as never)
      .mockResolvedValueOnce({ ...provider, display_name: "Updated OpenAI" } as never);
    render(<AISettingsPage />);

    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
    fireEvent.change(screen.getByLabelText("Display name"), {
      target: { value: "Updated OpenAI" },
    });
    fireEvent.change(screen.getByLabelText("API key", { exact: false }), {
      target: { value: "replacement-key" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => {
      expect(apiRequest).toHaveBeenLastCalledWith(
        `/workspaces/${workspace.id}/ai-providers/provider-1`,
        expect.objectContaining({ method: "PATCH" }),
      );
      expect(screen.getByRole("status").textContent).toContain(
        "Provider settings updated.",
      );
      expect(document.body.textContent).not.toContain("replacement-key");
    });

    const request = vi.mocked(apiRequest).mock.calls[2][1] as RequestInit;
    expect(JSON.parse(String(request.body))).toMatchObject({
      display_name: "Updated OpenAI",
      api_key: "replacement-key",
    });
  });

  it("loads Groq models and saves the selected free-tier model", async () => {
    const groqStatus = {
      enabled: true,
      configured: false,
      source: "missing",
      model_name: null,
      api_key_configured: false,
    };
    const provider = {
      id: "groq-provider",
      workspace_id: workspace.id,
      provider_name: "groq",
      display_name: "Free Groq",
      model_name: "llama-3.1-8b-instant",
      base_url: null,
      api_key_configured: true,
      masked_api_key: "********",
      is_active: true,
      is_default: true,
      configuration: {},
      created_by: "user-1",
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
      last_tested_at: null,
      last_test_status: null,
    };
    vi.mocked(apiRequest)
      .mockResolvedValueOnce([] as never)
      .mockResolvedValueOnce(groqStatus as never)
      .mockResolvedValueOnce({ models: ["llama-3.1-8b-instant"] } as never)
      .mockResolvedValueOnce(provider as never);
    render(<AISettingsPage />);

    fireEvent.change(await screen.findByLabelText("Provider"), {
      target: { value: "groq" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Load supported Groq models" }));
    expect(await screen.findByLabelText("Groq model")).toBeTruthy();
    fireEvent.change(await screen.findByLabelText("Display name"), {
      target: { value: "Free Groq" },
    });
    fireEvent.change(screen.getByLabelText("API key", { exact: false }), {
      target: { value: "groq-test-key" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save provider" }));

    await waitFor(() => {
      expect(apiRequest).toHaveBeenLastCalledWith(
        `/workspaces/${workspace.id}/ai-providers`,
        expect.objectContaining({ method: "POST" }),
      );
      expect(screen.getByRole("status").textContent).toContain("Provider saved.");
    });
    expect(apiRequest).toHaveBeenCalledWith(
      `/workspaces/${workspace.id}/ai-providers/groq/models`,
    );
    const request = vi.mocked(apiRequest).mock.calls[3][1] as RequestInit;
    expect(JSON.parse(String(request.body))).toMatchObject({
      provider_name: "groq",
      model_name: "llama-3.1-8b-instant",
      api_key: "groq-test-key",
    });
  });

  it("shows a clear Groq connection-test result", async () => {
    const provider = {
      id: "groq-provider",
      workspace_id: workspace.id,
      provider_name: "groq",
      display_name: "Free Groq",
      model_name: "llama-3.1-8b-instant",
      base_url: null,
      api_key_configured: true,
      masked_api_key: "********",
      is_active: true,
      is_default: true,
      configuration: {},
      created_by: "user-1",
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
      last_tested_at: null,
      last_test_status: null,
    };
    const status = {
      enabled: true,
      configured: true,
      source: "workspace",
      model_name: provider.model_name,
      api_key_configured: true,
    };
    vi.mocked(apiRequest)
      .mockResolvedValueOnce([provider] as never)
      .mockResolvedValueOnce(status as never)
      .mockResolvedValueOnce({
        status: "success",
        model: provider.model_name,
        source: "workspace",
        tested_at: "2026-01-01T00:00:00Z",
      } as never)
      .mockResolvedValueOnce([provider] as never)
      .mockResolvedValueOnce(status as never);
    render(<AISettingsPage />);

    fireEvent.click(await screen.findByRole("button", { name: "Test connection" }));

    expect(await screen.findByRole("status")).toBeTruthy();
    await waitFor(() => {
      expect(screen.getByRole("status").textContent).toContain(
        "Connection succeeded for llama-3.1-8b-instant.",
      );
    });
  });

  it("displays Facebook Pages and Instagram connections separately", async () => {
    const accounts = [
      {
        id: "facebook-connection",
        workspace_id: workspace.id,
        brand_id: null,
        platform: "facebook_page",
        platform_account_id: "page-1",
        username: "brand",
        display_name: "Brand Facebook",
        profile_image_url: null,
        account_type: "PAGE",
        parent_account_id: null,
        connection_status: "connected",
        granted_scopes: ["pages_show_list"],
        connected_by: "user-1",
        connected_at: "2026-01-01T00:00:00Z",
        last_verified_at: null,
        last_error_code: null,
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      },
      {
        id: "instagram-connection",
        workspace_id: workspace.id,
        brand_id: null,
        platform: "instagram",
        platform_account_id: "instagram-1",
        username: "brand",
        display_name: "brand",
        profile_image_url: null,
        account_type: "BUSINESS",
        parent_account_id: "facebook-connection",
        connection_status: "connected",
        granted_scopes: ["instagram_basic"],
        connected_by: "user-1",
        connected_at: "2026-01-01T00:00:00Z",
        last_verified_at: null,
        last_error_code: null,
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      },
    ];
    vi.mocked(apiRequest)
      .mockResolvedValueOnce(accounts as never)
      .mockResolvedValueOnce([] as never);
    render(<SocialAccountsPage />);

    expect(await screen.findByText("Brand Facebook")).toBeTruthy();
    expect(screen.getByText("Facebook Page")).toBeTruthy();
    expect(screen.getByText("Instagram Professional")).toBeTruthy();
    expect(screen.getByText(/BUSINESS/)).toBeTruthy();
  });
});
