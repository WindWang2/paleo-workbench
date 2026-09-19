# CONV-PROVIDERS — Provider / Plugin / Tool Runtime native C++ closure

Branch: `feat/cpp-provider-plugin-tool-runtime` (base: origin/main @ ff67dcf3)
Worktree: `../worktrees/cpp-provider-plugin-tool-runtime`

## Scope

Migrate the workbench's **capability provider runtime** — the sanctioned
extension unit (ADR 0055 track P.REG) — from
`paleo_workbench/providers/*` (Python) to a Qt-free C++20 library
(`libs/providers`, target `pwb_providers`, alias `Pwb::Providers`), plus the
real providers the product invokes today. This is *not* an agent-harness
rebuild and *not* a dynamic-plugin ABI project.

## Python surfaces → classification

| Python surface | Classification | C++ counterpart |
|---|---|---|
| `providers/contracts.py` (ProviderFamily, ResourceProfile, ProviderDescriptor, validate_descriptor) | **replaced** | `libs/providers/include/pwb/providers/contracts.hpp` |
| `providers/refs.py` (typed refs, ArtifactRef, ProviderResult) | **replaced** | `refs.hpp` (JSON payload form) |
| `providers/errors.py` (8-class hierarchy, byte-identical messages) | **replaced** | `errors.hpp` |
| `providers/base.py` (CapabilityProvider protocol, ProviderContext, progress, cancel) | **replaced** | `context.hpp` (`IProvider`, `ProviderContext`, `CancelToken`) |
| `providers/registry.py` (register/duplicate/quarantine/sorted descriptors/singleton) | **replaced** | `registry.hpp/.cpp` |
| `providers/execution.py` (`validate_parameters` #1178 subset, `_validate_inputs`, execute_provider pipeline, #1137 cancel, #1146 lease inheritance, Harness 2.0 verify hook) | **replaced** | `schema.hpp/.cpp`, `execution.hpp/.cpp` |
| `providers/paths.py` (resolve_contained_output #1177) | **replaced** | `context.cpp` |
| `providers/registry.py` entry-point discovery (`PALEO_PROVIDER_ENTRY_POINTS`) | **not ported by design** | Python's own rule is "No directory scanning, ever"; C++ has explicit registration. Dynamic loading/ABI versioning is deferred until a real third-party plugin need exists (mandate: no over-design). |
| `providers/execution.py` ResourceGovernor/ImportError degraded machinery (#1180) | **replaced by port seam** | `IAdmissionPort`/`IAdmissionLease` (hosts inject their governor); pressure shedding stays a first-class unwrapped outcome (`AdmissionRejected`) |
| `examples/provider_plugins/geology_factor_stats.py` | **replaced** | `builtin_factor_stats.cpp` (`geology.factor_stats`, real stats over `pwb::mapping::FactorDataset`) |
| `examples/provider_plugins/export_map_thumbnail.py` | **replaced (core-only)** | `builtin_map_thumbnail.cpp` (`export.map_thumbnail`, native software rasterizer + deterministic stored-deflate PNG writer; no LOD/threading machinery — not needed for thumbnails) |
| `providers/builtin/interpolation.py` (kriging/idw), `seismic_attribute.py`, `inference.py` (tiled ONNX), `map_export.py` (export.map_product + viz backends) | **Python-only (engine closures pending)** | Their engine seams belong to the science/QGIS closure lines; they re-enter as providers over the same C++ contract when those land. The `IMPORTER`/`DATA_FORMAT`/`PREVIEW`/`MAP_COMPONENT` families ship as vocabulary only, matching Python. |
| `agent/registries/tool_registry.py` (+ skill/algorithm/template registries) | **Python-only by scope** | Part of the agent harness (OpenAI function-calling schemas, decorators); the mandate excludes rebuilding the agent harness. The native provider registry *is* the tool/capability surface for the C++ runtime; `ProviderService.capability_report()` exposes it for host UIs. |

## Product wiring

- Root `CMakeLists.txt`: `PWB_BUILD_PROVIDERS` (implies `PWB_BUILD_DATA`,
  `PWB_BUILD_MAPPING_KERNEL`, `PWB_BUILD_CONV_02`); subdirectory added after
  the mapping kernels so the ALIAS targets exist.
- `apps/paleo_workbench_platform`: `if(TARGET Pwb::Providers)` gate links the
  SDK into `pwb-platform` with `PWB_WITH_PROVIDERS=1` (established seam
  pattern, mirrors `PWB_WITH_SEISMIC_IO`). The composition-root call-site
  rides the platform-closure PR (#1353) which owns `bootstrap`/`app_context`.
- `ProviderService` (`service.hpp`) is the Application/Workflow-facing
  contract: builtin-seeded registry, ordered JSON capability report,
  quarantine report, guarded `run()`. Workflow hosts resolve provider ids and
  validate node parameters through the same SDK (`validate_parameters`).

## Oracle

- `tools/oracle/generate_provider_fixtures.py` runs the **real Python
  implementation** and freezes 58 cases (35 `validate_parameters` + 23
  `validate_descriptor`, covering normal/empty/illegal/boundary/Unicode/
  union/unknown-type/additionalProperties paths) into
  `libs/providers/providers_tests/provider_oracle.json`.
- `providers.oracle` replays every case in C++ with verbatim problem-string
  and order parity, checks the typed-ref vocabulary, and includes a negative
  self-check (perturbed verdicts must be detectable; the generator also
  self-verifies).
- NaN/Inf are covered natively in `providers.schema` (JSON-frozen fixtures
  cannot carry NaN literals; C++ asserts Python float semantics: NaN passes
  bounds, `inf` violates maximum with `inf > maximum 1.0` formatting).

## Tests (all local, offscreen-free, no Python at C++ test time)

`providers.oracle`, `providers.contracts`, `providers.registry`,
`providers.schema`, `providers.execution`, `providers.builtins`,
`providers.service` — registration, duplicate (same-version vs
version-conflict quarantine), replace, invalid schema, failure wrapping,
cancellation as first-class outcome, capability query, containment
(escape/overwrite/no-root), deterministic PNG bytes, IHDR/painted-pixel
audit, catalog DataRun lifecycle.

## Local build & test

```
cmake -B build/providers -G Ninja -DPWB_BUILD_PROVIDERS=ON -DPWB_BUILD_PLATFORM=OFF -DBUILD_TESTING=ON
cmake --build build/providers --parallel 3     # -j3 hard cap
ctest --test-dir build/providers               # 38/38 passed (x2 runs)
```

Resource note: all builds ran at `--parallel 3` maximum; the library is
small (11 sources) so no OMD/mitigation was needed. Vendored QGIS SDK is
absent on this Linux host, so `PWB_BUILD_PLATFORM=OFF`; the app-side gate is
compile-verified by target existence, matching the repo's platform-off
convention (CONV-16 precedent).

## Known limitations

- `export.map_product` / QGIS-preferred product export and the viz render
  backends remain Python until their engine closures merge.
- Dynamic plugin loading (ABI version, load isolation, unload policy) is
  deliberately deferred — Python's registry never scanned directories either.
- Provider inputs carry typed names + JSON payloads; in-process domain
  objects travel in their JSON form (`make_dataset_typed_input` adapter for
  `pwb::mapping::FactorDataset`).
- Malformed-schema edges where Python would raise TypeError inside
  `validate_parameters` are handled defensively (fail-open skip) in the C++
  port: non-numeric `minimum`/`maximum`, non-array `enum`, and non-string
  entries of `required` are treated as absent instead of throwing. Frozen
  oracle cases do not exercise those paths. Negative `minItems`/`maxItems`
  follow Python's numeric comparison (maxItems < 0 trips, minItems < 0 does
  not).
- `validate_parameters` also exists as an independent port inside
  `libs/workflow_spec` (CONV-06, `src/validation.cpp`), which predates this
  branch. The fork is intentional: `pwb_providers` PUBLIC-links the mapping
  kernels, which workflow_spec must not drag in, so a shared leaf validator
  would need its own extraction PR. Known behavioral delta between the two:
  workflow_spec throws `ModelError` on non-numeric schema bounds (fail-closed)
  while this SDK skips them (see previous bullet). Follow-up: extract a
  common validator or document the fork as permanent.
- Registry borrowing contract: `get`/`find`/`by_family` return non-owning
  views; `register_provider(replace=true)`/`unregister` destroy the previous
  instance. Mutating registration must be externally serialized against
  execution (the composition root registers at startup, then only reads).
- Validation strictness deltas (all fail-closed or cosmetic, documented for
  honesty): C++ `regex_match` rejects a trailing-newline provider_id where
  Python `re.match` with `$` would accept it; the blank-`display_name` check
  uses ASCII whitespace where Python `str.strip()` also strips Unicode
  spaces (U+3000 etc.); `resolve_contained_output` comparison is
  case-sensitive, so Windows hosts may see false "outside workspace"
  rejections when path case differs (fail-closed direction).
- Catalog bookkeeping failures and the #1146 under-reservation warning are
  emitted through `pwb::providers::set_log_sink` (default quiet) instead of
  Python's `logging` module.
- The `geology.factor_stats` C++ provider enforces the declared
  `report_name` pattern (`^[a-z0-9._-]+$`) that the Python example left
  unenforced — a strict hardening over the source (the Python example could
  traverse out of the work dir via `report_name`).
- Platform `main_window` call-sites are intentionally untouched here to keep
  the shared-file surface minimal against the in-flight platform PRs.

## Parallel-branch interaction

- No overlap with open PRs' files except `CMakeLists.txt` (root: one
  self-contained CONV-PROVIDERS block) and
  `apps/paleo_workbench_platform/CMakeLists.txt` (one appended block) —
  append-only, merge-trivial.
- PR #1353 (native product closure) owns the composition root; the
  `ProviderService` + `PWB_WITH_PROVIDERS` seam here is its provider-side
  counterpart, not a competing one.
