# P2 Security Boundaries

## Agent-facing surface (what exists)

- The ONLY agent-callable surface is `ActionRegistry` → `HarnessExecutor`.
- 20 actions; risk classes READ/COMPUTE/WRITE; DESTRUCTIVE refused at registration.
- Tool schemas are derived from ActionSpec (same object validated at runtime).

## Explicitly absent (verified by construction + tests)

| Threat | Status |
|---|---|
| shell / subprocess execution action | absent — no action handler calls subprocess/os.system |
| eval / exec / arbitrary Python | absent — handlers are first-class functions over domain services |
| arbitrary SQL | absent — catalog access only through CatalogPort |
| arbitrary filesystem paths | inputs are typed refs; PathRef arrives from context, not free agent strings (export output_path is the one agent-supplied path — constrained by schema to a string, written through the export provider under governor admission; follow-up: workspace-relative confinement) |
| direct SQLite access | absent — DataCatalogService only |
| direct project-file writes | absent — WRITE actions mutate in-session documents; persistence stays on the existing GUI save path |
| catalog bypass | absent — derived/registered via CatalogPort inside providers/actions |
| bypass undo/version/provenance | absent — data writes create new versions + DataRun records |
| UI private-method access | absent — no findChild/click; actions call domain services only |
| LLM vendor coupling | absent — ChatModel/ToolSource protocols only; zero vendor imports |
| unrestricted plugin loading | absent — explicit registration + opt-in entry points, quarantine isolation |

## Provider SDK boundaries

- Providers receive typed refs (declared in input_types; executor enforces).
- Bad providers (invalid descriptor/raising factory/duplicate id) are quarantined;
  app boot unaffected (tested).
- Entry-point discovery is opt-in per launch (`PALEO_PROVIDER_ENTRY_POINTS=1`); no
  directory scanning.

## Resource-safety boundaries (P2-A)

- Admission rejects non-essential work under CRITICAL memory pressure with an
  explainable, non-retryable error before the OS OOM-killer acts.
- Cancellation is cooperative everywhere; no thread termination.
- Cache relief evicts (never deletes on-disk artifacts) via registered evictables.

## Residual risks (honest)

1. `map.export.output_path` is agent-chosen; it can overwrite an existing file
   chosen by the agent. Mitigation today: schema + governor + catalog OUTPUT
   registration makes overwrites visible in provenance. Follow-up: confine to
   workspace export directory + refuse existing files.
2. In-process WRITE actions mutate session documents; a malicious parameter set
   cannot corrupt project files (persistence is separate) but could alter the
   in-session map — acceptable for the current product stage, documented.
3. Entry-point discovery, when enabled, executes factory code from installed
   distributions — same trust level as any installed Python package (P.LOAD
   whitelist/signature checks remain future ADR 0055 stages).
