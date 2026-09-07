#!/usr/bin/env python
"""Goal V7 evidence driver: run the test suite file-by-file, surviving crashes.

Single-process full runs die on this machine (both checkouts — access
violations / a theme-test hang under ordering pollution). This driver runs
one pytest process per test file, records per-file exit codes, and retries
crashed files once in isolation so "pollution-dependent crash" vs
"deterministic crash" stays distinguishable. Output: JSON summary + readable
log next to it.

Usage: python scripts/run_suite_batched.py <repo_root> <out_prefix>
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path


def run_file(root: Path, rel: str, env: dict) -> tuple[int, str, float]:
    started = time.time()
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", rel, "-q", "--timeout=300",
         "-m", "not slow and not opengl", "-rf", "--tb=no"],
        cwd=str(root), env=env, capture_output=True, text=True,
    )
    return proc.returncode, proc.stdout[-4000:], time.time() - started


def main() -> int:
    root = Path(sys.argv[1]).resolve()
    out_prefix = Path(sys.argv[2]).resolve()
    log_path = Path(str(out_prefix) + ".log")
    json_path = Path(str(out_prefix) + ".json")

    test_dir = root / "tests"
    files = sorted(
        p.relative_to(root).as_posix()
        for p in test_dir.glob("test_*.py")
    )
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"

    results: dict[str, dict] = {}
    with open(log_path, "w", encoding="utf-8", newline="\n") as log:
        for index, rel in enumerate(files, 1):
            code, tail, seconds = run_file(root, rel, env)
            status = "pass" if code == 0 else "fail"
            if code < 0 or code >= 0xC0000000:  # hard crash (negative on posix, large on win via py)
                status = "crash"
            if code != 0:
                log.write(f"=== {rel} exit={code} ({status}) {seconds:.1f}s ===\n{tail}\n")
                log.flush()
            # Retry crashes once: deterministic vs pollution-dependent.
            retried = False
            if status == "crash":
                retried = True
                code2, tail2, seconds2 = run_file(root, rel, env)
                status = "pass" if code2 == 0 else ("crash" if code2 < 0 or code2 >= 0xC0000000 else "fail")
                log.write(f"--- retry {rel} exit={code2} ({status}) {seconds2:.1f}s ===\n{tail2}\n")
                log.flush()
            results[rel] = {"exit": code, "status": status, "retried": retried}
            json_path.write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
            if index % 20 == 0:
                log.write(f"[progress {index}/{len(files)}]\n")
                log.flush()
        counts: dict[str, int] = {}
        for entry in results.values():
            counts[entry["status"]] = counts.get(entry["status"], 0) + 1
        summary = {"files": len(files), **counts}
        log.write(f"SUMMARY {json.dumps(summary)}\n")
        json_path.write_text(
            json.dumps({"summary": summary, "files": results}, indent=1, ensure_ascii=False),
            encoding="utf-8",
        )
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
