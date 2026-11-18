# Hosting comparison

Where Autowok could run, what each option costs, and why one is recommended. **Nothing has been bought, created or signed up for.** Choosing a provider is a decision for the project owner ([PRODUCTION_ARCHITECTURE.md](PRODUCTION_ARCHITECTURE.md) explains the recommended design).

**About the prices.** They were read from each provider's own pricing page on 2026-11-17. Prices change, some pages did not show every figure, and taxes (VAT/GST) are extra. Items that could not be confirmed on a first-party page are marked *unverified*. Check the provider's page again on the day you order.

**About free tiers.** A free tier is a marketing offer, not a promise: providers shrink, pause or remove them, and several of the ones below sleep, expire or forbid commercial use. None of them is recommended for the production copy of Autowok.

## What Autowok needs from a host

These come from the existing code, not from preference. They decide which options are even possible.

| Need | Why | Effect on hosting |
|---|---|---|
| Run six containers together | proxy, web, API, worker, PostgreSQL, Redis ([docker-compose.prod.yml](../../docker-compose.prod.yml)) | Any Linux server with Docker works. A "platform" must support every piece. |
| A worker that is always running | It wakes at least every 15 seconds to publish scheduled posts | Hosts that put idle services to sleep cannot run it. |
| One disk shared by the API **and** the worker | Uploaded media are files on a disk (`STORAGE_PROVIDER` supports only `local`). The API saves them; the worker reads them to publish. | **This rules out most platforms**: Render, Railway and Fly.io attach a disk to one service only. They would need object storage (S3-style), which Autowok does not have yet. |
| Meta must be able to download media | Facebook/Instagram fetch each image or video from a signed public HTTPS link | The server needs a public HTTPS address and enough outbound bandwidth. |
| About 4 GB of memory | The Compose file caps the stack at about 4.2 GB | A 2 vCPU / 4 GB server is the starting size. |
| x86-64 processor (preferred) | GitHub's build machines produce x86-64 images | ARM servers (cheaper at some hosts) would need the images built differently. |

## Option 1 (recommended): one virtual server running the existing Compose stack

You rent one Linux server and run the stack exactly as it was built and tested. No code changes.

| Provider | Plan closest to 2 vCPU / 4 GB | Price per month | Next size (4 vCPU / 8 GB) | Server backups | Regions |
|---|---|---|---|---|---|
| **Hetzner Cloud** (cost-optimized) | CX23: 2 vCPU, 4 GB, 40 GB disk | €5.99 | CX33: €8.99 | +20% of server price (daily, 7 kept) | Germany, Finland only |
| **Hetzner Cloud** (regular) | CPX22: 2 vCPU, 4 GB, 80 GB disk | €16.99 Helsinki, €19.99 Nuremberg, €26.99 Singapore | CPX32: €30.49 – €49.49 | +20% | Germany, Finland, Singapore, USA |
| **DigitalOcean** | Basic: 2 vCPU, 4 GB, 80 GB disk | $24 | $48 | +20% weekly ($4.80) or +30% daily ($7.20) | USA, Canada, Netherlands, UK, Germany, **India (Bangalore)**, Singapore, Australia |
| **Akamai (Linode)** | Linode 4 GB: 2 vCPU, 4 GB, 80 GB disk | $24 | $48 | Paid add-on (*price unverified*, historically $5) | 30+ including **Mumbai, Chennai**, Singapore, Frankfurt, London |
| **Oracle Cloud "Always Free"** | ARM, documented as 2 cores / 12 GB | $0 | – | 5 volume backups, no schedule | Home region chosen at sign-up |

Notes:

* **Hetzner's cheapest line was shown as "currently unavailable" on 2026-11-17**, and Hetzner raised prices twice in 2026. If you can order a CX23 in your account it is the cheapest sound option; if not, the realistic Hetzner price is the CPX22 row. Hetzner prices exclude VAT.
* **None of these providers has a Middle East region.** If most users are in South Asia, the nearest choices are DigitalOcean Bangalore, Akamai Mumbai/Chennai, or Singapore (any provider). If most users are in Europe, Germany or Finland. Distance adds roughly 0.1–0.2 seconds to each click; it does not affect scheduled publishing.
* **Oracle's free server is not recommended for production.** Oracle documents that it may take back a server it considers idle, new servers often fail with "out of capacity", and it is ARM. It is acceptable for a short experiment.
* Vultr was not compared: its pricing page could not be read (*unverified*).

| Criterion | Assessment |
|---|---|
| Free tier | None (except Oracle, see above) |
| Ease of deployment | Medium. One-time server setup (about an hour, following [STAGING_DEPLOYMENT.md](STAGING_DEPLOYMENT.md)); after that a release is one command or one button. |
| Reliability | One server = one point of failure. A hardware fault means minutes to hours of downtime, and recovery from backups. Acceptable for a first launch; see [BACKUP_AND_RECOVERY.md](BACKUP_AND_RECOVERY.md). |
| Scalability | Resize the server (a few minutes of downtime). Beyond one server needs object storage first. |
| Persistent storage | Yes: the server's disk, plus optional extra volumes. |
| Docker, PostgreSQL, Redis, worker | Yes, all inside the Compose stack. |
| You are responsible for | Operating-system updates, the firewall, backups, watching disk space. |

## Option 2 (alternative): the same server, with a managed database

