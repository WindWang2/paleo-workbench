#include <pwb/ui_seqviz/qt/visualization_page.hpp>

#include <QApplication>
#include <QCloseEvent>
#include <QComboBox>
#include <QEvent>
#include <QFileDialog>
#include <QHBoxLayout>
#include <QLabel>
#include <QPushButton>
#include <QSizePolicy>
#include <QSplitter>
#include <QTimer>
#include <QVBoxLayout>

#include <filesystem>

#include <pwb/job_runtime/job_scheduler.hpp>
#include <pwb/ui_seqviz/page_tokens.hpp>
#include <pwb/ui_seqviz/qt/panel_float_button.hpp>
#include <pwb/ui_seqviz/qt/preview_controller.hpp>
#include <pwb/ui_seqviz/qt/viz_panels.hpp>
#include <pwb/ui_shell/dock_manager.hpp>
#include <pwb/ui_shell/float_controller.hpp>
#include <pwb/ui_shell/layout_persistence.hpp>

namespace pwb::ui_seqviz::qt {

namespace {

namespace fs = std::filesystem;

// _DOCKED_SIZES_DELAY_MS — splitter-drag persistence debounce.
constexpr int kDockedSizesDelayMs = 400;

// Safe file stem — [alnum-_] else '_', capped at 64 chars (Python
// `safe = "".join(...)[:64]` verbatim).
std::string safe_stem(const std::string& stem) {
    std::string out;
    out.reserve(stem.size());
    for (const char ch : stem) {
        const bool alnum = (ch >= '0' && ch <= '9') ||
                           (ch >= 'a' && ch <= 'z') ||
                           (ch >= 'A' && ch <= 'Z');
        out.push_back(alnum || ch == '-' || ch == '_' ? ch : '_');
        if (out.size() >= 64) {
            break;
        }
    }
    return out;
}

}  // namespace

VisualizationPage::VisualizationPage(
    QWidget* parent, ui_data_core::PreviewProvider preview_provider,
    ui_shell::LayoutPersistence* persistence)
    : QWidget(parent), persistence_(persistence) {
    setObjectName("VisualizationPage");
    setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Expanding);
    setMinimumSize(100, 100);

    preview_controller_ = new PreviewRequestController(
        std::move(preview_provider), this,
        ui_data_core::PreviewRequestKind::Visualization);
    connect(preview_controller_, &PreviewRequestController::loading, this,
            &VisualizationPage::show_preview_loading);
    connect(preview_controller_, &PreviewRequestController::result_ready,
            this, &VisualizationPage::apply_preview_result);
    connect(preview_controller_, &PreviewRequestController::failed, this,
            [this](const QString& message) { show_preview_error(message); });

    well_log_job_ = new job::qtbridge::JobOwner(this);
    connect(well_log_job_, &job::qtbridge::JobOwner::released, this,
            &VisualizationPage::on_well_log_job_released);
    export_job_ = new job::qtbridge::JobOwner(this);
    connect(export_job_, &job::qtbridge::JobOwner::released, this, [this] {
        if (export_busy_) {
            end_export_busy();
        }
    });

    auto* outer = new QVBoxLayout(this);
    const int margin = tokens::PAGE_MARGIN;
    outer->setContentsMargins(margin, margin, margin, margin);
    outer->setSpacing(tokens::SPACE_4);

    banner_ = new QLabel(
        QStringLiteral(
            "临时页面 —— 用于验证可视化能力，正式版将并入数据 / 井 / 地震 "
            "/ 编图各页"),
        this);
    banner_->setObjectName("TemporaryPageBanner");
    outer->addWidget(banner_);

    auto* top_bar = new QHBoxLayout();
    top_bar->setSpacing(tokens::SPACE_2);
    auto* asset_label = new QLabel("▤ 选择数据资产:", this);
    top_bar->addWidget(asset_label);
    asset_combo_ = new QComboBox(this);
    asset_combo_->setMinimumWidth(280);
    connect(asset_combo_, &QComboBox::currentIndexChanged, this,
            &VisualizationPage::on_asset_combo_changed);
    top_bar->addWidget(asset_combo_);
    coord_btn_ = new QPushButton("◆ 网格(IL/XL)", this);
    coord_btn_->setCheckable(true);
    connect(coord_btn_, &QPushButton::clicked, this,
            &VisualizationPage::on_coord_toggle);
    top_bar->addWidget(coord_btn_);
    top_bar->addStretch();
    outer->addLayout(top_bar);

    splitter_ = new QSplitter(Qt::Horizontal, this);
    splitter_->setObjectName("VisualizationSplitter");

