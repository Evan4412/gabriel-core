"""Tests for shared library-tool provisioning (opt-in governance bootstrap).

These lock down the Option-A fix for the reported field bug: an org that
never ran ``POST /tools/sync`` had *no* enabled ``Tool`` resources, so every
tool an agent declared was filtered out and the model saw none. Provisioning
now happens both on explicit sync and automatically at org registration,
while the org-level enablement gate itself is preserved.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gabriel.database.base import Base

# Import all ORM models needed for registration + tool provisioning.
import gabriel.organization.orm
import gabriel.organization.membership_orm
import gabriel.identity.orm
import gabriel.identity.refresh
import gabriel.events.orm
import gabriel.user.orm
import gabriel.tool.orm  # noqa: F401 (side-effect import: ORM registration)

from gabriel.identity.registration import RegistrationService
from gabriel.tool.provisioning import provision_library_tools
from gabriel.tool.repository import ToolRepository
from gabriel.tool.service import ToolService

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    yield factory
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


async def _enabled_tool_names(session_factory, org_id: str) -> set[str]:
    async with session_factory() as session:
        tools = await ToolService(ToolRepository(session)).list_tools(org_id)
    return {t.name for t in tools if t.org_id == org_id and t.enabled}


@pytest.mark.asyncio
async def test_provision_library_tools_creates_enabled_resources(session_factory):
    async with session_factory() as session:
        result = await provision_library_tools(session, "acme")

    # A representative set of library tools was provisioned and enabled.
    assert "calculate" in result["created"]
    assert "roll_dice" in result["created"]
    enabled = await _enabled_tool_names(session_factory, "acme")
    assert {"calculate", "roll_dice", "get_time"} <= enabled


@pytest.mark.asyncio
async def test_provision_library_tools_is_idempotent(session_factory):
    async with session_factory() as session:
        first = await provision_library_tools(session, "acme")
    async with session_factory() as session:
        second = await provision_library_tools(session, "acme")

    # Second run creates nothing new; everything is skipped (no duplicates).
    assert first["created"]
    assert second["created"] == []
    assert set(second["skipped"]) >= set(first["created"])


@pytest.mark.asyncio
async def test_registration_auto_provisions_tools_for_new_org(session_factory):
    async with session_factory() as session:
        result = await RegistrationService(session).register(
            email="evan@example.com",
            password="hunter2-strong-pass",
            display_name="Evan",
            organization_name="Evan Workspace",
        )
    org_id = result.organization.org_id

    # The reported bug: a brand-new org had zero enabled Tool resources, so
    # agents' declared tools never reached the model. Now they are provisioned.
    enabled = await _enabled_tool_names(session_factory, org_id)
    assert {"calculate", "roll_dice", "search_emails"} <= enabled
