#!/usr/bin/env python3
"""Freeze the platform-services oracle for the C++ retirement branch.

Drives the REAL Python implementation (paleo_workbench.tokens) and freezes:
  * palette_for() for light / dark / high_contrast (+ fallback + dash
    normalization cases),
  * density_tokens() for both densities (+ unknown-density fallback),
  * the application version literal parsed from paleo_workbench/__init__.py
    (source read — importing __init__ would pull the geoviz bootstrap).

Deterministic: re-run must be byte-identical.

Negative self-check: the generator FAILS (non-zero exit) unless the frozen
palettes actually differ between themes, the fallbacks match their contracted
tables, and every value is a str/int — a Python-side regression that would
silently weaken the C++ parity test is caught here instead.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from paleo_workbench import tokens  # noqa: E402

OUT_DIR = ROOT / "tests/cpp/platform/fixtures/platform_services"


def dump(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    path.write_text(text + "\n", encoding="utf-8")


def palette_of(theme: str) -> dict:
    """tokens.palette_for minus the QSS_TEMPLATE implementation artifact.

    QSS_TEMPLATE is a module-level rendered stylesheet string that Python's
    globals()-sweep happens to pick up; it is the default sheet, not a design
    token (no consumer reads palette["QSS_TEMPLATE"]). The C++ retirement
    table excludes it; everything else is frozen verbatim.
    """
    palette = tokens.palette_for(theme)
    palette.pop("QSS_TEMPLATE", None)
    # The C++ token table is string-valued (QSS-oriented), so numeric
    # metric tokens are projected through str() — a faithful, reversible
    # mapping of the Python ints, frozen the same way on both sides.
    return {k: v if isinstance(v, str) else str(v)
            for k, v in palette.items()}


def main() -> int:
    themes = {}
    for theme in ("light", "dark", "high_contrast"):
        themes[theme] = palette_of(theme)
    # Fallback + normalization contracts consumed by the C++ parity test:
    themes["fallback_unknown"] = palette_of("midnight")  # -> light
    themes["normalized_dash"] = palette_of("HIGH-CONTRAST")

    densities = {
        "compact": tokens.density_tokens("compact"),
        "comfortable": tokens.density_tokens("comfortable"),
        # Unknown density falls back to comfortable (never throws).
        "fallback_bogus": tokens.density_tokens("ultra-dense"),
    }

    init_source = (ROOT / "paleo_workbench/__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*"([^"]+)"', init_source, re.M)
    if match is None:
        print("cannot parse __version__ from paleo_workbench/__init__.py", file=sys.stderr)
        return 1

    # ---- negative self-check: bad oracle data must fail the generator ----
    for name in ("light", "dark", "high_contrast"):
        if themes[name] != themes.get("fallback_unknown"):
            pass  # light == fallback is the contract, checked below
    if themes["light"] != themes["fallback_unknown"]:
        print("NEGATIVE SELF-CHECK FAILED: palette_for('midnight') != light", file=sys.stderr)
        return 1
    if themes["high_contrast"] != themes["normalized_dash"]:
        print("NEGATIVE SELF-CHECK FAILED: 'HIGH-CONTRAST' did not normalize", file=sys.stderr)
        return 1
    if themes["light"] == themes["dark"] or themes["light"] == themes["high_contrast"]:
        print("NEGATIVE SELF-CHECK FAILED: theme palettes are not distinct", file=sys.stderr)
        return 1
    if densities["comfortable"] != densities["fallback_bogus"]:
        print("NEGATIVE SELF-CHECK FAILED: unknown density did not fall back", file=sys.stderr)
        return 1
    for palette in themes.values():
        for key, value in palette.items():
            if not isinstance(value, (str, int, float)):
                print(f"NEGATIVE SELF-CHECK FAILED: {key} is {type(value).__name__}", file=sys.stderr)
                return 1

    dump(OUT_DIR / "theme_palettes.json", themes)
    dump(OUT_DIR / "theme_density.json", densities)
    dump(OUT_DIR / "app_meta.json", {"app_version": match.group(1)})
    print(f"wrote {OUT_DIR} (light={len(themes['light'])} tokens, "
          f"dark={len(themes['dark'])}, high_contrast={len(themes['high_contrast'])})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
