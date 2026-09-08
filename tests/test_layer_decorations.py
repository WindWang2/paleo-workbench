"""V7 §7 图层呈现态（layer_decorations）单元测试（纯 Python）。"""
from __future__ import annotations

from paleo_workbench.ui.workstation.layer_decorations import (
    GroupPresentationSummary,
    LayerPresentationState,
    decoration_summary_text,
    decoration_token,
    primary_decoration,
)
from paleo_workbench.ui.workstation.state_language import state_token


def test_clean_layer_has_no_decoration() -> None:
    state = LayerPresentationState()
    assert primary_decoration(state) is None
    assert decoration_token(state) is None
    assert decoration_summary_text(state) == ""


def test_priority_missing_beats_everything() -> None:
    state = LayerPresentationState(
        missing=True, editing=True, dirty=True, stale=True, maturity="frozen",
    )
    kind, token = primary_decoration(state)
    assert kind == "missing"
    assert token.glyph == "✕"


def test_editing_dirty_beats_stale() -> None:
    state = LayerPresentationState(editing=True, dirty=True, stale=True)
    kind, token = primary_decoration(state)
    assert kind == "dirty"
    assert "未保存" in token.label


def test_editing_without_dirty() -> None:
    state = LayerPresentationState(editing=True, stale=True)
    kind, token = primary_decoration(state)
    assert kind == "editing"
    assert token.label == "编辑中"


def test_error_beats_stale_beats_maturity() -> None:
    assert primary_decoration(
        LayerPresentationState(missing_input=True, stale=True)
    )[0] == "missing_input"
    assert primary_decoration(
        LayerPresentationState(stale=True, superseded=False, maturity="draft")
    )[0] == "stale"
    assert primary_decoration(
        LayerPresentationState(superseded=True)
    )[0] == "superseded"
    assert primary_decoration(
        LayerPresentationState(maturity="frozen")
    )[0] == "frozen"
    assert primary_decoration(
        LayerPresentationState(maturity="published")
    )[0] == "published"
    assert primary_decoration(
        LayerPresentationState(maturity="reviewed")
    )[0] == "reviewed"


def test_decoration_token_maps_through_state_language() -> None:
    token = decoration_token(LayerPresentationState(stale=True))
    assert token is state_token("freshness", "stale")
    token = decoration_token(LayerPresentationState(editing=True, dirty=True))
    assert token is state_token("session", "dirty")
    token = decoration_token(LayerPresentationState(maturity="frozen"))
    assert token is state_token("maturity", "frozen")


def test_summary_text_lists_all_signals() -> None:
    state = LayerPresentationState(
        editing=True, dirty=True, stale=True, maturity="draft"
    )
    text = decoration_summary_text(state)
    assert "未保存" in text
    assert "已过期" in text
    # hover 摘要聚合全部信号（不只是 primary）。
    assert text.count("·") >= 1


def test_group_summary_from_counts() -> None:
    summary = GroupPresentationSummary(
        group_id="phase2.factors", title="单因素", layers=12, stale=3, errors=1,
        running=2, pending=1, frozen=1, published=2,
    )
    text = summary.summary_text()
    for fragment in ("12", "3", "1", "2", "已发布"):
        assert fragment in text, fragment
    assert summary.has_problems


def test_group_summary_clean_has_no_problems() -> None:
    summary = GroupPresentationSummary(
        group_id="g", title="干净组", layers=5, stale=0, errors=0
    )
    assert not summary.has_problems
    assert summary.summary_text() == "5 层 · 无异常"
