from __future__ import annotations

import argparse
import sys
from pathlib import Path

from paleo_workbench.pipeline.bootstrap import bootstrap_sample_project, write_project


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bootstrap a sample Paleo project from a data tree."
    )
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--name", default="惠西南样例工程")
    parser.add_argument("--region", default="惠西南")
    args = parser.parse_args(argv)

    try:
        result = bootstrap_sample_project(
            args.data_root,
            project_name=args.name,
            region=args.region,
            project_path=args.out,
        )
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
