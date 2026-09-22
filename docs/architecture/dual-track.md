# Dual-track product honesty

**Native product**: C++ `pwb-platform` (`apps/paleo_workbench_platform`, `libs/*`).
**Legacy Python product / oracle**: `paleo_workbench/` and `tools/oracle/*`.

The domain glossary in root [`CONTEXT.md`](../../CONTEXT.md) grew with the
Python product; treat Python paths there as domain definitions / oracle
locations unless a native type is named. Module placement:
[`module-map.md`](module-map.md). Doc IA: [`../README.md`](../README.md).

This note exists so agents do not miss the dual-track rule even when browsing
architecture docs first.

## Related

- Root [`CONTEXT.md`](../../CONTEXT.md) carries a dual-track banner: Python
  paths there are domain/oracle vocabulary.
- CMake `message(STATUS … Python pages remain the production path)` strings mean
  an **optional UI slice was skipped in that configure**, not that Python is the
  native product default.
