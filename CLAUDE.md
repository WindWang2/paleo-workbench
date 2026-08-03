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
