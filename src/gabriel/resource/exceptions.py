# TODO Add custom constructors only for exceptions where structured context is genuinely useful

class GabrielError(Exception):
    """Base exception for all Gabriel errors."""

class InvalidGRNError(GabrielError):
    """Raised when a GRN is malformed or cannot be parsed."""

class ResourceNotFoundError(GabrielError):
    """Raised when a resource cannot be located."""

class InvalidLifecycleTransitionError(GabrielError):
    """Raised when a lifecycle transition is not permitted."""

class ResourceTypeNotRegisteredError(GabrielError):
    """Raised when a resource type has not been registered."""

class DuplicateResourceError(GabrielError):
    """Raised when a resource with the same GRN already exists."""

class DuplicateResourceTypeError(GabrielError):
    """Raised when a resource type is registered more than once."""

class ResourceFactoryError(GabrielError):
    """Raised when resource creation fails."""

class ResourceValidationError(GabrielError):
    """Raised when resource validation fails."""

class ResourceSerializationError(GabrielError):
    """Raised when resource serialization/deserialization fails."""
