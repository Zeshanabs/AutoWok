"""Count SQL statements and time per endpoint, in process.

Usage (from ``backend/``, against a seeded NON-PRODUCTION database)::

    python -m perf.query_count --workspace <id> --email ... --password ...

For every endpoint it prints the number of SQL statements, the time spent in
the database driver and the total handler time. A high statement count for a
list endpoint is the signature of an N+1 query pattern.
"""

from __future__ import annotations

import argparse
import time

from fastapi.testclient import TestClient
from sqlalchemy import event

from app.db.session import engine
from app.main import app

CSRF = {"Origin": "http://localhost:3000", "X-CSRF-Protection": "1"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    args = parser.parse_args()
    ws = args.workspace

    stats = {"count": 0, "seconds": 0.0}

    @event.listens_for(engine, "before_cursor_execute")
    def _before(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        context._started = time.perf_counter()

    @event.listens_for(engine, "after_cursor_execute")
    def _after(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        stats["count"] += 1
        stats["seconds"] += time.perf_counter() - context._started

    paths = [
        "/auth/me",
        f"/workspaces/{ws}/brands",
        f"/content/projects?workspace_id={ws}",
        f"/media-assets?workspace_id={ws}",
        f"/workspaces/{ws}/calendar?view=month",
        f"/workspaces/{ws}/calendar?view=week",
        f"/workspaces/{ws}/publishing/queue",
        f"/workspaces/{ws}/publishing/jobs",
        f"/workspaces/{ws}/scheduled-posts",
        f"/workspaces/{ws}/analytics/overview",
        f"/workspaces/{ws}/analytics/timeseries?metric=reach",
        f"/workspaces/{ws}/analytics/posts",
        f"/workspaces/{ws}/analytics/content-performance",
        f"/workspaces/{ws}/analytics/reports",
        f"/workspaces/{ws}/automations",
        f"/workspaces/{ws}/notifications",
        f"/workspaces/{ws}/agent-workflows",
    ]
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={"email": args.email, "password": args.password}, headers=CSRF)
        login.raise_for_status()
        print(f"{'endpoint':52s} {'status':>6s} {'queries':>8s} {'db ms':>8s} {'total ms':>9s}")
        for path in paths:
            client.get("/api/v1" + path)  # warm-up
            stats["count"], stats["seconds"] = 0, 0.0
            started = time.perf_counter()
            response = client.get("/api/v1" + path)
            total = (time.perf_counter() - started) * 1000
            label = path.replace(ws, "{ws}")
            print(f"{label:52s} {response.status_code:>6d} {stats['count']:>8d} {stats['seconds'] * 1000:>8.1f} {total:>9.1f}")


if __name__ == "__main__":
    main()
