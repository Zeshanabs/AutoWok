"""Per-user rate limits for expensive endpoints, as route dependencies.

Usage::

    @router.post("/things", dependencies=[Depends(limits.publish)])

Limits are configured with the ``RATE_LIMIT_*`` settings and counted per user,
whatever address the request comes from. A rejected request receives HTTP 429
with a ``Retry-After`` header and a message naming the feature.
"""

from __future__ import annotations

from typing import Callable

from fastapi import Depends

from app.api.v1.dependencies.auth import get_current_user
from app.core.config import get_settings
from app.models import User
from app.services.rate_limit import enforce_user_rate_limit


def _per_hour(action: str, setting: str, category: str) -> Callable[..., None]:
    def dependency(current_user: User = Depends(get_current_user)) -> None:
        enforce_user_rate_limit(
            current_user.id,
            action=action,
            limit=getattr(get_settings(), setting),
            window_seconds=3600,
            category=category,
        )

    return dependency


publish = _per_hour("publish", "rate_limit_publish_per_hour", "Publishing")
schedule = _per_hour("schedule", "rate_limit_schedule_per_hour", "Scheduling")
export = _per_hour("export", "rate_limit_export_per_hour", "Report export")
provider_test = _per_hour("provider-test", "rate_limit_provider_test_per_hour", "Provider test")
automation_test = _per_hour("automation-test", "rate_limit_automation_test_per_hour", "Automation test")
ai_tools = _per_hour("ai-tools", "rate_limit_ai_tools_per_hour", "AI content tools")
