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

#include <pwb/ui_data_core/qc_helpers.hpp>
#include <pwb/ui_map/display_map_canvas.hpp>
#include <pwb/ui_review/qt/qc_issue_table.hpp>
#include <pwb/ui_review/qc_issue_rows.hpp>
#include <pwb/ui_review/review_core.hpp>
#include <pwb/ui_widgets/interactive_qc_hub.hpp>

namespace pwb::app {

namespace {

// 稿式窗格：题头 + 内容槽（页内固定区，非 dock 标题栏）。
QWidget* titled_pane(const QString& title, QWidget** host_out,
                     QWidget* parent) {
    auto* frame = new QFrame(parent);
    frame->setFrameShape(QFrame::StyledPanel);
    auto* layout = new QVBoxLayout(frame);
    layout->setContentsMargins(6, 2, 6, 4);
    layout->setSpacing(2);
    auto* header = new QLabel(title, frame);
    header->setObjectName(QStringLiteral("ValidationPaneTitle"));
    layout->addWidget(header);
    auto* host = new QWidget(frame);
    auto* host_layout = new QVBoxLayout(host);
    host_layout->setContentsMargins(0, 0, 0, 0);
    host_layout->setSpacing(0);
    layout->addWidget(host, 1);
    if (host_out != nullptr) *host_out = host;
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
    QWidget* seismic_slot = nullptr;
    auto* seismic_pane =
        titled_pane(QStringLiteral("地震剖面（两套解释对照）"),
                    &seismic_slot, compare_split);
    seismic_host_ = seismic_slot;
    seismic_host_->setObjectName(QStringLiteral("ValidationSeismicHost"));
    auto* seismic_layout =
        qobject_cast<QVBoxLayout*>(seismic_host_->layout());
    seismic_empty_ = new QLabel(
        QStringLiteral("地震剖面对照（打开工程并载入体版本后出现）"),
        seismic_host_);
    seismic_empty_->setObjectName(QStringLiteral("ValidationSeismicEmpty"));
    seismic_empty_->setAlignment(Qt::AlignCenter);
    seismic_layout->addWidget(seismic_empty_);

    compare_split->addWidget(map_);
    compare_split->addWidget(seismic_pane);
    compare_split->setStretchFactor(0, 3);
    compare_split->setStretchFactor(1, 2);

    // 井验证对比窗格（稿中列底部整宽）—— 宿主经 set_compare_view 注入
    // 真实 ComparisonView（解释 vs 预测深度带对照）。
    auto* compare_pane = titled_pane(QStringLiteral("井验证对比"),
                                     &compare_host_, left_split);
    auto* compare_layout =
        qobject_cast<QVBoxLayout*>(compare_host_->layout());
    auto* compare_empty = new QLabel(
        QStringLiteral(
            "井验证对比（选择对象/基准/成果后显示深度带对照）"),
        compare_host_);
    compare_empty->setObjectName(QStringLiteral("ValidationCompareEmpty"));
    compare_empty->setAlignment(Qt::AlignCenter);
    compare_layout->addWidget(compare_empty);

    left_split->addWidget(compare_split);
    left_split->addWidget(compare_pane);
    left_split->setStretchFactor(0, 3);
    left_split->setStretchFactor(1, 2);

    // Structured issue list (the same QcIssueTable the review surface
    // uses — one issue schema, no second table) — 稿右列上格「验证
    // 结果」。稿在表上有统计行「通过 N · 待复核 N · 未执行 N」——
    // 计数从报告真字段派生（rule_status.evaluated + issues 派生
    // severity），不是装饰。
    auto* right_split = new QSplitter(Qt::Vertical, this);
    right_split->setObjectName(QStringLiteral("ValidationRightColumn"));
    QWidget* results_host = nullptr;
    right_split->addWidget(
        titled_pane(QStringLiteral("验证结果"), &results_host, right_split));
    auto* stats_row = new QWidget(results_host);
    auto* stats_layout = new QHBoxLayout(stats_row);
    stats_layout->setContentsMargins(2, 0, 2, 2);
    stats_layout->setSpacing(10);
    stats_pass_ = new QLabel(stats_row);
    stats_pending_ = new QLabel(stats_row);
    stats_skipped_ = new QLabel(stats_row);
    stats_layout->addWidget(stats_pass_);
    stats_layout->addWidget(stats_pending_);
    stats_layout->addWidget(stats_skipped_);
    stats_layout->addStretch();
    qobject_cast<QVBoxLayout*>(results_host->layout())->addWidget(stats_row);
    table_ = new pwb::ui_review::qt::QcIssueTable(results_host);
    refresh_result_stats();
    connect(table_->table(), &QTableWidget::cellClicked, this,
            [this](int row, int column) { locate_rule_row(row, column); });
    qobject_cast<QVBoxLayout*>(results_host->layout())->addWidget(table_);

    // 稿右列下格「选中问题详情」：InteractiveQCHub（问题详情+定位）+
    // 复核处置面板（宿主经 set_review_panel 注入）。
    right_split->addWidget(titled_pane(QStringLiteral("选中问题详情"),
                                       &detail_host_, right_split));
    hub_ = new pwb::ui_widgets::InteractiveQCHub(detail_host_);
    qobject_cast<QVBoxLayout*>(detail_host_->layout())
        ->addWidget(hub_);
    right_split->setStretchFactor(0, 3);
    right_split->setStretchFactor(1, 2);

    outer->addWidget(left_split, 1);
    outer->addWidget(right_split);

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
    if (view == nullptr || compare_host_ == nullptr) return;
    auto* layout = qobject_cast<QVBoxLayout*>(compare_host_->layout());
    if (layout == nullptr) return;
    if (auto* hint = compare_host_->findChild<QLabel*>(
            QStringLiteral("ValidationCompareEmpty"),
            Qt::FindDirectChildrenOnly)) {
        hint->hide();
    }
    if (compare_view_ != nullptr) {
        layout->removeWidget(compare_view_);
        compare_view_->deleteLater();
    }
    compare_view_ = view;
    view->setParent(compare_host_);
    layout->addWidget(view);
}

void ValidationWorkspacePage::set_review_panel(QWidget* panel) {
    if (panel == nullptr || detail_host_ == nullptr) return;
    auto* layout = qobject_cast<QVBoxLayout*>(detail_host_->layout());
    if (layout == nullptr) return;
    if (review_panel_ != nullptr) {
        layout->removeWidget(review_panel_);
        review_panel_->deleteLater();
    }
    review_panel_ = panel;
    panel->setParent(detail_host_);
    layout->addWidget(panel);
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
    refresh_result_stats();
    emit reports_refreshed();
}

// 稿统计行「通过 N · 待复核 N · 未执行 N」—— 逐规则：
//   rule_status[rule].evaluated == false            → 未执行
//   评估且无 issues（derive_rule_result == pass）    → 通过
//   评估且有 issues（warning/error 尚无人工结论）    → 待复核
// 无报告时三档归零 —— 诚实缺席，不伪造通过数。
void ValidationWorkspacePage::refresh_result_stats() {
    int pass = 0;
    int pending = 0;
    int skipped = 0;
    if (!reports_.empty()) {
        const auto& report = reports_.front();
        const auto rules_it = report.find("rules");
        const auto issues_it = report.find("issues");
        const auto status_it = report.find("rule_status");
        if (rules_it != report.end() && rules_it->is_array()) {
            for (const auto& rule_json : *rules_it) {
                if (!rule_json.is_string()) continue;
                const auto rule = rule_json.get<std::string>();
                bool evaluated = true;
                if (status_it != report.end() && status_it->is_object()) {
                    const auto sit = status_it->find(rule);
                    if (sit != status_it->end() && sit->is_object()) {
                        const auto eit = sit->find("evaluated");
                        if (eit != sit->end() && eit->is_boolean()) {
                            evaluated = eit->get<bool>();
                        }
                    }
                }
                if (!evaluated) {
                    ++skipped;
                    continue;
                }
                const auto result = pwb::ui_data_core::derive_rule_result(
                    rule, issues_it != report.end() ? *issues_it
                                                    : pwb::domain::Json());
                if (result.severity == "pass") {
                    ++pass;
                } else {
                    ++pending;
                }
            }
        }
    }
    const auto paint = [](QLabel* label, const QString& text,
                          const char* color) {
        label->setText(text);
        label->setStyleSheet(
            QStringLiteral("color: %1; font-weight: 600;").arg(color));
    };
    paint(stats_pass_, QStringLiteral("✓ 通过 %1").arg(pass), "#2e7d32");
    paint(stats_pending_, QStringLiteral("⚠ 待复核 %1").arg(pending),
          "#e65100");
    paint(stats_skipped_, QStringLiteral("○ 未执行 %1").arg(skipped),
          "#757575");
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
