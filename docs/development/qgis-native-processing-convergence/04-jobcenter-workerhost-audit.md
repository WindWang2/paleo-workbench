# 04 — JobCenter / WorkerHost / UI execution audit

## JobCenter (apps/paleo_workbench_platform/job_center.*)

Composition root only: one `JobScheduler` (1+1 lanes) + `install_quit_drain(5000ms)` + `owners_` registry (append-only — grows monotonically per make_owner call) + shared `alive_` flag. `shutdown_workers(wait_ms)` sweeps owners. Task *display* lives in `ui_workstation::WorkstationTaskCenter` (QAbstractTableModel, 400ms polling `scheduler().statuses()`), wired in stage_flow_install.cpp:703-728, merged with `ui_shell::OperationRegistry` records via `task_projection.hpp`.

## JobOwner consumers (before) — 20 sites

Via JobCenter::make_owner: main_window ×3 (factor map :2594, seismic attr supervise :3478, SEG-Y import :3861), viz_a_install :122, viz_b_cross_well_dock :415/:730, viz_c_joint_host :133/:845, viz_e_install :303/:500, closure_preview_install :196, joint_analysis_install ×4 (:672/:909/:1084/:1132).
Private owners on `job::global_scheduler()`: ui_seqviz visualization_page/correlation_page/preview_controller/factor_panels. Private schedulers: ui_canvas ×2 (map_export_worker, native_raster_controller), ui_review ×4 dialogs.

## WorkerHost (closure_mapping_install.cpp:155-315)

File-local class: per-run `std::thread` + released flag + GUI delivery pump + bounded join w/ detach fallback. Consumers: factor-prepare worker (:1721), contour worker (:1980). `export_host` declared never used (dead). Shutdown chain: AppShell::shutdown_workers → PreparationPage::shutdown_workers.

## ui_workers

Qt-free worker cores taking `pwb::job::JobContext` (progress/cancel). No generic marshaling in-lib. 15+ kernel headers (contour_draft, correlation_load, dtw_propagation, factor_prepare, geological_modeling, integrity, viz_resolve, well_log_load, stratal, …).

## ui_controllers

`UiJobRunner` interface + `InlineJobRunner` (sync) + `JobOwnerRunner` (over JobOwner). WorkflowController is the only product-assembled controller (workflow_install.cpp:632-633, uses JobCenter scheduler).

## Shutdown order (before)

closeEvent: joint host shutdown(1000) → job_center_->shutdown_workers(400) → session close. ~MainWindow: same with 1000ms → app_shell_->shutdown_workers() (pages) → session. ~JobCenter: alive=false → owners shutdown(0) → scheduler shutdown(true,2.0). aboutToQuit → quit drain 5s.
