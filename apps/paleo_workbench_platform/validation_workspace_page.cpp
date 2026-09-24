#include "validation_workspace_page.hpp"

#include <algorithm>
#include <array>
#include <atomic>
#include <memory>

#include <QFrame>
#include <QHBoxLayout>
#include <QLabel>
#include <QPointer>
#include <QPushButton>
#include <QSplitter>
#include <QTabWidget>
#include <QTableWidget>
#include <QVariant>
#include <QVBoxLayout>

#include <pwb/qgis_processing/task_bridge.hpp>
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

QVariantMap issue_to_variant(const pwb::domain::Json& issue,
                             const std::string& report_id) {
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
    // definition the closure_review persistence also uses). The navigator
    // key disambiguates same-key issues across MAPS: report|issue_key.
    map.insert(QStringLiteral("issue_key"),
               QString::fromStdString(pwb::ui_review::qc_issue_key(issue)));
    map.insert(
        QStringLiteral("key"),
        QString::fromStdString(report_id) + QLatin1Char('|')
            + QString::fromStdString(pwb::ui_review::qc_issue_key(issue)));
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

void ValidationWorkspacePage::set_async_qc(AsyncQc seam) {
    async_qc_ = std::move(seam);
}

void ValidationWorkspacePage::set_task_owner(
    pwb::qgis_processing::PwbTaskOwner* owner) {
    task_owner_ = owner;
}

void ValidationWorkspacePage::update_reports(
    const std::vector<pwb::domain::Json>& reports) {
    reports_ = reports;
    table_->update_state(reports);
    // The hub carries the per-issue detail/fix surface — the FULL
    // flattened issue list across every report (one issue schema, one
    // list; the navigator walks the same list).
    rebuild_flattened_issues();
    refresh_result_stats();
    emit reports_refreshed();
}

// 扁平化全报告 issues；刷新后按 key 重定位游标（当前问题被修复/替换时
// 就近落位，绝不停留在 stale 问题上，也不无端跳回头一条）。
void ValidationWorkspacePage::rebuild_flattened_issues() {
    const QString keep_key = current_issue_key();
    flattened_issues_.clear();
    flattened_keys_.clear();
    for (const auto& report : reports_) {
        if (!report.is_object()) continue;
        const std::string report_id =
            report.contains("id") && report.at("id").is_string()
                ? report.at("id").get<std::string>()
                : std::string();
        const auto it = report.find("issues");
        if (it == report.end() || !it->is_array()) continue;
        for (const auto& issue : *it) {
            if (!issue.is_object()) continue;
            const QVariantMap variant = issue_to_variant(issue, report_id);
            flattened_issues_.push_back(variant);
            flattened_keys_.append(variant.value(QStringLiteral("key"))
                                       .toString());
        }
    }
    hub_->set_issues(QStringLiteral("map_qc"), flattened_issues_);
    if (flattened_keys_.isEmpty()) {
        cursor_ = -1;
        return;
    }
    int resolved = flattened_keys_.indexOf(keep_key);
    if (resolved < 0) {
        if (cursor_ < 0) {
            // No previous cursor (fresh list): stay unpositioned — the
            // first navigate(+1) lands on the head, navigate(-1) wraps
            // to the tail.
            cursor_ = -1;
            return;
        }
        // 当前问题已消失：就近落位（旧游标钳制到新范围）。
        resolved = std::min(cursor_,
                            static_cast<int>(flattened_keys_.size()) - 1);
    }
    cursor_ = resolved;
}

QString ValidationWorkspacePage::current_issue_key() const {
    if (cursor_ < 0 || cursor_ >= flattened_keys_.size()) {
        return QString();
    }
    return flattened_keys_.at(cursor_);
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
    if (qc_running_) {
        emit status_message(QStringLiteral("验证正在运行——可先取消"));
        return;
    }
    // Async path（seam 装全 + 有任务宿主）：快照在 GUI 线程拍，QC 在
    // worker 线程跑（协作取消），报告只在成功终点合并进 LIVE root——
    // cancelled 不合并，上一份有效报告保持不变。
    if (async_qc_.snapshot && async_qc_.run && async_qc_.merge
        && task_owner_ != nullptr) {
        auto request = async_qc_.snapshot();
        if (!request.has_value()) {
            emit status_message(
                QStringLiteral("验证：工程内没有编图文档"));
            return;
        }
        qc_running_ = true;
        emit qc_state_changed();
        emit status_message(QStringLiteral("验证运行中……"));
        // 结果与取消标记经 shared_ptr 跨线程；页面生死经 QPointer 守卫
        // （关闭后迟到结果整体丢弃）。root 经 shared_ptr 持有——worker
        // 侧 seam 以 Json& 接收（快照在其上就地 upsert），指针解引用与
        // 任务体的 lambda 常量性无关。
        const auto reports_out =
            std::make_shared<std::vector<pwb::domain::Json>>();
        auto root_out =
            std::make_shared<pwb::domain::Json>(std::move(request->first));
        const auto doc_ids_out = std::make_shared<std::vector<std::string>>(
            std::move(request->second));
        QPointer<ValidationWorkspacePage> self(this);
        task_owner_->start(
            QStringLiteral("background.compute"),
            QStringLiteral("运行验证"),
            [root_out, doc_ids_out, reports_out,
             run = async_qc_.run](
                pwb::qgis_processing::PaleoTaskBodyContext& ctx) -> bool {
                ctx.report_progress(0.0, QStringLiteral("验证规则"));
                *reports_out =
                    run(*root_out, *doc_ids_out, [&ctx]() {
                        return ctx.check_cancelled();
                    });
                ctx.report_progress(1.0, QStringLiteral("验证完成"));
                return true;
            },
            [self, reports_out, merge = async_qc_.merge](
                const pwb::qgis_processing::PaleoTaskOutcome& outcome) {
                if (self == nullptr) return;  // closed page: drop late
                self->qc_running_ = false;
                emit self->qc_state_changed();
                if (outcome.cancelled) {
                    emit self->status_message(
                        QStringLiteral("验证已取消——上一份报告保持不变"));
                    return;
                }
                if (!outcome.completed) {
                    emit self->status_message(
                        QStringLiteral("验证失败：%1")
                            .arg(outcome.error.isEmpty()
                                     ? QStringLiteral("未知错误")
                                     : outcome.error));
                    return;
                }
                const std::string error = merge(*reports_out);
                if (!error.empty()) {
                    emit self->status_message(
                        QStringLiteral("报告保存失败：%1")
                            .arg(QString::fromStdString(error)));
                    return;
                }
                pwb::ui_review::IReviewActions* actions =
                    self->actions_provider_ != nullptr
                        ? self->actions_provider_()
                        : nullptr;
                if (actions != nullptr) {
                    self->update_reports(actions->active_quality_reports());
                }
                emit self->status_message(QString::fromStdString(
                    pwb::ui_review::review_run_done_text(
                        static_cast<int>(reports_out->size()))));
            });
        return;
    }
    // Legacy sync path（异步缝未装配——如未装 owner 的测试宿主）。
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

void ValidationWorkspacePage::cancel_qc() {
    if (!qc_running_ || task_owner_ == nullptr) {
        emit status_message(
            QStringLiteral("当前没有可取消的验证任务"));
        return;
    }
    task_owner_->cancel();
    emit status_message(QStringLiteral("已请求取消验证……"));
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
    // it to the M5 review panel as the current selection. The navigator
    // cursor follows so prev/next continue from the located issue.
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
    const std::string report_id =
        report.contains("id") && report.at("id").is_string()
            ? report.at("id").get<std::string>()
            : std::string();
    for (const auto& issue : issues) {
        const QVariantMap variant = issue_to_variant(issue, report_id);
        if (variant.contains(QStringLiteral("locate"))) {
            const int index = flattened_keys_.indexOf(
                variant.value(QStringLiteral("key")).toString());
            if (index >= 0) cursor_ = index;
            emit issue_selected(variant);
            locate_issue(variant);
            return;
        }
    }
    emit status_message(QStringLiteral("该检查项没有空间定位信息"));
}

// ---- IssueNavigator --------------------------------------------------------

void ValidationWorkspacePage::navigate_issue(int delta) {
    if (flattened_issues_.isEmpty()) {
        emit status_message(
            QStringLiteral("没有可定位的问题（先运行检查）"));
        return;
    }
    const int n = flattened_issues_.size();
    // 固定规则：wrap-around（上一处在头 → 最后一条；下一处在尾 → 第一条）。
    int next = cursor_ + delta;
    if (next < 0) next = n - 1;
    if (next >= n) next = 0;
    cursor_ = next;
    locate_current_issue();
}

void ValidationWorkspacePage::locate_current_issue() {
    if (cursor_ < 0 || cursor_ >= flattened_issues_.size()) {
        emit status_message(
            QStringLiteral("没有可定位的问题（先运行检查）"));
        return;
    }
    const QVariantMap issue = flattened_issues_.at(cursor_);
    // 表格联动：选中该问题所属规则的行（规则表 = 一行一规则）。
    const QString rule = issue.value(QStringLiteral("rule")).toString();
    if (!rule.isEmpty() && !reports_.empty()) {
        const auto& rules = reports_.front();
        const auto rules_it = rules.find("rules");
        if (rules_it != rules.end() && rules_it->is_array()) {
            for (std::size_t i = 0; i < rules_it->size(); ++i) {
                const auto& entry = rules_it->at(i);
                const auto name_it = entry.find("rule");
                if (name_it != entry.end() && name_it->is_string()
                    && name_it->get<std::string>() == rule.toStdString()) {
                    table_->table()->selectRow(
                        static_cast<int>(i));
                    break;
                }
            }
        }
    }
    emit issue_selected(issue);
    locate_issue(issue);
    emit status_message(
        QStringLiteral("问题 %1/%2 · %3")
            .arg(cursor_ + 1)
            .arg(flattened_issues_.size())
            .arg(issue.value(QStringLiteral("rule")).toString()));
}

}  // namespace pwb::app
