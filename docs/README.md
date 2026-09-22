# Paleo Workbench documentation map

**Audience**: humans and agents landing in the repo.
**Baseline**: `origin/main` @ `18c674ef` (2026-09-22).
**Product default in this tree**: native C++ `pwb-platform` with the ribbon
five-workspaces shell. Python `paleo_workbench` remains a supported **legacy
product** and the **oracle / reference** surface for conversion work — it is
not the native product runtime.

## How to read this tree (IA)

| Layer | Paths | Authority | When to read |
| --- | --- | --- | --- |
| **Canonical product docs** | Root [`README.md`](../README.md), [`PROJECT.md`](../PROJECT.md), [`CLAUDE.md`](../CLAUDE.md), this file, [`architecture/`](architecture/) (incl. [`dual-track.md`](architecture/dual-track.md)); [`CONTEXT.md`](../CONTEXT.md) **with dual-track banner** (Python paths = domain/oracle) | Current product truth | First |
| **Decisions** | [`adr/`](adr/) (33 ADR files at `18c674ef` snapshot) | Binding architecture decisions | Before changing a contract |
| **Agent / process** | [`agents/`](agents/) | Issue tracker, triage, domain-doc rules | Before filing issues or exploring |
| **UI design authority** | [`ui-redesign/qt-ribbon-workspaces-2026-09-21/`](ui-redesign/qt-ribbon-workspaces-2026-09-21/), [`ui-redesign/qt-five-workspaces-2026-09-21/`](ui-redesign/qt-five-workspaces-2026-09-21/) + adoption [`development/ribbon-five-workspaces/STATUS.md`](development/ribbon-five-workspaces/STATUS.md) | Behaviour rules (screenshots = design refs) | UI work |
| **Conversion & feature ledgers** | [`development/`](development/) (many dated goal-loop folders) | Historical + in-flight evidence | When verifying a claim against a SHA |
| **Specs / research / audit** | [`specs/`](specs/), [`research/`](research/), [`audit/`](audit/), root `audit/` | Supporting material | As needed |
| **Stale / superseded** | Old workstation-v3 notes; root `FINAL_REPORT.md` / `TEST_*` / scratch `findings.md`·`progress.md`·`task_plan.md`·`design-qa.md` (now bannered); [`audit/`](audit/); early Python-only copy that conflicts with C++ truth | **Not** product authority when they contradict the canonical layer | Only for archaeology |

**Precedence when docs disagree**

1. Code + CTest / `--self-check` / `--capabilities` on the SHA you care about.
2. Canonical product docs (this layer).
3. Newest matching ledger under `development/` that cites that SHA.
4. Design drafts under `ui-redesign/` (behaviour rules beat decorative screenshots).
5. Older root / audit prose.

## Start here

1. [Root README](../README.md) — build, run, dual-track honesty.
2. [PROJECT.md](../PROJECT.md) — architecture, module groups, entry points.
3. [architecture/module-map.md](architecture/module-map.md) — `libs/*` / `apps/*` boundaries.
4. [development/cpp-conversion-status.md](development/cpp-conversion-status.md) — C++ conversion reality snapshot.
5. Dual-track honesty: [architecture/dual-track.md](architecture/dual-track.md).
6. Domain glossary: [CONTEXT.md](../CONTEXT.md) (Python-era paths = domain/oracle vocabulary; read the dual-track banner first).

## Development ledgers worth knowing

| Topic | Path |
| --- | --- |
| C++ conversion master plan | [development/cpp-conversion-main-plan.md](development/cpp-conversion-main-plan.md) |
| Entry-switch review (M5) | [development/cpp-entry-switch-review.md](development/cpp-entry-switch-review.md) |
| GeoViz native closure | [development/geoviz-cpp-final-closure/](development/geoviz-cpp-final-closure/) |
| Ribbon five-workspaces adoption | [development/ribbon-five-workspaces/](development/ribbon-five-workspaces/) |
| This documentation refresh | [development/project-documentation-refresh-2026/](development/project-documentation-refresh-2026/) |

Ledgers under `docs/development/<feature>/` are **evidence packs** for a goal
loop (baseline, findings, tests, limitations). They are not an alternate
product README. Prefer linking them from the canonical layer instead of
copying claims into root docs without a SHA.
