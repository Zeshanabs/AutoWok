# Phase 7 — Media library, platform previews, and controlled publishing

Phase 7 adds the first complete media-to-publishing workflow:

1. Upload an image or video to the **Media Library** (`/dashboard/media`).
2. Attach media to an approved content draft (`/dashboard/content/[projectId]`).
3. Preview the post as an approximate Facebook Page or Instagram rendering.
4. Choose a connected, eligible account, explicitly confirm, and publish immediately.
5. A background worker publishes through the official Meta Graph API and records
   every attempt. Results appear in the editor and in `/dashboard/publishing`.

Scheduled publishing is **not** part of Phase 7. Phase 8 adds it on top of the same job system.

## Verification status

| Area | Status |
| --- | --- |
| Media upload, validation, storage, thumbnails, EXIF stripping | Automated tests (real Pillow decoding, local storage) |
| Signed media URLs | Automated tests |
| Facebook Page publishing (text, photo, multi-photo, video) | **Mocked Meta API only — live publishing NOT VERIFIED** |
| Instagram publishing (image, Reel, carousel, container polling) | **Mocked Meta API only — live publishing NOT VERIFIED** |
| Worker, retries, idempotency, crash recovery | Automated tests against SQLite; PostgreSQL run pending (see README) |

No live Meta app, App Review approval, or eligible test accounts were available while building
this phase, so no post has been published to a real Facebook Page or Instagram account.

## Media storage

* Files are stored through the `StorageBackend` protocol in `backend/app/services/storage.py`.
  `LocalStorageService` writes to `LOCAL_STORAGE_PATH` (Docker: `./storage/local` mounted into
  the backend and worker). Writes are atomic (temporary file, then rename).
* Callers only use opaque storage keys (`workspaces/<workspace>/media/<uuid>.<ext>`). Keys are
  validated against path traversal and never derived from the user's filename.
* Object storage (S3, GCS, R2…) can be added by implementing the same protocol
  (`save_file`, `read_file`, `exists`, `delete_file`, `local_path`) and selecting it with
  `STORAGE_PROVIDER`. Only `local` is implemented in this phase.
* Media is private. Browsers read it through authenticated endpoints that check workspace membership.

### Upload validation

* Extensions allowed: `.jpg .jpeg .png .gif .mp4 .m4v .mov`. Everything else is rejected (415).
* The type is detected from **file contents** (magic bytes). The browser MIME type is ignored and
  the extension must agree with the contents.
* Images are fully decoded with Pillow. Decompression bombs and corrupt files are rejected.
  JPEG and PNG files are re-encoded to remove EXIF/GPS metadata, and a 480 px JPEG thumbnail is generated.
* MP4/QuickTime files are parsed structurally (`moov/mvhd/tkhd`) to read duration and dimensions.
  Files without a valid `moov` box are rejected. Video thumbnails are not generated (no ffmpeg dependency).
