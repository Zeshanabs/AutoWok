"""HTTP latency benchmark for the main read paths and a few write paths.

Run against a NON-PRODUCTION server seeded with ``perf.seed``::

    python -m perf.bench --base-url http://127.0.0.1:8010 --workspace <id> \
        --email perf-owner@example.com --password ... --requests 200 --concurrency 8 \
        --label after --out perf-after.json

Reports average, median, p95, p99, min, max and the error rate per endpoint.
Nothing here is a load generator for capacity planning; it measures latency
at a small fixed concurrency so that runs are comparable.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

ORIGIN = "http://localhost:3000"
CSRF = {"Origin": ORIGIN, "X-CSRF-Protection": "1"}


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
    return ordered[index]


def _summary(name: str, timings: list[float], errors: int, total: int, size: int) -> dict:
    return {
        "endpoint": name,
        "requests": total,
        "errors": errors,
        "error_rate": round(errors / total, 4) if total else 0,
        "avg_ms": round(statistics.fmean(timings), 2) if timings else None,
        "median_ms": round(statistics.median(timings), 2) if timings else None,
        "p95_ms": round(_percentile(timings, 0.95), 2) if timings else None,
        "p99_ms": round(_percentile(timings, 0.99), 2) if timings else None,
        "min_ms": round(min(timings), 2) if timings else None,
        "max_ms": round(max(timings), 2) if timings else None,
        "response_bytes": size,
    }


def run(client: httpx.Client, name: str, method: str, path: str, *, requests: int, concurrency: int, max_seconds: float, body=None) -> dict:
    timings: list[float] = []
    errors = 0
    size = 0

    def one(_: int) -> tuple[float, bool, int]:
        started = time.perf_counter()
        try:
            response = client.request(method, path, json=body, headers=CSRF if method != "GET" else None)
            ok = response.status_code < 400
            length = len(response.content)
        except httpx.HTTPError:
            ok, length = False, 0
        return (time.perf_counter() - started) * 1000, ok, length

    one(0)  # warm-up, not recorded
    # Requests are sent in waves of `concurrency`; no new wave starts after the
    # time budget, so slow endpoints are measured with fewer samples.
    started_all = time.perf_counter()
    done = 0
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        while done < requests and time.perf_counter() - started_all < max_seconds:
            wave = min(concurrency, requests - done)
            for elapsed, ok, length in pool.map(one, range(wave)):
                if ok:
                    timings.append(elapsed)
                    size = length
                else:
                    errors += 1
            done += wave
    requests = done
    return _summary(name, timings, errors, requests, size)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--requests", type=int, default=200)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--max-seconds", type=float, default=30, help="time budget per endpoint")
    parser.add_argument("--label", default="run")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    ws = args.workspace
    limits = httpx.Limits(max_connections=args.concurrency * 2)
    with httpx.Client(base_url=args.base_url + "/api/v1", timeout=60, limits=limits) as client:
        results = []
        # Authentication: Argon2 verification dominates. Kept below the login rate limit.
        login_timings = []
        for _ in range(5):
            started = time.perf_counter()
            response = client.post("/auth/login", json={"email": args.email, "password": args.password}, headers=CSRF)
            response.raise_for_status()
            login_timings.append((time.perf_counter() - started) * 1000)
        results.append(_summary("POST /auth/login (sequential)", login_timings, 0, 5, 0))

        paths = [
            ("GET /health", "GET", "/health"),
            ("GET /auth/me", "GET", "/auth/me"),
            ("GET brands", "GET", f"/workspaces/{ws}/brands"),
            ("GET content projects", "GET", f"/content/projects?workspace_id={ws}"),
            ("GET media assets", "GET", f"/media-assets?workspace_id={ws}"),
            ("GET calendar (month)", "GET", f"/workspaces/{ws}/calendar?view=month"),
            ("GET calendar (week)", "GET", f"/workspaces/{ws}/calendar?view=week"),
            ("GET publishing queue", "GET", f"/workspaces/{ws}/publishing/queue"),
            ("GET publishing jobs", "GET", f"/workspaces/{ws}/publishing/jobs"),
            ("GET scheduled posts", "GET", f"/workspaces/{ws}/scheduled-posts"),
            ("GET analytics overview", "GET", f"/workspaces/{ws}/analytics/overview"),
            ("GET analytics timeseries", "GET", f"/workspaces/{ws}/analytics/timeseries?metric=reach"),
            ("GET analytics posts", "GET", f"/workspaces/{ws}/analytics/posts"),
            ("GET analytics content-performance", "GET", f"/workspaces/{ws}/analytics/content-performance"),
            ("GET analytics report", "GET", f"/workspaces/{ws}/analytics/reports"),
            ("GET automations", "GET", f"/workspaces/{ws}/automations"),
            ("GET notifications", "GET", f"/workspaces/{ws}/notifications"),
            ("GET agent workflows", "GET", f"/workspaces/{ws}/agent-workflows"),
            ("GET agent workflow stats", "GET", f"/workspaces/{ws}/agent-workflows/stats"),
        ]
        for name, method, path in paths:
            result = run(client, name, method, path, requests=args.requests, concurrency=args.concurrency, max_seconds=args.max_seconds)
            results.append(result)
            print(f"{name:38s} n={result['requests']:<4d} avg {result['avg_ms']} ms  p50 {result['median_ms']}  p95 {result['p95_ms']}  p99 {result['p99_ms']}  err {result['errors']}  {result['response_bytes']} B", flush=True)

    report = {
        "label": args.label,
        "requests_per_endpoint": args.requests,
        "concurrency": args.concurrency,
        "max_seconds_per_endpoint": args.max_seconds,
        "client": {"python": platform.python_version(), "machine": platform.machine(), "system": platform.platform()},
        "results": results,
    }
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2)
    print(json.dumps(results[0]), flush=True)


if __name__ == "__main__":
    main()
