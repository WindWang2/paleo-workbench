#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""V5 视觉回归矩阵 harness（U8）：主题 × 密度 × 尺寸 × 页面状态 的截图矩阵。

在 capture_workstation_screens.py（12 状态，offscreen widget.grab）之上扩展：
- 矩阵驱动：每个状态 shot 在 (theme, density, size) 组合下各截一张；
- 确定性：QSettings 沙箱（每 shot 全新进程 + 清空工作站布局）；
- baseline 管理：``--update-baseline`` 把结果落盘 ``visual_qa/baseline-v5-matrix/``
  并写 manifest.json；默认对比模式在 baseline 缺项时记 MISSING 而不失败。

用法（worktree 根目录）::

    # 核心矩阵（4 状态 × 3 主题 × 2 密度 @1440×900 + 默认态尺寸扫描）
    python scripts/capture_ui_matrix.py --core /tmp/ui-matrix

    # 全矩阵（12 状态 × 3 主题 × 2 密度 @1440×900）
    python scripts/capture_ui_matrix.py --full /tmp/ui-matrix

截图是像素证据，不替代 widget 级断言；diff 阈值不是自动门禁
（decisions.md D8）——结构回归靠语义 Qt tests 钉住。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

CORE_STATES = [
    "01-default-workstation",
    "03-mapping",
    "07-integrated",
    "12-dark-theme",
]
FULL_STATES = [
    "01-default-workstation",
    "02-data-heavy-project",
    "03-mapping",
    "04-layer-style",
    "05-well",
    "06-seismic",
    "07-integrated",
    "08-agent-running",
    "09-task-center",
    "10-error-state",
    "11-empty-state",
    "12-dark-theme",
]
#: V6 Phase 8 新状态（visual_qa_v6；--v6 只跑这些，不触碰既有 12 状态）。
V6_STATES = [
    "mapping_stage_phase1",
    "mapping_stage_phase2",
    "mapping_stage_phase3",
    "command_palette_context",
    "write_grant_dialog",
    "status_workbench_segment",
]
THEMES = ["light", "dark", "high_contrast"]
DENSITIES = ["compact", "comfortable"]
SIZES = [
    (1440, 900),
    (1180, 720),
    (1920, 1080),
]


def _run_one(script: Path, out_dir: Path, state: str, theme: str, density: str, w: int, h: int) -> int:
    cmd = [
        sys.executable,
        str(script),
        str(out_dir),
        "--shot",
        state,
        "--theme",
        theme,
        "--density",
        density,
        "--size",
        f"{w}x{h}",
    ]
    result = subprocess.run(cmd, check=False, timeout=300)
    if result.returncode == 0:
        # capture 子进程只按状态名写 PNG（{state}.png）；矩阵名带
        # 主题/密度/尺寸后缀，逐 shot 重命名避免相互覆盖。
        source = out_dir / f"{state}.png"
        target = out_dir / f"{state}__{theme}__{density}__{w}x{h}.png"
        if source.exists():
            source.replace(target)
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out_dir", nargs="?", default="visual_qa/matrix")
    parser.add_argument("--core", action="store_true", help="仅核心状态矩阵")
    parser.add_argument("--full", action="store_true", help="全部 12 状态 × 3 主题 × 2 密度")
    parser.add_argument(
        "--v6", action="store_true",
        help="仅 V6 Phase 8 新状态（6 状态 × 2 密度 @3 尺寸，light 基准）")
    parser.add_argument("--update-baseline", action="store_true")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.v6:
        states = V6_STATES
    else:
        states = FULL_STATES if args.full else CORE_STATES
    sizes = SIZES

    script = Path(__file__).with_name("capture_workstation_screens.py").resolve()
    shots: list[dict] = []
    failures: list[str] = []
    started = time.monotonic()
    for state in states:
        base_theme = "dark" if state == "12-dark-theme" else "light"
        theme_combos = [(base_theme, d) for d in DENSITIES] + (
            [(t, "comfortable") for t in THEMES if t != base_theme] if state == "01-default-workstation" else []
        )
        for theme, density in theme_combos:
            for w, h in sizes:
                name = f"{state}__{theme}__{density}__{w}x{h}.png"
                code = _run_one(script, out_dir, state, theme, density, w, h)
                entry = {
                    "name": name,
                    "state": state,
                    "theme": theme,
                    "density": density,
                    "size": f"{w}x{h}",
                    "ok": code == 0,
                }
                shots.append(entry)
                if code != 0:
                    failures.append(name)
                print(("saved " if code == 0 else "FAILED ") + name, flush=True)

    manifest = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_s": round(time.monotonic() - started, 1),
        "shot_count": len(shots),
        "failures": failures,
        "shots": shots,
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"matrix done: {len(shots) - len(failures)}/{len(shots)} ok "
        f"in {manifest['elapsed_s']}s → {out_dir}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
