#include <pwb/ui_wellseis/qt/seismic_view_panel.hpp>

#include <QHBoxLayout>
#include <QLabel>
#include <QPushButton>
#include <QStackedLayout>
#include <QVBoxLayout>

#include <pwb/ui_wellseis/page_state.hpp>

namespace pwb::ui_wellseis::qt {

SeismicViewPanel::SeismicViewPanel(QWidget* parent,
                                   SeismicViewFactory view_factory)
    : QFrame(parent) {
    setObjectName(QStringLiteral("SeismicViewPanel"));

    auto* outer = new QVBoxLayout(this);
    outer->setContentsMargins(12, 12, 12, 12);
    outer->setSpacing(4);

    auto* host = new QFrame(this);
    host->setObjectName(QStringLiteral("SeismicViewHost"));
    stack_ = new QStackedLayout(host);
    stack_->setContentsMargins(0, 0, 0, 0);

    empty_label_ = new QLabel(QStringLiteral("未选择预测任务"), host);
    empty_label_->setObjectName(QStringLiteral("EmptyStateLabel"));
    empty_label_->setAlignment(Qt::AlignCenter);
    empty_label_->setWordWrap(true);
    stack_->addWidget(empty_label_);

    outer->addWidget(host, 1);

    // Interpretation lifecycle bar — actions are surfaced as signals; the
    // host binds them to the interpretation/session seam.
    auto* interp_row = new QWidget(this);
    auto* interp_layout = new QHBoxLayout(interp_row);
    interp_layout->setContentsMargins(0, 0, 0, 0);
    interp_layout->setSpacing(4);
    interp_draft_btn_ =
        new QPushButton(QStringLiteral("开始层位解释"), interp_row);
    interp_draft_btn_->setObjectName(QStringLiteral("SecondaryButton"));
    interp_draft_btn_->setToolTip(
        QStringLiteral("将拾取点收集为层位解释草稿（可撤销编辑）"));
    connect(interp_draft_btn_, &QPushButton::clicked, this,
            &SeismicViewPanel::interpretation_draft_requested);
    interp_sync_btn_ =
        new QPushButton(QStringLiteral("同步拾取→草稿"), interp_row);
    interp_sync_btn_->setObjectName(QStringLiteral("SecondaryButton"));
    interp_sync_btn_->setToolTip(
        QStringLiteral("把当前剖面拾取点写入解释草稿（稀疏可撤销）"));
    connect(interp_sync_btn_, &QPushButton::clicked, this,
            &SeismicViewPanel::interpretation_sync_requested);
    interp_undo_btn_ = new QPushButton(QStringLiteral("撤销"), interp_row);
    connect(interp_undo_btn_, &QPushButton::clicked, this,
            &SeismicViewPanel::interpretation_undo_requested);
    interp_redo_btn_ = new QPushButton(QStringLiteral("重做"), interp_row);
    connect(interp_redo_btn_, &QPushButton::clicked, this,
            &SeismicViewPanel::interpretation_redo_requested);
    interp_save_btn_ =
        new QPushButton(QStringLiteral("保存解释版本"), interp_row);
    interp_save_btn_->setObjectName(QStringLiteral("SecondaryButton"));
    interp_save_btn_->setToolTip(QStringLiteral(
        "冻结草稿为不可变解释版本（目录血缘 + 工程引用）"));
    connect(interp_save_btn_, &QPushButton::clicked, this,
            &SeismicViewPanel::interpretation_save_requested);
    interp_reload_btn_ =
        new QPushButton(QStringLiteral("重开解释"), interp_row);
    interp_reload_btn_->setObjectName(QStringLiteral("SecondaryButton"));
    interp_reload_btn_->setToolTip(
        QStringLiteral("从工程引用重开最新解释版本为草稿"));
    connect(interp_reload_btn_, &QPushButton::clicked, this,
            &SeismicViewPanel::interpretation_reopen_requested);
    for (QPushButton* btn : {interp_draft_btn_, interp_sync_btn_,
                             interp_undo_btn_, interp_redo_btn_,
                             interp_save_btn_, interp_reload_btn_}) {
        interp_layout->addWidget(btn);
    }
    interp_layout->addStretch(1);
    interp_status_label_ = new QLabel(QString(), interp_row);
    interp_layout->addWidget(interp_status_label_);
    outer->addWidget(interp_row);

    set_interpretation_state(false, false, false, false, false);
    if (view_factory) {
        set_view(view_factory(host));
    }
}

void SeismicViewPanel::set_view(SeismicViewSeam seam) {
    if (view_ != nullptr) {
        stack_->removeWidget(view_);
        view_->setParent(nullptr);
    }
    view_ = seam.widget;
    if (view_ != nullptr) {
        stack_->addWidget(view_);
        stack_->setCurrentWidget(view_);
    } else {
        stack_->setCurrentWidget(empty_label_);
        if (!seam.engine_error.empty()) {
            empty_label_->setText(QString::fromStdString(
                engine_unavailable_text("地震视图引擎", seam.engine_error)));
        }
    }
    emit view_ready(view_ != nullptr);
}

bool SeismicViewPanel::is_view_ready() const {
    return view_ != nullptr;
}

QWidget* SeismicViewPanel::view() const {
    return view_;
}

void SeismicViewPanel::set_volume_shape(
    std::optional<std::array<std::int64_t, 3>> shape) {
    volume_shape_ = shape;
}

std::optional<std::array<std::int64_t, 3>> SeismicViewPanel::volume_shape()
    const {
    return volume_shape_;
}

void SeismicViewPanel::set_interpretation_state(bool draft_open,
                                                bool session_available,
                                                bool can_undo, bool can_redo,
                                                bool version_saved) {
    // Python _sync_interp_buttons parity: sync/undo/redo/save need an open
    // draft; reopen needs a saved version on the session.
    interp_draft_btn_->setEnabled(session_available && !draft_open);
    interp_sync_btn_->setEnabled(draft_open);
    interp_undo_btn_->setEnabled(draft_open && can_undo);
    interp_redo_btn_->setEnabled(draft_open && can_redo);
    interp_save_btn_->setEnabled(draft_open);
    interp_reload_btn_->setEnabled(session_available && version_saved);
}

void SeismicViewPanel::set_interpretation_status(const QString& text) {
    interp_status_label_->setText(text);
}

void SeismicViewPanel::offer_cursor(double il, double xl, double twt_ms) {
    if (cursor_gate_.should_publish(il)) {
        emit cursor_published(il, xl, twt_ms);
    }
}

void SeismicViewPanel::reset_cursor_gate() {
    cursor_gate_ = SeismicCursorGate();
}

void SeismicViewPanel::set_unavailable_reason(const std::string& reason) {
    if (view_ == nullptr && !reason.empty()) {
        empty_label_->setText(QString::fromStdString(reason));
    }
}

void SeismicViewPanel::set_hooks(SeismicViewHooks hooks) {
    hooks_ = std::move(hooks);
}

void SeismicViewPanel::update_state(const PredictionTaskSlice* task,
                                    const ProjectSlice* project) {
    if (hooks_.update_state) {
        hooks_.update_state(task, project);
    }
}

bool SeismicViewPanel::show_resource(const ResourceSlice& resource,
                                     const ProjectSlice* project) {
    return hooks_.show_resource
               ? hooks_.show_resource(resource, project)
               : false;
}

void SeismicViewPanel::set_display_mode(const QString& mode) {
    display_mode_ = mode.isEmpty() ? QStringLiteral("vd") : mode;
    if (hooks_.set_display_mode) {
        hooks_.set_display_mode(mode);
    }
}

QString SeismicViewPanel::display_mode() const {
    return hooks_.display_mode ? hooks_.display_mode() : display_mode_;
}

void SeismicViewPanel::set_attribute_label(const QString& label) {
    if (!label.isEmpty()) {
        attribute_label_ = label;
    }
    if (hooks_.set_attribute_label) {
        hooks_.set_attribute_label(label);
    }
}

QString SeismicViewPanel::attribute_label() const {
    return hooks_.attribute_label ? hooks_.attribute_label()
                                  : attribute_label_;
}

void SeismicViewPanel::set_well_tie_enabled(bool enabled) {
    if (hooks_.set_well_tie_enabled) {
        hooks_.set_well_tie_enabled(enabled);
    }
}

void SeismicViewPanel::set_project_path(const QString& path) {
    if (hooks_.set_project_path) {
        hooks_.set_project_path(path);
    }
}

void SeismicViewPanel::shutdown() {
    if (hooks_.shutdown) {
        hooks_.shutdown();
    }
}

}  // namespace pwb::ui_wellseis::qt
