from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QFileDialog, QMessageBox
from pydantic import ValidationError

from paleo_workbench.project.manager import ProjectManager
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.project.paths import (
    ProjectPathError,
    artifact_dir_for,
    rebase_owned_artifact_path,
)
from paleo_workbench.pipeline.assets import ensure_demo_prediction
from paleo_workbench.pipeline.bootstrap import (
    bootstrap_sample_project,
    resolve_sample_data_root,
)

_PROJECT_SUFFIX = ".paleo.json"
_PROJECT_FILTER = "Project (*.paleo.json)"
_SAVE_LOGGER = logging.getLogger("paleo_workbench.project_save")


def _default_project_start_dir(window) -> str:
    """打开/保存工程对话框的起始目录。

    优先当前工程所在目录；否则定位工作区布局下的 ``data/project_area``
    （仓库 ``main/`` 与 ``data/`` 同级）；都没有时回退用户主目录。
    """
    project_path = getattr(window, "project_path", None)
    if project_path:
        return str(Path(project_path).parent)
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "data" / "project_area"
        if candidate.is_dir():
            return str(candidate)
    return str(Path.home())


class _DomainMigrationBridge(QObject):
    """Marshals background domain-migration staging onto the GUI thread.

    The worker performs ONLY extraction (file parsing).  The live
    ProjectDocument is mutated exclusively inside the GUI-thread slot —
    review finding #12 (cross-thread document mutation).  The session
    generation travels with the payload so a queued callback from a replaced
    project can never mutate the new document.
    """

    migration_staged = Signal(str, int, object, object)  # path, generation, mapping, staged


