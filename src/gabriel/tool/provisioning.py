"""Shared provisioning of library-discovered tools as governed org resources.

Tool exposure is opt-in (ADR-019/ADR-024): a tool only reaches the model when
it is backed by an *enabled* :class:`~gabriel.tool.models.Tool` resource for the
org. An agent declaring a tool is not enough. This module centralizes the
"provision every discovered library tool as an enabled Tool resource for an
org" operation so it can be reused by both:

* ``POST /tools/sync`` — the explicit admin/operator sync, and
* organization registration — so a brand-new org can use its agents' tools
  immediately instead of silently getting none until sync is run.

The org-level enablement gate itself is preserved: this only provisions the
default library catalog; admins can still disable individual tools afterwards.
"""

from __future__ import annotations

from gabriel.events.repository import EventRepository
from gabriel.logging_config import get_logger
from gabriel.tool.discovery import ToolLibraryIndexer
from gabriel.tool.repository import ToolRepository
from gabriel.tool.service import ToolService

logger = get_logger(__name__)


async def provision_library_tools(
    session,
    org_id: str,
    *,
    created_by: str = "system",
    enabled: bool = True,
) -> dict[str, list[str]]:
    """Provision all library-discovered tools as governed Tool resources.

    Idempotent: tools already present for the org are skipped. Per-tool
    failures are captured (never raised) so a single bad tool cannot abort
    org registration or a bulk sync.

    Args:
        session: An ``AsyncSession`` bound to the caller's transaction/factory.
        org_id: Organization to provision tools for.
        created_by: Principal recorded as the creator (defaults to ``system``).
        enabled: Whether the provisioned Tool resources start enabled.

    Returns:
        ``{"created": [...], "skipped": [...]}`` — created vs. skipped names.
    """
    indexer = ToolLibraryIndexer()
    discovered = indexer.discover()

    svc = ToolService(ToolRepository(session), EventRepository(session))

    existing_names = {
        t.name for t in await svc.list_tools(org_id) if t.org_id == org_id
    }

    created: list[str] = []
    skipped: list[str] = []
    for tool in discovered:
        if tool.name in existing_names:
            skipped.append(tool.name)
            continue
        try:
            await svc.create_tool(
                org_id,
                created_by,
                name=tool.name,
                description=tool.description,
                category=tool.category,
                parameters=tool.parameters,
                safety_level=tool.safety_level,
                runtime_binding=tool.runtime_binding,
                execution_runtime=tool.execution_runtime,
                enabled=enabled,
            )
            created.append(tool.name)
        except Exception:
            logger.exception(
                "Failed to provision tool %r for org %s", tool.name, org_id
            )
            skipped.append(tool.name)

    return {"created": created, "skipped": skipped}
