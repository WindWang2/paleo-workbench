# 02 — Definition of Done checklist

Baseline SHA for claims: `18c674ef` unless a row says otherwise.

| # | Criterion | Result | Evidence |
| --- | --- | --- | --- |
| D1 | Doc IA index exists and states precedence | **PASS** | `docs/README.md` |
| D2 | Root README leads with native `pwb-platform` and honest dual-track | **PASS** | `README.md` |
| D3 | PROJECT.md describes libs/apps architecture (not Python-only convergence sheet) | **PASS** | `PROJECT.md` |
| D4 | Module boundary map covers all 63 `libs/` groups | **PASS** | `docs/architecture/module-map.md` |
| D5 | C++ conversion reality snapshot cites ledgers + SHA | **PASS** | `docs/development/cpp-conversion-status.md` |
| D6 | Dual-track honesty documented for agents | **PASS** | `docs/architecture/dual-track.md` |
| D7 | CLAUDE.md steers agents to native-first + doc IA | **PASS** | `CLAUDE.md` |
| D8 | Ribbon adoption status recorded as adopted on main | **PASS** | `docs/development/ribbon-five-workspaces/STATUS.md` (plan §7 already documents M0–M6 complete) |
| D9 | Refresh ledger (baseline/findings/DoD) committed | **PASS** | this directory |
| D10 | No product source changes (docs-only PR) | **PASS** | `git diff --stat` vs main shows docs paths only |
| D11 | Branch pushed and PR opened (not merged) | **PASS** | https://github.com/WindWang2/paleo-workbench/pull/1474 |

## Explicit non-claims

- Did **not** run a full native rebuild/CTest on this documentation-only change.
- Did **not** merge `#1473` or rewrite geo-viz limitation lists beyond pointing
  readers at them.
- Did **not** change `pyproject.toml` default entry.
