"""Provider registry: validation, duplicate detection, isolation (P2-B).

Registration model (ADR 0055 track P.REG):

- **Explicit registration** is the default and the only automatic path:
  built-ins register themselves via :func:`ensure_builtin_providers`.
- **Entry-point discovery** is opt-in per launch with
  ``PALEO_PROVIDER_ENTRY_POINTS=1`` (P.DISC staged adoption): distributions
  may declare ``[project.entry-points.paleo_workbench.providers]`` factories
  returning provider instances or classes. No directory scanning, ever.
- **Failure isolation**: one bad provider (raises on construction, invalid
  descriptor, duplicate id) is quarantined with a reason; the registry — and
  therefore the app — keeps booting. Quarantine is inspectable, never silent.
"""
from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable, Iterable

from paleo_workbench.providers.base import CapabilityProvider
from paleo_workbench.providers.contracts import (
    ProviderDescriptor,
    ProviderFamily,
    validate_descriptor,
)
from paleo_workbench.providers.errors import (
    DuplicateProviderError,
    InvalidProviderError,
    UnknownProviderError,
)

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "paleo_workbench.providers"
ENTRY_POINT_ENV = "PALEO_PROVIDER_ENTRY_POINTS"


class ProviderRegistry:
    """Thread-safe registry of capability providers by id."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._providers: dict[str, CapabilityProvider] = {}
        self._quarantine: dict[str, str] = {}

    # -------------------------------------------------------- registration --
    def register(self, provider: CapabilityProvider, *, replace: bool = False) -> ProviderDescriptor:
        """Validate + install one provider instance.

        Raises :class:`InvalidProviderError` / :class:`DuplicateProviderError`;
        never partially installs.
        """
        descriptor = self._descriptor_of(provider)
        problems = validate_descriptor(descriptor)
        if problems:
            self._quarantine[descriptor.provider_id] = "invalid descriptor: " + "; ".join(problems)
            raise InvalidProviderError(descriptor.provider_id, problems)
        with self._lock:
            existing = self._providers.get(descriptor.provider_id)
            if existing is not None:
                if not replace:
                    existing_version = self._descriptor_of(existing).version
                    if existing_version != descriptor.version:
                        self._quarantine[descriptor.provider_id] = (
                            f"version conflict {descriptor.version} vs registered {existing_version}"
                        )
                    raise DuplicateProviderError(descriptor.provider_id, existing_version)
            self._providers[descriptor.provider_id] = provider
            self._quarantine.pop(descriptor.provider_id, None)
        return descriptor

    def unregister(self, provider_id: str) -> bool:
        with self._lock:
            return self._providers.pop(provider_id, None) is not None

    # ------------------------------------------------------------ lookups --
    def get(self, provider_id: str) -> CapabilityProvider:
        provider = self.find(provider_id)
        if provider is None:
            raise UnknownProviderError(provider_id)
        return provider

    def find(self, provider_id: str) -> CapabilityProvider | None:
        with self._lock:
            return self._providers.get(provider_id)

    def by_family(self, family: ProviderFamily) -> list[CapabilityProvider]:
        with self._lock:
            return [
                p
                for p in self._providers.values()
                if self._descriptor_of(p).family is family
            ]

    def descriptors(self, family: ProviderFamily | None = None) -> list[ProviderDescriptor]:
        with self._lock:
            descriptors = [self._descriptor_of(p) for p in self._providers.values()]
        if family is not None:
            descriptors = [d for d in descriptors if d.family is family]
        return sorted(descriptors, key=lambda d: (d.family.value, d.provider_id))

    def __len__(self) -> int:
        with self._lock:
            return len(self._providers)

    # ---------------------------------------------------------- quarantine --
    def quarantined(self) -> dict[str, str]:
        with self._lock:
            return dict(self._quarantine)

    # ------------------------------------------------------------ loading --
    def load_entry_points(self) -> dict[str, str]:
        """Opt-in P.DISC discovery (env ``PALEO_PROVIDER_ENTRY_POINTS=1``).

        Returns a per-provider status map; failures quarantine the provider
        and are reported, never raised — boot must survive bad plugins.
        """
        statuses: dict[str, str] = {}
        if os.environ.get(ENTRY_POINT_ENV, "").strip() not in ("1", "true", "yes", "on"):
            return {"_disabled": f"set {ENTRY_POINT_ENV}=1 to enable entry-point discovery"}
        try:
            from importlib.metadata import entry_points
        except Exception as exc:  # pragma: no cover - exotic environments
            return {"_error": f"importlib.metadata unavailable: {exc}"}
        try:
            eps = entry_points(group=ENTRY_POINT_GROUP)
        except TypeError:  # pragma: no cover - py<3.10 signature
            eps = entry_points().get(ENTRY_POINT_GROUP, [])  # type: ignore[attr-defined]
        for ep in eps:
            name = getattr(ep, "name", str(ep))
            try:
                factory = ep.load()
                provider = factory() if isinstance(factory, type) else factory
                self.register(provider)
                statuses[name] = "registered"
            except Exception as exc:
                reason = f"{type(exc).__name__}: {exc}"
                self._quarantine[name] = reason
                statuses[name] = f"quarantined ({reason})"
                logger.warning("provider entry point %s quarantined: %s", name, reason)
        return statuses

    # ------------------------------------------------------------- helpers --
    @staticmethod
    def _descriptor_of(provider: CapabilityProvider) -> ProviderDescriptor:
        descriptor = getattr(provider, "descriptor", None)
        if descriptor is None:
            raise InvalidProviderError(repr(provider), ["provider has no descriptor attribute"])
        return descriptor


# --------------------------------------------------------------- singleton

_GLOBAL_REGISTRY: ProviderRegistry | None = None
_REGISTRY_LOCK = threading.Lock()


def get_provider_registry() -> ProviderRegistry:
    global _GLOBAL_REGISTRY
    with _REGISTRY_LOCK:
        if _GLOBAL_REGISTRY is None:
            registry = ProviderRegistry()
            ensure_builtin_providers(registry)
            _GLOBAL_REGISTRY = registry
        return _GLOBAL_REGISTRY


def set_provider_registry(registry: ProviderRegistry | None) -> None:
    """Test/teardown helper; ``None`` resets to the lazy default."""
    global _GLOBAL_REGISTRY
    with _REGISTRY_LOCK:
        _GLOBAL_REGISTRY = registry


def ensure_builtin_providers(registry: ProviderRegistry) -> list[str]:
    """Register the built-in production providers (idempotent).

    Built-ins are the workbench's own deep seams exposed as providers —
    interpolation engines, the seismic attribute kernel table, the tiled
    ONNX inference bridge, the map render backends and the map product
    exporter. Each registration is individually guarded so one unavailable
    engine (e.g. onnxruntime missing) never blocks the others.
    """
    registered: list[str] = []
    from paleo_workbench.providers.builtin import BUILTIN_PROVIDER_FACTORIES

    for factory in BUILTIN_PROVIDER_FACTORIES:
        try:
            made = factory()
        except Exception as exc:
            logger.warning(
                "builtin provider factory %s unavailable: %s",
                getattr(factory, "__name__", factory),
                exc,
            )
            continue
        providers = made if isinstance(made, list) else [made]
        for provider in providers:
            try:
                descriptor = registry.register(provider, replace=True)
                registered.append(descriptor.provider_id)
            except Exception as exc:
                logger.warning("builtin provider %s rejected: %s", provider, exc)
    return registered
