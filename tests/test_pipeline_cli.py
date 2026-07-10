from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from paleo_workbench.project.manager import ProjectManager

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _cli_env() -> dict[str, str]:
    env = os.environ.copy()
    prev = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        str(_REPO_ROOT) if not prev else f"{_REPO_ROOT}{os.pathsep}{prev}"
    )
    return env


def test_cli_writes_loadable_project(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "井曲线").mkdir()
    (data / "井曲线" / "A1.Las").write_text("~Version\n", encoding="utf-8")
    out = tmp_path / "sample.paleo.json"

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "paleo_workbench.pipeline",
            "--data-root",
            str(data),
            "--out",
            str(out),
            "--name",
            "CLIDemo",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        env=_cli_env(),
    )
    assert proc.returncode == 0, proc.stderr
    assert out.exists()
    doc = ProjectManager(out).load()
    assert doc.meta.name == "CLIDemo"
    assert len(doc.resources) == 1


def test_cli_missing_data_root_exits_2(tmp_path: Path):
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "paleo_workbench.pipeline",
            "--data-root",
            str(tmp_path / "missing"),
            "--out",
            str(tmp_path / "x.paleo.json"),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=_cli_env(),
    )
    assert proc.returncode == 2


def test_cli_with_demo_tasks_seeds_prediction(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "井曲线").mkdir()
    (data / "井曲线" / "A1.Las").write_text("~Version\n", encoding="utf-8")
    out = tmp_path / "sample.paleo.json"

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "paleo_workbench.pipeline",
            "--data-root",
            str(data),
            "--out",
            str(out),
            "--name",
            "CLIDemo",
            "--with-demo-tasks",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        env=_cli_env(),
    )
    assert proc.returncode == 0, proc.stderr
    doc = ProjectManager(out).load()
    assert doc.prediction_tasks
    task = doc.prediction_tasks[-1]
    assert task.input_refs.get("well_log_resource_ids")
