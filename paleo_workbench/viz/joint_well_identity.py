"""Stable source-well identity reconciliation for the joint workbench."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
import json


class WellIdentityAmbiguityError(ValueError):
    """Raised when changed source records cannot be matched without guessing."""


@dataclass(frozen=True)
class SourceWellRecord:
    """Identity-relevant snapshot of one imported source record."""

    name: str
    geometry: tuple[float, float, float, float, float, float]


@dataclass(frozen=True)
class WellIdentityRegistry:
    """Own matching, migration, validation, and persistence of source-well IDs."""

    asset_id: str
    entries: dict[str, str]

    @classmethod
    def restore(
        cls,
        *,
        asset_id: str,
        persisted_asset_id: str | None,
        entries: dict[str, str] | None,
    ) -> WellIdentityRegistry:
        restored = dict(entries or {}) if persisted_asset_id == asset_id else {}
        return cls(asset_id=asset_id, entries=restored)

    def reconcile(
        self, records: list[SourceWellRecord]
    ) -> tuple[list[str], WellIdentityRegistry]:
        keys = self._record_keys(records)
        active = {
            key: self.entries[key] for key in keys if key in self.entries
        }
        self._migrate_unique(keys, active, field="geometry")
        self._migrate_unique(keys, active, field="name")
        self._raise_on_ambiguous_overlap(keys, active)

        for key in keys:
            if key not in active:
                digest = sha256(
                    f"{self.asset_id}\0{key}".encode("utf-8")
                ).hexdigest()[:24]
                active[key] = f"well-head:{digest}"

        updated = WellIdentityRegistry(
            asset_id=self.asset_id,
            entries={key: active[key] for key in keys},
        )
        return [updated.entries[key] for key in keys], updated

    def _record_keys(self, records: list[SourceWellRecord]) -> list[str]:
        bases = [self._record_key(record) for record in records]
        counts = Counter(bases)
        occurrences: Counter[str] = Counter()
        keys: list[str] = []
        for base in bases:
            occurrences[base] += 1
            duplicate = occurrences[base] if counts[base] > 1 else None
            payload = json.loads(base)
            payload["duplicate"] = duplicate
            keys.append(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
        return keys

    def _record_key(self, record: SourceWellRecord) -> str:
        geometry = "|".join(f"{value:.17g}" for value in record.geometry)
        payload = {
            "asset_id": self.asset_id,
            "geometry": sha256(geometry.encode("utf-8")).hexdigest()[:20],
            "name": record.name,
        }
        return json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    def _migrate_unique(
        self,
        current_keys: list[str],
        active: dict[str, str],
        *,
        field: str,
    ) -> None:
        current = self._unmatched_by_field(current_keys, active, field=field)
        previous = self._unmatched_by_field(
            list(self.entries),
            active,
            field=field,
            previous=True,
        )
        for lineage, candidates in current.items():
            old_candidates = previous.get(lineage, [])
            if len(candidates) == 1 and len(old_candidates) == 1:
                active[candidates[0]] = self.entries[old_candidates[0]]

    def _raise_on_ambiguous_overlap(
        self, current_keys: list[str], active: dict[str, str]
    ) -> None:
        for field in ("geometry", "name"):
            current = self._unmatched_by_field(
                current_keys, active, field=field
            )
            previous = self._unmatched_by_field(
                list(self.entries),
                active,
                field=field,
                previous=True,
            )
            overlap = set(current) & set(previous)
            if overlap:
                values = ", ".join(repr(value[1]) for value in overlap)
                raise WellIdentityAmbiguityError(
                    "Cannot safely reconcile changed duplicate wells by "
                    f"{field} ({values}); provide immutable source record IDs."
                )

    def _unmatched_by_field(
        self,
        keys: list[str],
        active: dict[str, str],
        *,
        field: str,
        previous: bool = False,
    ) -> dict[tuple[str, str], list[str]]:
        grouped: dict[tuple[str, str], list[str]] = {}
        for key in keys:
            if key in active:
                continue
            if previous and self.entries[key] in active.values():
                continue
            payload = json.loads(key)
            lineage = (str(payload["asset_id"]), str(payload[field]))
            grouped.setdefault(lineage, []).append(key)
        return grouped
