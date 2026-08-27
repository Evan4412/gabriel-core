"""Events subsystem exceptions."""


class EventsError(Exception):
    """Base exception for Gabriel events subsystem."""


class HandlerNotFoundError(EventsError):
    """Raised when no handler is registered for a command type."""


class CommandValidationError(EventsError):
    """Raised when a command fails validation."""


class HandlerExecutionError(EventsError):
    """Raised when a handler fails during execution."""


class InvalidEventError(EventsError):
    """Raised when an event is malformed or invalid."""
