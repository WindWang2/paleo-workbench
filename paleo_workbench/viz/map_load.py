from __future__ import annotations

from typing import Any

from paleo_workbench.viz.mapping_helpers import preview_payload_from_document


def load_map_payload_from_document(doc: Any) -> tuple[list, list, str]:
    """Reuse mapping_helpers.preview_payload_from_document."""
    return preview_payload_from_document(doc)
