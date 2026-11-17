# Dependency audit (Phase 12)

Audit date: 2026-11-16. Tools: `pip-audit` 2.7.3 (PyPI and OSV advisory data) and `npm audit`. Container images were built but **not scanned**: no image scanner was available locally (the CI workflow runs Trivy).

## Result

| Area | Before | After |
|---|---|---|
| Backend, all resolved packages (43) | 74 advisories in 4 packages | No known vulnerabilities |
| Frontend, production dependencies | 0 | 0 |
| Frontend, development tooling | 7 moderate | 7 moderate (not shipped; see below) |

## Backend

### Advisories found and resolved

| Package | Was | Advisories | Now | Why it mattered here |
|---|---|---|---|---|
| Pillow | 11.0.0 | 55 | 13.0.0 | Decodes every uploaded image. All fixes are in 12.x–13.0.0. |
| Starlette (via FastAPI) | 0.38.6 | 7 | 1.10.0 | Multipart form parts buffered without limit (denial of service on the upload endpoint); request URL built from an unvalidated `Host` header; request path handling. |
| python-multipart | 0.0.20 | 6 | 0.0.34 | Denial of service while parsing crafted multipart bodies; `Content-Length` not validated. |
| cryptography | 44.0.2 | 6 | 50.0.2 | Bundled OpenSSL updates; certificate and PKCS#7 handling. Autowok uses only Fernet, so direct exposure was low, but the OpenSSL fixes apply to every TLS connection the process makes. |

### Upgrades made

| Package | From → to | Kind | Compatibility work |
|---|---|---|---|
| FastAPI | 0.115.0 → 0.163.1 | Many minor versions | Required to move Starlette. One behaviour change found: a matched route's path no longer includes the router prefix. Autowok's own code did not depend on that; the new metrics and log labels did, and now derive the route pattern from path parameters instead. |
| Starlette | 0.38.6 → 1.10.0 | **Major** | No application changes needed. Now pinned explicitly. |
| Pillow | 11.0.0 → 13.0.0 | **Two majors** | No changes needed. Upload validation, EXIF stripping, thumbnail and decompression-bomb tests pass. |
| cryptography | 44.0.2 → 50.0.2 | **Six major versions** | No changes needed. Fernet encryption, decryption and key-rotation tests pass. |
| python-multipart | 0.0.20 → 0.0.34 | Patch series | None. |
| prometheus-client | new, 0.21.1 | Added | Metrics endpoint. Pure Python, no dependencies. |

Evidence of compatibility: the full backend suite (232 tests, including upload, encryption, OAuth, publishing and the end-to-end workflow) passes on the upgraded set with the in-memory database, and the end-to-end and operations suites pass on PostgreSQL 16; the production image builds and runs; an alternating old/new timing comparison showed no measurable performance difference ([performance-report.md](performance-report.md#noise-and-what-the-numbers-can-support)). Existing stored ciphertext (Fernet tokens) is format-stable across cryptography versions; this was not tested against a database encrypted by the old version, only by the unit tests.

**Breaking changes for operators:** none in configuration or data. Rebuild the image; do not reuse a virtual environment created from the old pins.

### Not upgraded

These have newer releases but no known vulnerability at the pinned version, so they were left alone rather than changed without a reason:

| Package | Pinned | Latest seen | Note |
|---|---|---|---|
| uvicorn | 0.32.1 | 0.54.0 | |
| pydantic / pydantic-settings | 2.9.2 / 2.5.2 | 2.14.3 | Same major. |
| SQLAlchemy | 2.0.36 | 2.1.8 | 2.1 is a minor series with behaviour changes; evaluate separately. |
| alembic, psycopg, redis, httpx, argon2-cffi, email-validator | as pinned | – | Not checked individually beyond the vulnerability scan. |

### Other changes

* `pytest` was listed as a runtime dependency and was installed in the image. Test and audit tools moved to `requirements-dev.txt`.
* `constraints.txt` pins all 43 resolved packages, generated inside `python:3.12-slim` so that Linux-only packages (`uvloop`, `httptools`, `watchfiles`) are included. The image and CI install with `-c constraints.txt`.
* No unused runtime dependency was identified among the 17 pinned direct dependencies (a usage check by import search, not an exhaustive analysis).
* All packages come from PyPI; no alternative index, VCS or URL dependency.

## Frontend

* Runtime dependencies: `next` 16.4.3, `react` 19.3.0, `react-dom` 19.3.0. No known vulnerabilities. Patch updates exist (next 16.4.6, react 19.3.1); not applied because nothing required them.
* Development dependencies: 7 moderate advisories, all in the ESLint/TypeScript-ESLint toolchain. They are not part of the production image or the browser bundle (`npm audit --omit=dev` is clean). `npm audit fix` would resolve them; left for a routine update.
* Major updates available and deliberately not taken: TypeScript 7, ESLint 10, Vitest 5, jsdom 31, `@types/node` 26.
* `package-lock.json` is committed; CI and the image use `npm ci`. The image build passes `--ignore-scripts`, so dependency install scripts do not run.

## Container base images

| Image | Used for | Note |
|---|---|---|
| `python:3.12-slim` | API, worker | Official image, Debian based. |
| `node:22-alpine` | Web | Official image. Moved from `node:20-alpine` (development server) to the current LTS line. |
| `postgres:16-alpine`, `redis:7-alpine` | Data | Official images. |
| `caddy:2.8-alpine` | Proxy | Official image. |

Images are referenced by tag, not digest, so a rebuild picks up base-image security updates. Final image sizes: API/worker 377 MB (was 471 MB as a development image), web 315 MB (was 1.28 GB).

**Not done:** a vulnerability scan of the built images (operating-system packages). CI runs Trivy and fails on critical vulnerabilities that have a fix. Run it once on a GitHub runner, or locally with `trivy image autowok-backend:<tag>`, before the first deployment.

## Upgrade policy

1. Dependabot proposes updates weekly as pull requests.
2. Patch and minor updates: merge when CI passes.
3. Major updates: read the release notes, check the items below, run the full suite including the PostgreSQL job, and note the change here.
   * FastAPI/Starlette: middleware order, request body handling, `TestClient` behaviour.
   * Pillow: formats accepted by `media_processing.py`, decompression-bomb behaviour.
   * cryptography: Fernet only; confirm decryption of existing tokens on staging.
   * SQLAlchemy: run the PostgreSQL integration job and `alembic check`.
   * Next.js: read the guides shipped in `frontend/node_modules/next/dist/docs/`; this project targets a version whose conventions differ from older releases.
4. A new advisory in a pinned package fails the CI security job. To accept one temporarily, pass `--ignore-vuln <id>` in `ci.yml` and record the id, reason and review date here. None is accepted at present.
