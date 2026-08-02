"""Host session store for imported wells (#218).

Holds loaded documents until full Python WellLogSession bindings exist.
Curves are readable via ``get_document`` / ``sample_value`` (engine-like access).
"""

from __future__ import annotations

from well_log_workstation.las_import import ImportedWellDocument


class HostSessionStore:
    """In-memory well documents keyed by catalog / document id."""

    def __init__(self) -> None:
        self._docs: dict[str, ImportedWellDocument] = {}

    def put(self, document: ImportedWellDocument) -> None:
        self._docs[document.document_id] = document

    def get(self, document_id: str) -> ImportedWellDocument | None:
        return self._docs.get(document_id)

    def remove(self, document_id: str) -> None:
        self._docs.pop(document_id, None)

    def clear(self) -> None:
        self._docs.clear()

    def document_ids(self) -> list[str]:
        return list(self._docs.keys())

    def sample_value(
        self, document_id: str, mnemonic: str, index: int
    ) -> float | None:
        doc = self.get(document_id)
        if doc is None:
            return None
        return doc.sample_value(mnemonic, index)