    summary_ = new VisualizationSummaryPanel(this);
    summary_->setHidden(true);

    composite_ = new VisualizationWorkspace(this);
    splitter_->addWidget(composite_);

    trace_ = new VisualizationTracePanel(this);
    trace_->setMaximumWidth(16'777'215);  // QWIDGETSIZE_MAX parity
    splitter_->addWidget(trace_);

    splitter_->setStretchFactor(0, 1);
    splitter_->setStretchFactor(1, 0);
    splitter_->setSizes({1000, 260});
    outer->addWidget(splitter_, 1);

    // M6: the trace list floats; the composite center is never registered.
    float_controller_ = std::make_unique<ui_shell::FloatController>(
        [this](const std::string& key) -> QWidget* {
            for (const auto& [k, w] : floatable_) {
                if (k == key) {
                    return w;
                }
            }
            return nullptr;
        },
        persistence_, nullptr, this);
    make_floatable("visualization:trace", trace_, "追踪记录");

    auto* sizes_timer = new QTimer(this);
    sizes_timer->setSingleShot(true);
    sizes_timer->setInterval(kDockedSizesDelayMs);
    connect(sizes_timer, &QTimer::timeout, this,
            &VisualizationPage::persist_docked_sizes);
    connect(splitter_, &QSplitter::splitterMoved, this,
            [sizes_timer](int, int) { sizes_timer->start(); });
    for (const auto& [key, panel] : floatable_) {
        float_controller_->restore_saved(key, panel);
    }

    connect(summary_, &VisualizationSummaryPanel::asset_selected, this,
            &VisualizationPage::open_ref);
    connect(trace_, &VisualizationTracePanel::refresh_requested, this,
            &VisualizationPage::reload_current);
    connect(trace_, &VisualizationTracePanel::export_requested, this,
            &VisualizationPage::export_current_view);
    connect(composite_->tabs(), &QTabWidget::currentChanged, this,
            [this](int) { sync_export_capabilities(); });
    sync_export_capabilities();

    QWidget::setTabOrder(asset_combo_, coord_btn_);
    QWidget::setTabOrder(coord_btn_, trace_->refresh_btn());
}

VisualizationPage::~VisualizationPage() { shutdown_workers(); }

void VisualizationPage::set_seams(VizPageSeams seams) {
    seams_ = std::move(seams);
    composite_->set_seams(seams_.workspace);
}

void VisualizationPage::set_preview_provider(
    ui_data_core::PreviewProvider provider) {
    if (preview_controller_ != nullptr) {
        preview_controller_->set_provider(std::move(provider));
    }
}

void VisualizationPage::set_project_path(const std::string& path) {
    project_path_ = path;
}

void VisualizationPage::update_state(const VizPageProjectSlice& project) {
    project_ = project;

    const std::string crs = project.comparison_crs;
    preview_controller_->set_comparison_crs(
        crs.empty() ? std::nullopt : std::optional<std::string>(crs));
    const std::string root = project.project_root;
    preview_controller_->set_project_root(
        !root.empty() && root != "."
            ? std::optional<std::string>(root)
            : std::nullopt);

    // Stage-12: bind the live project into the well-log host so
    // correlation tops overlay the main visualization well-log tab.
    composite_->set_project(project.raw, project_path_);

    summary_->update_state(project.resources, project.prediction_tasks,
                           project.map_documents);
    trace_->update_state(project.prediction_tasks, project.map_documents);

    // Signature-gated asset combo refill (V6 Phase 5 parity).
    combo_entries_ = asset_combo_entries(project.resources,
                                         project.map_documents);
    const VizRefSignature signature = combo_signature(combo_entries_);
    if (signature != combo_signature_) {
        asset_combo_->blockSignals(true);
        asset_combo_->clear();
        for (std::size_t i = 0; i < combo_entries_.size(); ++i) {
            asset_combo_->addItem(
                QString::fromStdString(combo_entries_[i].label),
                static_cast<int>(i));
        }
        asset_combo_->blockSignals(false);
        combo_signature_ = signature;
    }

    composite_->update_state(project.prediction_tasks);

    if (!current_ref_.has_value()) {
        // File probes cached per source revision (V6 parity).
        if (probe_signature_ == signature) {
            if (probe_first_ref_.has_value()) {
                open_ref(*probe_first_ref_);
            }
        } else {
            std::optional<VizRefSlice> first;
            for (std::size_t i = 0; i < combo_entries_.size(); ++i) {
                const VizRefSlice& ref = combo_entries_[i].ref;
                if (ref.kind == "well_log" && !ref.path.empty() &&
                    ref_path_is_file(ref.path)) {
                    asset_combo_->blockSignals(true);
                    asset_combo_->setCurrentIndex(static_cast<int>(i));
                    asset_combo_->blockSignals(false);
                    first = ref;
                    break;
                }
            }
            probe_signature_ = signature;
            probe_first_ref_ = first;
            if (first.has_value()) {
                open_ref(*first);
            }
        }
    } else {
        open_ref(*current_ref_);
    }
}

