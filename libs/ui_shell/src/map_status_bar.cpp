#include "pwb/ui_shell/map_status_bar.hpp"

#include <QFontMetrics>
#include <QHBoxLayout>
#include <QLocale>
#include <QMouseEvent>

#include <cmath>
#include <string_view>

#include <pwb/platform_services/theme_tokens.hpp>
#include <pwb/tool_policy/tool_availability.hpp>
#include <pwb/ui_shell/style_registry.hpp>

namespace pwb::ui_shell {

namespace {

// Elide cap for a squeezed readout (full text stays in the tooltip).
constexpr int kMaxLabelWidth = 168;
// Geographic (degrees) → 6 decimals (≈0.1 m); projected (linear) → 2.
constexpr int kGeoDecimals = 6;
constexpr int kProjectedDecimals = 2;
// Narrow-width hide priority (edit chip / coordinate / scale / CRS never
// hide).
constexpr const char* kCollapsePriority[] = {"render", "measure",
                                             "topology", "snapping"};

QString qstr(const std::string& s) {
    return QString::fromUtf8(s.data(), static_cast<qsizetype>(s.size()));
}

void elide_label(QLabel* label, const QString& text) {
    // A squeezed QLabel only clips ("CRS: EPS…") — elide proactively to the
    // cap and keep the full text in the tooltip.
    label->setText(text);
    label->setToolTip(text);
    const QFontMetrics metrics(label->font());
    if (metrics.horizontalAdvance(text) > kMaxLabelWidth) {
        label->setText(metrics.elidedText(text, Qt::TextElideMode::ElideRight,
                                          kMaxLabelWidth));
    }
}

QString pal(const char* key, const char* fallback) {
    const auto palette = style_palette();
    const auto it = palette.find(key);
    return it == palette.end() ? QString::fromLatin1(fallback)
                               : qstr(it->second);
}

// Chip QSS read through style_bind so theme switches re-evaluate tokens.
QString chip_qss(bool emphasis, bool warning) {
    if (warning) {
        return QStringLiteral(
                   "color: %1; background: %2; border: 1px solid %3;"
                   " border-radius: 4px; padding: 1px 8px; font-weight: 600;")
            .arg(pal("TEXT_PRIMARY", "#212121"), pal("BG_SEARCH", "#eeeeee"),
                 pal("WARNING", "#b26a00"));
    }
    if (emphasis) {
        return QStringLiteral(
                   "color: %1; background: %2; border: 1px solid %2;"
                   " border-radius: 4px; padding: 1px 8px;")
            .arg(pal("ON_PRIMARY", "#ffffff"), pal("PRIMARY", "#1565c0"));
    }
    return QStringLiteral(
               "color: %1; background: %2; border: 1px solid %3;"
               " border-radius: 4px; padding: 1px 8px;")
        .arg(pal("TEXT_SECONDARY", "#616161"), pal("BG_SEARCH", "#eeeeee"),
             pal("BORDER_LIGHT", "#dddddd"));
}

QString text_secondary_sheet() {
    return QStringLiteral(
               "color: %1; border: none; background: transparent;"
               " padding: 0 2px;")
        .arg(pal("TEXT_SECONDARY", "#616161"));
}

CrsDecimalsResolver& decimals_resolver_slot() {
    static CrsDecimalsResolver resolver;
    return resolver;
}

}  // namespace

QString short_crs_name(const QString& text) {
    const QString cleaned = text.split(QLatin1Char('/')).first().trimmed();
    if (cleaned.isEmpty()) {
        return QString();
    }
    if (cleaned.startsWith(QLatin1String("+proj"))) {
        const QString units = cleaned.contains(QLatin1String("+units=m"))
                                  ? QStringLiteral("（米）")
                                  : QString();
        return QStringLiteral("本地坐标") + units;
    }
    return cleaned;
}

QString format_scale(double denominator) {
    if (denominator >= 1.0) {
        return QStringLiteral("1:%1")
            .arg(QLocale().toString(static_cast<qlonglong>(
                std::llround(denominator))));
    }
    return QStringLiteral("1:—");
}

void set_crs_decimals_resolver(CrsDecimalsResolver resolver) {
    decimals_resolver_slot() = std::move(resolver);
}

int coordinate_decimals(const QString& crs,
                        const std::pair<double, double>* point) {
    const QString text = crs.split(QLatin1Char('/')).first().trimmed();
    if (!text.isEmpty()) {
        const auto& resolver = decimals_resolver_slot();
        if (resolver) {
            const std::optional<bool> geographic = resolver(text);
            if (geographic.has_value()) {
                return *geographic ? kGeoDecimals : kProjectedDecimals;
            }
        }
    }
    // Same magnitude fallback Python uses when pyproj is unavailable.
    if (point != nullptr && std::abs(point->first) <= 360.0 &&
        std::abs(point->second) <= 90.0) {
        return kGeoDecimals;
    }
    return kProjectedDecimals;
}

MapStatusBar::MapStatusBar(QWidget* parent) : QFrame(parent) {
    setObjectName(QStringLiteral("MapStatusBar"));
    auto* layout = new QHBoxLayout(this);
    layout->setContentsMargins(8, 4, 8, 4);  // SPACE_2 / SPACE_1
    layout->setSpacing(12);                   // SPACE_3
    coordinate_ = new QLabel(QStringLiteral("X: —  Y: —"), this);
    scale_ = new QLabel(QStringLiteral("1:—"), this);
    crs_ = new QLabel(QStringLiteral("CRS: —"), this);
    render_ = new QLabel(QStringLiteral("渲染器: —"), this);
    selection_ = new QLabel(QStringLiteral("已选 0"), this);
    snapping_ = new QLabel(QString(), this);
    topology_ = new QLabel(QString(), this);
    measure_ = new QLabel(QString(), this);
    labels_ = {{"render", render_},
               {"measure", measure_},
               {"topology", topology_},
               {"snapping", snapping_}};
    const QString sheet = text_secondary_sheet();
    for (QLabel* label : {coordinate_, scale_, crs_, render_, selection_,
                          snapping_, topology_, measure_}) {
        label->setStyleSheet(sheet);
        layout->addWidget(label);
    }
    // Snapping readout is clickable (QGIS status-bar magnet convention).
    snapping_->setCursor(Qt::CursorShape::PointingHandCursor);
    // Topology issue chip (V10 §15): only with error count > 0; click to
    // validate/locate.
    topology_issue_ = new QLabel(QString(), this);
    topology_issue_->setObjectName(
        QStringLiteral("MapStatusBarTopologyIssue"));
    topology_issue_->setCursor(Qt::CursorShape::PointingHandCursor);
    topology_issue_->hide();
    layout->addWidget(topology_issue_);
    // Edit-session chip: 编辑 层名 ● 未保存 / RAW · 只读 / 已冻结 / 锁定.
    edit_ = new QLabel(QStringLiteral("查看"), this);
    layout->addWidget(edit_);
    layout->addStretch(1);
    // Theme responsiveness: chip styles re-evaluate tokens via style_bind.
    style_bind(edit_, [this] { return render_edit_chip(); });
    style_bind(topology_issue_, [this] { return render_issue_chip(); });
}

QString MapStatusBar::snap_tooltip_text() const {
    QStringList lines = snap_tip_lines_;
    if (last_snap_match_.has_value()) {
        const SnapMatch& match = *last_snap_match_;
        if (match.matched) {
            QStringList detail;
            if (!match.match_type.isEmpty()) {
                detail << QStringLiteral("类型 ") + match.match_type;
            }
            if (!match.layer_doc_id.isEmpty()) {
                detail << QStringLiteral("图层 ") + match.layer_doc_id;
            }
            if (match.distance.has_value()) {
                detail << QStringLiteral("距离 %1")
                              .arg(*match.distance, 0, 'g', 4);
            }
            lines << QStringLiteral("最近命中：") +
                         (detail.isEmpty() ? QStringLiteral("已吸附")
                                           : detail.join(QStringLiteral("、")));
        } else {
            lines << QStringLiteral("最近命中：无");
        }
    }
    if (lines.isEmpty()) {
        return QString();
    }
    return QStringLiteral("捕捉设置\n") + lines.join(QLatin1Char('\n'));
}

void MapStatusBar::set_snap_match(bool matched, const QString& match_type,
                                  const QString& layer_doc_id,
                                  std::optional<double> distance) {
    last_snap_match_ =
        SnapMatch{matched, match_type, layer_doc_id, distance};
    snapping_->setToolTip(snap_tooltip_text());
}

int MapStatusBar::decimals_for(const QString& crs,
                               const std::pair<double, double>* point) {
    // Cache per CRS string — called per mouse-move frame; re-resolving the
    // CRS every frame is wasteful even for the cheap heuristic.
    if (!crs_decimals_valid_ || crs != crs_decimals_key_) {
        coord_decimals_ = coordinate_decimals(crs, point);
        crs_decimals_key_ = crs;
        crs_decimals_valid_ = true;
    }
    return coord_decimals_;
}

void MapStatusBar::update_coordinate(std::pair<double, double> point,
                                     const QString& crs) {
    const int decimals = decimals_for(crs, &point);
    elide_label(coordinate_,
                QStringLiteral("X: %1  Y: %2")
                    .arg(point.first, 0, 'f', decimals)
                    .arg(point.second, 0, 'f', decimals));
}

void MapStatusBar::update_scale(double denominator) {
    elide_label(scale_, format_scale(denominator));
}

void MapStatusBar::set_measure(const QString& text) {
    elide_label(measure_, text);
    measure_->setToolTip(text);
}

void MapStatusBar::update_state(const LegacyState& state) {
    if (state.point.has_value()) {
        const int decimals = decimals_for(qstr(state.crs), &*state.point);
        elide_label(coordinate_,
                    QStringLiteral("X: %1  Y: %2")
                        .arg(state.point->first, 0, 'f', decimals)
                        .arg(state.point->second, 0, 'f', decimals));
    }
    if (state.scale_denominator > 0.0) {
        elide_label(scale_, format_scale(state.scale_denominator));
    } else if (state.extent.has_value()) {
        const double width =
            std::max(0.0, state.extent->at(2) - state.extent->at(0));
        elide_label(scale_, QStringLiteral("宽: %1").arg(width, 0, 'g', 6));
    }
    const QString display = short_crs_name(qstr(state.crs));
    elide_label(crs_, QStringLiteral("CRS: %1")
                          .arg(display.isEmpty() ? QStringLiteral("未声明")
                                                 : display));
    elide_label(render_, QStringLiteral("渲染器: %1")
                             .arg(state.renderer.empty()
                                      ? QStringLiteral("—")
                                      : qstr(state.renderer)));
    selection_->setText(QStringLiteral("已选 %1").arg(state.selection_count));
    if (!state.snapping.has_value()) {
        snapping_->setText(QString());
    } else {
        snapping_->setText(QStringLiteral("捕捉: %1")
                               .arg(*state.snapping ? QStringLiteral("开")
                                                    : QStringLiteral("关")));
    }
    apply_edit_chip(state.editing, qstr(state.editing_label), false, false,
                    false, false, QString(), false, false);
}

void MapStatusBar::apply_edit_chip(bool editing,
                                   const QString& editing_label, bool dirty,
                                   bool raw_locked, bool frozen,
                                   bool gate_closed,
                                   const QString& gate_reason,
                                   bool editable_unknown, bool save_blocked) {
    // Edit-chip vocabulary (V10 §14): 查看/编辑/dirty/RAW/冻结/锁定.
    QString text;
    QString tip;
    ChipMode mode = ChipMode::Neutral;
    if (editing) {
        // dirty/save-blocked ride as the text glyph 「●」 — accessibility,
        // not color-only.
        text = QStringLiteral("编辑");
        tip = QStringLiteral("编辑会话进行中");
        if (!editing_label.isEmpty()) {
            text = QStringLiteral("编辑 ") + editing_label;
            tip = QStringLiteral("正在编辑：") + editing_label;
        }
        if (dirty) {
            text += QStringLiteral(" ● 未保存");
            tip += QStringLiteral("（有未保存修改）");
        }
        if (save_blocked) {
            text += QStringLiteral("（保存受阻）");
            tip += QStringLiteral("；存在拓扑错误，保存将被校验阻断");
        }
        mode = ChipMode::Emphasis;
    } else if (raw_locked) {
        text = QStringLiteral("RAW · 只读");
        // V11 Goal §7 (A3): the reason sentence comes from the same
        // vocabulary as the evaluator/asset menu (single wording source).
        tip = qstr(pwb::tool_policy::raw_layer_gate_reason());
    } else if (frozen) {
        text = QStringLiteral("已冻结");
        tip = qstr(pwb::tool_policy::frozen_layer_gate_reason());
    } else if (gate_closed) {
        text = QStringLiteral("锁定");
        tip = qstr(pwb::tool_policy::stage_lock_reason(
            gate_reason.toStdString()));
    } else if (editable_unknown) {
        text = QStringLiteral("可编辑性未知");
        tip = QStringLiteral(
            "当前图层可编辑性未知（阶段/门禁状态未就绪）");
    } else if (!editing_label.isEmpty()) {
        text = editing_label + QStringLiteral(" · 可编辑");
        tip = editing_label +
              QStringLiteral("：可编辑（未开启会话）");
    } else {
        text = QStringLiteral("查看");
        tip = QStringLiteral("未开启编辑会话");
    }
    edit_->setText(text);
    edit_->setToolTip(tip);
    if (!edit_chip_mode_set_ || mode != edit_chip_mode_) {
        edit_chip_mode_ = mode;
        edit_chip_mode_set_ = true;
        style_refresh(edit_);
    }
}

QString MapStatusBar::render_edit_chip() const {
    const ChipMode mode =
        edit_chip_mode_set_ ? edit_chip_mode_ : ChipMode::Neutral;
    return chip_qss(mode == ChipMode::Emphasis, mode == ChipMode::Warning);
}

QString MapStatusBar::render_issue_chip() const {
    return chip_qss(false, true);
}

void MapStatusBar::apply_context(const MapStatusFacts& facts) {
    std::pair<double, double> point_value{0.0, 0.0};
    const std::pair<double, double>* point_ptr = nullptr;
    if (facts.point.has_value()) {
        point_value = *facts.point;
        point_ptr = &point_value;
    }
    const QString crs = facts.crs.has_value() ? qstr(*facts.crs) : QString();
    if (point_ptr != nullptr) {
        const int decimals = decimals_for(crs, point_ptr);
        elide_label(coordinate_,
                    QStringLiteral("X: %1  Y: %2")
                        .arg(point_value.first, 0, 'f', decimals)
                        .arg(point_value.second, 0, 'f', decimals));
    }
    // CRS readout (§16): short name; custom +proj folds to 本地坐标;
    // undeclared → 「未声明」; mismatch adds a ⚠ text warning (not
    // color-only) plus the layer CRS in the tooltip.
    const QString display_crs = short_crs_name(crs);
    QString crs_text = display_crs.isEmpty()
                           ? QStringLiteral("CRS: 未声明")
                           : QStringLiteral("CRS: ") + display_crs;
    const QString layer_full =
        facts.layer_crs.has_value() ? qstr(*facts.layer_crs) : QString();
    const QString layer_crs = short_crs_name(layer_full);
    const bool warning =
        facts.crs_mismatch.value_or(false) && !layer_crs.isEmpty();
    QString crs_tip;
    if (warning) {
        crs_text = QStringLiteral("⚠ ") + crs_text;
        crs_tip = crs_text +
                  QStringLiteral(
                      "\n图层 CRS（%1）与工程 CRS 不一致——"
                      "数字化几何将按工程 CRS 落地，注意坐标单位")
                      .arg(layer_full.isEmpty() ? layer_crs : layer_full);
    } else {
        crs_tip = crs.isEmpty()
                      ? crs_text
                      : crs_text + QStringLiteral("\n工程坐标系：") + crs;
    }
    elide_label(crs_, crs_text);
    crs_->setToolTip(crs_tip);
    if (warning != crs_warning_) {
        crs_warning_ = warning;
        crs_->setStyleSheet(
            warning ? QStringLiteral(
                          "color: %1; border: none; background: transparent;"
                          " padding: 0 2px; font-weight: 600;")
                          .arg(pal("TEXT_PRIMARY", "#212121"))
                    : text_secondary_sheet());
    }
    elide_label(scale_,
                format_scale(facts.scale_denominator.value_or(0.0)));
    elide_label(render_,
                QStringLiteral("渲染器: %1")
                    .arg(facts.renderer.has_value() && !facts.renderer->empty()
                             ? qstr(*facts.renderer)
                             : QStringLiteral("—")));
    selection_->setText(
        QStringLiteral("已选 %1").arg(facts.selection_count.value_or(0)));

    // Snapping readout (§15): ON/OFF + tooltip details (tolerance/modes/
    // participating references/recommendation).
    if (!facts.snapping_enabled.has_value()) {
        snapping_->setText(QString());
        snap_tip_lines_.clear();
        snapping_->setToolTip(QString());
    } else {
        const bool enabled = *facts.snapping_enabled;
        snapping_->setText(QStringLiteral("捕捉: %1")
                               .arg(enabled ? QStringLiteral("开")
                                            : QStringLiteral("关")));
        QStringList tip_lines{QStringLiteral("点击打开捕捉设置")};
        if (enabled) {
            const double tolerance =
                facts.snapping_tolerance_px.value_or(0.0);
            if (tolerance > 0.0) {
                tip_lines << QStringLiteral(
                                   "有效容差 %1 px（含图层覆盖）")
                                 .arg(tolerance, 0, 'g', 6);
            }
            if (facts.snapping_modes.has_value() &&
                !facts.snapping_modes->empty()) {
                QStringList modes;
                for (const auto& mode : *facts.snapping_modes) {
                    modes << qstr(mode);
                }
                tip_lines << QStringLiteral("模式：") +
                                 modes.join(QStringLiteral("、"));
            }
            const int references =
                facts.snapping_reference_count.value_or(0);
            if (references > 0) {
                tip_lines << QStringLiteral(
                                 "参与捕捉的引用图层 %1 个（不含编辑层）")
                                 .arg(references);
            }
            if (facts.snapping_role_recommended.has_value()) {
                tip_lines << (*facts.snapping_role_recommended
                                  ? QStringLiteral("当前配置 = 角色推荐")
                                  : QStringLiteral(
                                        "用户自定义（与角色推荐不同）"));
            }
        }
        if (!facts.snapping_available.value_or(true)) {
            tip_lines << QStringLiteral("当前环境的捕捉引擎不可用");
        }
        snap_tip_lines_ = tip_lines;
        snapping_->setToolTip(snap_tooltip_text());
    }

    // Topology readout (§15): toggle state; error count > 0 → clickable
    // issue chip.
    if (!facts.topology_enabled.has_value()) {
        topology_->setText(QString());
        topology_->setToolTip(QString());
    } else {
        topology_->setText(
            QStringLiteral("拓扑: %1")
                .arg(*facts.topology_enabled ? QStringLiteral("开")
                                             : QStringLiteral("关")));
        topology_->setToolTip(QStringLiteral(
            "拓扑编辑：共享节点传播 + 保存编辑时执行拓扑校验"));
    }
    const int errors = facts.topology_error_count.value_or(0);
    const bool visible = errors > 0;
    if (visible) {
        topology_issue_->setText(
            QStringLiteral("⚠ 拓扑: %1 个问题").arg(errors));
        topology_issue_->setToolTip(
            QStringLiteral(
                "当前编辑会话存在 %1 个拓扑错误\n"
                "点击查看/定位问题（合并等操作被阻断）")
                .arg(errors));
    }
    if (visible != issue_visible_) {
        issue_visible_ = visible;
        topology_issue_->setVisible(visible);
        if (visible) {
            style_refresh(topology_issue_);
        }
    }

    apply_edit_chip(
        facts.editing.value_or(false),
        facts.layer_name.has_value() ? qstr(*facts.layer_name) : QString(),
        facts.dirty.value_or(false), facts.raw_locked.value_or(false),
        facts.layer_frozen.value_or(false),
        facts.edit_gate_open.has_value() && !*facts.edit_gate_open,
        facts.edit_gate_reason.has_value() ? qstr(*facts.edit_gate_reason)
                                           : QString(),
        !facts.edit_gate_open.has_value(),
        facts.save_blocked.value_or(false));
    apply_collapse();
}

void MapStatusBar::apply_collapse() {
    // Width squeeze: hide low-value readouts in priority order; the edit
    // chip and coordinate/scale/CRS never hide.
    const int available = width();
    if (available <= 0) {
        return;
    }
    int fixed_hint = 0;
    for (QLabel* label :
         {coordinate_, scale_, crs_, selection_, edit_, topology_issue_}) {
        if (label->isVisible() || label == edit_) {
            fixed_hint += std::max(label->sizeHint().width(), 24);
        }
    }
    int budget = available - fixed_hint - 4 * 12;  // 4 × SPACE_3
    std::set<std::string> collapsed;
    QStringList flexible;
    for (const char* name : {"snapping", "topology", "measure", "render"}) {
        if (!labels_.at(name)->text().isEmpty()) {
            flexible << QLatin1String(name);
        }
    }
    for (const char* name : kCollapsePriority) {
        if (budget < 0 && flexible.contains(QLatin1String(name))) {
            collapsed.insert(name);
            budget += std::max(labels_.at(name)->sizeHint().width(), 24);
        }
    }
    if (collapsed != collapsed_) {
        collapsed_ = collapsed;
        for (const auto& [name, label] : labels_) {
            label->setHidden(collapsed.count(name) != 0);
        }
    }
}

void MapStatusBar::resizeEvent(QResizeEvent* event) {
    QFrame::resizeEvent(event);
    apply_collapse();
}

const char* MapStatusBar::hit_clickable(const QPoint& pos) const {
    if (topology_issue_->isVisible() &&
        topology_issue_->geometry().contains(pos)) {
        return "topology_issue";
    }
    if (snapping_->isVisible() && snapping_->geometry().contains(pos)) {
        return "snapping";
    }
    return nullptr;
}

void MapStatusBar::mousePressEvent(QMouseEvent* event) {
    press_inside_ = hit_clickable(event->position().toPoint());
    QFrame::mousePressEvent(event);
}

void MapStatusBar::mouseReleaseEvent(QMouseEvent* event) {
    const char* inside = hit_clickable(event->position().toPoint());
    const char* pressed = press_inside_;
    press_inside_ = nullptr;
    if (inside != nullptr && inside == pressed &&
        event->button() == Qt::MouseButton::LeftButton) {
        if (std::string_view(inside) == "topology_issue") {
            emit topology_activated();
        } else if (std::string_view(inside) == "snapping") {
            emit snapping_activated();
        }
        return;
    }
    QFrame::mouseReleaseEvent(event);
}

}  // namespace pwb::ui_shell
