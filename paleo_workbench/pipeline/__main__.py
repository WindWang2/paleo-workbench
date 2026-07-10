from __future__ import annotations

import argparse
import sys
from pathlib import Path

from paleo_workbench.pipeline.assets import ensure_demo_prediction
from paleo_workbench.pipeline.bootstrap import bootstrap_sample_project, write_project
from paleo_workbench.pipeline.compile_map import compile_map_draft


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bootstrap a sample Paleo project from a data tree."
    )
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--name", default="惠西南样例工程")
    parser.add_argument("--region", default="惠西南")
    parser.add_argument(
        "--with-demo-tasks",
        action="store_true",
        help="Seed a demo prediction task bound to sample LAS/SEGY assets.",
    )
    parser.add_argument(
        "--with-map-draft",
        action="store_true",
        help="Compile a deterministic demo paleomap draft into the project.",
    )
    args = parser.parse_args(argv)

    try:
        result = bootstrap_sample_project(
            args.data_root,
            project_name=args.name,
            region=args.region,
            project_path=args.out,
        )
        # Order: bootstrap → demo tasks → map draft → write
        if args.with_demo_tasks:
            ensure_demo_prediction(result.document, seed=0)
        if args.with_map_draft:
            compile_map_draft(result.document, seed=0)
        path = write_project(result.document, args.out)
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return 2
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    except Exception as e:  # noqa: BLE001 — CLI boundary
        print(f"unexpected error: {e}", file=sys.stderr)
        return 1

    print(f"Wrote {path} with {result.stats.get('files', 0)} resources")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