void VisualizationPage::on_asset_combo_changed(int index) {
    if (index < 0) {
        return;
    }
    const int entry = asset_combo_->itemData(index).toInt();
    if (entry >= 0 &&
        static_cast<std::size_t>(entry) < combo_entries_.size()) {
        open_ref(combo_entries_[static_cast<std::size_t>(entry)].ref);
    }
}

void VisualizationPage::open_ref(const VizRefSlice& ref) {
    current_ref_ = ref;
    // Sync the combo selection (same logical ref, instance-tolerant).
    for (int i = 0; i < asset_combo_->count(); ++i) {
        const int entry = asset_combo_->itemData(i).toInt();
        if (entry >= 0 &&
            static_cast<std::size_t>(entry) < combo_entries_.size() &&
            refs_match(combo_entries_[static_cast<std::size_t>(entry)].ref,
                       ref)) {
            asset_combo_->blockSignals(true);
            asset_combo_->setCurrentIndex(i);
            asset_combo_->blockSignals(false);
            break;
        }
    }

    if (ref.kind == "engine_preview") {
        const auto resource = engine_preview_resource(ref, project_);
        if (!resource.has_value()) {
            show_preview_error(QStringLiteral("未找到对应的数据资产"));
            return;
        }
        trace_->update_ref(&ref, nullptr);
        const ui_data_core::AssetObjectData asset = *resource;
        preview_controller_->request(&asset);
        return;
    }

    preview_controller_->invalidate();
    if (ref.kind == "well_log") {
        open_well_log(ref);
        return;
    }
    const UiVizPayload payload =
        resolve_page_payload(ref, project_, seams_.resolve);
    composite_->load_payload(payload);
    trace_->update_ref(&ref, &payload);
    sync_export_capabilities();
}

void VisualizationPage::open_well_log(const VizRefSlice& ref) {
    const std::string path =
        ref.path.empty() ? std::string{}
                         : absolute_ref_path(ref.path, project_);
    const bool cached = seams_.well_log_cached_fn &&
                        seams_.well_log_cached_fn(path);
    if (!path.empty() && cached) {
        if (well_log_job_->is_running()) {
            // worker.cancel() parity: the cooperative event AND the job
            // token (the parse-in-flight case checks both).
            ui_workers::request_well_log_cancel(well_log_phase_, {});
            well_log_job_->cancel();
        }
        UiVizPayload payload;
        try {
            payload =
                resolve_page_payload(ref, project_, seams_.resolve);
        } catch (const std::exception& exc) {
            on_well_log_failed(ref, exc.what());
            return;
        }
        apply_well_log_payload(ref, payload);
        return;
    }

    if (well_log_job_->is_running()) {
        // Latest-wins: an in-flight cold load cannot restart in place;
        // cancel and re-open once the job releases (#842 parity).
        pending_well_log_ref_ = ref;
        ui_workers::request_well_log_cancel(well_log_phase_, {});
        well_log_job_->cancel();
        return;
    }

    load_seq_ += 1;
    const long long seq = load_seq_;
    const std::string label =
        !ref.label.empty() ? ref.label
                           : (!ref.id.empty() ? ref.id : "井数据");
    composite_->status_label()->setText(
        QString::fromStdString("正在加载: " + label));

    well_log_phase_ = std::make_shared<ui_workers::WellLogLoadPhase>();
    ui_workers::WellLogLoadInput input;
    input.ref = ref;
    input.resources = resource_slices(project_.resources);
    input.project_root = project_.project_root;
    input.load_fn = seams_.resolve.load_fn;
    input.phase = well_log_phase_;

    job::JobSpec spec = ui_workers::make_well_log_load_job_spec(
        std::move(input));
    well_log_job_->start(
        job::global_scheduler(), std::move(spec),
        [this, ref, seq](const job::qtbridge::JobOutcome& outcome) {
            switch (outcome.state) {
            case job::JobState::done:
            case job::JobState::degraded: {
                const auto* result =
                    std::any_cast<ui_workers::WellLogLoadResult>(
                        &outcome.result);
                if (result != nullptr) {
                    on_well_log_resolved(ref, result->payload, seq);
                }
                return;
            }
            case job::JobState::failed:
                on_well_log_failed(ref, outcome.error);
                return;
            case job::JobState::cancelled:
                // Python wires no cancelled handler here — the release
                // path (pending re-open) owns the follow-up.
                return;
            }
        });
}

