"""Provider-side output path containment (#1177).

File-writing providers must not blindly ``Path(...) + mkdir`` an
agent-supplied ``output_path``: the resolved destination has to stay inside
the workspace the execution context provides. This helper centralizes the
same containment + no-overwrite contract the harness uses
(``harness/actions/mapping.py::_resolve_export_path``) so provider and
handler paths cannot drift apart:

- the containment root is ``context.workspace_root`` (the harness passes the
  project workspace) falling back to ``context.work_dir`` (the execution's
  own scratch directory);
- absolute paths must resolve under that root, relative paths resolve
  against it — after ``resolve()``, so ``../`` traversal cannot escape;
- existing files are refused (no provider-side silent overwrite);
- a context with no root at all is an error: containment cannot be verified,
  so the write is refused rather than trusted.
"""
from __future__ import annotations

from pathlib import Path

from paleo_workbench.providers.base import ProviderContext
from paleo_workbench.providers.errors import ProviderExecutionError


def resolve_contained_output(
    context: ProviderContext, raw: str | Path, *, provider_id: str
) -> Path:
    """Resolve an output path and enforce workspace containment (#1177).

    Raises :class:`ProviderExecutionError` when the path escapes the
    workspace, would overwrite an existing file, or the context provides no
    workspace root to check against.
    """
    root_raw = getattr(context, "workspace_root", None) or getattr(context, "work_dir", None)
    if not root_raw:
        raise ProviderExecutionError(
            provider_id,
            ValueError(
                "no workspace_root/work_dir in the execution context; refusing "
                "to write an output path that cannot be containment-checked"
            ),
        )
    root = Path(str(root_raw)).expanduser().resolve()
    raw_path = Path(str(raw)).expanduser()
    resolved = (raw_path if raw_path.is_absolute() else root / raw_path).resolve()
    try:
        # Containment AFTER resolution: relative traversal ("../..") must not
        # escape the workspace either.
        resolved.relative_to(root)
    except ValueError:
        raise ProviderExecutionError(
            provider_id,
            PermissionError(
                f"output path {raw!r} resolves outside the execution workspace ({root})"
            ),
        ) from None
    if resolved.exists():
        raise ProviderExecutionError(
            provider_id,
            FileExistsError(f"refusing to overwrite existing file {resolved}"),
        )
    return resolved
