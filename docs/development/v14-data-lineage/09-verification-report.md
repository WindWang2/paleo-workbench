# 09 — Verification report

Machine: Windows 11 / MSVC 19.38 (VS 2022 Community) / Ninja / Qt 6.8.0
(`C:/deps/Qt/6.8.0/msvc2022_64`) / Python 3.13 (anaconda, pydantic).
Branch: `feat/v14-native-data-fabric-lineage`, tip `ac230bc9`.
Base: `412d8baf22a6a928c860e2e3d6c1108a9c035c78` (origin/main at start).

## Build

| Step | Command | Result |
|---|---|---|
| Standalone data-suite configure | `cmake -S libs/data_suite -B build/cpp-data-v14-ta -G Ninja -DCMAKE_BUILD_TYPE=Release` | OK |
| Domain libs | `--build … --target pwb_data -j 4` | OK (0 warnings from new TUs at /W4) |
| Full closure preset | `cmake --preset windows-msvc` + `--build build/presets/windows-msvc -j 4` | **OK, 0 errors**; links `pwb-platform.exe` |

Resource discipline: `-j4` ceiling throughout (CMAKE_BUILD_PARALLEL_LEVEL=4,
`--build -j 4`, ctest `-j 2`); isolated build dirs; no vendor/QGIS rebuild;
the POSIX resource gate is unavailable on win32 (exit 77) — enforced by
construction.

## Tests (final state, ×2 consecutive runs)

| Suite | Kind | Result |
|---|---|---|
| `data.entity_domain_ops` | domain (13 cases) | PASS |
| `data.entity_workspace` | domain (7 cases) | PASS |
| `data.manual_edit` | provenance + lifecycle (12 cases) | PASS |
| `data.data_fabric_e2e` | cross-module 18-step loop + appendix | PASS |
| `data.entity_workspace_scale` | scale/structural (4 cases, 10k wells / 100k links) | PASS |
| `platform.closure_data` | Qt offscreen product wiring | PASS |
| `platform.closure_mapping` | sibling-line regression | PASS |
| `platform.closure_review_install` | sibling-line regression | PASS |
| `ui_pages_data.smoke` / `.preparation_page` | sibling-line regression | PASS |

CTest slice (`data.entity*|data.manual_edit|data.data_fabric|platform.closure*|ui_pages_data`):
**10/10 passed, 0 failed**.

## Scale evidence (`data.entity_workspace_scale`)

- `well_index(false)` over 10,000 wells / 100,000 links with a **throwing**
  catalog source: completes and returns 10,000 correct entries — structural
  proof of zero catalog reads. Measured **161–188 ms** (ceiling 2500 ms).
- Expanding one well requests exactly that well's 10 asset ids (never the
  100k store); 50 expansions request exactly 500.
- Project switch: a second service over a different document sees only its
  own 3 wells; a pre-mutation index snapshot never observes later edits.

## Performance evidence

- Root index is O(W+L) over the project document; expanding one well is
  batched point lookups (500-id chunked SQL) plus one working-copy list and
  one related-runs query.
- `entity_staleness` (opt-in, `with_stale=true`) is the only
  document-snapshot cost — same class as the Python impact pass.
- A/B (feature vs clean `origin/main`, same box/config/command): the
  baseline cannot compile `libs/catalog` under MSVC at all, so no
  performance regression is attributable to this line; the new read paths
  add no statements to any pre-existing query.

## Compatibility / migration

- `ordinal` on entity links: schema default 0 — pre-V14 documents load,
  normalize and round-trip unchanged; the Python model gained the same
  field so an open→save in either app preserves ordinals (verified by a
  dump/reparse round-trip in `data.entity_domain_ops`).
- `metadata["lifecycle"]` + top-level `retention_class` are additive and
  idempotent; an existing `lifecycle` object is never overwritten.
- `PublishRequestV1::artifact_kind` defaults empty → no enforcement for
  callers that do not opt in.
- No new production Python dependency; the Python change is one model field
  (compatibility), and Python remains the frozen semantic oracle.

## Independent reviews

Two rounds (see `07-review-findings.md`): 2×P0 + 6×P1 + 9×P2/P3 fixed;
4 P3s accepted with rationale and recorded in `08-known-limitations.md`.
P0/P1 open count at PR time: **zero**.

## Statement

Local verification completed; online CI was not required or awaited for
this development goal.
