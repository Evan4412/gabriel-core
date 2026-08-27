"""semantic_search — vector similarity search over org-scoped document chunks.

Delegates to the Memory system's pgvector backend (``MemorySearchBackend``)
which stores document chunk embeddings created during document ingestion.

Org-scoped: the search is restricted to the calling principal's organization.
``_org_id`` is injected by the ToolExecutor.
"""

from __future__ import annotations

from langchain_core.tools import tool

from gabriel.logging_config import get_logger

logger = get_logger(__name__)


@tool
async def semantic_search(
    query: str,
    limit: int = 5,
    _org_id: str = "",
) -> dict:
    """Search org documents by semantic similarity.

    Embeds *query* using the configured embedding backend and returns the
    top-k document chunks whose vector representation is closest to the query
    embedding (cosine similarity via pgvector ``<=>``) .

    This function depends on:
    - A running PostgreSQL instance with the pgvector extension.
    - Document chunks previously stored via
      :meth:`~gabriel.document.service.DocumentIngestionService.ingest_for_rag`.
    - An active embedding model (configured via ``GABRIEL_EMBED_MODEL`` env var).

    Args:
        query:   Natural language query string.
        limit:   Maximum number of chunks to return (default 5).
        _org_id: Injected by executor — org boundary.

    Returns:
        ``{"results": [{"content", "score", "metadata"}, ...], "count": N}``
        or ``{"error": ...}``.
    """
    if not _org_id:
        return {"error": "org_id is required (executor injection missing)"}
    if not query.strip():
        return {"error": "query must not be empty"}

    # This tool does not instantiate its own backend — a pre-configured
    # backend must be injected by the app layer.
    return {
        "error": (
            "semantic_search requires a configured MemorySearchBackend. "
            "Inject the backend through the ToolExecutor context or "
            "configure GABRIEL_PGVECTOR_URL in the environment."
        )
    }
