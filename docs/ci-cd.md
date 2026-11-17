# CI/CD

Two GitHub Actions workflows: `ci.yml` checks every change, `deploy-staging.yml` deploys to staging when a person starts it. Nothing deploys automatically, and there is no production deployment workflow.

**Verification status.** The repository has no remote, so neither workflow has run on GitHub. Every command in `ci.yml` was run locally on 2026-11-16 (results below), except the Trivy image scan, which needs the GitHub runner. `deploy-staging.yml` has not been executed at all: it needs a staging server and secrets.

## `ci.yml`: checks on every pull request and push to `main`

| Job | Steps | Required by section 12 |
|---|---|---|
| **Backend** | Install pinned dependencies with the transitive lock (`-c constraints.txt`); `ruff check`; byte-compile; full pytest suite on in-memory SQLite with mocked Meta, Groq and Redis | Dependency installation, lint, backend tests |
| **Backend integration** | PostgreSQL 16 and Redis 7 service containers; `alembic upgrade head` from empty; `alembic check` (models match migrations); `alembic downgrade -1` then upgrade (latest migration reversible); start the API and wait for `/api/v1/ready`; full pytest suite against PostgreSQL | Integration tests, migration validation |
| **Frontend** | `npm ci`; ESLint; `next typegen` + `tsc --noEmit`; Vitest; production build | Lint, type check, frontend tests, production build |
| **Security** | `pip-audit` on the full lock; `npm audit` for production dependencies (high and critical); no tracked environment files; no credential-shaped strings in the repository | Security and dependency checks |
| **Docker** | Both Compose files valid; production file publishes only ports 80 and 443; build both production images; images run as non-root; production image refuses to start without secrets; Trivy scan (critical, fixable) | Docker build |

Every step fails the job on error; there are no `continue-on-error` steps. The workflow has read-only repository permissions and uses no secrets.

To make the checks binding, protect `main` in the repository settings: require a pull request, require these five jobs to pass, and disallow force pushes. That is repository configuration and is not set by these files.

### Type checking

The frontend is type-checked with TypeScript in strict mode. The backend has no static type check in CI: running one over the existing code would need a round of annotation fixes first, so the lint is limited to correctness rules (syntax errors, undefined names, unused imports and variables). Adding mypy or pyright is a reasonable follow-up.

### Formatting

No formatter is enforced. Introducing one would rewrite most files in a single change; if you want it, do it as its own commit.

### Local equivalents

```sh
make check        # lint, types, backend and frontend tests
make audit        # dependency vulnerabilities
# PostgreSQL integration run (needs a database whose name contains "test"):
cd backend && TEST_DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/autowok_test pytest
```

### Local results, 2026-11-16

| Check | Result |
|---|---|
| `ruff check app perf scripts tests` | Pass (22 unused imports/variables removed first) |
| Backend tests, SQLite, final code | 232 passed |
| Backend tests, PostgreSQL 16, full suite | 231 passed in 11 min 22 s. This run was made before the dependency upgrade and the last non-database changes (route labels, configuration error text, one added test). |
| Backend tests, PostgreSQL 16, final code | End-to-end and operations suites only: 28 passed in 3 min 10 s. The full suite was not repeated on the final code because the workstation was saturated by unrelated work (the SQLite run took 52 minutes instead of 2). CI runs the full suite on PostgreSQL. |
| `alembic upgrade head` / `check` / `downgrade -1` / `upgrade head` on PostgreSQL 16 | Pass, no drift, no invalid indexes |
| ESLint, `tsc --noEmit` | Pass |
| Frontend tests | 59 passed |
| Frontend production build | Pass, 45 routes |
| `pip-audit` (43 packages) | No known vulnerabilities |
| `npm audit --omit=dev` | 0 vulnerabilities |
| Compose files | Both valid |
| Production images | Built; non-root; fail-closed start verified |
| Trivy scan | **Not run** (GitHub Action) |

## `deploy-staging.yml`: manual staging deployment

* Trigger: `workflow_dispatch` only, with the commit to deploy and whether to run migrations.
* Approval: both jobs use the `staging` GitHub environment. Configure that environment with required reviewers so a second person approves each run.
* Steps: build both images for the chosen commit and push them to GitHub Container Registry tagged with the commit; then, over SSH on the staging server: pull, **back up**, migrate, `up -d`, and wait for `/api/v1/ready`. The job fails if the new version does not become ready.
* Secrets (environment secrets, never in the repository): `STAGING_SSH_HOST`, `STAGING_SSH_USER`, `STAGING_SSH_KEY`, `STAGING_SSH_KNOWN_HOSTS`, `STAGING_DEPLOY_PATH`; variable `STAGING_PUBLIC_ORIGIN`.
* The server's `.env.production` is managed on the server. The workflow never writes application secrets.

Before first use: create the staging server ([deployment.md](deployment.md)), log it in to the registry (`docker login ghcr.io` with a read-only token), create the environment and its secrets, and run the workflow once against a commit that passed CI.

### Production

There is deliberately no production workflow. When you add one, copy the staging workflow with a `production` environment, its own secrets and reviewers, and deploy only image tags that were already verified on staging (same commit, same images, no rebuild).

## Dependency updates

`.github/dependabot.yml` proposes weekly updates for Python, npm, Docker base images and GitHub Actions as pull requests. They go through the same CI and are merged by a person ([dependency-audit.md](dependency-audit.md#upgrade-policy)).

## Supply chain notes

* Python: direct dependencies pinned in `requirements.txt`; all 43 resolved packages pinned in `constraints.txt`. Hashes are not pinned (`--require-hashes`); that is a possible hardening step.
* npm: `package-lock.json` with `npm ci`; the image build uses `--ignore-scripts` so dependency install scripts do not run.
* GitHub Actions are referenced by version tag, not commit SHA. Pinning to SHAs is stricter; Dependabot can maintain them.
* Base images are referenced by tag (`python:3.12-slim`, `node:22-alpine`, `postgres:16-alpine`, `redis:7-alpine`, `caddy:2.8-alpine`), not digest.
