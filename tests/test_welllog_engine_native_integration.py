"""Focused Workbench ↔ built WellLogEngine retained-session coverage."""

from __future__ import annotations

import numpy as np
import pytest

from geoviz import CurveData, FaciesInterval, LithologyInterval, WellLogData

from paleo_workbench.viz import welllog_engine_adapter as adapter


def _well() -> WellLogData:
    depth = [1000.0, 1001.0, 1002.0, 1003.0]
    return WellLogData(
        well_name="native-session",
        top_depth=1000.0,
        bottom_depth=1003.0,
        curves=[
            CurveData(
                name="GR", unit="API", depth=list(depth),
                values=[20.0, 30.0, 40.0, 50.0], display_range=(0.0, 150.0),
            ),
            CurveData(
                name="RT", unit="ohm.m", depth=list(depth),
                values=[2.0, 3.0, 4.0, 5.0], display_range=(0.2, 2000.0),
            ),
        ],
        lithology=[LithologyInterval(top=1000.0, bottom=1002.0, lithology="砂")],
        facies=[FaciesInterval(top=1002.0, bottom=1003.0, facies="三角洲")],
    )


def test_workbench_plan_uses_native_multitrack_append_and_patch(qtbot):
    _, view_class, _ = adapter.try_import_welllog()
    if view_class is None:
        pytest.skip("built WellLogEngine binding is not on PYTHONPATH")
    view = view_class()
    qtbot.addWidget(view)

    first = adapter.adapt_well_log_data(_well())
    loaded = adapter.submit_plan_to_view(view, first)
    assert loaded["curve_count"] == 2
    assert loaded["lithology_count"] == 1
    assert loaded["facies_count"] == 1
    assert loaded["track_count"] == 4

    changed = _well()
    for curve in changed.curves:
        curve.depth.extend([1004.0, 1005.0])
        curve.values.extend([curve.values[-1] + 1.0, curve.values[-1] + 2.0])
    changed.lithology[0].bottom = 1002.5
    second = adapter.adapt_well_log_data(changed)
    update = adapter.update_plan_to_view(view, second, first)
    assert update["update_kind"] == "append"

    unchanged = adapter.update_plan_to_view(view, second, second)
    assert unchanged["update_kind"] == "unchanged"

    metrics = view.document_metrics(second.document_id)
    assert metrics["curve_lengths"] == [6, 6]
    assert metrics["revision"] >= 3  # append plus interval patch
    assert metrics["lod_points_avg"] >= 0

    # Retained buffers were normalized to typed, read-only arrays.  The native
    # document, not this test's temporary payload dict, owns their lifetime.
    assert all(not curve.depth.flags.writeable for curve in second.curves)
    assert all(not curve.values.flags.writeable for curve in second.curves)
    assert np.isfinite(second.primary.depth).all()


def test_binding_contract_not_silently_skipped() -> None:
    """#896: workbench↔engine 集成契约不可静默零覆盖。

    该文件是唯一的 workbench↔engine 契约；三条 CI 腿都不装 welllog 绑定
    (主 gate 只装 geoviz; WLWS 腿 WLWS_DISABLE_ENGINE=1; WLE 腿纯 ctest)，
    原 skip 会让契约在 CI 永久跳绿。本守卫统计同模块的 collected vs
    skipped：若除本守卫外全部因绑定缺失被 skip，则显式 fail 并提示
    “绑定契约零覆盖”。有绑定环境正常通过；无绑定 CI 显式红出。
    """

    import pathlib
    import re
    import subprocess
    import sys
    import os

    repo_root = pathlib.Path(__file__).resolve().parents[1]
    # Subprocess must propagate binding visibility. On this host the built
    # welllog wheel needs the system libstdc++ (conda's is too old for
    # GLIBCXX_3.4.35); without LD_PRELOAD the subprocess self-skips and hides
    # the skip phrase unless -rS is used. Preserve parent env and ensure the
    # reason is visible.
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    # If parent needed LD_PRELOAD for welllog, propagate it to the child.
    if "LD_PRELOAD" in os.environ:
        env["LD_PRELOAD"] = os.environ["LD_PRELOAD"]
    else:
        # Default to system libstdc++ if the child would otherwise fail to
        # import welllog on this host. No effect on CI where binding is absent.
        env.setdefault("LD_PRELOAD", "/usr/lib/libstdc++.so.6")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-rS", "-v", "tests/test_welllog_engine_native_integration.py::test_workbench_plan_uses_native_multitrack_append_and_patch"],
        capture_output=True,
        text=True,
        cwd=str(repo_root),
        env=env,
    )
    combined = result.stdout + result.stderr
    binding_skip_phrase = "built WellLogEngine binding is not on PYTHONPATH"
    skipped_due_to_binding = combined.count(binding_skip_phrase)
    has_passed = bool(re.search(r"\b1 passed\b", combined))
    has_binding_skip = skipped_due_to_binding > 0

    _, view_class, _ = adapter.try_import_welllog()
    binding_available = view_class is not None

    if binding_available:
        assert has_passed, (
            "binding is available but the native contract test did not pass; "
            f"output:\n{combined[:6000]}"
        )
        return

    assert has_binding_skip, (
        "binding unavailable but skip phrase not found — guard cannot verify zero coverage; "
        f"output:\n{combined[:6000]}"
    )
    pytest.fail(
        "绑定契约零覆盖: built WellLogEngine binding is not on PYTHONPATH — "
        "tests/test_welllog_engine_native_integration.py 的唯一契约在当前环境全部被 skip，"
        "CI 必须显式红出而非静默绿。请在绑定可用环境(PYTHONPATH 含 well-log-engine)重跑，"
        "或检查 CI 是否应增设绑定腿。(#896)"
    )
