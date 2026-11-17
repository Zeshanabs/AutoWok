# Autowok backend

FastAPI API and background worker. Setup, tests and deployment are described in the repository [README](../README.md) and in [docs/](../docs/).

* `app/` application code; `app/worker.py` is the background worker (`python -m app.worker`).
* `alembic/` database migrations (`alembic upgrade head`).
* `tests/` test suite (`pytest`).
* `perf/` seed, benchmark and query-count tools ([performance report](../docs/performance-report.md)).
* `requirements.txt` runtime dependencies, `requirements-dev.txt` development tools, `constraints.txt` full lock.
