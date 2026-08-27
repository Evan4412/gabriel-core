from abc import ABC, abstractmethod

from gabriel.memory.models import MemoryEntry, MemoryLayer


class MemoryAccessInterface(ABC):
    """Memory Access Interface (MAI) — ADR-014 contract.

    All memory backends implement this interface. The ScopedMemoryClient
    delegates to a MAI implementation after PEEL authorisation.

    Methods
    -------
    store    : Persist a new entry; returns its opaque ID.
    retrieve : Fetch entries from a layer (keyword/exact match).
    recall   : Alias for retrieve — preferred name in the task spec.
    search   : Semantic (vector) search ranked by relevance.
    forget   : Hard-delete a single entry by ID.
    """

    @abstractmethod
    async def store(self, entry: MemoryEntry) -> str:
        """Stores a memory entry and returns its ID."""
        ...

    @abstractmethod
    async def retrieve(
        self,
        layer: MemoryLayer,
        query: str | None = None,
        limit: int = 10,
    ) -> list[MemoryEntry]:
        """Retrieve entries from a specific layer.

        If *query* is provided, implementations should filter by it
        (keyword match for simple backends; ignored by pgvector search —
        use :meth:`search` for semantic retrieval instead).
        """
        ...

    async def recall(
        self,
        layer: MemoryLayer,
        query: str | None = None,
        limit: int = 10,
    ) -> list[MemoryEntry]:
        """Alias for :meth:`retrieve` (task spec naming)."""
        return await self.retrieve(layer=layer, query=query, limit=limit)

    @abstractmethod
    async def search(
        self,
        query: str,
        layer: MemoryLayer | None = None,
        limit: int = 10,
    ) -> list[MemoryEntry]:
        """Semantic search across memory entries ranked by relevance.

        Backends that do not support vector search should fall back to
        keyword matching via :meth:`retrieve`.

        Args:
            query : Natural-language query string.
            layer : Optional layer filter. None = search all layers.
            limit : Maximum entries to return.

        Returns:
            Entries ranked by descending relevance.
        """
        ...

    @abstractmethod
    async def forget(self, memory_id: str) -> None:
        """Hard-delete a memory entry by ID."""
        ...
