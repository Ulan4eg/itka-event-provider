class ProviderError(Exception):
    """Base error of the Events Provider integration."""


class ProviderUnavailableError(ProviderError):
    """Network problem, rate limit or 5xx from the provider."""


class ProviderAuthError(ProviderError):
    """The provider rejected our API key."""


class ProviderNotFoundError(ProviderError):
    """The requested resource does not exist on the provider side."""


class ProviderBadRequestError(ProviderError):
    """The provider rejected the data (business error, 400)."""