class ProjectController:
    """Manages project lifecycle operations and file I/O for PaleoWorkbenchWindow."""

    def __init__(self, window) -> None:
        self.window = window
        self._last_open_error: str | None = None
        self._confirm_title: str | None = None
        self._confirm_message: str | None = None
        # Runtime-only session identity.  It never becomes project data; its
        # sole job is making project replacement an explicit lifecycle edge.
        self._session_generation = 0
        self._maintenance_thread: threading.Thread | None = None
        self._maintenance_cancel: threading.Event | None = None
        self._migration_bridge = _DomainMigrationBridge()
        self._migration_bridge.migration_staged.connect(
            self._on_domain_migration_staged
        )
        # One background save at a time (#1040): the OwnedWorkerJob executing
        # ProjectManager.execute_save while the GUI keeps serving input.
        self._save_job = None

    @property
    def session_generation(self) -> int:
        return self._session_generation

    def _end_current_session(self) -> bool:
        """Stop old-project work before its catalog/path can be replaced.

        A non-cooperative worker may be detached for safe process shutdown,
        but a normal project replacement must not close its catalog underneath
        it.  Callers abort the replacement and leave the current session live.
        Detached (timed-out) jobs are also part of the gate: they are no
        longer owned by any page, so ``shutdown_workers`` reports them as
        joined, yet their threads are still running — ending the session (or
        the application) while one of them is alive tears down QApplication on
        a running QThread (C18: "QThread: Destroyed while thread is still
        running", SIGABRT).  The session stays live until the keeper drains;
        the user closes again afterwards (documented UX).
        """
        self._session_generation += 1
        if self._maintenance_cancel is not None:
            self._maintenance_cancel.set()
        # An in-flight background save must finish (or refuse) before the
        # catalog underneath it closes (#1040).
        if not self._drain_save_job():
            self._session_generation += 1
            return False
        thread = self._maintenance_thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            # Signal cooperative cancellation and join with a short grace window
            thread.join(timeout=0.5)
            if thread.is_alive():
                self._session_generation += 1
                return False
        shell = getattr(self.window, "app_shell", None)
        shutdown = getattr(shell, "shutdown_workers", None)
        if callable(shutdown):
            try:
                if shutdown() is False:
                    self._session_generation += 1
                    return False
            except Exception:
                self._session_generation += 1
                return False
        try:
            from paleo_workbench.ui.thread_keeper import detached_job_keeper

            if detached_job_keeper().job_count() > 0:
                self._session_generation += 1
                return False
        except Exception:
            self._session_generation += 1
            return False
        self._close_catalog()
        try:
            from paleo_workbench.catalog import reset_catalog

            reset_catalog()
        except Exception:
            pass
        return True

    def shutdown_current_session(self) -> bool:
        """Public deterministic shutdown hook for the window/application."""
        return self._end_current_session()

    def _restore_current_shell_after_failed_stop(self) -> None:
        """Rebuild the unchanged project UI after a non-cooperative timeout.

        ``OwnedWorkerJob`` has already detached the timed-out job and severed
        its result connections.  Rebuilding the old shell restores a usable
        UI bound to the same document/catalog without allowing that worker to
        mutate a subsequently selected project.
        """

        refresh = getattr(self.window, "_refresh_shell", None)
        if callable(refresh):
            refresh(defer_nonvisible_bindings=True)

    def new_project(self, name: str = "Untitled Project") -> None:
        """Replace the in-memory project (no confirm — callers that need one ask first)."""
        if not self._end_current_session():
            self._restore_current_shell_after_failed_stop()
            self.window._show_project_error("切换工程失败", "当前工程仍有未停止的后台任务。")
            return
        self.window.project = ProjectDocument.new(name)
        self.window.project_path = None
        self.window._refresh_shell(defer_nonvisible_bindings=True)

    def open_project_path(self, path: str | Path) -> bool:
        """Load project from path (no confirm — UI handlers ask before calling)."""
        self._last_open_error = None
        target = Path(path)
        try:
            loaded = ProjectManager(target).load()
        except FileNotFoundError:
            self._last_open_error = f"文件不存在：\n{target}"
            return False
        except json.JSONDecodeError as e:
            self._last_open_error = f"工程文件 JSON 损坏：\n{target}\n{e}"
            return False
        except UnicodeDecodeError as e:
            # Non-UTF-8 project file (e.g. saved in a legacy encoding): a
            # ValueError sibling of JSONDecodeError that previously escaped
            # this handler and crashed the menu slot without any dialog.
            self._last_open_error = f"工程文件不是 UTF-8 编码，无法读取：\n{target}\n{e}"
            return False
        except ValidationError as e:
            self._last_open_error = f"工程文件格式无效：\n{target}\n{e}"
            return False
        except ProjectPathError as e:
            self._last_open_error = (
                f"工程内相对路径非法（疑似逃出工程目录）：\n{target}\n{e}"
            )
            return False
        except OSError as e:
            self._last_open_error = f"无法读取工程文件：\n{target}\n{e}"
            return False
        # The old shell may own native sessions/workers that still point at its
        # document/catalog.  Tear it down before publishing the new project.
        if not self._end_current_session():
            self._restore_current_shell_after_failed_stop()
            self._last_open_error = "当前工程仍有未停止的后台任务，无法安全切换。"
            return False
        self.window.project = loaded
        self.window.project.meta.project_root = str(target.resolve().parent)
        self.window.project_path = target
        catalog_error = self._open_catalog(target, loaded)
        if catalog_error is not None:
            # The project opened; the catalog is degraded, not fatal. The
            # _last_open_error channel is only DISPLAYED when open_project_path
            # returns False, so storing it alone kept this warning invisible
            # and the app silently ran with a dead catalog (audit A4).
            self._last_open_error = (
                f"目录元数据不可用：\n{target}\n{catalog_error}"
            )
            self.window._show_project_error(
                "目录元数据不可用",
                "工程已打开，但数据目录元数据不可用（分类 / 标签 / 溯源功能受限）。\n"
                f"{target}\n{catalog_error}",
            )
        self.window._refresh_shell(defer_nonvisible_bindings=True)
        self._schedule_catalog_maintenance(target, loaded)
        return True

    @staticmethod
    def _close_catalog() -> None:
        """Close the active catalog service's SQLite handle, if any.

        Called before replacing/resetting the catalog so the previous
        project's handle never leaks. Best-effort, never raises. Also drops
        the process-global session caches so a closed project's grids /
        graphs / plans do not linger in memory until LRU eviction (audit
        #848).
        """
        try:
            from paleo_workbench.catalog import get_catalog_service

            service = get_catalog_service()
            if service is not None:
                service.close()
        except Exception:
            pass
        try:
            from paleo_workbench.project.factor_grid_artifacts import (
                clear_session_caches,
            )
            from paleo_workbench.workflow.freshness import (
                clear_dependency_graph_cache,
            )
            from paleo_workbench.workflow.interpolation_fingerprint import (
                plan_cache_clear,
            )

            clear_session_caches()
            clear_dependency_graph_cache()
            plan_cache_clear()
        except Exception:
            pass

    @staticmethod
    def _open_catalog(target: Path, loaded: ProjectDocument) -> str | None:
        """Wire the Core Data Catalog for the opened project.

        Installs the Core-backed CatalogPort adapter as the active runtime
        backend (replacing any previous project's), then projects legacy
        ResourceItems into the catalog (deterministic, idempotent, no file
        copies or re-hashing). Best-effort: a catalog failure never blocks
        project open.
        """
        try:
            from paleo_workbench.catalog import (
                CoreCatalogAdapter,
                DataCatalogService,
                set_catalog,
            )

            ProjectController._close_catalog()
            service = DataCatalogService.open(
                target, ensure_index=False, sweep_temp=False
            )
            set_catalog(CoreCatalogAdapter(service))
            return None
        except Exception as error:
            # Never leave a closed/stale adapter from the previous project
            # installed after a recoverable catalog-open failure.
            try:
                from paleo_workbench.catalog import reset_catalog

                reset_catalog()
            except Exception:
                pass
            return f"{error.__class__.__name__}: {error}"

    def _schedule_catalog_maintenance(
        self, target: Path, loaded: ProjectDocument
    ) -> None:
        """Move optional catalog migration/index work past first usable UI.

        The authoritative project and canonical catalog have already opened.
        Legacy projection and the rebuildable SQLite index are deliberately
        deferred one event turn; identity checks make a queued callback from a
        replaced project a no-op.  The resource snapshot is taken HERE on the
        GUI thread so the worker never iterates a list the GUI may mutate.
        """
        generation = self._session_generation
        resources_snapshot = list(getattr(loaded, "resources", []) or [])

        def kickoff() -> None:
            if (
                generation != self._session_generation
                or self.window.project is not loaded
                or self.window.project_path != target
            ):
                return
            if self._maintenance_cancel is not None:
                self._maintenance_cancel.set()
            cancel_event = threading.Event()
            self._maintenance_cancel = cancel_event
            thread = threading.Thread(
                target=self._run_catalog_maintenance,
                args=(generation, target, loaded, resources_snapshot, cancel_event),
                name="catalog-maintenance",
                daemon=True,
            )
            self._maintenance_thread = thread
            thread.start()

        # The callback dereferences self.window, so the zero-delay timer must
        # not outlive the controller (#951 — late timer delivery into
        # destroyed Qt objects). Parenting it to the controller's migration
        # bridge (a QObject with the controller's own lifetime) also keeps the
        # timer alive until it fires; a bare local QTimer would be collected
        # before its 0ms timeout is ever delivered.
        kickoff_timer = QTimer(self._migration_bridge)
        kickoff_timer.setSingleShot(True)
        kickoff_timer.timeout.connect(kickoff)
        kickoff_timer.start(0)

    def _run_catalog_maintenance(
        self,
        generation: int,
        target: Path,
        loaded: ProjectDocument,
        resources_snapshot: list,
        cancel_event: threading.Event | None = None,
    ) -> None:
        if (
            generation != self._session_generation
            or (cancel_event is not None and cancel_event.is_set())
            or self.window.project is not loaded
            or self.window.project_path != target
        ):
            return
        service = None
        try:
            from paleo_workbench.catalog import get_catalog_service

            service = get_catalog_service()
        except Exception:
            service = None
        if (cancel_event is not None and cancel_event.is_set()) or generation != self._session_generation:
            return
        if service is not None:
            try:
                service.migrate_legacy_resources(resources_snapshot)
                service.sweep_temp_on_open()
                service.ensure_index_ready()
            except Exception:
                # Canonical project/catalog remain available even if an
                # optional acceleration rebuild cannot complete.
                pass
        if (cancel_event is not None and cancel_event.is_set()) or generation != self._session_generation:
            return
        # WorkArea domain staging (schema v1 → v2): heavy file parsing only —
        # NO document mutation on this thread.  Binding runs in the GUI slot.
        try:
            from paleo_workbench.catalog.domain_binding import stage_resources
            from paleo_workbench.project.domain_migration import build_asset_id_mapping
            from paleo_workbench.project.paths import resolve_project_path

            mapping = build_asset_id_mapping(service)

            def resolver(relative: str):
                raw = Path(relative)
                if raw.is_absolute():
                    return raw
                try:
                    return Path(resolve_project_path(relative, target))
                except Exception:
                    return raw

            staged = stage_resources(
                loaded,
                resources_snapshot,
                path_resolver=resolver,
                cancel_event=cancel_event,
            )
            if (cancel_event is not None and cancel_event.is_set()) or generation != self._session_generation:
                return
            if staged or mapping:
                self._migration_bridge.migration_staged.emit(
                    str(target), generation, mapping, staged
                )
        except Exception:
            # A migration failure must never break the open project.
            return

    def _on_domain_migration_staged(
        self, project_path: str, generation: int, mapping: dict, staged: object
    ) -> None:
        """GUI-thread binding pass after background extraction."""
        window = self.window
        if (
            generation != self._session_generation
            or window.project is None
            or window.project_path is None
            or str(window.project_path) != project_path
        ):
            return
        try:
            from paleo_workbench.project.domain_migration import (
                migrate_project_to_workarea,
            )

            report = migrate_project_to_workarea(
                window.project,
                asset_id_by_legacy=dict(mapping or {}),
                staged=staged,
            )
        except Exception:
            return
        changed = bool(getattr(report, "migrated", False)) or any(
            (getattr(report.binding, attr, 0) for attr in
             (
                 "wells_created",
                 "wells_updated",
                 "surveys_created",
                 "surveys_updated",
                 "links_created",
                 "links_updated",
             ))
        )
        if changed:
            shell = getattr(window, "app_shell", None)
            data_page = getattr(shell, "data_page", None)
            refresh = getattr(data_page, "refresh_domain_views", None)
            if callable(refresh):
                try:
                    refresh()
                except Exception:
                    pass

    def save_project(self) -> Path | None:
        """Blocking save facade (tests, programmatic flows, save-as fallback).

        The interactive Ctrl+S / menu path uses :meth:`save_project_async`
        (#1040); both share the same prepare → execute → commit phases.
        """
        if not self.window._flush_mapping_draft():
            self.window._show_project_error(
                "保存工程失败",
                "编图草稿未通过拓扑检查，工程文件未写入。请修复拓扑问题后重试。",
            )
            return None
        self._flush_joint_analysis_state()
        if self.window.project_path is not None:
            try:
                self.window.project.meta.project_root = str(
                    self.window.project_path.resolve().parent
                )
                ProjectManager(self.window.project_path).save(self.window.project)
                self._register_persisted_factor_grids(self.window.project_path)
            except (OSError, ValueError, TypeError, ValidationError) as e:
                self.window._show_project_error("保存工程失败", str(e))
                return None
            return self.window.project_path
        # No path yet: ask the user via the save dialog, then save to that path.
        chosen = self.window._choose_save_project()
        return self.save_project_as(chosen)

    def save_project_async(self) -> bool:
        """Interactive save: run the heavy I/O phase on a worker thread (#1040).

        ``prepare_save`` (document diff + detached payload build) and the
        post-write commit stay on the GUI thread because they touch the live
        ``ProjectDocument``; only ``execute_save`` (serialize + write + fsync)
        moves off-thread. Returns ``False`` when a save is already in flight,
        the mapping draft rejects the save, or preparation fails.
        """
        if self.save_job_running():
            _SAVE_LOGGER.info("保存已在进行中，忽略重复的保存请求")
            return False
        if not self.window._flush_mapping_draft():
            self.window._show_project_error(
                "保存工程失败",
                "编图草稿未通过拓扑检查，工程文件未写入。请修复拓扑问题后重试。",
            )
            return False
        self._flush_joint_analysis_state()
        path = self.window.project_path
        if path is None:
            # Save-as relocates artifacts and rebinds the catalog; keep it on
            # the synchronous path until that flow is split too.
            chosen = self.window._choose_save_project()
            return self.save_project_as(chosen) is not None
        try:
            self.window.project.meta.project_root = str(Path(path).resolve().parent)
            manager = ProjectManager(path)
            prepared = manager.prepare_save(self.window.project)
        except (OSError, ValueError, TypeError, ValidationError) as e:
            self.window._show_project_error("保存工程失败", str(e))
            return False
        if prepared is None:
            _SAVE_LOGGER.info("工程无变更，无需保存")
            return True

        from paleo_workbench.ui.owned_worker_job import OwnedWorkerJob
        from paleo_workbench.ui.project_save_worker import ProjectSaveTask

        generation = self._session_generation
        task = ProjectSaveTask(manager, prepared)
        job = OwnedWorkerJob()
        job.start(
            task,
            terminal_signals=(task.terminal,),
            result_connections=(
                (
                    task.saved,
                    lambda stats, _manager=manager, _prepared=prepared, _gen=generation:
                        self._finish_async_save(_manager, _prepared, stats, _gen),
                ),
                (task.failed, self._on_async_save_failed),
            ),
        )
        self._save_job = job
        _SAVE_LOGGER.info("工程保存已在后台线程启动: %s", path)
        return True

    def save_job_running(self) -> bool:
        job = self._save_job
        return job is not None and job.is_running

    def _finish_async_save(self, manager, prepared, stats, generation: int) -> None:
        """GUI-thread completion slot: commit snapshot + register artifacts."""
        if generation != self._session_generation:
            # The project was switched/replaced mid-save. The file write for
            # the old path already completed; committing the persistence
            # snapshot onto the NEW live document would corrupt its dirty
            # tracking, so drop the commit and let the next save re-diff.
            _SAVE_LOGGER.warning(
                "后台保存完成时会话已切换，丢弃提交: %s", manager.project_path
            )
            return
        try:
            manager.commit_save(self.window.project, prepared, stats)
            self._register_persisted_factor_grids(Path(manager.project_path))
        except (OSError, ValueError, TypeError, ValidationError) as e:
            self.window._show_project_error("保存工程失败", str(e))
            return
        _SAVE_LOGGER.info("工程已保存: %s", manager.project_path)

    def _on_async_save_failed(self, message: str) -> None:
        self.window._show_project_error("保存工程失败", message)

    def _drain_save_job(self, wait_ms: int = 2_000) -> bool:
        """Join an in-flight background save; False when it refuses to stop."""
        job = self._save_job
        if job is None or not job.is_running:
            self._save_job = None
            return True
        joined = job.shutdown(wait_ms)
        self._save_job = None
        return joined

    def save_project_as(self, path: str | Path | None) -> Path | None:
        if path is None:
            return None
        if not self.window._flush_mapping_draft():
            self.window._show_project_error(
                "保存工程失败",
                "编图草稿未通过拓扑检查，工程文件未写入。请修复拓扑问题后重试。",
            )
            return None
        self._flush_joint_analysis_state()
        target = self._normalize_project_path(Path(path))
        old_path = self.window.project_path
        old_root = self.window.project.meta.project_root
        relocation = None
        # A timed-out worker remains attached to the current project/catalog.
        # Do not enter the rollback path below: it rebases runtime paths and
        # refreshes the shell, both of which would disturb that live session.
        if old_path is not None and old_path != target and not self._end_current_session():
            self._restore_current_shell_after_failed_stop()
            self.window._show_project_error(
                "另存为失败", "当前工程仍有未停止的后台任务，无法安全另存为。"
            )
            return None
        try:
            # Re-home <old>.artifacts/ BEFORE writing the project file (whose
            # layout creation would otherwise pre-create the target artifacts
            # dir and defeat the move): payloads + catalog travel with the
            # project — no orphan-on-save-as, no forced re-import.  Close the
            # old SQLite handle first (important on Windows) and fail closed if
            # relocation cannot complete; otherwise a new JSON could claim
            # artifact paths that were never moved.
            if old_path is not None and old_path != target:
                from paleo_workbench.project.paths import stage_artifact_relocation
                from paleo_workbench.project.paths import artifact_dir_for

                if artifact_dir_for(target).exists():
                    raise OSError(
                        "Save As 目标已存在工程成果目录；为避免混合两个工程的数据，"
                        "请选择空目标路径。"
                    )

                relocation = stage_artifact_relocation(old_path, target)
                self._rebase_factor_grid_artifact_paths(old_path, target)
                self._rebase_interpretation_artifact_paths(old_path, target)
                # The copied catalog belongs to the target before its project
                # JSON lands.  Rebase it now so an interruption after JSON
                # replacement can never leave a valid target project pointing
                # at the old artifact-directory name.
                self._rebase_staged_catalog_artifact_paths(target)
            self.window.project.meta.project_root = str(target.resolve().parent)
            ProjectManager(target).save(self.window.project)
        except Exception as e:
            if relocation is not None:
                relocation.rollback()
            if old_path is not None and old_path != target:
                self._rebase_factor_grid_artifact_paths(target, old_path)
                self._rebase_interpretation_artifact_paths(target, old_path)
                self.window.project.meta.project_root = old_root
                self.window.project_path = old_path
                self._open_catalog(old_path, self.window.project)
                refresh = getattr(self.window, "_refresh_shell", None)
                if callable(refresh):
                    refresh()
            self.window._show_project_error("保存工程失败", str(e))
            return None
        self.window.project_path = target
        # The catalog is bound to the project path: rebind to the new location
        # (best-effort — a catalog failure never blocks saving).
        self._open_catalog(target, self.window.project)
        refresh = getattr(self.window, "_refresh_shell", None)
        if old_path is not None and old_path != target and callable(refresh):
            # ``_end_current_session`` deliberately released the old shell's
            # native/worker state before moving its artifacts. Rebuild a fresh
            # shell only after the new path and catalog are authoritative.
            refresh()
        self._schedule_catalog_maintenance(target, self.window.project)
        self._register_persisted_factor_grids(target)
        if relocation is not None:
            try:
                relocation.commit()
            except OSError as error:
                self.window._show_project_error(
                    "另存为后清理失败",
                    f"新工程已保存，但旧成果目录未能清理：{error}",
                )
        return target

    @staticmethod
    def _rebase_staged_catalog_artifact_paths(target: Path) -> None:
        """Commit target-catalog path rebasing before target JSON publication."""

        try:
            from paleo_workbench.catalog.service import DataCatalogService

            service = DataCatalogService.open(
                target, ensure_index=False, sweep_temp=False
            )
            try:
                service.rebase_artifact_paths()
            finally:
                service.close()
        except Exception:
            # The caller's staged artifact rollback removes target-only data;
            # re-raise so target metadata is never published with stale links.
            raise

    def _register_persisted_factor_grids(self, project_path: Path) -> None:
        """Attach newly persisted grid artifacts to the active project catalog."""
        try:
            from paleo_workbench.catalog.lifecycle import register_persisted_factor_grids

            if register_persisted_factor_grids(self.window.project):
                # Store returned version ids/managed paths in the portable project file.
                ProjectManager(project_path).save(self.window.project)
        except Exception:
            # Catalog provenance is best-effort; the already-written project artifact
            # remains usable and can be registered on a later save. Log it so a
            # repeated failure (and the follow-up duplicate registration it can
            # cause) is visible instead of silent (H14).
            import logging

            logging.getLogger(__name__).warning(
                "register_persisted_factor_grids failed; will retry on next save",
                exc_info=True,
            )

    def _rebase_factor_grid_artifact_paths(
        self, old_project_path: Path, new_project_path: Path
    ) -> None:
        """Keep runtime artifact paths aligned after a successful save-as relocation."""
        old_root = artifact_dir_for(old_project_path).resolve()
        new_root = artifact_dir_for(new_project_path).resolve()
        old_dir = Path(old_project_path).expanduser().resolve().parent
        for task in self.window.project.factor_map_tasks:
            raw = task.grid_artifact_path
            if not raw:
                continue
            rebased = rebase_owned_artifact_path(
                raw, old_root=old_root, new_root=new_root, project_dir=old_dir
            )
            if rebased is not None:
                task.grid_artifact_path = rebased

    def _rebase_interpretation_artifact_paths(
        self, old_project_path: Path, new_project_path: Path
    ) -> None:
        """Rebase horizon / correlation / fault payloads owned by the moved tree."""

        old_root = artifact_dir_for(old_project_path).resolve()
        new_root = artifact_dir_for(new_project_path).resolve()
        old_dir = Path(old_project_path).expanduser().resolve().parent
        refs = (
            list(self.window.project.horizon_interpretations)
            + list(self.window.project.correlation_interpretations)
            + list(self.window.project.fault_interpretations)
        )
        for interpretation in refs:
            raw = getattr(interpretation, "artifact_path", None)
            if not raw:
                continue
            rebased = rebase_owned_artifact_path(
                raw, old_root=old_root, new_root=new_root, project_dir=old_dir
            )
            if rebased is not None:
                interpretation.artifact_path = rebased

    def _flush_joint_analysis_state(self) -> None:
        """Persist joint presentation from 井震联合 page before project write.

        Only flush when the hybrid joint UI has actually been loaded/shown
        (``_joint_loaded_once``). Otherwise a pristine page defaults to Time
        and would clobber a previously saved Depth/fence/tree state when the
        user saves from another page without revisiting 井震联合.
        """
        shell = getattr(self.window, "app_shell", None)
        page = getattr(shell, "geomodel_page", None) if shell is not None else None
        if page is not None and hasattr(page, "save_joint_analysis_to_project"):
            if not getattr(page, "_joint_loaded_once", False):
                return
            try:
                # Keep page project pointer aligned with window project
                if hasattr(page, "set_project"):
                    page.set_project(self.window.project)
                page.save_joint_analysis_to_project()
            except Exception:
                pass

    def open_sample_project(self, data_root: Path | None = None) -> bool:
        """Bootstrap sample data into the current window (no auto-save)."""
        if not self.window._confirm_replace_project():
            return False
        # The sample project is unsaved/in-memory → no catalog. Reset BEFORE
        # bootstrapping so sample imports never write into the previous
        # project's catalog (cross-project pollution).
        if not self._end_current_session():
            self._restore_current_shell_after_failed_stop()
            self.window._show_project_error("打开样例工程失败", "当前工程仍有未停止的后台任务。")
            return False
        try:
            root = resolve_sample_data_root(data_root)
            result = bootstrap_sample_project(root)
        except (FileNotFoundError, ValueError, OSError) as e:
            self.window._show_project_error("打开样例工程失败", str(e))
            return False
        self.window.project = result.document
        ensure_demo_prediction(self.window.project, seed=0)
        self.window.project_path = None
        self.window._refresh_shell()
        return True

    def _confirm_replace_project(self) -> bool:
        """Ask the user before discarding the current in-memory project.

        Zero-arg signature is intentional so tests can monkeypatch with
        ``lambda: True`` / ``lambda: False``.
        """
        title = (
            getattr(self.window, "_confirm_title", None)
            or self._confirm_title
            or "替换工程"
        )
        message = (
            getattr(self.window, "_confirm_message", None)
            or self._confirm_message
            or "将替换当前工程（未保存更改会丢失）。是否继续？"
        )
        reply = QMessageBox.question(
            self.window,
            title,
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    def create_project_from_document(self, doc, intermediate_dir) -> bool:
        """向导产出文档 → 落盘 <intermediate_dir>/<工程名>.paleo.json → 成为当前工程。"""
        if not self._end_current_session():
            self._restore_current_shell_after_failed_stop()
            self.window._show_project_error("切换工程失败", "当前工程仍有未停止的后台任务。")
            return False
        target = Path(intermediate_dir) / f"{doc.meta.name}{_PROJECT_SUFFIX}"
        # Normalize suffix without double-appending
        target = self._normalize_project_path(target)
        if target.exists():
            self.window._show_project_error("新建工程失败", f"目标已存在：\n{target}")
            return False
        try:
            ProjectManager(target).save(doc)
        except Exception as e:
            self.window._show_project_error("新建工程失败", str(e))
            return False
        self.window.project = doc
        self.window.project_path = target
        catalog_error = None
        try:
            catalog_error = self._open_catalog(target, doc)
        except Exception as e:
            catalog_error = f"{e.__class__.__name__}: {e}"
        if catalog_error is not None:
            self.window._show_project_error(
                "目录元数据不可用",
                "工程已创建，但数据目录元数据不可用（分类 / 标签 / 溯源功能受限）。\n"
                f"{target}\n{catalog_error}",
            )
        refresh = getattr(self.window, "_refresh_shell", None)
        if callable(refresh):
            refresh(defer_nonvisible_bindings=True)
        try:
            self._schedule_catalog_maintenance(target, doc)
        except Exception:
            pass
        return True

    def _on_new_project(self) -> None:
        from paleo_workbench.ui.pages.new_project_wizard import NewProjectWizardDialog

        dlg = NewProjectWizardDialog(self.window)
        if dlg.exec() and dlg.result_document is not None:
            self.create_project_from_document(dlg.result_document, dlg.intermediate_dir)

    def _on_open_project(self) -> None:
        path = self.window._choose_open_project()
        if path is None:
            return
        self.window._confirm_title = "打开工程"
        self.window._confirm_message = (
            "将打开所选工程并替换当前内容（未保存更改会丢失）。是否继续？"
        )
        if not self.window._confirm_replace_project():
            return
        if not self.open_project_path(path):
            detail = self._last_open_error or f"无法打开工程文件：\n{path}"
            self.window._show_project_error("打开工程失败", detail)

    def _on_open_sample_project(self) -> None:
        self.window._confirm_title = "打开样例工程"
        self.window._confirm_message = (
            "将用样例数据替换当前工程（未保存更改会丢失）。是否继续？"
        )
        self.open_sample_project()

    def _on_save_project(self) -> None:
        # Menu/shortcut entry: keep the GUI responsive during the I/O phase.
        self.save_project_async()

    def _on_properties(self) -> None:
        self.window._show_properties()

    def _choose_open_project(self) -> Path | None:
        path, _ = QFileDialog.getOpenFileName(
            self.window, "打开工程", _default_project_start_dir(self.window), _PROJECT_FILTER
        )
        return Path(path) if path else None

    def _choose_save_project(self) -> Path | None:
        suggested = f"{self.window.project.meta.name}{_PROJECT_SUFFIX}"
        start_dir = _default_project_start_dir(self.window)
        path, _ = QFileDialog.getSaveFileName(
            self.window, "保存工程", str(Path(start_dir) / suggested), _PROJECT_FILTER
        )
        return Path(path) if path else None

    def _show_project_error(self, title: str, message: str) -> None:
        QMessageBox.critical(self.window, title, message)

    def project_properties_text(self) -> str:
        """Build the read-only summary shown by the properties dialog."""
        project = self.window.project
        path_str = (
            str(self.window.project_path)
            if self.window.project_path is not None
            else "未保存"
        )
        return "\n".join(
            [
                f"工程名称: {project.meta.name}",
                f"区域: {project.meta.region or '—'}",
                f"工程文件: {path_str}",
                f"资源数量: {len(project.resources)}",
                f"导出图件: {len(project.export_artifacts)}",
                f"显示坐标系: {project.coordinate.display_crs}",
                f"版本: {project.meta.version}",
            ]
        )

    def _show_properties(self) -> None:
        QMessageBox.information(
            self.window, "工程属性", self.project_properties_text()
        )

    @staticmethod
    def _normalize_project_path(path: Path) -> Path:
        """Ensure the filename ends with ``.paleo.json`` without double-appending.

        - "p"            -> "p.paleo.json"
        - "p.json"       -> "p.paleo.json"
        - "p.paleo.json" -> "p.paleo.json" (unchanged)
        """
        if path.name.endswith(_PROJECT_SUFFIX):
            return path
        stem = (
            path.name[: -len(".json")] if path.name.endswith(".json") else path.name
        )
        return path.with_name(stem + _PROJECT_SUFFIX)
