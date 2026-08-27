"""Gabriel runtime: Execution context and lifecycle management.

The runtime subsystem implements the execution pipeline:

    command → dispatcher → event → ExecutionContext → Execution →

ExecutionContext is the immutable "process block" that determines what
a principal can do. Execution tracks the mutable state of a running context.
"""

from gabriel.runtime.capabilities import Capability
from gabriel.runtime.context import ExecutionContext
from gabriel.runtime.exceptions import (
    CapabilityError,
    ExecutionError,
    InvalidExecutionStateError,
    RuntimeError,
    SchedulerError,
)
from gabriel.runtime.execution import (
    Execution,
    ExecutionContextBuilder,
    ExecutionState,
)
from gabriel.runtime.scope import ScopedClient

__all__ = [
    # Context
    "ExecutionContext",
    # Capabilities
    "Capability",
    # Execution lifecycle
    "ExecutionState",
    "ExecutionContextBuilder",
    "Execution",
    # Scheduling
    # Scoped access
    "ScopedClient",
    # Exceptions
    "RuntimeError",
    "CapabilityError",
    "ExecutionError",
    "SchedulerError",
    "InvalidExecutionStateError",
]
