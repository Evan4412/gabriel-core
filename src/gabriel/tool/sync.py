"""ToolCatalogSynchronizer — idempotent tool provisioning for an org.

Replaces the deprecated scripts/seed_tools.py auto-seeder.
Called explicitly from:
  - organization provisioning (new org onboarding)
  - admin API: POST /tools/sync
  - CLI: gabriel tools sync --org <org_id>

Never called automatically at app startup.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gabriel.logging_config import get_logger
from gabriel.resource.grn import GRN
from gabriel.tool.discovery import tool_indexer
from gabriel.tool.models import Tool
from gabriel.tool.repository import ToolRepository
from gabriel.tool.service import ToolService

logger = get_logger(__name__)


@dataclass
class SyncReport:
    org_id: str
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class ToolCatalogSynchronizer:
    """Idempotent sync of discovered tools into an org's Tool resource table.

    Governance-controlled fields (enabled, safety_level, configuration,
    labels, metadata) are NEVER overwritten on existing rows — only the
    implementation-derived fields (description, parameters, runtime_binding,
    execution_runtime, category) are updated.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def sync_org(self, org_id: str, actor_id: str = "system:sync") -> SyncReport:
        report = SyncReport(org_id=org_id)
        discovered = {t.name: t for t in tool_indexer.discover()}

        async with self._session_factory() as session:
            repo = ToolRepository(session)
            service = ToolService(repo)
            existing = {
                t.name: t
                for t in [
                    __import__("gabriel.tool.mappers", fromlist=["orm_to_domain"])
                    .orm_to_domain(orm)
                    for orm in await repo.list_for_org(org_id)
                ]
            }

        for name, disc in discovered.items():
            try:
                if name in existing:
                    ex = existing[name]
                    needs_update = (
                        ex.description != disc.description
                        or ex.parameters != disc.parameters
                        or ex.runtime_binding != disc.runtime_binding
                        or ex.category != disc.category
                        or ex.execution_runtime != disc.execution_runtime
                    )
                    if needs_update:
                        async with self._session_factory() as session:
                            svc = ToolService(ToolRepository(session))
                            await svc.update_tool(
                                str(ex.grn),
                                actor_id,
                                description=disc.description,
                                parameters=disc.parameters,
                                runtime_binding=disc.runtime_binding,
                                category=disc.category,
                                execution_runtime=disc.execution_runtime,
                                # Preserve: enabled, safety_level, configuration
                            )
                        report.updated.append(name)
                    else:
                        report.unchanged.append(name)
                else:
                    async with self._session_factory() as session:
                        svc = ToolService(ToolRepository(session))
                        await svc.create_tool(
                            org_id,
                            actor_id,
                            name=name,
                            description=disc.description,
                            category=disc.category,
                            parameters=disc.parameters,
                            safety_level=disc.safety_level,
                            runtime_binding=disc.runtime_binding,
                            execution_runtime=disc.execution_runtime,
                            enabled=True,
                            fn=disc.fn,
                        )
                    report.created.append(name)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Failed to sync tool '%s' for org '%s'", name, org_id)
                report.errors.append(f"{name}: {exc}")

        logger.info(
            "Tool sync for org '%s': created=%d updated=%d unchanged=%d errors=%d",
            org_id,
            len(report.created),
            len(report.updated),
            len(report.unchanged),
            len(report.errors),
        )
        return report