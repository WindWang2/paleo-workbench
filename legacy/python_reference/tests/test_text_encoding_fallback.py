"""Regression tests for GBK/GB18030 fallback in well-data parsers (ISSUE-010).

Chinese formation tops, SMI well heads, and LAS well-name headers routinely
arrive GBK-encoded; the parsers used to read them as UTF-8 with
``errors="replace"``, silently corrupting every Chinese character. These
tests drive the real parsers with GB18030-encoded bytes and assert the
Chinese text survives.
"""

from __future__ import annotations

from pathlib import Path

from paleo_workbench.resources.text_codec import (
    decode_text_with_fallback,
    read_text_with_fallback,
)


def _gbk_bytes(text: str) -> bytes:
    return text.encode("gb18030")


def test_decode_fallback_chain_gbk_survives(tmp_path: Path):
    text = "井名: 张家1井\n层位: 寒武系"
    p = tmp_path / "tops.txt"
    p.write_bytes(_gbk_bytes(text))
    assert read_text_with_fallback(p) == text
    assert decode_text_with_fallback(_gbk_bytes(text)) == text


def test_decode_fallback_chain_prefers_utf8(tmp_path: Path):
    p = tmp_path / "u.txt"
    p.write_bytes("层位\nOrdovician\n".encode("utf-8"))
    assert read_text_with_fallback(p) == "层位\nOrdovician\n"


def test_well_tops_parser_decodes_gbk_names(tmp_path: Path):
    from paleo_workbench.resources import well_tops_parser

    content = "# 层位顶界\n张家1井 长兴组 3200.5\n李家2井 茅口组 3450.0\n"
    p = tmp_path / "tops.dat"
    p.write_bytes(_gbk_bytes(content))
    tops = well_tops_parser.parse_well_tops(p)
    assert [(t.well_name, t.top_name) for t in tops] == [
        ("张家1井", "长兴组"),
        ("李家2井", "茅口组"),
    ]
    assert tops[0].md == 3200.5


def test_well_heads_parser_decodes_gbk(tmp_path: Path):
    from paleo_workbench.viz import joint_well_parsers as jwp
    from paleo_workbench.viz.joint_well_identity import WellIdentityRegistry

    content = (
        "# 井头\n"
        "张家1井 1000.0 2000.0 30.0 3500.0 1001.0 2001.0\n"
        "李家2井 1500.0 2500.0 40.0 3800.0 1501.0 2501.0\n"
    )
    p = tmp_path / "heads.smi"
    p.write_bytes(_gbk_bytes(content))
    registry = WellIdentityRegistry.restore(
        asset_id="asset", persisted_asset_id=None, entries=None
    )
    parsed = jwp.parse_well_heads(p, identity_registry=registry)
    names = [w.name for w in parsed.wells]
    assert "张家1井" in names and "李家2井" in names, names
