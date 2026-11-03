# Groq setup (free-tier workflow)

Autowok supports Groq's OpenAI-compatible API at `https://api.groq.com/openai/v1`. Groq is optional; no API request is made just by opening settings. Listing models and testing a connection make real requests to Groq.

## Create and configure a free-tier key

1. Sign in to [Groq Console](https://console.groq.com/) and review the current account and model limits.
2. Create an API key in [Groq API Keys](https://console.groq.com/keys). Keep the key private.
3. Use one of these server-side configuration paths:
   - **Workspace key:** Open Autowok **Settings → AI**, choose **Groq (free tier)**, enter a display name, model ID, and key, then save. The key is encrypted at rest using `AI_ENCRYPTION_KEY`.
   - **Server-managed key:** Put `GROQ_API_KEY` in the ignored root `.env` and set `GROQ_DEFAULT_MODEL` to an available model ID. Restart the backend. The UI shows whether a key is available but never receives the secret.
4. In the workspace AI settings, load available models and select a model that your account permits. Model IDs and limits can change; use the live list rather than copying a stale example.
5. Run **Test connection** only when ready to make a real Groq request. A successful test confirms that the saved key can access the selected model.

The API key is never a `NEXT_PUBLIC_*` variable. Do not paste it into source files, screenshots, issue reports, or chat. If a key is disclosed, revoke it in Groq Console and replace it.

## Free-only usage

Groq's free-tier limits, model access, and availability are determined by Groq and can change. Autowok does not upgrade an account, enable billing, switch to another provider, or retry a rate-limited request. If Groq returns a rate limit, wait for the applicable limit to reset and check the Console. Do not add a payment method or enable paid billing if you want to remain free-only.

## Environment variables

```dotenv
GROQ_API_KEY=
GROQ_API_BASE_URL=https://api.groq.com/openai/v1
GROQ_DEFAULT_MODEL=
GROQ_TIMEOUT_SECONDS=60
GROQ_MAX_RETRIES=2
GROQ_ENABLED=true
```

`GROQ_API_BASE_URL` is restricted to Groq's official HTTPS API hostname. The backend may make bounded retries for transient model-list GETs only; it does not retry HTTP 429 responses or completion POSTs.

See [Phase 3 integrations](./phase-3-integrations.md) for endpoint behavior and [token storage](./security/token-storage.md) for key handling and rotation.
