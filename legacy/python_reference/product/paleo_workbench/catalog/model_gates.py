"""Catalog-owned promote-to-production safety gates (no prediction imports).

The Stage-13 promotion policy lives here, in the catalog layer, so the
catalog service never imports prediction domain code (layering inversion —
audit #848: catalog/service.py used to lazy-import
``prediction.model_package.can_promote_to_production``, making headless
catalog use impossible without the prediction package).

:func:`prediction.model_package` re-exports these for API compatibility.
"""

from __future__ import annotations

from typing import Any

# Providers / model types that must never be promoted into scientific
# production. Literals mirror ``prediction.providers.PROVIDER_DEMO``
# (``"demo"``) and ``PROVIDER_LOCAL_ASSET`` (``"local_asset"``); the catalog
# must not import prediction, so the policy values are duplicated here with
# the mirror kept in sync by tests.
NON_PROMOTABLE_PROVIDERS: frozenset[str] = frozenset({"demo", "local_asset"})
NON_PROMOTABLE_MODEL_TYPES: frozenset[str] = frozenset({"demo", "heuristic"})


def can_promote_to_production(
    service: Any,
    model_id: str,
    model_version: str,
    *,
    require_input_schema: bool = True,
) -> tuple[bool, str]:
    """Return (ok, reason) for promote gates (shared with catalog.promote_model).

    ``require_input_schema`` is a PROMOTE-time requirement: a version promoted
    before the schema contract existed must not silently disappear from
    find_production_model on upgrade (Agent L P2) — reads keep the other
    gates but tolerate the legacy empty-schema case.
    """
    try:
        model = service.get_model(model_id)
        version = service.get_model_version(model_id, model_version)
    except Exception as exc:  # CatalogError
        return False, str(exc)
    if version.demo_only:
        return False, "demo_only model versions cannot be promoted to production"
    # Case/alias-insensitive checks: "Demo"/"DEMO"/"local-asset" must not
    # slip past exact-match allowlists (H4-3c).
    provider_norm = (model.provider or "").strip().casefold()
    if provider_norm in {p.strip().casefold() for p in NON_PROMOTABLE_PROVIDERS}:
        return False, f"provider {model.provider!r} is not promotable to production"
    type_norm = (model.model_type or "").strip().casefold()
    if type_norm in {t.strip().casefold() for t in NON_PROMOTABLE_MODEL_TYPES}:
        return False, f"model_type {model.model_type!r} is not promotable to production"
    if model.metadata.get("scientific") is False:
        return False, "model metadata marks scientific=False"
    if version.metadata.get("scientific") is False:
        return False, "version metadata marks scientific=False (H4-3b)"
    if require_input_schema and not version.input_schema:
        return False, "input_schema is required for production promotion (H5-b)"
    return True, "ok"