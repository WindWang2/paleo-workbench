#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""V5 视觉回归 diff 报告（U8）。

对比当前矩阵截图与 baseline，输出 markdown 报告（逐 shot 像素差比例 +
差异热区 bbox）。阈值**不是自动门禁**（decisions.md D8）：报告供人工
判读，重要结构回归由语义 Qt tests 钉住。

用法::

    python scripts/diff_ui_matrix.py visual_qa/baseline-v5-matrix /tmp/ui-matrix \
        --out /tmp/ui-matrix/diff-report.md
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageChops

#: 像素差比例分级（仅报告标注，非门禁）
_WARN_RATIO = 0.01   # >1% 像素显著不同
_ALERT_RATIO = 0.05  # >5% 大面积不同


def _diff_ratio(path_a: Path, path_b: Path) -> tuple[float, tuple[int, int, int, int] | None]:
    img_a = Image.open(path_a).convert("RGB")
    img_b = Image.open(path_b).convert("RGB")
    if img_a.size != img_b.size:
        return 1.0, None
    diff = ImageChops.difference(img_a, img_b).convert("L")
    hist = diff.histogram()
    total = img_a.size[0] * img_a.size[1]
    changed = sum(hist[16:])  # 灰度差 >16 计为显著变化（容忍字体渲染微差）
    if changed == 0:
        return 0.0, None
    bbox = diff.point(lambda v: 255 if v > 16 else 0).getbbox()
    ratio = changed / total
    return ratio, bbox


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline_dir")
    parser.add_argument("current_dir")
    parser.add_argument("--out", default="diff-report.md")
    args = parser.parse_args()

    baseline_dir = Path(args.baseline_dir)
    current_dir = Path(args.current_dir)
    manifest = json.loads((current_dir / "manifest.json").read_text(encoding="utf-8"))

    lines = [
        "# UI V5 矩阵 diff 报告",
        "",
        f"- baseline: `{baseline_dir}`",
        f"- current: `{current_dir}`",
        f"- shots: {manifest.get('shot_count')}",
        "",
        "| shot | 状态 | 像素差 | 差异区 bbox |",
        "|---|---|---|---|",
    ]
    missing = 0
    changed = 0
    for shot in manifest.get("shots", []):
        if not shot.get("ok"):
            continue
        name = shot["name"]
        base = baseline_dir / name
        cur = current_dir / name
        if not base.exists():
            lines.append(f"| {name} | MISSING(无基线) | — | — |")
            missing += 1
            continue
        if not cur.exists():
            lines.append(f"| {name} | FAILED | — | — |")
            changed += 1
            continue
        ratio, bbox = _diff_ratio(base, cur)
        if ratio == 0.0:
            status = "identical"
        elif ratio < _WARN_RATIO:
            status = "ok"
        elif ratio < _ALERT_RATIO:
            status = "changed"
            changed += 1
        else:
            status = "**CHANGED(大)**"
            changed += 1
        lines.append(f"| {name} | {status} | {ratio:.2%} | {bbox} |")

    lines += [
        "",
        f"**摘要**: {changed} 张变化, {missing} 张缺基线。",
        "",
        "> 阈值仅作分级提示（>1% changed / >5% 大面积变化）。",
        "> 主题切换批次间的大面积差异属预期（各自与同名基线比）。",
        "",
    ]
    out = Path(args.out)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"diff report → {out} ({changed} changed, {missing} missing)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
