"""Phase 10 automation engine.

Modules:

* ``registry`` – trigger registry: stable event identifiers and documented payload schemas.
* ``conditions`` – strict JSON condition validation and evaluation (no expression languages).
* ``actions`` – allowlisted action registry with configuration validation and permission rules.
* ``events`` – outbox-style event emission and publishing hooks.
* ``engine`` – worker-side dispatching (event → executions) and execution (steps, retries, limits).
* ``service`` – automation management (CRUD, validation, dry-run).
* ``reminders`` – periodic approval-reminder event producer.
* ``worker_tasks`` – registration with ``python -m app.worker``.
"""
