"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";

import { useAuth } from "@/components/auth-provider";
import { AppShell, ProtectedPage } from "@/components/route-guards";
import { ApiError, apiRequest } from "@/lib/api";
import type { AIProvider } from "@/lib/brand-types";

type ProviderTest = {
  status: string;
  message?: string;
  model?: string;
  tested_at: string;
};

type GroqStatus = {
  enabled: boolean;
  configured: boolean;
  source: "workspace" | "environment" | "missing";
  model_name: string | null;
  api_key_configured: boolean;
};

export default function AISettingsPage() {
  const { selectedWorkspace } = useAuth();
  const [providers, setProviders] = useState<AIProvider[]>([]);
  const [providerName, setProviderName] = useState("openai");
  const [displayName, setDisplayName] = useState("");
  const [modelName, setModelName] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [makeDefault, setMakeDefault] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [busyProvider, setBusyProvider] = useState<string | null>(null);
  const [editingProviderId, setEditingProviderId] = useState<string | null>(null);
  const [groqStatus, setGroqStatus] = useState<GroqStatus | null>(null);
  const [groqModels, setGroqModels] = useState<string[]>([]);
  const [loadingGroqModels, setLoadingGroqModels] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const loadProviders = useCallback(async () => {
    if (!selectedWorkspace) {
      setProviders([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const [providerData, groqData] = await Promise.all([
        apiRequest<AIProvider[]>(
          `/workspaces/${selectedWorkspace.id}/ai-providers`,
        ),
        apiRequest<GroqStatus>(
          `/workspaces/${selectedWorkspace.id}/ai-providers/groq/status`,
        ),
      ]);
      setProviders(providerData);
      setGroqStatus(groqData);
      setError(null);
    } catch (loadError) {
      setError(
        loadError instanceof ApiError
          ? loadError.message
          : "AI provider settings could not be loaded.",
      );
    } finally {
      setLoading(false);
    }
  }, [selectedWorkspace]);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadProviders(), 0);
    return () => window.clearTimeout(timer);
  }, [loadProviders]);

  async function createProvider(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedWorkspace) return;
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const requestBody: Record<string, unknown> = {
        display_name: displayName,
        model_name: modelName,
      };
      if (apiKey || !editingProviderId) requestBody.api_key = apiKey;
      if (providerName === "openai_compatible" || !editingProviderId) {
        requestBody.base_url =
          providerName === "openai_compatible" ? baseUrl || null : null;
      }
      if (editingProviderId) {
        requestBody.is_default = makeDefault;
      } else {
        requestBody.provider_name = providerName;
        requestBody.is_default = makeDefault;
      }
      const saved = await apiRequest<AIProvider>(
        `/workspaces/${selectedWorkspace.id}/ai-providers${
          editingProviderId ? `/${editingProviderId}` : ""
        }`,
        {
          method: editingProviderId ? "PATCH" : "POST",
          body: JSON.stringify(requestBody),
        },
      );
      setProviders((current) => {
        const remaining = current
          .filter((item) => item.id !== saved.id)
          .map((item) =>
            saved.is_default ? { ...item, is_default: false } : item,
          );
        return [...remaining, saved];
      });
      const wasEditing = editingProviderId !== null;
      setEditingProviderId(null);
      setDisplayName("");
      setModelName("");
      setApiKey("");
      setBaseUrl("");
      setMakeDefault(false);
      setNotice(
        wasEditing
          ? "Provider settings updated. The secret key is not shown again."
          : "Provider saved. The secret key is not shown again.",
      );
    } catch (createError) {
      setError(
        createError instanceof ApiError
          ? createError.message
          : "AI provider could not be saved.",
      );
    } finally {
      setSaving(false);
    }
  }

  function editProvider(provider: AIProvider) {
    setEditingProviderId(provider.id);
    setProviderName(provider.provider_name);
    setDisplayName(provider.display_name);
    setModelName(provider.model_name);
    setBaseUrl(provider.base_url ?? "");
    setApiKey("");
    setMakeDefault(provider.is_default);
    setError(null);
    setNotice(null);
  }

  function cancelEdit() {
    setEditingProviderId(null);
    setProviderName("openai");
    setDisplayName("");
    setModelName("");
    setApiKey("");
    setBaseUrl("");
    setMakeDefault(false);
  }

  async function updateProvider(
    provider: AIProvider,
    changes: { is_default?: boolean; is_active?: boolean },
  ) {
    if (!selectedWorkspace) return;
    setBusyProvider(provider.id);
    setError(null);
    setNotice(null);
    try {
      const updated = await apiRequest<AIProvider>(
        `/workspaces/${selectedWorkspace.id}/ai-providers/${provider.id}`,
        { method: "PATCH", body: JSON.stringify(changes) },
      );
      setProviders((current) =>
        current.map((item) => {
          if (item.id === updated.id) return updated;
          if (updated.is_default) return { ...item, is_default: false };
          return item;
        }),
      );
      setNotice("Provider settings updated.");
    } catch (updateError) {
      setError(
        updateError instanceof ApiError
          ? updateError.message
          : "Provider settings could not be updated.",
      );
    } finally {
      setBusyProvider(null);
    }
  }

  async function testProvider(provider: AIProvider) {
    if (!selectedWorkspace) return;
    setBusyProvider(provider.id);
    setError(null);
    setNotice(null);
    try {
      const result = await apiRequest<ProviderTest>(
        provider.provider_name === "groq"
          ? `/workspaces/${selectedWorkspace.id}/ai-providers/groq/test`
          : `/workspaces/${selectedWorkspace.id}/ai-providers/${provider.id}/test`,
        {
          method: "POST",
          ...(provider.provider_name === "groq"
            ? {
                body: JSON.stringify({ model_name: provider.model_name }),
              }
            : {}),
        },
      );
      setNotice(
        `${provider.display_name}: ${
          result.message ??
          (result.model
            ? `Connection succeeded for ${result.model}.`
            : "Connection test completed.")
        }`,
      );
      await loadProviders();
    } catch (testError) {
      setError(
        testError instanceof ApiError
          ? testError.message
          : "The provider connection test could not be completed.",
      );
    } finally {
      setBusyProvider(null);
    }
  }

  async function loadGroqModels() {
    if (!selectedWorkspace) return;
    setLoadingGroqModels(true);
    setError(null);
    try {
      const result = await apiRequest<{ models: string[] }>(
        `/workspaces/${selectedWorkspace.id}/ai-providers/groq/models`,
      );
      setGroqModels(result.models);
      if (result.models.length > 0 && !result.models.includes(modelName)) {
        setModelName(result.models[0]);
      }
    } catch (loadError) {
      setError(
        loadError instanceof ApiError
          ? loadError.message
          : "Groq models could not be loaded.",
      );
    } finally {
      setLoadingGroqModels(false);
    }
  }

  async function testEnvironmentGroq() {
    if (!selectedWorkspace) return;
    setBusyProvider("groq-environment");
    setError(null);
    setNotice(null);
    try {
      const result = await apiRequest<{ status: string; model: string }>(
        `/workspaces/${selectedWorkspace.id}/ai-providers/groq/test`,
        {
          method: "POST",
          body: JSON.stringify({ model_name: modelName || groqStatus?.model_name }),
        },
      );
      setNotice(`Groq connection succeeded for ${result.model}.`);
    } catch (testError) {
      setError(
        testError instanceof ApiError
          ? testError.message
          : "The Groq connection test could not be completed.",
      );
    } finally {
      setBusyProvider(null);
    }
  }

  async function deleteProvider(provider: AIProvider) {
    if (!selectedWorkspace) return;
    if (!window.confirm(`Remove ${provider.display_name}?`)) return;
    setBusyProvider(provider.id);
    setError(null);
    setNotice(null);
    try {
      await apiRequest(
        `/workspaces/${selectedWorkspace.id}/ai-providers/${provider.id}`,
        { method: "DELETE" },
      );
      setProviders((current) =>
        current.filter((item) => item.id !== provider.id),
      );
      setNotice("Provider removed.");
    } catch (deleteError) {
      setError(
        deleteError instanceof ApiError
          ? deleteError.message
          : "Provider could not be removed.",
      );
    } finally {
      setBusyProvider(null);
    }
  }

  const canManage =
    selectedWorkspace?.role === "OWNER" || selectedWorkspace?.role === "ADMIN";

  return (
    <ProtectedPage>
      <AppShell>
        <h1 className="text-3xl font-bold tracking-tight">AI provider settings</h1>
        <p className="mt-2 max-w-3xl text-slate-600">
          Configure a provider for this workspace. API keys are encrypted by the
          backend, never returned to the browser, and are only used when you
          explicitly test the connection.
        </p>
        {!selectedWorkspace ? (
          <p className="mt-6 rounded-xl border border-dashed border-slate-300 p-6 text-sm text-slate-600">
            Select or create a workspace to configure an AI provider.
          </p>
        ) : (
          <>
            {error && (
              <p role="alert" className="mt-5 rounded-lg bg-red-50 p-3 text-sm text-red-800">
                {error}
              </p>
            )}
            {notice && (
              <p role="status" className="mt-5 rounded-lg bg-emerald-50 p-3 text-sm text-emerald-800">
                {notice}
              </p>
            )}
            {loading ? (
              <p className="mt-6">Loading providers…</p>
            ) : (
              <>
              {groqStatus?.source === "environment" && (
                <article className="mt-7 rounded-2xl border border-indigo-200 bg-indigo-50 p-5">
                  <h2 className="font-semibold">Groq · Server-managed</h2>
                  <p className="mt-1 text-sm text-slate-700">
                    The server has a Groq API key configured. Its value is
                    never sent to the browser. Model:{" "}
                    {groqStatus.model_name || "Choose a model below"}.
                    Free-tier usage is subject to account-specific rate limits;
                    Autowok will not switch to a paid provider.
                  </p>
                  {canManage && (
                    <button
                      disabled={busyProvider !== null}
                      onClick={() => void testEnvironmentGroq()}
                      className="mt-3 rounded-lg bg-indigo-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-60"
                    >
                      {busyProvider === "groq-environment"
                        ? "Testing…"
                        : "Test server Groq key"}
                    </button>
                  )}
                </article>
              )}
              <section className="mt-7 space-y-3">
                {providers.length === 0 ? (
                  <p className="rounded-xl border border-dashed border-slate-300 p-6 text-sm text-slate-600">
                    No provider has been configured for {selectedWorkspace.name}.
                  </p>
                ) : (
                  providers.map((provider) => (
                    <article
                      key={provider.id}
                      className="rounded-2xl border border-slate-200 bg-white p-5"
                    >
                      <div className="flex flex-wrap items-start justify-between gap-4">
                        <div>
                          <h2 className="font-semibold">{provider.display_name}</h2>
                          <p className="mt-1 text-sm text-slate-600">
                            {provider.provider_name.replaceAll("_", " ")} ·{" "}
                            {provider.model_name}
                            {provider.is_default ? " · Default" : ""}
                            {!provider.is_active ? " · Inactive" : ""}
                          </p>
                          <p className="mt-1 text-xs text-slate-500">
                            API key: {provider.masked_api_key || "Not configured"}
                            {provider.last_tested_at
                              ? ` · Last test: ${provider.last_test_status} (${new Date(provider.last_tested_at).toLocaleString()})`
                              : " · Not tested"}
                          </p>
                        </div>
                        {canManage && (
                          <div className="flex flex-wrap gap-2">
                            <button
                              disabled={busyProvider !== null}
                              onClick={() => editProvider(provider)}
                              className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium hover:bg-slate-50 disabled:opacity-60"
                            >
                              Edit
                            </button>
                            <button
                              disabled={busyProvider !== null}
                              onClick={() =>
                                void updateProvider(provider, {
                                  is_default: !provider.is_default,
                                  ...(provider.is_active
                                    ? {}
                                    : { is_active: true }),
                                })
                              }
                              className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium hover:bg-slate-50 disabled:opacity-60"
                            >
                              {provider.is_default ? "Default" : "Set default"}
                            </button>
                            <button
                              disabled={busyProvider !== null}
                              onClick={() => void testProvider(provider)}
                              className="rounded-lg bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-60"
                            >
                              {busyProvider === provider.id ? "Working…" : "Test connection"}
                            </button>
                            <button
                              disabled={busyProvider !== null}
                              onClick={() =>
                                void updateProvider(provider, {
                                  is_active: !provider.is_active,
                                })
                              }
                              className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium hover:bg-slate-50 disabled:opacity-60"
                            >
                              {provider.is_active ? "Disable" : "Enable"}
                            </button>
                            <button
                              disabled={busyProvider !== null}
                              onClick={() => void deleteProvider(provider)}
                              className="rounded-lg border border-red-200 px-3 py-2 text-sm font-medium text-red-700 hover:bg-red-50 disabled:opacity-60"
                            >
                              Remove
                            </button>
                          </div>
                        )}
                      </div>
                    </article>
                  ))
                )}
              </section>
              </>
            )}
            {canManage ? (
              <form
                onSubmit={createProvider}
                id="provider-form"
                className="mt-9 max-w-2xl rounded-2xl border border-slate-200 bg-white p-6"
              >
                <h2 className="text-lg font-semibold">
                  {editingProviderId ? "Edit provider" : "Add a provider"}
                </h2>
                <label className="mt-4 block text-sm font-medium">
                  Provider
                  <select
                    value={providerName}
                    onChange={(event) => setProviderName(event.target.value)}
                    disabled={editingProviderId !== null}
                    className="mt-1 w-full rounded-xl border border-slate-300 bg-white px-3 py-2.5"
                  >
                    <option value="openai">OpenAI</option>
                    <option value="anthropic">Anthropic</option>
                    <option value="gemini">Google Gemini</option>
                    <option value="groq">Groq (free tier)</option>
                    <option value="openai_compatible">OpenAI-compatible</option>
                  </select>
                </label>
                <TextField label="Display name" value={displayName} onChange={setDisplayName} required />
                {providerName === "groq" && groqModels.length > 0 ? (
                  <label className="mt-4 block text-sm font-medium">
                    Groq model
                    <select
                      value={modelName}
                      onChange={(event) => setModelName(event.target.value)}
                      required
                      className="mt-1 w-full rounded-xl border border-slate-300 bg-white px-3 py-2.5"
                    >
                      {groqModels.map((model) => (
                        <option key={model} value={model}>{model}</option>
                      ))}
                    </select>
                    <button
                      type="button"
                      onClick={() => void loadGroqModels()}
                      disabled={loadingGroqModels}
                      className="mt-2 text-sm font-semibold text-indigo-700 disabled:opacity-60"
                    >
                      {loadingGroqModels ? "Refreshing models…" : "Refresh model list"}
                    </button>
                  </label>
                ) : (
                  <div>
                    <TextField
                      label="Model name"
                      value={modelName}
                      onChange={setModelName}
                      required
                    />
                    {providerName === "groq" && (
                      <button
                        type="button"
                        onClick={() => void loadGroqModels()}
                        disabled={loadingGroqModels}
                        className="mt-2 text-sm font-semibold text-indigo-700 disabled:opacity-60"
                      >
                        {loadingGroqModels ? "Loading models…" : "Load supported Groq models"}
                      </button>
                    )}
                  </div>
                )}
                <label className="mt-4 block text-sm font-medium">
                  API key
                  <input
                    type="password"
                    autoComplete="new-password"
                    value={apiKey}
                    onChange={(event) => setApiKey(event.target.value)}
                    required={editingProviderId === null}
                    className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2.5"
                  />
                  {editingProviderId && (
                    <span className="mt-1 block text-xs font-normal text-slate-500">
                      Leave blank to keep the currently encrypted key. Enter a
                      new value to replace it.
                    </span>
                  )}
                </label>
                {providerName === "groq" && (
                  <p className="mt-2 text-sm text-slate-600">
                    Groq uses its OpenAI-compatible API. Free-tier usage has
                    model-specific rate limits; check your Groq Console limits.
                    Autowok only calls Groq when you explicitly test the
                    connection.
                  </p>
                )}
                {providerName === "openai_compatible" && (
                  <label className="mt-4 block text-sm font-medium">
                    Custom base URL
                    <input
                      type="url"
                      value={baseUrl}
                      onChange={(event) => setBaseUrl(event.target.value)}
                      placeholder="https://api.example.com/v1"
                      required
                      className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2.5"
                    />
                    <span className="mt-1 block text-xs font-normal text-slate-500">
                      The host must be HTTPS and explicitly allowlisted by the
                      operator.
                    </span>
                  </label>
                )}
                <label className="mt-4 flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={makeDefault}
                    onChange={(event) => setMakeDefault(event.target.checked)}
                    className="size-4"
                  />
                  Use as workspace default
                </label>
                <button
                  disabled={saving}
                  className="mt-5 rounded-xl bg-indigo-600 px-4 py-2.5 font-semibold text-white disabled:opacity-60"
                >
                  {saving
                    ? "Saving…"
                    : editingProviderId
                      ? "Save changes"
                      : "Save provider"}
                </button>
                {editingProviderId && (
                  <button
                    type="button"
                    onClick={cancelEdit}
                    className="ml-3 mt-5 rounded-xl border border-slate-300 px-4 py-2.5 font-semibold"
                  >
                    Cancel
                  </button>
                )}
              </form>
            ) : (
              <p className="mt-6 text-sm text-slate-600">
                You have read-only access to this workspace’s AI provider
                settings.
              </p>
            )}
          </>
        )}
      </AppShell>
    </ProtectedPage>
  );
}

function TextField({
  label,
  value,
  onChange,
  required = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  required?: boolean;
}) {
  return (
    <label className="mt-4 block text-sm font-medium">
      {label}
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        required={required}
        maxLength={160}
        className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2.5"
      />
    </label>
  );
}
