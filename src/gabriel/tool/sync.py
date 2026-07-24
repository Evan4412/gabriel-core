"""ToolCatalogSynchronizer — idempotent tool provisioning for an org.

Replaces the deprecated scripts/seed_tools.py auto-seeder (ADR-016).

Called explicitly from:
  - POST /tools/sync  (admin API endpoint)
  - gabriel tools sync --org <org_id>  (CLI, future)
  - Organisation provisioning flow (new org onboarding)

Never called automatically at app startup — fail-closed is preserved.

Governance-controlled fields (enabled, safety_level, configuration,
labels, metadata) are NEVER overwritten on existing rows.
Only implementation-derived fields are updated:
  description, parameters, runtime_binding, execution_runtime, category.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gabriel.logging_config import get_logger
from gabriel.tool.discovery import tool_indexer
from gabriel.tool.mappers import orm_to_domain
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

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0


class ToolCatalogSynchronizer:
    """Idempotent sync of the discovered tool library into an org's Tool table."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def sync_org(
        self,
        org_id: str,
        actor_id: str = "system:sync",
    ) -> SyncReport:
        report = SyncReport(org_id=org_id)

        # Snapshot the discovered catalog once.
        discovered = {t.name: t for t in tool_indexer.discover()}

        # Snapshot existing persisted tools for this org.
        async with self._session_factory() as session:
            repo = ToolRepository(session)
            existing = {
                orm.name: orm_to_domain(orm)
                for orm in await repo.list_for_org(org_id)
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
                                # Intentionally NOT passing: enabled, safety_level,
                                # configuration — those are org-admin-controlled.
                            )
                        report.updated.append(name)
                        logger.info("sync_org[%s]: updated tool '%s'", org_id, name)
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
                    logger.info("sync_org[%s]: created tool '%s'", org_id, name)

            except Exception as exc:  # noqa: BLE001
                msg = f"{name}: {exc}"
                report.errors.append(msg)
                logger.exception(
                    "sync_org[%s]: failed to sync tool '%s'", org_id, name
                )

        logger.info(
            "Tool sync complete — org=%s created=%d updated=%d unchanged=%d errors=%d",
            org_id,
            len(report.created),
            len(report.updated),
            len(report.unchanged),
            len(report.errors),
        )
        return report