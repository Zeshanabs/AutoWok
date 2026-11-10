# Meta developer setup

This guide configures Meta OAuth for the Facebook Login flow used to discover Facebook Pages and linked Instagram Business or Creator accounts.

## Create the Meta app

1. Create a Meta app in [Meta for Developers](https://developers.facebook.com/). Configure the app's business and privacy details as required for your deployment.
2. Add and configure **Facebook Login** for the relevant platform. Add the exact OAuth redirect URI to the app's valid OAuth redirect URI allowlist:
   `http://localhost:8000/api/v1/oauth/meta/callback`
3. For a deployed environment, replace the local callback with the public HTTPS API URL and set the exact same value in `META_REDIRECT_URI`. Do not use a redirect URI with an extra path, query, fragment, or different trailing slash.
4. Add and request all permissions used by this integration:
   - `pages_show_list` to list Pages the user can access.
   - `pages_read_engagement` for Page/Instagram-related Graph API access as required by Meta.
   - `instagram_basic` to read basic metadata for linked Instagram Professional accounts.
   - `read_insights` (Phase 9) to read Page Insights; the connecting user also needs the ANALYZE task on the Page.
   - `instagram_manage_insights` (Phase 9) to read Instagram account and media insights.
   - Publishing permissions from Phase 7 (`pages_manage_posts`, `publish_video`, `instagram_content_publish`).
   OAuth completes only when Meta reports the first three permissions as granted; the insights and publishing permissions are optional and are checked per feature. Accounts connected without them show insights as unavailable until reconnected (see [Phase 9 analytics](./phase-9-analytics.md)).
5. Keep the app in development mode for initial testing. Add developers, testers, and other permitted test roles to the app and test with their eligible assets.
6. For access to users or assets outside app roles, request the access level Meta requires for the relevant permissions and complete App Review, business verification, and data-handling requirements that Meta applies to the app. Approval is controlled by Meta and is not included in this repository.

Official reference: [Instagram API with Facebook Login](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-facebook-login), [Permissions Reference](https://developers.facebook.com/documentation/development/permissions), and [Meta App Review](https://developers.facebook.com/docs/app-review).

## Configure Autowok

Set these values in the ignored root `.env` file. Never commit real values or expose them through `NEXT_PUBLIC_*`.

```dotenv
META_APP_ID=
META_APP_SECRET=
META_GRAPH_API_VERSION=v26.0
META_REDIRECT_URI=http://localhost:8000/api/v1/oauth/meta/callback
META_OAUTH_STATE_SECRET=
TOKEN_ENCRYPTION_KEY=
TOKEN_ENCRYPTION_KEY_PREVIOUS=
CORS_ORIGINS=http://localhost:3001
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

Use a long, random `META_OAUTH_STATE_SECRET`. Generate a Fernet key for `TOKEN_ENCRYPTION_KEY` with:

```powershell
cd backend
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

`META_GRAPH_API_VERSION` must use the `vNN.N` format. Confirm the selected Graph API version is currently supported by Meta before deployment. `CORS_ORIGINS` must contain the browser origin from your environment (the template defaults to port 3000), not the API origin.

Restart Docker Compose after changing server-side environment values:

```powershell
docker compose up --build -d backend frontend
docker compose ps
```

## Connect eligible accounts

1. Sign in to Autowok as a workspace Owner or Admin and open **Settings → Social accounts**.
2. Select **Connect Facebook / Instagram with Meta** and approve the requested permissions.
3. After the redirect, select the Pages or linked Instagram Professional accounts to connect. Pages must include a `MANAGE` or `CREATE_CONTENT` task. Instagram accounts must be linked to an eligible Page and report account type `BUSINESS` or `MEDIA_CREATOR`. Consumer/personal Instagram accounts are excluded by Meta's API.
4. Optionally associate each connection with a brand, then use **Verify** to recheck its metadata or **Disconnect** to remove its stored token.

If OAuth is redirected to an error, confirm that the logged-in user is still a workspace Owner/Admin, the redirect URI matches exactly, the callback is reachable, the encryption key is configured, and the required permission was granted. Meta may require review or business verification before accounts outside the app's test roles can authorize.

Meta refresh behavior and account eligibility are described in [Phase 3 integrations](./phase-3-integrations.md). No live Meta credentials were used for repository tests; test-mode and production approval must be verified by the app owner.
