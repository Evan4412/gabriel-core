import os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gabriel.logging_config import configure_logging

# Allow environment override; default to SQLite for local dev (aligns with fallback).
# Production deployments should set GABRIEL_DATABASE_URL to a real Postgres DSN.
DATABASE_URL = os.getenv(
    "GABRIEL_DATABASE_URL",
    "sqlite+aiosqlite:///./.gabriel/gabriel.db",
)

configure_logging()

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
