"""Phase 11: controlled multi-agent AI workflows.

``registry``      explicit agent registry (no user-supplied agents)
``tools``         allowlisted, workspace-scoped tools
``agents``        the eight specialized agents
``workflows``     the four predefined workflows
``orchestrator``  planning, execution, retries, cancellation, recovery
``service``       human review (accept / reject / revise) and statistics
"""

from app.services.agents import agents as _agents  # noqa: F401 - registers the agents
from app.services.agents import workflows as _workflows  # noqa: F401 - registers the workflows
