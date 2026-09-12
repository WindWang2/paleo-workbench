"""Role governance backfill (V11 docs 10-migration §3).

Deterministic, idempotent pass run at project open:

- For every (entity, role) whose registry policy is ``required_single`` and
  that has NO primary link but exactly ONE live member, promote that member.
- Roles with zero or multiple candidates are left for a human — the pass
  never silently chooses between real alternatives.
- Unknown roles (foreign vocabularies) are skipped entirely.
"""

from __future__ import annotations

from typing import Any

from paleo_workbench.project.roles import primary_required


def backfill_role_primaries(project: Any) -> dict[str, int]:
    """Promote unique-candidate primaries; returns a per-role promotion count."""
    promoted: dict[str, int] = {}
    links = list(getattr(project, "entity_asset_links", None) or [])
    # Group live well/survey links by (entity_type, entity_id, role).
    groups: dict[tuple[str, str, str], list] = {}
    for link in links:
        key = (link.entity_type, link.entity_id, link.role)
        groups.setdefault(key, []).append(link)
    for (entity_type, _entity_id, role), members in groups.items():
        if entity_type not in ("well", "seismic_survey", "geological_entity"):
            continue
        if not primary_required(role):
            continue
        if any(m.is_primary for m in members):
            continue  # already governed
        # Unresolved bindings are ambiguous identity claims — promoting one
        # to primary would silently canonize it (10-migration §2).
        candidates = [m for m in members if not m.unresolved]
        if len(candidates) != 1:
            continue  # zero or multiple → human decision
        candidates[0].is_primary = True
        promoted[role] = promoted.get(role, 0) + 1
    return promoted
