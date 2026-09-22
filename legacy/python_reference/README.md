# legacy/python_reference — retired Python implementation (reference only)

This directory contains retired Python implementations preserved only for
historical, semantic-reference, migration, and oracle purposes.

**The production Paleo Workbench application is implemented in C++**
(the `pwb-platform` executable built from `apps/` + `libs/`). Nothing under
this directory is part of the product.

Files under this directory MUST NOT be:

- imported by the production application;
- packaged into the native product;
- installed as runtime resources;
- used as runtime fallbacks;
- launched through subprocess/QProcess;
- treated as an alternative supported product implementation.

## 中文说明

本目录存放**已退役的 Python 实现**，仅用于历史参考、语义对照、迁移
取证与 oracle 基准生成。

**Paleo Workbench 的正式产品实现是 C++**（由 `apps/` + `libs/` 构建的
`pwb-platform` 可执行程序）。本目录内容与产品运行时无关。

禁止将本目录内容：

- 供正式应用 import；
- 打包进原生产品；
- 作为运行时资源安装；
- 作为运行时 fallback；
- 通过 subprocess/QProcess 启动；
- 视为另一种受支持的产品实现。

## Layout

```text
product/    retired Python product implementation, launchers, benchmarks,
            examples — repo-relative paths preserved verbatim
tests/      the retired implementation's pytest suite (structure preserved)
scratch/    scratch / one-off development files
metadata/retirement_manifest.json — per-file record: classification,
            native replacement (verbatim from the migration matrix; never
            fabricated), baseline SHA, retirement date
```

## Why files still live here (not deleted)

Retirement is archival, not destruction: `git mv` preserved every file's
history. Development-time oracle/fixture generators under `tools/oracle`
and `tests/cpp/**` import the archived reference through an explicit path
shim (`tools/oracle/_legacy_reference.py`) so parity fixture generation
keeps working. That shim is the ONLY sanctioned way active tooling reaches
this tree; CTest consumes frozen fixtures and never runs Python.

## Runtime assets

Product-owned runtime assets that used to live inside the Python package
(`facies_taxonomy.json`, `facies_adjacency.json`, `ui/assets/icons/**`)
now live in the repository's `resources/` tree and are installed from
there. The copies inside this archive are inert duplicates kept so the
retired implementation remains importable as a reference.

Retired at: 2026-09-22 · Base: `0936779e` (stacked on PR #1473,
"C++ 100% final closure"). See `docs/development/python-retirement/` for
the full retirement ledger.
