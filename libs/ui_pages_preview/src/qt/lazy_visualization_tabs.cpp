#include <pwb/ui_pages_preview/qt/lazy_visualization_tabs.hpp>

#include <QPushButton>
#include <QStackedWidget>
#include <QVBoxLayout>

#include <stdexcept>

#include <pwb/ui_pages_preview/preview_settings.hpp>
#include <pwb/ui_pages_preview/qt/message_preview_widget.hpp>
#include <pwb/ui_pages_preview/qt/summary_table_preview_widget.hpp>
#include <pwb/ui_pages_preview/qt/table_preview_widget.hpp>
#include <pwb/ui_pages_preview/qt/text_preview_widget.hpp>

namespace pwb::ui_pages_preview {

LazyVisualizationTabs::LazyVisualizationTabs(QWidget* parent)
    : QTabWidget(parent) {
    summary_ = new TablePreviewWidget();
    text_ = new TextPreviewWidget();
    well_log_summary_ = new SummaryTablePreviewWidget();
    summary_stack_ = new QStackedWidget();
    summary_stack_->addWidget(summary_);
    summary_stack_->addWidget(text_);
    summary_stack_->addWidget(well_log_summary_);
    addTab(summary_stack_, QStringLiteral("数据列表"));

    visual_stack_ = new QStackedWidget();
    prompt_label_ = new MessagePreviewWidget();
    prompt_label_->set_message(
        QStringLiteral("点击此选项卡生成可视化预览"));
    loading_label_ = new MessagePreviewWidget();
    loading_label_->set_message(
        QStringLiteral("正在生成可视化预览…"));
    message_panel_ = new QWidget();
    auto* message_layout = new QVBoxLayout(message_panel_);
    message_layout->setContentsMargins(0, 0, 0, 0);
    message_label_ = new MessagePreviewWidget(message_panel_);
    reload_button_ =
        new QPushButton(QStringLiteral("重新加载"), message_panel_);
    reload_button_->setObjectName(
        QStringLiteral("VisualizationPreviewReloadButton"));
    reload_button_->setAccessibleName(
        QStringLiteral("重新加载可视化预览"));
    connect(reload_button_, &QPushButton::clicked, this,
            [this] { request_retry(); });
    message_layout->addWidget(message_label_, 1);
    message_layout->addWidget(reload_button_);
    visual_stack_->addWidget(prompt_label_);
    visual_stack_->addWidget(loading_label_);
    visual_stack_->addWidget(message_panel_);
    addTab(visual_stack_, QStringLiteral("可视化预览"));

    connect(this, &QTabWidget::currentChanged, this,
            [this](int index) { on_current_changed(index); });
    setCurrentIndex(0);
}

void LazyVisualizationTabs::set_host_factory(
    std::function<QWidget*(QWidget*)> factory) {
    if (host_ != nullptr) {
        throw std::runtime_error(
            "cannot replace engine after visualization host creation");
    }
    host_factory_ = std::move(factory);
}

QWidget* LazyVisualizationTabs::host() {
    if (host_ == nullptr && host_factory_) {
        // Deferred: the concrete host (geoviz engine stack) is owned by
        // the factory; lazy creation keeps startup cost off the tab.
        host_ = host_factory_(this);
        if (host_ != nullptr) {
            visual_stack_->addWidget(host_);
        }
    }
    return host_;
}

void LazyVisualizationTabs::load_summary(const LazySummaryResult& result) {
    if (result.mode == "text") {
        text_->load_text(QString::fromStdString(result.text));
        summary_stack_->setCurrentWidget(text_);
    } else if (result.mode == "well_log") {
        well_log_summary_->load_summary(
            result.summary_rows, result.table_headers, result.table_rows,
            QString::fromStdString(result.message), result.data_headers,
            result.data_rows);
        summary_stack_->setCurrentWidget(well_log_summary_);
    } else {
        summary_->load_table(result.table_headers, result.table_rows);
        summary_stack_->setCurrentWidget(summary_);
    }
    state_.load_summary();
    visual_stack_->setCurrentWidget(prompt_label_);
    setCurrentIndex(0);
}

void LazyVisualizationTabs::show_loading() {
    state_.show_loading();
    visual_stack_->setCurrentWidget(loading_label_);
    // No setCurrentIndex(1) here: background prefetches also emit loading,
    // and a user-initiated click has already switched to this tab.
    // Completion (show_preview) owns the same no-steal contract (#630).
}

void LazyVisualizationTabs::show_preview(bool activate) {
    const bool was_visual = currentIndex() == 1;
    QWidget* host_widget = host();
    state_.show_preview(activate || was_visual);
    if (host_widget != nullptr) {
        visual_stack_->setCurrentWidget(host_widget);
    }
    if (state_.current_tab == 1) {
        setCurrentIndex(1);
    }
}

void LazyVisualizationTabs::show_error(const QString& message,
                                       bool retryable, bool activate) {
    const bool was_visual = currentIndex() == 1;
    state_.show_error(retryable, activate || was_visual);
    message_label_->set_message(message.isEmpty()
                                    ? QStringLiteral("可视化预览不可用")
                                    : message);
    // A structural source error is not retryable from the cache's point of
    // view, but the user can correct the external file and reload it.
    reload_button_->setVisible(true);
    visual_stack_->setCurrentWidget(message_panel_);
    if (state_.current_tab == 1) {
        setCurrentIndex(1);
    }
}

void LazyVisualizationTabs::reset() {
    state_.reset();
    visual_stack_->setCurrentWidget(prompt_label_);
    setCurrentIndex(0);
}

void LazyVisualizationTabs::clear_host() {
    if (host_ != nullptr) {
        // GeoVizPreviewHost.clear() — invoke by name so a plain QWidget
        // host degrades gracefully.
        QMetaObject::invokeMethod(host_, "clear", Qt::DirectConnection);
    }
}

void LazyVisualizationTabs::release_all() {
    if (host_ != nullptr) {
        QMetaObject::invokeMethod(host_, "release_all",
                                  Qt::DirectConnection);
    }
    reset();
}

void LazyVisualizationTabs::apply_settings(const PreviewSettings& settings) {
    for (QWidget* widget :
         {static_cast<QWidget*>(summary_), static_cast<QWidget*>(text_),
          static_cast<QWidget*>(well_log_summary_)}) {
        if (auto* table = qobject_cast<TablePreviewWidget*>(widget)) {
            table->apply_settings(settings);
        } else if (auto* text_w = qobject_cast<TextPreviewWidget*>(widget)) {
            text_w->apply_settings(settings);
        } else if (auto* summary_w =
                       qobject_cast<SummaryTablePreviewWidget*>(widget)) {
            summary_w->apply_settings(settings);
        }
    }
}

void LazyVisualizationTabs::on_current_changed(int index) {
    const int before = state_.visualization_emitted;
    state_.tab_changed(index);
    if (state_.visualization_emitted != before) {
        emit visualization_requested();
    }
}

void LazyVisualizationTabs::request_retry() {
    state_.request_retry();
    emit visualization_requested();
}

}  // namespace pwb::ui_pages_preview
