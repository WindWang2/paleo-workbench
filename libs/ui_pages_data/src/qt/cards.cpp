// UI-06 — card shells (see qt/cards.hpp). Display strings come from the
// Qt-free cores; styling mirrors the Python style.bind lambdas 1:1.
#include <pwb/ui_pages_data/qt/cards.hpp>

#include <QPushButton>

#include <pwb/ui_pages_data/onboarding_report.hpp>
#include <pwb/ui_pages_data/readiness.hpp>
#include <pwb/ui_pages_data/vocab.hpp>
#include <pwb/ui_shell/style_registry.hpp>

namespace pwb::ui_pages_data::qt {
namespace {

QString pal(const char* token) {
    const auto p = ui_shell::style_palette();
    const auto it = p.find(token);
    return it != p.end() ? QString::fromStdString(it->second) : QString();
}

QString title_qss() {
    return QStringLiteral("color: %1; font-size: 14px; font-weight: 600;")
        .arg(pal("TEXT_PRIMARY"));                       // FONT_SIZE_TITLE
}

QString time_qss() {
    return QStringLiteral("color: %1; font-size: 11px;")
        .arg(pal("TEXT_SECONDARY"));                     // FONT_SIZE_STATUS
}

QString desc_qss() {
    // 12.5px 历史微调值（无对应刻度 token，保留字面量 — Python 同款）。
    return QStringLiteral("color: %1; font-size: 12.5px;")
        .arg(pal("TEXT_PRIMARY"));
}

QLabel* bound_label(const QString& text, std::function<QString()> render,
                    QWidget* parent = nullptr) {
    auto* label = new QLabel(text, parent);
    ui_shell::style_bind(label, std::move(render));
    return label;
}

}  // namespace

// ---------------------------------------------------------------------------
// RecentActivityCard

RecentActivityCard::RecentActivityCard(QWidget* parent) : QFrame(parent) {
    setObjectName(QStringLiteral("PanelCard"));
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(20, 20, 20, 20);  // SPACE_4
    layout->setSpacing(8);                       // SPACE_2
    auto* title = bound_label(QStringLiteral("最近活动"), title_qss, this);
    layout->addWidget(title);
    auto* scroll = new QScrollArea(this);
    scroll->setWidgetResizable(true);
    scroll->setFrameShape(QFrame::Shape::NoFrame);
    auto* entries = new QWidget();
    entries_layout_ = new QVBoxLayout(entries);
    entries_layout_->setContentsMargins(0, 0, 0, 0);
    entries_layout_->setSpacing(4);              // SPACE_1
    entries->setLayout(entries_layout_);
    scroll->setWidget(entries);
    layout->addWidget(scroll, 1);
    empty_label_ = new QLabel(QStringLiteral("暂无活动"), entries);
    empty_label_->setObjectName(QStringLiteral("EmptyStateLabel"));
    entries_layout_->addWidget(empty_label_);
}

void RecentActivityCard::update_state(const domain::Json& state,
                                      const std::vector<ActivityStep>& steps) {
    clear_entries();
    int count = 0;
    for (const auto& e : compute_activity_entries(state, steps)) {
        count += append_entry(QString::fromStdString(e.when),
                              QString::fromStdString(e.description));
    }
    if (count > 0) {
        empty_label_->hide();
    } else {
        empty_label_->show();
    }
    entry_count_ = count;
}

int RecentActivityCard::append_entry(const QString& when,
                                     const QString& description) {
    auto* time_label = bound_label(when, time_qss);
    auto* desc_label = bound_label(description, desc_qss);
    auto* entry_layout = new QHBoxLayout();
    entry_layout->setContentsMargins(0, 0, 0, 0);
    entry_layout->setSpacing(8);                 // SPACE_2
    entry_layout->addWidget(time_label);
    entry_layout->addWidget(desc_label, 1);
    auto* entry_widget = new QWidget();
    entry_widget->setLayout(entry_layout);
    entries_layout_->addWidget(entry_widget);
    entry_widgets_.push_back(entry_widget);
    return 1;
}

void RecentActivityCard::clear_entries() {
    for (QWidget* entry : entry_widgets_) {
        entries_layout_->removeWidget(entry);
        entry->deleteLater();
    }
    entry_widgets_.clear();
}

// ---------------------------------------------------------------------------
// ResourceSummaryBar

ResourceSummaryBar::ResourceSummaryBar(QWidget* parent) : QFrame(parent) {
    setObjectName(QStringLiteral("PanelCard"));
    auto* layout = new QHBoxLayout(this);
    // Compact single-line strip (UI v2) — Python margins verbatim.
    layout->setContentsMargins(12, 4, 12, 4);    // SPACE_3 / SPACE_1
    layout->setSpacing(12);                      // SPACE_3
    for (const std::string_view rtype : kRequiredResourceTypes) {
        auto* group = new QWidget(this);
        auto* group_layout = new QHBoxLayout(group);
        group_layout->setContentsMargins(0, 0, 0, 0);
        group_layout->setSpacing(4);             // SPACE_1
        auto* name_label = bound_label(
            QString::fromStdString(std::string(resource_label(rtype))),
            [this] {
                return QStringLiteral("color: %1; font-size: 12px;")
                    .arg(pal("TEXT_SECONDARY")); // FONT_SIZE_MINOR
            },
            group);
        group_layout->addWidget(name_label);
        auto* count_label = bound_label(
            QStringLiteral("0%1").arg(QString::fromStdString(
                std::string(resource_unit(rtype)))),
            [this] {
                return QStringLiteral(
                           "color: %1; font-size: 12px; font-weight: 500;")
                    .arg(pal("TEXT_PRIMARY"));
            },
            group);
        group_layout->addWidget(count_label);
        count_labels_.push_back(count_label);
        layout->addWidget(group);
    }
    layout->addStretch();
    status_label_ = new QLabel(QStringLiteral("—"), this);
    ui_shell::style_bind(status_label_, [this] { return status_qss(); });
    layout->addWidget(status_label_);
}

QString ResourceSummaryBar::status_qss() const {
    if (ready_ < 0) {
        return QStringLiteral("color: %1; font-size: 12px;")
            .arg(pal("TEXT_SECONDARY"));
    }
    const QString token = ready_ ? QStringLiteral("SUCCESS")
                                 : QStringLiteral("ERROR_RED");
    return QStringLiteral("color: %1; font-size: 12px; font-weight: 500;")
        .arg(pal(token.toUtf8().constData()));
}

void ResourceSummaryBar::update_state(const domain::Json& state) {
    const ResourceReadinessView view = format_resource_readiness(state);
    for (std::size_t i = 0; i < view.rows.size() && i < count_labels_.size();
         ++i) {
        count_labels_[i]->setText(
            QString::fromStdString(view.rows[i].count_label));
    }
    status_label_->setText(QString::fromStdString(view.status_line));
    ready_ = view.ready ? 1 : 0;
    ui_shell::style_refresh(status_label_);
}

// ---------------------------------------------------------------------------
// DataCompletenessCard

DataCompletenessCard::DataCompletenessCard(QWidget* parent) : QFrame(parent) {
    setObjectName(QStringLiteral("PanelCard"));
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(20, 20, 20, 20);  // SPACE_4
    layout->setSpacing(8);                       // SPACE_2
    auto* title = bound_label(QStringLiteral("数据完整度"), title_qss, this);
    layout->addWidget(title);
    for (const std::string_view rtype : kRequiredResourceTypes) {
        auto* name_label = bound_label(
            QString::fromStdString(std::string(resource_label(rtype))),
            [this] {
                return QStringLiteral("color: %1; font-size: 13px;")
                    .arg(pal("TEXT_PRIMARY"));   // FONT_SIZE_BASE
            });
        auto* count_label = bound_label(
            QStringLiteral("0%1").arg(QString::fromStdString(
                std::string(resource_unit(rtype)))),
            [this] {
                return QStringLiteral("color: %1; font-size: 11px;")
                    .arg(pal("TEXT_SECONDARY"));
            });
        auto* status_label = new QLabel(QStringLiteral("—"));
        row_ready_.push_back(-1);
        const int row_index = static_cast<int>(row_ready_.size()) - 1;
        ui_shell::style_bind(status_label, [this, row_index] {
            if (row_ready_[row_index] < 0) {
                return QStringLiteral("color: %1; font-size: 14px;")
                    .arg(pal("TEXT_SECONDARY"));
            }
            const QString token = row_ready_[row_index]
                                      ? QStringLiteral("SUCCESS")
                                      : QStringLiteral("ERROR_RED");
            return QStringLiteral(
                       "color: %1; font-size: 11px; font-weight: 500;")
                .arg(pal(token.toUtf8().constData()));
        });
        auto* row_layout = new QHBoxLayout();
        row_layout->setContentsMargins(0, 0, 0, 0);
        row_layout->setSpacing(8);               // SPACE_2
        row_layout->addWidget(name_label, 1);
        row_layout->addWidget(count_label);
        row_layout->addWidget(status_label);
        auto* row_widget = new QFrame(this);
        row_widget->setLayout(row_layout);
        count_labels_.push_back(count_label);
        status_labels_.push_back(status_label);
        layout->addWidget(row_widget);
    }
    summary_label_ = new QLabel(QStringLiteral("—"), this);
    ui_shell::style_bind(summary_label_, [this] { return summary_qss(); });
    layout->addWidget(summary_label_);
    layout->addStretch();
}

QString DataCompletenessCard::summary_qss() const {
    if (summary_tone_.isEmpty()) {
        return QStringLiteral("color: %1; font-size: 11px;")
            .arg(pal("TEXT_SECONDARY"));
    }
    const QString token = summary_tone_ == QLatin1String("ok")
                              ? QStringLiteral("SUCCESS")
                              : QStringLiteral("ERROR_RED");
    return QStringLiteral("color: %1; font-size: 11px; font-weight: 500;")
        .arg(pal(token.toUtf8().constData()));
}

void DataCompletenessCard::update_state(const domain::Json& state) {
    const ResourceReadinessView view = format_resource_readiness(state);
    for (std::size_t i = 0; i < view.rows.size() && i < status_labels_.size();
         ++i) {
        count_labels_[i]->setText(
            QString::fromStdString(view.rows[i].count_label));
        status_labels_[i]->setText(
            QString::fromStdString(view.rows[i].status_label));
        row_ready_[i] = view.rows[i].ready ? 1 : 0;
        ui_shell::style_refresh(status_labels_[i]);
    }
    summary_label_->setText(QString::fromStdString(view.status_line));
    summary_tone_ = view.ready ? QStringLiteral("ok") : QStringLiteral("missing");
    ui_shell::style_refresh(summary_label_);
}

// ---------------------------------------------------------------------------
// OnboardingReportCard

OnboardingReportCard::OnboardingReportCard(QWidget* parent) : QFrame(parent) {
    setObjectName(QStringLiteral("OnboardingReportCard"));
    ui_shell::style_bind(this, [] {
        return QStringLiteral(
                   "QFrame#OnboardingReportCard { background: %1;"
                   " border: 1px solid %2; border-radius: 4px; }")
            .arg(pal("BG_SIDEBAR"), pal("BORDER"));  // RADIUS_CARD
    });
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(20, 20, 20, 20);  // SPACE_4
    layout->setSpacing(8);                       // SPACE_2
    auto* title = bound_label(QStringLiteral("数据盘点报告"), title_qss, this);
    title->setObjectName(QStringLiteral("report_title_label"));
    layout->addWidget(title);
    auto make = [&](const char* name, std::function<QString()> render) {
        auto* l = bound_label(QString(), std::move(render), this);
        l->setObjectName(QLatin1String(name));
        l->setWordWrap(true);
        layout->addWidget(l);
        return l;
    };
    source_label_ = make("report_source_label", time_qss);
    summary_label_ = make("report_summary_label", [this] {
        return QStringLiteral("color: %1; font-size: 13px;")
            .arg(pal("TEXT_PRIMARY"));
    });
    by_type_label_ = make("report_by_type_label", time_qss);
    extent_label_ = make("report_extent_label", time_qss);
    issues_label_ = make("report_issues_label", [this] {
        return QStringLiteral("color: %1; font-size: 11px;")
            .arg(pal("WARNING"));
    });
    warnings_label_ = make("report_warnings_label", [this] {
        return QStringLiteral("color: %1; font-size: 11px;")
            .arg(pal("WARNING"));
    });
    setVisible(false);
}

void OnboardingReportCard::set_report(const domain::Json& report) {
    const OnboardingReportView view = format_onboarding_report(report);
    setVisible(view.card_visible);
    if (!view.card_visible) return;
    source_label_->setText(QString::fromStdString(view.source.text));
    source_label_->setVisible(view.source.visible);
    summary_label_->setText(QString::fromStdString(view.summary.text));
    summary_label_->setVisible(view.summary.visible);
    by_type_label_->setText(QString::fromStdString(view.by_type.text));
    by_type_label_->setVisible(view.by_type.visible);
    extent_label_->setText(QString::fromStdString(view.extent.text));
    extent_label_->setVisible(view.extent.visible);
    // Python keeps two labels but always hides warnings_label when
    // combined lines exist (or when empty) — mirror that exactly.
    issues_label_->setText(QString::fromStdString(view.issues.text));
    issues_label_->setVisible(view.issues.visible);
    warnings_label_->setVisible(false);
}

// ---------------------------------------------------------------------------
// StartGuideCard

StartGuideCard::StartGuideCard(QWidget* parent) : QFrame(parent) {
    setObjectName(QStringLiteral("PanelCard"));
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(20, 20, 20, 20);  // SPACE_4
    layout->setSpacing(8);                       // SPACE_2
    auto* title = bound_label(
        QStringLiteral("开始使用 Paleogeography Workbench"), title_qss, this);
    layout->addWidget(title);
    auto* subtitle = bound_label(
        QStringLiteral(
            "新建工程从数据文件夹自动构建工区，或打开已有工程文件。"),
        [this] {
            return QStringLiteral("color: %1; font-size: 12px;")
                .arg(pal("TEXT_SECONDARY"));
        },
        this);
    subtitle->setWordWrap(true);
    layout->addWidget(subtitle);
    auto* btn_row = new QHBoxLayout();
    btn_row->setContentsMargins(0, 0, 0, 0);
    btn_row->setSpacing(8);                      // SPACE_2
    new_project_button_ = new QPushButton(QStringLiteral("新建工程"), this);
    new_project_button_->setObjectName(QStringLiteral("PrimaryButton"));
    connect(new_project_button_, &QPushButton::clicked, this,
            &StartGuideCard::new_project_requested);
    btn_row->addWidget(new_project_button_);
    open_project_button_ = new QPushButton(QStringLiteral("打开工程"), this);
    open_project_button_->setObjectName(QStringLiteral("SecondaryButton"));
    connect(open_project_button_, &QPushButton::clicked, this,
            &StartGuideCard::open_project_requested);
    btn_row->addWidget(open_project_button_);
    open_sample_button_ = new QPushButton(QStringLiteral("打开样例工程"), this);
    open_sample_button_->setObjectName(QStringLiteral("SecondaryButton"));
    connect(open_sample_button_, &QPushButton::clicked, this,
            &StartGuideCard::open_sample_requested);
    btn_row->addWidget(open_sample_button_);
    btn_row->addStretch();
    layout->addLayout(btn_row);
}

// ---------------------------------------------------------------------------
// ResultSummary

ResultSummary::ResultSummary(QWidget* parent) : QFrame(parent) {
    setObjectName(QStringLiteral("PanelCard"));
    // 侧栏宽度：保底 240，窄屏可收缩、宽屏最多 1.6 倍有界弹性。
    setMinimumWidth(240);
    setMaximumWidth(static_cast<int>(240 * 1.6));
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(12, 12, 12, 12);  // PANEL_PADDING
    layout->setSpacing(8);                       // SPACE_2
    auto* title = new QLabel(QStringLiteral("检查结果输出"), this);
    title->setObjectName(QStringLiteral("MapDockTitle"));
    layout->addWidget(title);
    pass_label_ = new QLabel(QStringLiteral("通过项: 0"), this);
    recolor(pass_label_, QStringLiteral("SUCCESS"));
    layout->addWidget(pass_label_);
    warning_label_ = new QLabel(QStringLiteral("警告项: 0"), this);
    recolor(warning_label_, QStringLiteral("WARNING"));
    layout->addWidget(warning_label_);
    error_label_ = new QLabel(QStringLiteral("待处理项: 0"), this);
    recolor(error_label_, QStringLiteral("ERROR_RED"));
    layout->addWidget(error_label_);
    advisory_label_ = new QLabel(QStringLiteral("全部通过，可输出成果"), this);
    recolor(advisory_label_, QStringLiteral("SUCCESS"));
    layout->addWidget(advisory_label_);
    auto* divider = new QFrame(this);
    divider->setFrameShape(QFrame::Shape::HLine);
    ui_shell::style_bind(divider, [] {
        return QStringLiteral("background: %1; border: none; max-height: 1px;")
            .arg(pal("BORDER"));
    });
    layout->addWidget(divider);
    auto* export_title = new QLabel(QStringLiteral("导出图件"), this);
    ui_shell::style_bind(export_title, [] {
        return QStringLiteral(
                   "color: %1; font-size: 14px; font-weight: 600;"
                   " border: none; background: transparent;")
            .arg(pal("TEXT_PRIMARY"));
    });
    layout->addWidget(export_title);
    auto* export_container = new QWidget(this);
    ui_shell::style_bind(export_container, [] {
        return QStringLiteral("border: none; background: transparent;");
    });
    export_layout_ = new QVBoxLayout(export_container);
    export_layout_->setContentsMargins(0, 0, 0, 0);
    export_layout_->setSpacing(4);               // SPACE_1
    layout->addWidget(export_container);
    layout->addStretch();
    update_state(domain::Json::array(), domain::Json::array());
}

void ResultSummary::recolor(QLabel* label, const QString& token) {
    label->setProperty("_pwb_color_token", token);
    ui_shell::style_bind(label, [label] {
        const QString t =
            label->property("_pwb_color_token").toString();
        return QStringLiteral(
                   "color: %1; font-size: 13px;"
                   " border: none; background: transparent;")
            .arg(pal(t.toUtf8().constData()));  // FONT_SIZE_BASE
    });
}

void ResultSummary::clear_export() {
    while (export_layout_->count()) {
        QLayoutItem* item = export_layout_->takeAt(0);
        if (QWidget* widget = item->widget()) {
            widget->hide();
            widget->setParent(nullptr);
            widget->deleteLater();
        }
        delete item;
    }
}

void ResultSummary::update_state(const domain::Json& reports,
                                 const domain::Json& artifacts) {
    const QcSummary summary = summarize_qc(reports, artifacts);
    pass_label_->setText(QStringLiteral("通过项: %1").arg(summary.pass_count));
    warning_label_->setText(
        QStringLiteral("警告项: %1").arg(summary.warning_count));
    error_label_->setText(
        QStringLiteral("待处理项: %1").arg(summary.error_count));
    advisory_label_->setText(QString::fromStdString(summary.advisory));
    recolor(advisory_label_,
            QString::fromStdString(summary.advisory_token));
    clear_export();
    if (summary.export_rows.empty()) {
        auto* empty = new QLabel(QStringLiteral("暂无导出图件"));
        empty->setObjectName(QStringLiteral("EmptyStateLabel"));
        export_layout_->addWidget(empty);
    } else {
        for (const auto& row : summary.export_rows) {
            auto* label = new QLabel(QString::fromStdString(row));
            recolor(label, QStringLiteral("TEXT_PRIMARY"));
            export_layout_->addWidget(label);
        }
    }
}

}  // namespace pwb::ui_pages_data::qt
