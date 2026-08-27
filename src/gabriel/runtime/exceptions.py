"""Runtime subsystem exceptions."""


class RuntimeError(Exception):
    """Base exception for Gabriel runtime."""


class CapabilityError(RuntimeError):
    """Raised when a capability is missing or invalid."""


class ExecutionError(RuntimeError):
    """Raised during execution failures."""


class SchedulerError(RuntimeError):
    """Raised when scheduler operations fail."""


class RuntimeNotFoundError(RuntimeError):
    """Raised when Runtime cannot be found"""


class DuplicateRuntimeError(RuntimeError):
    """Raised when runtime name is already registered."""


class InvalidExecutionStateError(ExecutionError):
    """Raised when execution state transition is invalid."""
