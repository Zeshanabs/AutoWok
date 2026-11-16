# syntax=docker/dockerfile:1
# Autowok API and worker image.
#   target "runtime" (default) - production: no build tools, no tests, non-root.
#   target "dev"               - local development with docker-compose.yml (source is bind-mounted).

FROM python:3.15-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY requirements.txt constraints.txt ./
RUN python -m venv /opt/venv && /opt/venv/bin/pip install -r requirements.txt -c constraints.txt

FROM python:3.15-slim AS dev
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.txt requirements-dev.txt constraints.txt ./
RUN pip install -r requirements-dev.txt -c constraints.txt
COPY . ./
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"]

FROM python:3.15-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH \
    LOCAL_STORAGE_PATH=/app/storage/local
# Fixed, unprivileged uid/gid so volume ownership is predictable.
RUN groupadd --system --gid 10001 autowok \
 && useradd --system --uid 10001 --gid autowok --home-dir /app --no-create-home --shell /usr/sbin/nologin autowok
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY scripts ./scripts
RUN mkdir -p /app/storage/local && chown -R autowok:autowok /app/storage
USER autowok
EXPOSE 8000
# Liveness only: a short database outage must not restart the API (readiness is /api/v1/ready).
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/live', timeout=4).status == 200 else 1)"]
STOPSIGNAL SIGTERM
# One process per container; scale by adding containers. The proxy address that
# may set X-Forwarded-For is FORWARDED_ALLOW_IPS (see docs/deployment.md).
# Migrations are NOT run here: run the "migrate" service once per release.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips \"${FORWARDED_ALLOW_IPS:-127.0.0.1}\" --timeout-graceful-shutdown 30 --no-server-header"]
