## Product track (read first)

- **Native product** is `pwb-platform` (`apps/paleo_workbench_platform`), C++20/Qt/QGIS.
- **Legacy Python** (`paleo_workbench/`) is oracle + parallel legacy app — do not add new production UI there (`docs/development` “Python 生产路径零新增”).
- Doc IA: [`docs/README.md`](docs/README.md). Module map: [`docs/architecture/module-map.md`](docs/architecture/module-map.md). Dual-track: [`docs/architecture/dual-track.md`](docs/architecture/dual-track.md).
- Conversion snapshot: [`docs/development/cpp-conversion-status.md`](docs/development/cpp-conversion-status.md).

## Agent skills

### Issue tracker

Issues and PRDs live in GitHub Issues (using the `gh` CLI). See `docs/agents/issue-tracker.md`.

### Triage labels

Canonical triage label vocabulary mapped 1:1 (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout (`CONTEXT.md` + `docs/adr/` at repo root). See `docs/agents/domain.md`.
When docs conflict: code/tests on the SHA > canonical docs > newest ledger > design drafts.

### Coding guidelines

Always follow the Karpathy guidelines when writing, reviewing, or refactoring code (full text: `agent/skills/karpathy-guidelines/SKILL.md`):

- **Think before coding** - state assumptions explicitly; if multiple interpretations exist, surface them; stop and ask when confused.
- **Simplicity first** - write the minimum code that solves the problem; no speculative abstractions or unrequested configurability.
- **Surgical changes** - touch only what the task requires; match existing style; don't refactor unrelated code.
- **Goal-driven execution** - define verifiable success criteria (e.g., a failing test, then make it pass) and loop until met.

Native-specific invariants:

- Qt-free domain logic in `libs/`; host wiring in `apps/`.
- Single catalog rail; honest failure; no silent Python fallback in `pwb-platform`.
- Ribbon / menus / shortcuts share one command identity.

## gstack (recommended)

This project recommends [gstack](https://github.com/garrytan/gstack) for AI-assisted workflows. Install it for the best experience (requires Bun >= 1.3.10):

```bash
git clone --depth 1 https://github.com/garrytan/gstack.git ~/.claude/skills/gstack
cd ~/.claude/skills/gstack && ./setup --team
```

After install, gstack skills like `/ship`, `/investigate`, `/browse`, `/design-shotgun`, and `/cso` become available. Note: gstack also registers `/qa` and `/review`, which shadow this repo's own `agent/skills/qa` and `agent/skills/code-review` - prefer the repo-vendored versions for project-specific review workflows. Use `/browse` for web browsing.

## 地图栈

- **Native product**: QGIS via `libs/qgis` + vendored QGIS SDK linked by `pwb-platform`.
- **Legacy Python product**: `paleo_workbench/ui/qgis_stack` + optional `qgis_render_bridge` pybind; M1+ 综合编修硬依赖桥。无桥时 Python CI 走 fallback；不要把该段写成 native 产品行为。
