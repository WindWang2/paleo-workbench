# Product Wiring Audit

The formal composition root remains:

```text
main -> Bootstrap -> AppContext -> MainWindow/AppShell -> native services
```

This closure adds declarative native-product implications for the product
features already consumed by `pwb-platform`: QGIS editing, data lifecycle,
workflow runtime, seismic service, composition export, job runtime, providers,
prediction closure, Geo3D, and cross-well visualization.

The final configure summary checks every hard capability for:

```text
required target exists
-> declared consumer links the target
-> pwb-platform receives the required host definition
```

Configuration fails instead of accepting a feature switch as product wiring
when any link in that chain is absent.

`AppContext` now owns a `ProviderService`, seeded with built-in providers, and
the runtime capability audit verifies that its registry is reachable.

Honest exclusions remain:

- `Pwb::ClosureWorkflow` has no formal `pwb-platform` host call site;
- `Pwb::ClosureAgentWorkflow` has no production plan resolver/executor binding;
- optional pybind targets are Python compatibility facades, not product
  runtime;
- unsupported agent execution remains fail-closed with the existing
  no-resolver diagnostic.

These exclusions are represented as `NATIVE_LIBRARY_NOT_WIRED` or
`PARTIAL_NATIVE`, never as product support.