* Size limits: `MEDIA_MAX_IMAGE_BYTES` (default 8 MB, Instagram's image limit) and
  `MEDIA_MAX_VIDEO_BYTES` (default 100 MB). Uploads are read in chunks and stopped at the limit.
* Duplicates are detected by SHA-256 checksum per workspace. The existing asset is returned with `duplicate: true`.
* If storage fails, the request returns 503, any partial files are removed, and no database row is created.

### Signed URLs for Meta

Meta's publishing APIs fetch media from a public URL. Autowok never makes media permanently public.
Instead the worker generates `PUBLIC_MEDIA_BASE_URL/api/v1/public-media/<id>?expires=…&signature=…`:

* An HMAC-SHA256 signature over asset ID, expiry, and variant using `MEDIA_URL_SIGNING_SECRET`.
* It expires after `MEDIA_SIGNED_URL_TTL_SECONDS` (default 1 hour).
* It is constant-time compared, and archived assets stop resolving immediately.

`PUBLIC_MEDIA_BASE_URL` must be an HTTPS address that Meta's servers can reach. In local
development, use an HTTPS tunnel to the backend. Without it, posts with media are blocked with
a clear validation error. Text-only Facebook posts still work.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/v1/media-assets/upload` | Multipart upload (`workspace_id`, `file`, optional `brand_id`, `title`) |
| `GET` | `/api/v1/media-assets?workspace_id=&media_type=&brand_id=&search=&include_archived=` | List/filter/search |
| `GET` | `/api/v1/media-assets/{id}` | Details |
| `PATCH` | `/api/v1/media-assets/{id}` | Update `title`, `brand_id` |
| `GET` | `/api/v1/media-assets/{id}/content` · `/download` · `/thumbnail` | Authenticated file access |
| `POST` | `/api/v1/media-assets/{id}/access-url` | Short-lived (≤15 min) signed path |
| `DELETE` | `/api/v1/media-assets/{id}` | Archive (uploader, Owner, or Admin) |
| `PUT` | `/api/v1/content/drafts/{draft_id}/media` | Set the ordered attachment list (attach/reorder/remove). `POST` is kept as an alias |
| `DELETE` | `/api/v1/content/drafts/{draft_id}/media/{media_id}` | Remove one attachment |
| `GET` | `/api/v1/content/drafts/{draft_id}/media-preview?social_account_id=` | Approximate platform preview and validation |
| `POST` | `/api/v1/content/drafts/{draft_id}/publishing/validate` | Full eligibility report for one account |
| `POST` | `/api/v1/content/drafts/{draft_id}/publish` | Request immediate publishing (`confirm: true` required; optional `idempotency_key` or `Idempotency-Key` header) → `202` job |
| `GET` | `/api/v1/workspaces/{workspace_id}/publishing/jobs` | History (filters: `status`, `platform`, `project_id`, `draft_id`, `source`) |
| `GET` | `/api/v1/publishing/jobs/{id}` | Job with attempts |
| `POST` | `/api/v1/publishing/jobs/{id}/retry` | Retry a failed job (`confirm_not_published` for uncertain results) |
| `POST` | `/api/v1/publishing/jobs/{id}/cancel` | Cancel a job that has not started |

### Approval and versioning

Media is part of the approved content. Attaching, removing, or reordering media creates a new draft
version (the snapshot includes `media_asset_ids`) and resets an approved project to `draft`, so it must be
approved again. Media cannot change while a project is awaiting review. Restoring a version restores its media.

## Eligibility checks (enforced server-side on request **and** again by the worker)

1. The user is authenticated and is a workspace **Owner or Admin** (Members can preview but not publish).
2. The draft, account, and media all belong to the same workspace (cross-workspace IDs return 404).
3. The project and draft are `approved`, and the draft version still matches the version the job was created for.
4. The account's platform matches the draft (`facebook` → Facebook Page, `instagram` → Instagram account).
5. The account is `connected`, has a credential that has not expired, and for Instagram is a
   `BUSINESS` or `MEDIA_CREATOR` (Professional) account.
6. The account was granted the publishing permissions:
   * Facebook: `pages_manage_posts`, `pages_read_engagement`, `pages_show_list` (+ `publish_video` for video)
   * Instagram: `instagram_basic`, `instagram_content_publish`, `pages_read_engagement`
7. Caption and hashtag limits pass (Instagram: ≤2,200 characters including hashtags, ≤30 hashtags).
8. Media exists, is not archived, is ready, and its file is present. Supported formats:
   * Facebook: text, 1 photo, 2–10 photos (multi-photo post), or 1 video (no mixing video with photos).
   * Instagram: 1 JPEG image, 1 video (published as a Reel), or a 2–20 item carousel. **JPEG only**
     for images (official requirement). Aspect ratios outside 4:5–1.91:1 and Reels outside 3 s–15 min are warnings.
9. It has not already been published (or is not being published) to that account.

## Meta Graph API calls

The calls reuse `MetaGraphClient` from Phase 3, and the Page access token stored encrypted at connection time.

* Facebook text: `POST /{page-id}/feed` (`message`)
* Facebook photo: `POST /{page-id}/photos` (`url`, `message`)
* Facebook multi-photo: `POST /{page-id}/photos` (`url`, `published=false`) for each photo, then
  `POST /{page-id}/feed` with `attached_media[n]={"media_fbid": …}`
* Facebook video: `POST /{page-id}/videos` (`file_url`, `description`)
* Instagram: `POST /{ig-id}/media` (`image_url` | `media_type=REELS` + `video_url` | carousel children with
  `is_carousel_item=true`, then `media_type=CAROUSEL` + `children`). Poll `GET /{container}?fields=status_code`
  (`IN_PROGRESS`, `FINISHED`, `ERROR`, `EXPIRED`, `PUBLISHED`). Check
  `GET /{ig-id}/content_publishing_limit`, then `POST /{ig-id}/media_publish` (`creation_id`).
* Permalinks: `permalink_url` (Facebook) / `permalink` (Instagram), fetched best-effort.

These were checked against Meta's current Instagram Content Publishing and Pages API documentation.
The Pages documentation does not describe the photo caption parameter or the multi-photo and video
flows; those use the Graph API reference (`message`, `attached_media`, `file_url`/`description`) and
must be confirmed during live testing.

### Meta app configuration

* The login dialog now also requests `pages_manage_posts`, `publish_video`, and `instagram_content_publish`.
  These are optional at callback time, so existing connections keep working. Accounts connected before
  Phase 7 must **reconnect** to grant them, and eligibility reports exactly which permission is missing.
* Publishing to Pages or Instagram accounts the app does not own requires **Advanced Access through
  Meta App Review** for these permissions. In development mode, only app roles (admins, developers,
  testers) can publish.
* The person connecting a Page needs the `CREATE_CONTENT` or `MANAGE` task on it.
* Personal Instagram accounts cannot publish through the API.

## Publishing jobs and reliability

* `content_publications` is the job table (it existed unused before Phase 7 and was extended).
  `publishing_attempts` records every attempt with stage, error category, code, and message.
* **Idempotency:** `(workspace_id, idempotency_key)` is unique. The UI sends a fresh key per confirmation,
  so double-clicks and network retries return the same job.
* **Duplicate prevention:** `active_guard` (`draft:account`) is unique and is set while a job is active
  or published. The database rejects a second job for the same draft and account, even under concurrency.
* **Claiming:** workers claim jobs with one conditional `UPDATE … WHERE status = … AND (lease expired)`,
  so exactly one worker wins. A lease (`PUBLISHING_LEASE_SECONDS`) lets another worker recover a job after a crash.
* **Checkpoints:** stage, container IDs, and child IDs are committed *before* each next Meta call.
* **Never published without confirmation:** status becomes `published` only after Meta returns the post or media ID.

### Retry rules

| Category | Example | Behaviour |
| --- | --- | --- |
| `network`, `platform_temporary` | timeouts before the final call, 5xx, code 1/2, container still processing | Automatic retry with bounded exponential backoff and jitter, up to `PUBLISHING_MAX_ATTEMPTS` |
| `rate_limited` | codes 4/17/32/613, Instagram publishing quota | Automatic retry, minimum 5 minute base delay |
| `token_expired` | code 190 | Fails; the account is marked `expired`. Reconnect, then retry |
| `permission` | code 10, 200–299 | Fails; reconnect and grant permissions, then retry |
| `invalid_media` / `invalid_content` | Instagram 2207xxx subcodes, code 100, container `ERROR` | Fails; fix the content or media (requires re-approval), then retry |
| `permanent` | anything else | Fails; not retryable |
| `uncertain` | timeout/5xx **during the final Facebook publish call**, or a worker crash at that point | Fails and is **never retried automatically**. The duplicate guard stays in place. The user checks the Page and confirms "not published" to retry |

Instagram is safe to resume because the media container ID is saved before `media_publish`. A retry
first checks the container: `PUBLISHED` means it already went live, so it is marked published without
publishing again. `EXPIRED` or `ERROR` containers are recreated.

## Worker

```
cd backend && python -m app.worker        # or: make worker / docker compose up worker
```

The worker waits on the Redis list `autowok:publishing:ready` for fast pickup and also polls the database
every `WORKER_POLL_INTERVAL_SECONDS`. A Redis outage only adds latency. Run as many workers as needed.

## Security notes

* Access tokens are decrypted only inside the worker, sent only as `Authorization: Bearer` headers, and never
  logged, stored in job responses, or returned to the browser (tests assert this).
* Only server-generated signed URLs are given to Meta. No user-supplied URLs are fetched, so this phase adds no SSRF surface.
* All IDs from the browser are re-checked against the database for workspace ownership.

## Known limitations

* Live Meta publishing is **not verified** (mocks only).
* Local storage only. Object storage needs a new `StorageBackend` implementation.
* No video thumbnails or transcoding. Instagram PNG/GIF images must be converted to JPEG by the user.
* Instagram resumable (`rupload`) video uploads are not used. Videos are fetched by Meta from the signed URL.
* Recovering an Instagram post that was published during a timeout records it as published, but the media
  ID and permalink may be unknown (Meta returns only the container status).
