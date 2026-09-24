#include "pwb/ui_review/qt/catalog_health_dialog.hpp"

#include <pwb/qgis_processing/job_compat.hpp>
#include "pwb/ui_review/audit_summary.hpp"
#include "pwb/ui_review/tokens.hpp"
#include "pwb/ui_widgets/object_table.hpp"
#include "pwb/ui_widgets/states.hpp"

#include <QCloseEvent>
#include <QHBoxLayout>
#include <QHeaderView>
#include <QLabel>
#include <QPushButton>
#include <QResizeEvent>
#include <QTableView>
#include <QVBoxLayout>

namespace pwb::ui_review::qt {

// Table row object: Python rows are (stable_key, issue) pairs — the key
// mirrors f"{i}:{issue.kind}:{issue.ref_id}". Named (non-anonymous)
// scope so Q_DECLARE_METATYPE can resolve it for QVariant::fromValue.
struct AuditIssueRow {
    QString key;
    catalog::AuditIssue issue;
};

CatalogHealthDialog::CatalogHealthDialog(
    QWidget* parent, std::function<ICatalogApi*()> service_provider)
    : QDialog(parent), service_provider_(std::move(service_provider)) {
    setWindowTitle(QStringLiteral("数据健康检查 (Catalog Health)"));
    resize(760, 520);
    job_ = std::make_unique<pwb::qgis_processing::PwbTaskOwner>(this);

    auto* layout = new QVBoxLayout(this);
    layout->setSpacing(tokens::kSpace2);

    summary_label_ = new QLabel(QStringLiteral("尚未运行检查"), this);
    summary_label_->setWordWrap(true);
    summary_label_->setObjectName(QStringLiteral("WorkstationPanelTitle"));
    layout->addWidget(summary_label_);

    model_ = new ui_widgets::ObjectTableModel(
        {ui_widgets::ColumnSpec{
             QStringLiteral("severity"), QStringLiteral("级别"),
             [](const QVariant& row) -> QVariant {
                 const auto& issue = row.value<AuditIssueRow>().issue;
                 // "{zh} ({severity})"
                 return QString::fromUtf8(
                            audit_severity_label(issue.severity).data(),
                            int(audit_severity_label(issue.severity)
                                    .size())) +
                        " (" + QString::fromStdString(issue.severity) + ")";
             },
             {},
             Qt::AlignLeft | Qt::AlignVCenter,
             {},
             [](const QVariant& row) -> QString {
                 const char* token = audit_severity_token(
                     row.value<AuditIssueRow>().issue.severity);
                 return token != nullptr ? QString::fromLatin1(token)
                                         : QString();
             }},
         ui_widgets::ColumnSpec{
             QStringLiteral("kind"), QStringLiteral("类型"),
             [](const QVariant& row) -> QVariant {
                 return QString::fromStdString(
                     row.value<AuditIssueRow>().issue.kind);
             }},
         ui_widgets::ColumnSpec{
             QStringLiteral("ref"), QStringLiteral("对象"),
             [](const QVariant& row) -> QVariant {
                 return QString::fromStdString(
                     row.value<AuditIssueRow>().issue.ref_id);
             }},
         ui_widgets::ColumnSpec{
             QStringLiteral("detail"), QStringLiteral("详情"),
             [](const QVariant& row) -> QVariant {
                 return QString::fromStdString(
                     row.value<AuditIssueRow>().issue.detail);
             }}},
        [](const QVariant& row) { return row.value<AuditIssueRow>().key; },
        this);
    issues_table_ = new QTableView(this);
    issues_table_->setModel(model_);
    ui_widgets::bind_table_defaults(issues_table_);
    issues_table_->horizontalHeader()->setSectionResizeMode(
        QHeaderView::Stretch);
    layout->addWidget(issues_table_, 1);

    empty_state_ = new ui_widgets::PwbEmptyState(
        QStringLiteral("未发现目录健康问题"),
        QStringLiteral("可定期运行深度检查复核数据校验和。"),
        QStringLiteral("inbox.svg"), nullptr, this);
    empty_state_->setAttribute(Qt::WA_TransparentForMouseEvents);
    empty_state_->setParent(issues_table_);
    empty_state_->hide();
    connect(model_, &QAbstractItemModel::modelReset, this,
            &CatalogHealthDialog::update_empty_state);
    connect(model_, &QAbstractItemModel::rowsInserted, this,
            &CatalogHealthDialog::update_empty_state);
    connect(model_, &QAbstractItemModel::rowsRemoved, this,
            &CatalogHealthDialog::update_empty_state);

    progress_ = new ui_widgets::PwbLoadingState(QStringLiteral("正在检查…"),
                                              this);
    progress_->hide();
    layout->addWidget(progress_);

    auto* buttons = new QHBoxLayout();
    refresh_btn_ = new QPushButton(QStringLiteral("快速检查"), this);
    refresh_btn_->setObjectName(QStringLiteral("PrimaryButton"));
    connect(refresh_btn_, &QPushButton::clicked, this,
            [this]() { run_audit(false); });
    buttons->addWidget(refresh_btn_);
    deep_btn_ = new QPushButton(
        QStringLiteral("深度检查 (含 SHA-256 重哈希)"), this);
    deep_btn_->setObjectName(QStringLiteral("SecondaryButton"));
    connect(deep_btn_, &QPushButton::clicked, this,
            [this]() { run_audit(true); });
    buttons->addWidget(deep_btn_);
    relink_btn_ =
        new QPushButton(QStringLiteral("缺失源与重链接…"), this);
    relink_btn_->setObjectName(QStringLiteral("SecondaryButton"));
    connect(relink_btn_, &QPushButton::clicked, this,
            &CatalogHealthDialog::relink_requested);
    buttons->addWidget(relink_btn_);
    buttons->addStretch();
    auto* close_btn = new QPushButton(QStringLiteral("关闭"), this);
    connect(close_btn, &QPushButton::clicked, this, &QDialog::accept);
    buttons->addWidget(close_btn);
    layout->addLayout(buttons);
}

CatalogHealthDialog::~CatalogHealthDialog() = default;

void CatalogHealthDialog::run_audit(bool deep) {
    ICatalogApi* service = service_provider_ ? service_provider_() : nullptr;
    if (service == nullptr) {
        summary_label_->setText(
            QStringLiteral("未连接数据目录（请先打开项目）"));
        return;
    }
    if (job_->is_running()) {
        return;
    }
    set_running(true);
    const QString busy =
        QString::fromUtf8(audit_busy_text(deep).data(),
                          int(audit_busy_text(deep).size()));
    progress_->set_text(busy);
    summary_label_->setText(busy);

    job::JobSpec spec;
    spec.title = deep ? "catalog audit (deep)" : "catalog audit";
    spec.run = [service, deep](job::JobContext& ctx) -> std::any {
        return service->audit(deep, [&ctx] {
            return ctx.token().is_cancelled();
        });
    };
    pwb::qgis_processing::start_job_spec(
        *job_, std::move(spec),
        [this](const pwb::qgis_processing::CompatJobOutcome& outcome) {
            set_running(false);
            switch (outcome.state) {
            case job::JobState::done:
            case job::JobState::degraded:
                update_report(
                    std::any_cast<catalog::AuditReport>(outcome.result));
                break;
            case job::JobState::failed:
                summary_label_->setText(
                    QStringLiteral("检查失败: ") +
                    QString::fromStdString(outcome.error));
                break;
            case job::JobState::cancelled:
                summary_label_->setText(QStringLiteral("已取消检查"));
                break;
            default:
                break;
            }
        });
}

void CatalogHealthDialog::cancel_running_audit() {
    if (job_ != nullptr && job_->is_running()) {
        // Cooperative cancel + bounded join (Python shutdown(wait_ms=3000)
        // parity): deep hashing checks the token between payloads; a huge
        // payload overshooting the wait detaches to the keeper with the
        // token already set.
        job_->shutdown(3000);
    }
}

void CatalogHealthDialog::closeEvent(QCloseEvent* event) {
    cancel_running_audit();
    QDialog::closeEvent(event);
}

void CatalogHealthDialog::reject() {
    cancel_running_audit();
    QDialog::reject();
}

void CatalogHealthDialog::set_running(bool running) {
    progress_->setVisible(running);
    refresh_btn_->setEnabled(!running);
    deep_btn_->setEnabled(!running);
}

void CatalogHealthDialog::update_report(const catalog::AuditReport& report) {
    summary_label_->setText(
        QString::fromStdString(audit_summary_line(report)) + "\n" +
        QString::fromUtf8(audit_verdict(report.ok()).data(),
                          int(audit_verdict(report.ok()).size())));

    const auto issues = audit_issues_sorted(report.issues);
    std::vector<QVariant> rows;
    rows.reserve(issues.size());
    for (std::size_t i = 0; i < issues.size(); ++i) {
        // Stable key mirrors Python's f"{i}:{issue.kind}:{issue.ref_id}".
        AuditIssueRow row;
        row.key = QString::fromStdString(std::to_string(i) + ":" +
                                         issues[i].kind + ":" +
                                         issues[i].ref_id);
        row.issue = issues[i];
        rows.push_back(QVariant::fromValue(row));
    }
    model_->set_rows(rows);
}

void CatalogHealthDialog::resizeEvent(QResizeEvent* event) {
    QDialog::resizeEvent(event);
    if (empty_state_->isVisible()) {
        empty_state_->setGeometry(issues_table_->viewport()->rect());
    }
}

void CatalogHealthDialog::update_empty_state() {
    if (model_->rowCount() == 0) {
        empty_state_->setGeometry(issues_table_->viewport()->rect());
        empty_state_->show();
        empty_state_->raise();
    } else {
        empty_state_->hide();
    }
}

}  // namespace pwb::ui_review::qt

Q_DECLARE_METATYPE(pwb::ui_review::qt::AuditIssueRow)