Keep the server for the proxy, web, API, worker, Redis and media, and move PostgreSQL to a database service that takes care of backups and point-in-time recovery.

| Database service | Free tier | Paid entry | Notes |
|---|---|---|---|
| Neon | 1 GB per project, sleeps after 5 idle minutes (cannot be turned off) | Pay per use: $0.106 per compute-hour + $0.35 per GB-month | The free tier's sleeping suits tests, not production. |
| Supabase | 500 MB, **pauses after 1 week without activity**, no backups | Pro: $25 per month, daily backups kept 7 days | |
| DigitalOcean / Akamai managed PostgreSQL | none | *not researched* | Same network as the server if you use the same provider. |

* **Benefit:** the database survives the loss of the server, and recovery to "five minutes ago" becomes possible (the bundled PostgreSQL only has the daily dump).
* **Cost:** roughly $15–30 per month more, and one more account to secure.
* **Code change:** none. `DATABASE_URL` points at the service and the `postgres` container is removed ([DATABASE_DEPLOYMENT.md](DATABASE_DEPLOYMENT.md#using-a-managed-postgresql-service)).
* **When to choose it:** when losing up to a day of data (the worst case with daily backups) is not acceptable.

## Option 3 (not possible today): a container platform

Platforms such as Render, Railway and Fly.io run containers for you, so there is no server to maintain. **Autowok cannot run on them yet**, because the API and the worker must share one media disk and these platforms attach a disk to a single service. Making this option possible requires adding S3-compatible object storage to Autowok: a code change in `backend/app/services/storage.py`, tests, and a media migration. That is a development task needing your approval, not a configuration step.

For reference, what it would cost once object storage exists:

| Piece | Render | Railway | Fly.io |
|---|---|---|---|
| Web app (Next.js) | $7 (512 MB) | usage: about $10 per GB RAM + $20 per vCPU | $6.70 (1 GB) |
| API | $7 – $25 | usage | $6.70 – $13.39 |
| Worker (always on) | from $7 | usage | $6.70 |
| PostgreSQL | from $6 (256 MB) | usage | managed from $38 |
| Redis | $10 (256 MB) | usage | – |
| Plan fee | $0 – $25 | $5 – $20 (includes the same amount of usage) | – |
| Object storage for media | external (below) | external | external |
| **Rough total** | **about $40–75** | **about $30–60** | **about $60+** |
| Free tier | Web sleeps after 15 minutes; free database is deleted after 30 days; no free worker | $1 of usage per month | none |
| Regions | USA, Frankfurt, Singapore | USA, Amsterdam, Singapore | 18 including Singapore, Frankfurt |

Vercel (for the Next.js part only): the free Hobby plan is **not allowed for commercial use** by Vercel's terms; Pro is $20 per developer per month. Autowok's web app and API are designed to share one address (which is what keeps the login cookie simple and safe), so splitting the web app onto Vercel would also need cross-site cookie and CORS changes. Not recommended.

## Supporting services (used with any option)

| Purpose | Service | Free allowance | Paid price |
|---|---|---|---|
| Off-server copy of backups | Backblaze B2 | first 10 GB | about $0.007 per GB-month |
| | Cloudflare R2 | 10 GB | $0.015 per GB-month, no download fees |
| Uptime checks ("is the site up?") | UptimeRobot | 50 checks, every 5 minutes, commercial use allowed | $10 per month for faster checks |
| | Better Stack | 10 checks, every 3 minutes (labelled for personal projects) | from $34 per month |
| Error tracking (optional) | Sentry | 1 user, 5,000 errors per month | $29 per month |
| HTTPS certificate | Let's Encrypt, obtained by the bundled proxy | free | – |
| Container image storage, CI | GitHub (GHCR, Actions) | free quota depends on the account and whether the repository is private (*not researched*) | – |
| Domain name | any registrar | none | typically $10–20 per year (*estimate, depends on the ending*) |
| AI | Groq | free tier with rate limits set by Groq | paid tiers exist (*not researched*); Autowok never switches to a paid AI provider by itself |
| Facebook / Instagram | Meta | free | App Review and business verification take time, not money |

Autowok's backups for a small installation are a few megabytes to a few gigabytes, so off-server backup storage is likely to stay inside the free allowance at first.

## Estimated monthly cost of the recommended setup

| Item | Low (Hetzner CX23, if orderable) | Typical (Hetzner CPX22 EU) | Asia region (DigitalOcean) |
|---|---|---|---|
| Production server | €5.99 | €16.99 – €19.99 | $24 |
| Provider's own server backups | €1.20 | €3.40 – €4.00 | $4.80 – $7.20 |
| Off-server backup storage | €0 (within free 10 GB) | €0 | $0 |
| Uptime monitoring | €0 | €0 | $0 |
| Domain (per month, averaged) | about €1 | about €1 | about $1 |
| **Production total** | **about €8** | **about €21 – €25** | **about $30 – $32** |
| Staging server while testing | same server price, billed by the hour; delete it when not testing | | |

Recurring costs you would be committing to: the server, its backups and the domain. Everything else starts free and has a paid step only if you outgrow it.

## Decision needed from you

1. **Provider and plan** for the production server (and whether to keep a staging server running or create it only for tests).
2. **Region**, based on where most of your users are.
3. **Whether to pay for a managed database** (Option 2) or accept daily backups.
4. **Where off-server backups go** (Backblaze B2 or Cloudflare R2).

No account is created and nothing is ordered until you decide.
