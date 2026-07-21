from __future__ import annotations

import pytest

from paleo_workbench.tokens import (
    BG_BODY,
    BG_HEADER,
    BORDER,
    PRIMARY,
    RADIUS_BUTTON,
    RADIUS_CARD,
    build_modern_qss,
)


def test_modern_light_theme_tokens():
    assert PRIMARY == "#2563eb"
    assert BG_BODY == "#f6f8fa"
    assert BG_HEADER == "#ffffff"
    assert BORDER == "#e2e8f0"
    assert RADIUS_BUTTON == 6
    assert RADIUS_CARD == 10


def test_build_modern_qss_generator():
    qss_comfortable = build_modern_qss(font_size=13, density="comfortable")
    assert isinstance(qss_comfortable, str)
    assert "padding: 6px 12px" in qss_comfortable
    assert "#2563eb" in qss_comfortable
    assert "QPushButton" in qss_comfortable

    qss_compact = build_modern_qss(font_size=11, density="compact")
    assert "padding: 3px 8px" in qss_compact
