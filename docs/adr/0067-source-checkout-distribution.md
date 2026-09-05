# ADR 0067: source-checkout distribution (no published wheel)

Date: 2026-09-05
Status: accepted (records existing practice; closes #1191)

## Context

`pip install paleo-workbench` followed by running the `paleo-workbench`
entry point exits with `SystemExit(2)` plus install guidance whenever the
geoviz packages are unavailable (#1191). geoviz is consumed as a git
submodule (`./geo-viz-engine`, installed editable via
`requirements-geoviz.txt` with repo-relative `-e` paths) and deliberately
NOT listed as PEP 508 dependencies (pip cannot expand
`${PROJECT_ROOT}`-style variables; install order matters, leaf first).

## Decision

The product distributes as a **source checkout + editable installs**.
There is no published, directly-runnable wheel, by design:

- `requirements-geoviz.txt` (repo-relative editable paths) is the geoviz
  install mechanism; it only resolves inside a checkout.
- The `paleo-workbench` entry point (`paleo_workbench.main:main`) keeps its
  fail-loud contract: missing geoviz -> `SystemExit(2)` with the exact
  recovery commands, never a half-working app.
- Native extensions (`native/*`, `geo-viz-engine/native/*`) are built
  in place per host interpreter (see ADR 0061 for the zarr/sharding
  storage choice and `tests/test_native_abi_gate.py` for the ABI gate);
  they are not shipped as prebuilt binaries.

## Consequences

- A wheel built from this tree (`tests/test_wheel_assets.py` pins its
  assets) is NOT a runnable artifact without the checkout beside it.
- If external distribution is ever required, the prerequisite work is:
  publish geoviz subpackages as versioned wheels, convert the submodule
  dependency to version pins, and ship native extensions as per-platform
  wheels. Until then, this ADR is the documented answer to #1191.
