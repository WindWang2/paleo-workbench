"""Provider SDK error hierarchy (P2-B).

All errors are part of the stable SDK surface: plugin authors catch them,
the harness maps them to explainable ActionResults, and the registry uses
them to quarantine bad providers instead of refusing to boot.
"""
from __future__ import annotations


class ProviderError(Exception):
    """Base class for every SDK-raised error."""


class InvalidProviderError(ProviderError):
    """A provider (or its descriptor) failed structural validation.

    Carries the list of human-readable validation problems.
    """

    def __init__(self, provider_id: str, problems: list[str]):
        self.provider_id = provider_id
        self.problems = list(problems)
        super().__init__(
            f"provider {provider_id!r} failed validation: {'; '.join(self.problems)}"
        )


class DuplicateProviderError(ProviderError):
    """A provider with the same id (or an id-version clash) is registered."""

    def __init__(self, provider_id: str, existing_version: str):
        self.provider_id = provider_id
        self.existing_version = existing_version
        super().__init__(
            f"provider {provider_id!r} already registered (version {existing_version})"
        )


class UnknownProviderError(ProviderError):
    """No provider registered under the requested id."""

    def __init__(self, provider_id: str, family: str | None = None):
        self.provider_id = provider_id
        self.family = family
        scope = f" in family {family!r}" if family else ""
        super().__init__(f"no provider {provider_id!r}{scope}")


class ProviderRejectedInputError(ProviderError):
    """The provider does not accept the given typed inputs (before execution).

    Raised for unsupported input kinds or unresolvable references — distinct
    from execution failures, which the provider raises itself.
    """

    def __init__(self, provider_id: str, reason: str):
        self.provider_id = provider_id
        self.reason = reason
        super().__init__(f"provider {provider_id!r} rejected inputs: {reason}")


class InvalidParametersError(ProviderError):
    """Parameters do not conform to the provider's declared JSON schema."""

    def __init__(self, provider_id: str, problems: list[str]):
        self.provider_id = provider_id
        self.problems = list(problems)
        super().__init__(
            f"parameters for {provider_id!r} failed schema validation: "
            + "; ".join(self.problems)
        )


class ProviderExecutionError(ProviderError):
    """The provider raised during execution; wrapped for isolation."""

    def __init__(self, provider_id: str, cause: BaseException):
        self.provider_id = provider_id
        self.cause = cause
        super().__init__(f"provider {provider_id!r} failed: {type(cause).__name__}: {cause}")
