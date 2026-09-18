# Vendored pybind11 (CONV-20)

pybind11 **v3.1.0** headers (BSD-3-Clause, see `LICENSE`), vendored because the
build hosts for this migration have no PyPI access. Upstream:
<https://github.com/pybind/pybind11> (tag `v3.1.0`, directory `include/`).

Only `include/pybind11/**` is vendored — it is the complete compile-time
surface; pybind11 is header-only for module builds that wire CMake themselves
(`find_package(Python3 COMPONENTS Development.Module)` +
`Python3_add_library(... MODULE WITH_SOABI)`, see `libs/mapping_bind/CMakeLists.txt`).

To update: copy the new tag's `include/pybind11` over this directory and bump
the version note above and in `docs/development/cpp-conversion-swarm-20/ledgers/20-decisions.md` (D3).
