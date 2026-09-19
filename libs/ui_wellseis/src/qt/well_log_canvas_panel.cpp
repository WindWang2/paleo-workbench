#include <pwb/ui_wellseis/qt/well_log_canvas_panel.hpp>

#include <QComboBox>
#include <QFrame>
#include <QHBoxLayout>
#include <QLabel>
#include <QStackedLayout>
#include <QVBoxLayout>

#include <pwb/ui_wellseis/page_state.hpp>

namespace pwb::ui_wellseis::qt {

namespace {

QString qs(const std::string& text) {
    return QString::fromUtf8(text.data(), static_cast<int>(text.size()));
}

}  // namespace

WellLogCanvasPanel::WellLogCanvasPanel(QWidget* parent) : QWidget(parent) {
    setObjectName(QStringLiteral("WellLogCanvasPanel"));
    auto* outer = new QVBoxLayout(this);
    outer->setContentsMargins(8, 8, 8, 8);
    outer->setSpacing(4);

    auto* header = new QHBoxLayout();
    backend_combo_ = new QComboBox(this);
    backend_combo_->setObjectName(QStringLiteral("WellLogBackendCombo"));
    backend_combo_->addItem(qs(well_log_backend_label(kWellLogBackendLegacy)),
                            qs(kWellLogBackendLegacy));
    backend_combo_->addItem(qs(well_log_backend_label(kWellLogBackendEngine)),
                            qs(kWellLogBackendEngine));
    backend_combo_->setCurrentIndex(0);
    connect(backend_combo_, &QComboBox::currentIndexChanged, this,
            [this](int index) {
                if (suppress_) {
                    return;
                }
                set_backend(
                    backend_combo_->itemData(index).toString().toStdString());
                emit backend_changed(qs(backend_));
            });
    header->addWidget(backend_combo_, 0);
    header->addStretch(1);
    status_label_ = new QLabel(this);
    status_label_->setObjectName(QStringLiteral("WorkFieldValue"));
    header->addWidget(status_label_);
    outer->addLayout(header);

    auto* host = new QFrame(this);
    stack_ = new QStackedLayout(host);
    stack_->setContentsMargins(0, 0, 0, 0);
    empty_page_ = new QWidget(host);
    auto* empty_layout = new QVBoxLayout(empty_page_);
    empty_label_ = new QLabel(empty_page_);
    empty_label_->setObjectName(QStringLiteral("EmptyStateLabel"));
    empty_label_->setAlignment(Qt::AlignCenter);
    empty_label_->setWordWrap(true);
    empty_layout->addWidget(empty_label_);
    stack_->addWidget(empty_page_);
    outer->addWidget(host, 1);
}

void WellLogCanvasPanel::set_canvas_seam(const std::string& backend,
                                         WellLogCanvasSeam seam) {
    WellLogCanvasSeam& slot = backend == kWellLogBackendEngine
                                  ? engine_seam_
                                  : legacy_seam_;
    if (slot.widget != nullptr && slot.widget != seam.widget) {
        stack_->removeWidget(slot.widget);
    }
    slot = seam;
    if (slot.widget != nullptr) {
        if (slot.widget->parent() == nullptr) {
            slot.widget->setParent(stack_->parentWidget());
        }
        stack_->addWidget(slot.widget);
    }
    refresh_stack();
}

void WellLogCanvasPanel::set_backend(const std::string& backend) {
    backend_ = backend == kWellLogBackendEngine ? kWellLogBackendEngine
                                                : kWellLogBackendLegacy;
    suppress_ = true;
    backend_combo_->setCurrentIndex(
        backend_ == kWellLogBackendEngine ? 1 : 0);
    suppress_ = false;
    refresh_stack();
}

std::string WellLogCanvasPanel::backend() const {
    return backend_;
}

void WellLogCanvasPanel::refresh_stack() {
    const WellLogCanvasSeam& seam = backend_ == kWellLogBackendEngine
                                        ? engine_seam_
                                        : legacy_seam_;
    QWidget* widget = seam.widget;
    if (widget == nullptr && backend_ == kWellLogBackendEngine) {
        // Engine selected but its widget failed → honest placeholder or
        // legacy fallback (Python paints the Legacy fallback but keeps
        // "engine" selected; when no legacy either, the empty page shows
        // the engine error).
        if (legacy_seam_.widget != nullptr) {
            widget = legacy_seam_.widget;
        } else {
            empty_label_->setText(qs(engine_unavailable_text(
                "WellLogEngine", seam.engine_error)));
            widget = empty_page_;
        }
    }
    if (widget == nullptr) {
        empty_label_->setText(QStringLiteral("未加载测井曲线"));
        widget = empty_page_;
    }
    stack_->setCurrentWidget(widget);
}

bool WellLogCanvasPanel::is_native_backend() const {
    // Python parity: selection only — a failed native load still reports
    // the engine backend (is_canvas_ready covers liveness separately).
    return backend_ == kWellLogBackendEngine;
}

bool WellLogCanvasPanel::is_canvas_ready() const {
    return active_canvas() != nullptr && active_canvas() != empty_page_;
}

QWidget* WellLogCanvasPanel::active_canvas() const {
    QWidget* current = stack_->currentWidget();
    return current;
}

void WellLogCanvasPanel::set_depth_unit(DepthUnitInfo info) {
    depth_unit_ = std::move(info);
}

std::optional<std::string>
WellLogCanvasPanel::depth_cursor_unavailable_reason() const {
    // Delegates to the Qt-free core (single authority for the fail-closed
    // unit contract — cursor_gates.hpp).
    return pwb::ui_wellseis::depth_cursor_unavailable_reason(depth_unit_);
}

bool WellLogCanvasPanel::depth_cursor_supported() const {
    if (backend_ == kWellLogBackendLegacy) {
        return true;
    }
    return engine_seam_.depth_cursor_supported;
}

std::string WellLogCanvasPanel::depth_cursor_unit() const {
    return depth_unit_.unit.value_or("");
}

void WellLogCanvasPanel::offer_depth_cursor(double depth_m) {
    const DepthCursorGate::Decision decision = depth_gate_.offer(depth_m);
    if (decision.publish_now) {
        emit depth_cursor_published(decision.depth);
    }
    // Held samples flush through flush_depth_cursor() — the host schedules
    // it via decision.flush_in_ms (Python's single-shot QTimer).
}

void WellLogCanvasPanel::flush_depth_cursor() {
    const auto pending = depth_gate_.flush_pending();
    if (pending.has_value()) {
        emit depth_cursor_published(*pending);
    }
}

void WellLogCanvasPanel::set_status(const QString& text) {
    status_label_->setText(text);
}

void WellLogCanvasPanel::set_hooks(WellLogCanvasHooks hooks) {
    hooks_ = std::move(hooks);
}

void WellLogCanvasPanel::update_state(const PredictionTaskSlice* task,
                                      const ProjectSlice* project) {
    if (hooks_.update_state) {
        hooks_.update_state(task, project);
    }
}

bool WellLogCanvasPanel::show_resource(const ResourceSlice& resource,
                                       const ProjectSlice* project) {
    return hooks_.show_resource
               ? hooks_.show_resource(resource, project)
               : false;
}

bool WellLogCanvasPanel::has_bound_las() const {
    return hooks_.has_bound_las ? hooks_.has_bound_las() : false;
}

std::string WellLogCanvasPanel::well_name() const {
    return hooks_.well_name ? hooks_.well_name() : std::string();
}

void WellLogCanvasPanel::shutdown() {
    if (hooks_.shutdown) {
        hooks_.shutdown();
    }
}

std::optional<std::string> WellLogCanvasPanel::export_legacy(
    const std::string& path, const std::string& format_label,
    const ProjectSlice* project,
    const std::vector<std::string>& source_task_ids) const {
    if (!hooks_.export_legacy) {
        return std::string("export hook unavailable");
    }
    return hooks_.export_legacy(path, format_label, project,
                                source_task_ids);
}

QWidget* WellLogCanvasPanel::engine_view_widget() const {
    return hooks_.engine_view ? hooks_.engine_view() : nullptr;
}

}  // namespace pwb::ui_wellseis::qt
