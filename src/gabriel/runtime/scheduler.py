"""Execution scheduler: Manages execution lifecycle."""

from abc import ABC, abstractmethod
from uuid import UUID

from gabriel.runtime.execution import Execution


class Scheduler(ABC):
    """Abstract scheduler for managing executions.

    A scheduler implements the execution pipeline:
    - command → handler → event → execution → schedule(execution)

    Different schedulers can implement different execution models:
    - Immediate/synchronous execution
    - Async/background execution
    - Distributed/remote execution
    - Rate-limited execution
    """

    @abstractmethod
    async def schedule(self, execution: Execution) -> Execution:
        """Schedule an execution to run.

        Args:
            execution: The execution to schedule (in PENDING state).

        Returns:
            Execution: The scheduled execution (may be RUNNING or PENDING).

        Raises:
            SchedulerError: If scheduling fails.
        """
        ...

    @abstractmethod
    async def cancel(self, execution_id: UUID) -> None:
        """Cancel a running execution.

        Args:
            execution_id: The execution to cancel.

        Raises:
            SchedulerError: If cancellation fails or execution not found.
        """
        ...

    @abstractmethod
    async def get_execution(self, execution_id: UUID) -> Execution | None:
        """Get an execution by ID.

        Args:
            execution_id: The execution ID to retrieve.

        Returns:
            Execution | None: The execution or None if not found.
        """
        ...
