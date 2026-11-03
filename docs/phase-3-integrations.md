# Phase 3 integrations

Phase 3 adds workspace-scoped Meta OAuth foundations for Facebook Pages and Instagram Professional accounts, plus a reusable Groq provider integration. It does not add content generation, publishing, or Phase 4 research workflows.

## What is included

- Meta OAuth authorization with a random, HMAC-hashed, user- and workspace-bound state that expires after ten minutes and can be consumed only once.
- Redis-backed per-user/IP request limits for Meta authorization, callback, refresh, discovery, connect, and verification operations.
- Encrypted Meta user and Page access tokens. API responses and browser UI never return token values.
- Page discovery limited to Pages where the authorizing user has `MANAGE` or `CREATE_CONTENT` tasks.
- Instagram discovery limited to linked `BUSINESS` and `MEDIA_CREATOR` accounts. A linked Facebook Page is required; personal Instagram accounts are not supported by this Meta API flow.
- Workspace-isolated account records with optional brand associations, status verification, disconnection, and credential refresh.
- Groq model listing, configuration status, and explicit connection tests. The service layer also has bounded input validation and completion/usage primitives, but no generation workflow or user-facing generation endpoint is exposed.

## Meta API endpoints

All paths below are under `/api/v1` and require an authenticated workspace Owner or Admin, except account listing and reading, which are available to workspace members.

| Method | Path | Purpose |
|---|---|---|
| GET | `/oauth/meta/authorize?workspace_id={id}` | Start Meta OAuth; optional `brand_id` can be included |
| GET | `/oauth/meta/callback` | Exchange and store the authorization after state validation |
| POST | `/oauth/meta/refresh?workspace_id={id}` | Refresh the current user's Meta authorization and Page credentials |
| GET | `/workspaces/{id}/social-accounts/meta/facebook-pages` | Discover eligible Facebook Pages |
| GET | `/workspaces/{id}/social-accounts/meta/instagram-accounts` | Discover linked Instagram Professional accounts |
| POST | `/workspaces/{id}/social-accounts/meta/connect` | Connect a discovered Page or Instagram account |
| GET | `/workspaces/{id}/social-accounts` | List workspace connections |
| PATCH | `/workspaces/{id}/social-accounts/{account_id}` | Change the optional brand association |
| POST | `/workspaces/{id}/social-accounts/{account_id}/verify` | Verify an account token and refresh metadata |
| POST | `/workspaces/{id}/social-accounts/{account_id}/disconnect` | Remove the stored account credential |

Use the setup guide in [Meta developer setup](./meta-developer-setup.md) before attempting OAuth. The callback URL must exactly match `META_REDIRECT_URI` and the URL configured in the Meta app.

## Groq endpoints

All paths are under `/api/v1/workspaces/{workspace_id}/ai-providers/groq`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/status` | Show whether Groq is configured and whether the key source is workspace or environment |
| GET | `/models` | Explicitly fetch the available models (Owner/Admin) |
| POST | `/test` | Explicitly test the selected model and configured key (Owner/Admin) |

Groq calls use the official OpenAI-compatible API host. The server does not silently switch providers, start paid billing, retry a rate-limited request, or automatically retry completion POSTs. Free-tier model availability and limits vary by account and can change. Follow [Groq setup](./groq-setup.md) and do not enable paid billing if you require free-only usage.

## Verification limits

The backend and frontend tests use mocked Meta and Groq responses. No production Meta app credentials, App Review approval, or real vendor account was used, so deployment OAuth and live API behavior remain unverified. Meta access for users outside app roles requires the access level, review, and business verification applicable to the selected permissions. The app should remain in development/test mode until Meta approves the required access.

Apply migrations before starting the services. See the [README](../README.md) for validation commands and the specific vendor setup guides.