void VisualizationPage::on_well_log_job_released() {
    const auto pending = pending_well_log_ref_;
    pending_well_log_ref_.reset();
    if (pending.has_value()) {
        open_ref(*pending);
    }
}

void VisualizationPage::apply_well_log_payload(
    const VizRefSlice& ref, const UiVizPayload& payload) {
    composite_->load_payload(payload);
    trace_->update_ref(&ref, &payload);
    sync_export_capabilities();
}

void VisualizationPage::on_well_log_resolved(
    const VizRefSlice& ref, const ui_workers::VizPayloadSlice& slice,
    long long seq) {
    if (seq != load_seq_ ||
        !refs_match(current_ref_, ref)) {
        return;
    }
    apply_well_log_payload(ref, payload_from_slice(slice));
}

void VisualizationPage::on_well_log_failed(const VizRefSlice& ref,
                                           const std::string& message) {
    if (!refs_match(current_ref_, ref)) {
        return;
    }
    UiVizPayload payload;
    payload.kind = "message";
    payload.label = !ref.label.empty() ? ref.label
                                       : (!ref.id.empty() ? ref.id
                                                          : "井数据");
    payload.message = "井数据加载失败: " + message;
    apply_well_log_payload(ref, payload);
}

void VisualizationPage::reload_current() {
    if (current_ref_.has_value()) {
        open_ref(*current_ref_);
    } else {
        composite_->update_state(project_.prediction_tasks);
        sync_export_capabilities();
    }
}

void VisualizationPage::sync_export_capabilities() {
    trace_->set_export_capabilities(composite_->export_capabilities());
}

void VisualizationPage::export_current_view(const QString& format_label) {
    QWidget* widget = composite_->tabs()->currentWidget();
    if (widget == nullptr) {
        emit warning_requested("导出", "当前没有可导出的视图");
        return;
    }
    const std::string label =
        (format_label.isEmpty() ? QStringLiteral("PNG") : format_label)
            .toUpper()
            .toStdString();
    const auto caps = composite_->export_capabilities();
    if (caps.count(label) == 0U) {
        std::string supported;
        for (const auto& cap : caps) {
            if (!supported.empty()) {
                supported += "、";
            }
            supported += cap;
        }
        emit warning_requested(
            "导出",
            QString::fromStdString(
                "当前 Tab 不支持 " + label + " 导出（可用: " +
                (supported.empty() ? "无" : supported) +
                "）。测井 / 连井 / 古地理支持矢量 SVG/PDF。"));
        return;
    }
    const QString tab_name = composite_->tabs()->tabText(
        composite_->tabs()->currentIndex());
    const std::string suffix = label == "SVG" ? ".svg"
                               : label == "PDF" ? ".pdf"
                                                : ".png";
    const std::string stem =
        safe_stem(current_ref_.has_value() && !current_ref_->label.empty()
                      ? current_ref_->label
                      : tab_name.toStdString());
    const std::string start_dir =
        seams_.export_dir_fn ? seams_.export_dir_fn() : std::string{};
    const QString suggested = QString::fromStdString(
        (fs::path(start_dir.empty() ? "." : start_dir) /
         (stem + "_" + tab_name.toStdString() + suffix))
            .string());
    const QString path = QFileDialog::getSaveFileName(
        this, QString::fromStdString("导出视图 (" + label + ")"), suggested,
        QString::fromStdString(label + " (*" + suffix + ")"));
    if (path.isEmpty()) {
        return;
    }
    if (label == "PNG" && seams_.map_png_export_fn &&
        seams_.map_png_export_fn(
            widget, path.toStdString(),
            [this, widget](const std::string& done_path) {
                end_export_busy();
                if (seams_.register_view_fn) {
                    seams_.register_view_fn(widget, done_path, "PNG");
                }
                composite_->status_label()->setText(
                    QString::fromStdString(
                        "已导出视图: " +
                        fs::path(done_path).filename().string()));
            },
            [this](const std::string& message) {
                end_export_busy();
                emit warning_requested(
                    "导出失败", QString::fromStdString(message));
            },
            [this] {
                end_export_busy();
                composite_->status_label()->setText("已取消导出");
            })) {
        begin_export_busy();
        return;
    }

    // Vector exports render synchronously on the GUI thread — busy
    // cursor + status while it runs (#897 parity).
    const bool had_cursor = QApplication::overrideCursor() != nullptr;
    const QCursor saved = had_cursor ? *QApplication::overrideCursor()
                                     : QCursor();
    QApplication::setOverrideCursor(Qt::WaitCursor);
    composite_->status_label()->setText(
        QString::fromStdString("正在导出 " + label + " …"));
    QApplication::processEvents();
    bool ok = false;
    if (seams_.workspace.export_fn) {
        ok = seams_.workspace.export_fn(widget, path.toStdString(), label);
    }
    QApplication::restoreOverrideCursor();
    if (had_cursor) {
        QApplication::setOverrideCursor(saved);
    }
    if (ok) {
        composite_->status_label()->setText(
            QString::fromStdString(
                "已导出视图: " + fs::path(path.toStdString())
                                     .filename()
                                     .string()));
    } else {
        emit warning_requested("导出失败", "导出未完成");
    }
}

