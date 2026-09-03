## Agent skills

### Issue tracker

Issues and PRDs live in GitHub Issues (using the `gh` CLI). See `docs/agents/issue-tracker.md`.

### Triage labels

Canonical triage label vocabulary mapped 1:1 (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout (`CONTEXT.md` + `docs/adr/` at repo root). See `docs/agents/domain.md`.

### Coding guidelines

Always follow the Karpathy guidelines when writing, reviewing, or refactoring code (full text: `agent/skills/karpathy-guidelines/SKILL.md`):

- **Think before coding** - state assumptions explicitly; if multiple interpretations exist, surface them; stop and ask when confused.
- **Simplicity first** - write the minimum code that solves the problem; no speculative abstractions or unrequested configurability.
- **Surgical changes** - touch only what the task requires; match existing style; don't refactor unrelated code.
- **Goal-driven execution** - define verifiable success criteria (e.g., a failing test, then make it pass) and loop until met.

## gstack (recommended)

This project recommends [gstack](https://github.com/garrytan/gstack) for AI-assisted workflows. Install it for the best experience (requires Bun >= 1.3.10):

```bash
git clone --depth 1 https://github.com/garrytan/gstack.git ~/.claude/skills/gstack
cd ~/.claude/skills/gstack && ./setup --team
```

After install, gstack skills like `/ship`, `/investigate`, `/browse`, `/design-shotgun`, and `/cso` become available. Note: gstack also registers `/qa` and `/review`, which shadow this repo's own `agent/skills/qa` and `agent/skills/code-review` - prefer the repo-vendored versions for project-specific review workflows. Use `/browse` for web browsing.

## 地图栈（M1 起）

综合编修区由 QGIS 画布承载（`paleo_workbench/ui/qgis_stack/QgisCanvasShim` 包装 `QgsMapCanvas`，经 `qgis_render_bridge.mapstack`）；其余页面（`mapping_page` / `home_page` / `workarea_map_widget`）仍使用 `UnifiedMapCanvas` + fallback 渲染器。fallback 拆除在 M4（届时全量切 QGIS 栈）。
