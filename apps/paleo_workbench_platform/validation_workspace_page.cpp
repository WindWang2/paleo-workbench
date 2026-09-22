#include "validation_workspace_page.hpp"

#include <algorithm>
#include <array>

#include <QFrame>
#include <QHBoxLayout>
#include <QLabel>
#include <QPushButton>
#include <QSplitter>
#include <QTabWidget>
#include <QTableWidget>
#include <QVariant>
#include <QVBoxLayout>

#include <pwb/ui_map/display_map_canvas.hpp>
#include <pwb/ui_review/qt/qc_issue_table.hpp>
#include <pwb/ui_review/qc_issue_rows.hpp>
#include <pwb/ui_review/review_core.hpp>
#include <pwb/ui_widgets/interactive_qc_hub.hpp>

namespace pwb::app {

namespace {

// Honest M5 placeholder surface — named gap, never a fake implementation.
QWidget* m5_placeholder(const QString& title, const QString& body,
                        QWidget* parent) {
    auto* frame = new QFrame(parent);
    frame->setObjectName(QStringLiteral("M5Placeholder"));
    auto* layout = new QVBoxLayout(frame);
    auto* title_label = new QLabel(title, frame);
    title_label->setObjectName(QStringLiteral("M5PlaceholderTitle"));
    auto* body_label = new QLabel(body, frame);
    body_label->setObjectName(QStringLiteral("M5PlaceholderBody"));
    body_label->setWordWrap(true);
    layout->addWidget(title_label);
    layout->addWidget(body_label, 1);
    return frame;
}

QVariantMap issue_to_variant(const pwb::domain::Json& issue) {
    QVariantMap map;
    auto set_str = [&map, &issue](const char* key, const char* qkey) {
        const auto it = issue.find(key);
        if (it != issue.end() && it->is_string()) {
            map.insert(QString::fromLatin1(qkey),
                       QString::fromStdString(it->get<std::string>()));
        }
    };
    set_str("rule", "rule");
    set_str("severity", "severity");
    set_str("message", "message");
    set_str("feature_id", "feature_id");
    set_str("feature_kind", "feature_kind");
    // M5 stable review identity (ui_review::qc_issue_key — the canonical
    // definition the closure_review persistence also uses).
    map.insert(QStringLiteral("key"),
               QString::fromStdString(pwb::ui_review::qc_issue_key(issue)));
    // locate point [x, y] (review_qc_core issue_locate_point parity).
    const auto geom_it = issue.find("geometry");
    if (geom_it != issue.end() && geom_it->is_object()) {
        const auto loc_it = geom_it->find("locate");
        if (loc_it != geom_it->end() && loc_it->is_array() &&
            loc_it->size() >= 2) {
            QVariantList point;
            point << loc_it->at(0).get<double>()
                  << loc_it->at(1).get<double>();
            map.insert(QStringLiteral("locate"), point);
        }
    }
    return map;
}

}  // namespace

ValidationWorkspacePage::ValidationWorkspacePage(QWidget* parent)
    : QWidget(parent) {
    setObjectName(QStringLiteral("ValidationWorkspacePage"));
    auto* outer = new QHBoxLayout(this);
    outer->setContentsMargins(0, 0, 0, 0);
    outer->setSpacing(0);

    auto* left_split = new QSplitter(Qt::Vertical, this);
    auto* compare_split = new QSplitter(Qt::Horizontal, this);

    // Read-only comparison map (its own isolated MapSession — the main
    // canvas authority is never touched by validation pan/zoom).
    map_ = new pwb::ui_map::DisplayMapCanvas(compare_split);

    // Seismic comparison pane slot — the host injects the real viewer.
    seismic_host_ = new QWidget(compare_split);
    seismic_host_->setObjectName(QStringLiteral("ValidationSeismicHost"));
    auto* seismic_layout = new QVBoxLayout(seismic_host_);
    seismic_layout->setContentsMargins(0, 0, 0, 0);
    seismic_empty_ = new QLabel(
        QStringLiteral("地震剖面对照（打开工程并载入体版本后出现）"),
        seismic_host_);
    seismic_empty_->setObjectName(QStringLiteral("ValidationSeismicEmpty"));
    seismic_empty_->setAlignment(Qt::AlignCenter);
    seismic_layout->addWidget(seismic_empty_);

    compare_split->addWidget(map_);
    compare_split->addWidget(seismic_host_);
    compare_split->setStretchFactor(0, 3);
    compare_split->setStretchFactor(1, 2);

    // Structured issue list (the same QcIssueTable the review surface
    // uses — one issue schema, no second table).
    table_ = new pwb::ui_review::qt::QcIssueTable(left_split);
    connect(table_->table(), &QTableWidget::cellClicked, this,
            [this](int row, int column) { locate_rule_row(row, column); });

    left_split->addWidget(compare_split);
    left_split->addWidget(table_);
    left_split->setStretchFactor(0, 3);
    left_split->setStretchFactor(1, 2);

    // Right rail: review detail + the two explicit M5 gaps.
    hub_ = new pwb::ui_widgets::InteractiveQCHub(this);
    right_tabs_ = new QTabWidget(this);
    right_tabs_->setObjectName(QStringLiteral("ValidationRightTabs"));
    right_tabs_->addTab(hub_, QStringLiteral("复核详情"));
    right_tabs_->addTab(
        m5_placeholder(QStringLiteral("解释 vs 预测对比视图"),
                       QStringLiteral(
                           "M5 范围：并排/叠加/差异三模式对照（解释版本 vs "
                           "预测成果），数据源为 StratigraphyCorrelationPage "
                           "解释版本 + WellLogPredictionPage 预测成果。"),
                       this),
        QStringLiteral("对比视图（M5）"));
    right_tabs_->addTab(
        m5_placeholder(QStringLiteral("问题级人工复核状态机"),
                       QStringLiteral(
                           "M5 范围：通过/未通过/待复核/未执行/不适用/已过期 "
                           "状态词汇；复核备注必填；输入版本变化时旧报告标记"
                           "已过期。已复核 ≠ 检查通过。"),
                       this),
        QStringLiteral("复核记录（M5）"));

    auto* run = new QPushButton(QStringLiteral("运行检查"), this);
    run->setObjectName(QStringLiteral("ValidationRunQc"));
    run->setToolTip(QStringLiteral("对工程内全部编图文档运行 QC 规则"));
    connect(run, &QPushButton::clicked, this,
            [this] { run_qc(); });
    auto* right_column = new QWidget(this);
    auto* right_layout = new QVBoxLayout(right_column);
    right_layout->setContentsMargins(0, 0, 0, 0);
    right_layout->setSpacing(2);
    right_layout->addWidget(run, 0, Qt::AlignRight);
    right_layout->addWidget(right_tabs_, 1);

    outer->addWidget(left_split, 1);
    outer->addWidget(right_column);

    // Issue click → smooth pan on the read-only map (locate point padded
    // 10% — core::kFocusPad parity). Never a text-only popup. Selection
    // also feeds the M5 review panel (issue_selected).
    pan_ = new pwb::ui_widgets::SmoothPanController(this);
    connect(hub_, &pwb::ui_widgets::InteractiveQCHub::issue_focused, this,
            [this](const QVariantMap& issue) {
                emit issue_selected(issue);
                locate_issue(issue);
            });
}

ValidationWorkspacePage::~ValidationWorkspacePage() {
    if (map_ != nullptr) map_->shutdown();
}

void ValidationWorkspacePage::set_seismic_pane(QWidget* pane) {
    if (pane == nullptr) return;
    pane->setParent(seismic_host_);
    if (auto* layout = qobject_cast<QVBoxLayout*>(seismic_host_->layout())) {
        layout->addWidget(pane);
    }
    seismic_empty_->hide();
}

void ValidationWorkspacePage::set_compare_view(QWidget* view) {
    if (view == nullptr || right_tabs_ == nullptr) return;
    const int index = right_tabs_->indexOf(compare_view_);
    const int at = index >= 0 ? index : 1;
    if (auto* old = right_tabs_->widget(at)) {
        right_tabs_->removeTab(at);
        old->deleteLater();
    }
    compare_view_ = view;
    right_tabs_->insertTab(at, view, QStringLiteral("对比视图"));
}

void ValidationWorkspacePage::set_review_panel(QWidget* panel) {
    if (panel == nullptr || right_tabs_ == nullptr) return;
    const int index = right_tabs_->indexOf(review_panel_);
    const int at = index >= 0 ? index : 2;
    if (auto* old = right_tabs_->widget(at)) {
        right_tabs_->removeTab(at);
        old->deleteLater();
    }
    review_panel_ = panel;
    right_tabs_->insertTab(at, panel, QStringLiteral("复核记录"));
}

void ValidationWorkspacePage::set_actions_provider(
    std::function<pwb::ui_review::IReviewActions*()> provider) {
    actions_provider_ = std::move(provider);
}

void ValidationWorkspacePage::update_reports(
    const std::vector<pwb::domain::Json>& reports) {
    reports_ = reports;
    table_->update_state(reports);
    // The hub carries the per-issue detail/fix surface (one issue list,
    // converted from the same report payload).
    QList<QVariantMap> issues;
    if (!reports.empty()) {
        const auto& report = reports.front();
        const auto it = report.find("issues");
        if (it != report.end() && it->is_array()) {
            for (const auto& issue : *it) {
                if (issue.is_object()) issues.push_back(issue_to_variant(issue));
            }
        }
    }
    hub_->set_issues(QStringLiteral("map_qc"), issues);
    emit reports_refreshed();
}

void ValidationWorkspacePage::run_qc() {
    pwb::ui_review::IReviewActions* actions =
        actions_provider_ != nullptr ? actions_provider_() : nullptr;
    if (actions == nullptr) {
        emit status_message(QStringLiteral("验证：请先打开工程"));
        return;
    }
    const pwb::domain::Json docs = actions->paleomap_documents();
    if (!docs.is_array() || docs.empty()) {
        emit status_message(QStringLiteral("验证：工程内没有编图文档"));
        return;
    }
    int ran = 0;
    for (const auto& doc : docs) {
        const auto id_it = doc.find("id");
        if (id_it == doc.end() || !id_it->is_string()) continue;
        const auto error = actions->run_map_qc(id_it->get<std::string>());
        if (!error.ok()) {
            emit status_message(QStringLiteral("验证：QC 运行失败 — %1")
                                    .arg(QString::fromStdString(
                                        error.message)));
            return;
        }
        ++ran;
    }
    update_reports(actions->active_quality_reports());
    emit status_message(QString::fromStdString(
        pwb::ui_review::review_run_done_text(ran)));
}

void ValidationWorkspacePage::locate_issue(const QVariantMap& issue) {
    const QVariant point = issue.value(QStringLiteral("locate"));
    if (point.typeId() != QMetaType::QVariantList ||
        point.toList().size() < 2) {
        emit status_message(
            QStringLiteral("该问题没有可定位的几何信息"));
        return;
    }
    const double x = point.toList().at(0).toDouble();
    const double y = point.toList().at(1).toDouble();
    pwb::ui_widgets::PanCanvas canvas;
    canvas.view_extent = [this]() -> std::array<double, 4> {
        return map_->view_extent();
    };
    canvas.set_extent = [this](const std::array<double, 4>& extent,
                               bool record, bool coalesce) {
        map_->set_extent(extent, record, coalesce);
    };
    // Pad around the locate point (10% of the current view span — the
    // padded_bbox contract needs a bbox; a degenerate point bbox works).
    const auto view = map_->view_extent();
    const double span_x = std::max(view[2] - view[0], 1e-9);
    const double span_y = std::max(view[3] - view[1], 1e-9);
    const std::vector<double> bbox = {
        x - span_x * 0.05, y - span_y * 0.05,
        x + span_x * 0.05, y + span_y * 0.05,
    };
    pan_->pan_to_extent(canvas, bbox);
}

void ValidationWorkspacePage::locate_rule_row(int row, int /*column*/) {
    // One table row per rule: locate the first spatial issue of that rule
    // (the QcIssueTable keeps the locatable issues per rule) and publish
    // it to the M5 review panel as the current selection.
    if (row < 0 || reports_.empty()) return;
    const auto& report = reports_.front();
    const auto rules_it = report.find("rules");
    if (rules_it == report.end() || !rules_it->is_array() ||
        row >= static_cast<int>(rules_it->size())) {
        return;
    }
    const auto& rule = rules_it->at(static_cast<size_t>(row));
    const auto name_it = rule.find("rule");
    if (name_it == rule.end() || !name_it->is_string()) return;
    const auto issues = table_->spatial_issues_for_rule(
        name_it->get<std::string>());
    for (const auto& issue : issues) {
        const QVariantMap variant = issue_to_variant(issue);
        if (variant.contains(QStringLiteral("locate"))) {
            emit issue_selected(variant);
            locate_issue(variant);
            return;
        }
    }
    emit status_message(QStringLiteral("该检查项没有空间定位信息"));
}

}  // namespace pwb::app