void VisualizationPage::begin_export_busy() {
    if (!export_busy_) {
        QApplication::setOverrideCursor(Qt::WaitCursor);
        export_busy_ = true;
    }
    trace_->export_png_btn()->setEnabled(false);
    trace_->export_svg_btn()->setEnabled(false);
    trace_->export_pdf_btn()->setEnabled(false);
    composite_->status_label()->setText("正在导出…");
}

void VisualizationPage::end_export_busy() {
    if (!export_busy_) {
        return;
    }
    QApplication::restoreOverrideCursor();
    export_busy_ = false;
    sync_export_capabilities();
}

void VisualizationPage::show_preview_loading() {
    const std::string label =
        current_ref_.has_value() ? current_ref_->label : std::string{};
    composite_->status_label()->setText(QString::fromStdString(
        "正在加载: " + (label.empty() ? "引擎预览" : label)));
}

void VisualizationPage::apply_preview_result(
    const ui_data_core::PreviewResult& result) {
    if (!current_ref_.has_value() ||
        current_ref_->kind != "engine_preview") {
        return;
    }
    const VizRefSlice ref = *current_ref_;
    const UiVizPayload payload =
        payload_from_engine_preview_result(ref, result);
    composite_->load_payload(payload);
    trace_->update_ref(&ref, &payload);
    sync_export_capabilities();
}

void VisualizationPage::show_preview_error(const QString& message) {
    if (!current_ref_.has_value() ||
        current_ref_->kind != "engine_preview") {
        return;
    }
    const VizRefSlice ref = *current_ref_;
    UiVizPayload payload;
    payload.kind = "message";
    payload.label = !ref.label.empty() ? ref.label
                                       : (!ref.id.empty() ? ref.id
                                                          : ref.kind);
    payload.message =
        message.isEmpty() ? "引擎预览失败" : message.toStdString();
    composite_->load_payload(payload);
    trace_->update_ref(&ref, &payload);
    sync_export_capabilities();
}

void VisualizationPage::closeEvent(QCloseEvent* event) {
    shutdown_workers();
    QWidget::closeEvent(event);
}

bool VisualizationPage::event(QEvent* event) {
    if (event->type() == QEvent::DeferredDelete &&
        preview_controller_ != nullptr) {
        shutdown_workers();
    }
    return QWidget::event(event);
}

bool VisualizationPage::shutdown_workers(int wait_ms) {
    pending_well_log_ref_.reset();
    ui_workers::request_well_log_cancel(well_log_phase_, {});
    const bool well_ok = well_log_job_->shutdown(wait_ms);
    const bool export_ok = export_job_->shutdown(wait_ms);
    end_export_busy();
    const bool preview_ok = preview_controller_->shutdown(wait_ms);
    return export_ok && well_ok && preview_ok;
}

void VisualizationPage::on_coord_toggle() {
    // The actual coord-mode propagation lives on the 3D modeling page;
    // this button only relabels itself (Python parity).
    coord_btn_->setText(coord_btn_->isChecked() ? "◉ 地理(X/Y)"
                                                : "◆ 网格(IL/XL)");
}

void VisualizationPage::persist_docked_sizes() {
    if (persistence_ == nullptr) {
        return;
    }
    const auto sizes = splitter_->sizes();
    const std::vector<int> size_vec(sizes.begin(), sizes.end());
    for (const auto& [key, panel] : floatable_) {
        if (panel->parentWidget() == splitter_) {
            persistence_->save_docked_sizes(key, size_vec);
        }
    }
}

void VisualizationPage::make_floatable(const std::string& key,
                                       QWidget* panel,
                                       const QString& title) {
    ui_shell::dock_manager().register_panel(key, title.toStdString());
    floatable_.emplace_back(key, panel);
    new PanelFloatButton(key, panel, float_controller_.get());
}

}  // namespace pwb::ui_seqviz::qt
