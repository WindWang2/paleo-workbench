#include "pwb/ui_review/qt/review_export_page.hpp"

#include "pwb/ui_pages_data/qt/action_header.hpp"
#include "pwb/ui_review/qt/qc_issue_table.hpp"
#include "pwb/ui_review/qt/result_summary_panel.hpp"
#include "pwb/ui_review/tokens.hpp"
#include "pwb/ui_shell/dock_manager.hpp"
#include "pwb/ui_shell/float_controller.hpp"
#include "pwb/ui_shell/layout_persistence.hpp"

#include <QEvent>
#include <QFileDialog>
#include <QMessageBox>
#include <QPushButton>
#include <QSplitter>
#include <QTimer>
#include <QToolButton>
#include <QVBoxLayout>

#include <filesystem>

namespace pwb::ui_review::qt {

// QWIDGETSIZE_MAX: lifts the side panel's fixed-width bound (the designed
// width stays the minimum) so the splitter handle can resize it.
constexpr int kPanelMaxWidth = 16777215;
// Delay before a splitter drag is persisted (no QSettings sync per tick).
constexpr int kDockedSizesDelayMs = 400;

// -- PanelFloatButton ----------------------------------------------------------

PanelFloatButton::PanelFloatButton(const QString& key, QWidget* panel,
                                   ui_shell::FloatController* controller)
    : QToolButton(panel),
      key_(key),
      panel_(panel),
      controller_(controller) {
    setObjectName(QStringLiteral("PanelFloatButton"));
    setText(QStringLiteral("⇱"));
    setToolTip(QStringLiteral("浮动面板 (Float panel)"));
    // Icon-glyph text carries no semantics for assistive tech (audit F4).
    setAccessibleName(QStringLiteral("浮动面板"));
    setFixedSize(18, 18);
    connect(this, &QToolButton::clicked, this, [this]() {
        controller_->toggle(key_.toStdString());
    });
    panel_->installEventFilter(this);
    connect(controller_, &ui_shell::FloatController::float_changed, this,
            [this](const QString& key, bool floating) {
                if (key == key_) {
                    setVisible(!floating);
                }
            });
    reposition();
}

void PanelFloatButton::reposition() {
    move(panel_->width() - width() - 4, 2);
}

bool PanelFloatButton::eventFilter(QObject* obj, QEvent* event) {
    if (obj == panel_ && event->type() == QEvent::Resize) {
        reposition();
    }
    return false;
}

// -- ReviewExportPage ------------------------------------------------------------

ReviewExportPage::ReviewExportPage(
    QWidget* parent, std::function<IReviewActions*()> actions_provider,
    ui_shell::LayoutPersistence* persistence)
    : QWidget(parent),
      actions_provider_(std::move(actions_provider)),
      persistence_(persistence) {
    setObjectName(QStringLiteral("ReviewExportPage"));
    if (persistence_ == nullptr) {
        owned_persistence_ =
            std::make_unique<ui_shell::LayoutPersistence>();
        persistence_ = owned_persistence_.get();
    }

    auto* outer = new QVBoxLayout(this);
    outer->setContentsMargins(tokens::kPageMargin, tokens::kPageMargin,
                              tokens::kPageMargin, tokens::kPageMargin);
    outer->setSpacing(tokens::kSpace4);

    action_header_ = new ui_pages_data::qt::ActionHeader(this);
    outer->addWidget(action_header_, 0);

    content_splitter_ = new QSplitter(Qt::Horizontal, this);
    content_splitter_->setObjectName(
        QStringLiteral("ReviewExportSplitter"));

    qc_table_ = new QcIssueTable(content_splitter_);
    // 质检问题表 stays the stretchy center; the summary is the resizable
    // side panel.
    content_splitter_->addWidget(qc_table_);

    result_summary_ = new ResultSummaryPanel(content_splitter_);
    result_summary_->setMaximumWidth(kPanelMaxWidth);
    content_splitter_->addWidget(result_summary_);

    content_splitter_->setStretchFactor(0, 1);
    content_splitter_->setStretchFactor(1, 0);
    content_splitter_->setSizes({1000, 260});

    outer->addWidget(content_splitter_, 1);

    // M6: the QC summary floats through the shared FloatController; the
    // issue table stays the docked center.
    float_controller_ = new ui_shell::FloatController(
        [this](const std::string& key) -> QWidget* {
            const auto it = floatable_.find(QString::fromStdString(key));
            return it != floatable_.end() ? it->second : nullptr;
        },
        persistence_, nullptr, this);
    make_floatable(QStringLiteral("review:summary"), result_summary_,
                   QStringLiteral("结果摘要"));
    float_sizes_timer_ = new QTimer(this);
    float_sizes_timer_->setSingleShot(true);
    float_sizes_timer_->setInterval(kDockedSizesDelayMs);
    connect(float_sizes_timer_, &QTimer::timeout, this,
            &ReviewExportPage::persist_docked_sizes);
    connect(content_splitter_, &QSplitter::splitterMoved, this,
            [this](int, int) { float_sizes_timer_->start(); });
    for (const auto& [key, panel] : floatable_) {
        float_controller_->restore_saved(key.toStdString(), panel);
    }

    connect(action_header_,
            &ui_pages_data::qt::ActionHeader::run_requested, this,
            &ReviewExportPage::run_qc);
    connect(action_header_,
            &ui_pages_data::qt::ActionHeader::export_requested, this,
            &ReviewExportPage::export_report);
    connect(action_header_,
            &ui_pages_data::qt::ActionHeader::config_requested, this,
            &ReviewExportPage::on_config);
    connect(action_header_,
            &ui_pages_data::qt::ActionHeader::finalize_requested, this,
            &ReviewExportPage::finalize_version);
    setup_tab_order();
}

ReviewExportPage::~ReviewExportPage() = default;

IReviewActions* ReviewExportPage::actions() const {
    return project_bound_ && actions_provider_ ? actions_provider_()
                                               : nullptr;
}

void ReviewExportPage::setup_tab_order() {
    // Explicit tab chain: 运行 → 规则 → 导出 → 定稿 → QC issue table.
    QWidget::setTabOrder(action_header_->run_button(),
                        action_header_->config_button());
    QWidget::setTabOrder(action_header_->config_button(),
                        action_header_->export_button());
    QWidget::setTabOrder(action_header_->export_button(),
                        action_header_->finalize_button());
    QWidget::setTabOrder(action_header_->finalize_button(),
                        qc_table_->table());
}

void ReviewExportPage::make_floatable(const QString& key,
                                      QWidget* panel,
                                      const QString& title) {
    ui_shell::dock_manager().register_panel(key.toStdString(),
                                            title.toStdString());
    floatable_[key] = panel;
    new PanelFloatButton(key, panel, float_controller_);
}

void ReviewExportPage::persist_docked_sizes() {
    const auto sizes_q = content_splitter_->sizes();
    std::vector<int> sizes(sizes_q.begin(), sizes_q.end());
    for (const auto& [key, panel] : floatable_) {
        if (panel->parentWidget() == content_splitter_) {
            persistence_->save_docked_sizes(key.toStdString(), sizes);
        }
    }
}

void ReviewExportPage::set_project_bound(bool bound) {
    project_bound_ = bound;
}

void ReviewExportPage::update_state(const domain::Json& reports,
                                    const domain::Json& map_documents,
                                    const domain::Json& artifacts) {
    reports_ = reports.is_array() ? reports : domain::Json::array();
    map_documents_ = map_documents.is_array() ? map_documents
                                              : domain::Json::array();
    artifacts_ = artifacts.is_array() ? artifacts
                                      : domain::Json::array();
    action_header_->update_state(reports_, map_documents_);
    std::vector<domain::Json> report_list(reports_.begin(),
                                          reports_.end());
    qc_table_->update_state(report_list);
    result_summary_->update_state(reports_, artifacts_);
}

void ReviewExportPage::run_qc() {
    IReviewActions* acts = actions();
    if (acts == nullptr) {
        QMessageBox::warning(this, QStringLiteral("质检"),
                             QStringLiteral("未绑定工程"));
        return;
    }
    const domain::Json docs = acts->paleomap_documents();
    if (!docs.is_array() || docs.empty()) {
        QMessageBox::information(
            this, QStringLiteral("质检"),
            QStringLiteral(
                "工程中尚无古地理图草稿，请先编图或生成演示草稿"));
        return;
    }
    int ran = 0;
    for (const auto& doc : docs) {
        const auto it = doc.find("id");
        const std::string doc_id =
            (doc.is_object() && it != doc.end() && it->is_string())
                ? it->get<std::string>()
                : std::string();
        if (doc_id.empty()) {
            continue;
        }
        acts->run_map_qc(doc_id);
        ++ran;
    }
    refresh_from_project();
    emit reports_updated();
    QMessageBox::information(this, QStringLiteral("质检完成"),
                             QString::fromStdString(
                                 review_run_done_text(ran)));
}

void ReviewExportPage::export_report() {
    IReviewActions* acts = actions();
    const domain::Json reports =
        acts != nullptr ? acts->active_quality_reports() : reports_;
    if (!reports.is_array() || reports.empty()) {
        QMessageBox::information(
            this, QStringLiteral("导出"),
            QStringLiteral("暂无质检报告可导出，请先运行检查"));
        return;
    }
    const domain::Json& report = reports.front();
    const std::string start_dir =
        acts != nullptr ? acts->default_export_dir() : std::string(".");
    const std::string suggested =
        (std::filesystem::path(start_dir) /
         review_report_filename(report))
            .string();
    const QString path = QFileDialog::getSaveFileName(
        this, QStringLiteral("导出质检报告"),
        QString::fromStdString(suggested),
        QStringLiteral("JSON (*.json)"));
    if (path.isEmpty()) {
        return;
    }
    if (acts != nullptr) {
        const auto error =
            acts->export_report_json(report, path.toStdString());
        if (!error.ok()) {
            QMessageBox::warning(
                this, QStringLiteral("导出失败"),
                QString::fromStdString(error.message));
            return;
        }
    }
    refresh_from_project();
    emit reports_updated();
    QMessageBox::information(
        this, QStringLiteral("导出完成"),
        QStringLiteral("已导出: ") +
            QString::fromStdString(
                std::filesystem::path(path.toStdString())
                    .filename()
                    .string()));
}

void ReviewExportPage::on_config() {
    QMessageBox::information(this, QStringLiteral("质检规则"),
                             QString::fromStdString(
                                 review_config_text()));
}

void ReviewExportPage::finalize_version() {
    IReviewActions* acts = actions();
    if (acts == nullptr) {
        QMessageBox::warning(this, QStringLiteral("专家定稿"),
                             QStringLiteral("未绑定工程"));
        return;
    }
    const domain::Json docs = acts->paleomap_documents();
    if (!docs.is_array() || docs.empty()) {
        QMessageBox::information(
            this, QStringLiteral("专家定稿"),
            QStringLiteral("工程中尚无古地理图可定稿"));
        return;
    }
    const domain::Json reports = acts->active_quality_reports();
    const auto target = review_finalize_target(reports, docs);
    if (!target) {
        QMessageBox::information(
            this, QStringLiteral("专家定稿"),
            QStringLiteral("工程中尚无古地理图可定稿"));
        return;
    }
    const auto id_it = target->find("id");
    const auto name_it = target->find("name");
    const std::string doc_id =
        (id_it != target->end() && id_it->is_string())
            ? id_it->get<std::string>()
            : std::string();
    const std::string doc_name =
        (name_it != target->end() && name_it->is_string())
            ? name_it->get<std::string>()
            : std::string();
    auto result = acts->finalize_map_version(doc_id);
    if (!result) {
        QMessageBox::warning(this, QStringLiteral("定稿失败"),
                             QString::fromStdString(
                                 result.error().message));
        return;
    }
    refresh_from_project();
    emit version_finalized();
    emit reports_updated();
    QMessageBox::information(
        this, QStringLiteral("定稿完成"),
        QString::fromStdString(
            review_finalize_done_text(doc_name, result.value())));
}

void ReviewExportPage::refresh_from_project() {
    IReviewActions* acts = actions();
    if (acts == nullptr) {
        return;
    }
    update_state(acts->active_quality_reports(),
                 acts->paleomap_documents(), acts->export_artifacts());
}

}  // namespace pwb::ui_review::qt
