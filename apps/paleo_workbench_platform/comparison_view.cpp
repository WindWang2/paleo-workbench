#include "comparison_view.hpp"

#include <algorithm>
#include <cmath>
#include <utility>

#include <QComboBox>
#include <QEvent>
#include <QHBoxLayout>
#include <QLabel>
#include <QMouseEvent>
#include <QPainter>
#include <QPen>
#include <QToolButton>
#include <QVBoxLayout>

namespace pwb::app {

namespace {

using pwb::ui_review::CompareBand;
using pwb::ui_review::CompareMode;

// Stable class color: hue from the class string — same class, same
// color across wells and sessions. 未标注 renders gray.
QColor class_color(const QString& klass) {
    if (klass.isEmpty()) {
        return QColor(0x9a, 0xa4, 0xad);
    }
    quint32 hash = 0;
    for (const QChar c : klass) {
        hash = hash * 31 + c.unicode();
    }
    return QColor::fromHsv(static_cast<int>(hash % 360), 140, 200);
}

QString band_label(const CompareBand& band) {
    return band.klass.empty() ? QStringLiteral("未标注")
                              : QString::fromStdString(band.klass);
}

// The painted surface: depth axis + the mode's columns for one well.
class CompareCanvas : public QWidget {
public:
    explicit CompareCanvas(ComparisonView* view) : QWidget(view), view_(view) {
        setObjectName(QStringLiteral("CompareCanvas"));
        setMouseTracking(true);
    }

    double depth_at_y(int y) const;

protected:
    void paintEvent(QPaintEvent* event) override;

private:
    std::pair<double, double> depth_range() const;

    ComparisonView* view_;
};

}  // namespace

// ---------------------------------------------------------------------------
// ComparisonView
// ---------------------------------------------------------------------------

ComparisonView::ComparisonView(QWidget* parent) : QWidget(parent) {
    setObjectName(QStringLiteral("ComparisonView"));
    auto* outer = new QVBoxLayout(this);
    outer->setContentsMargins(4, 2, 4, 2);
    outer->setSpacing(2);

    auto* selectors = new QHBoxLayout;
    selectors->setSpacing(6);
    auto* object_label = new QLabel(QStringLiteral("对象"), this);
    object_ = new QComboBox(this);
    object_->setObjectName(QStringLiteral("CompareObject"));
    auto* baseline_label = new QLabel(QStringLiteral("基准"), this);
    baseline_ = new QComboBox(this);
    baseline_->setObjectName(QStringLiteral("CompareBaseline"));
    auto* prediction_label = new QLabel(QStringLiteral("预测"), this);
    prediction_ = new QComboBox(this);
    prediction_->setObjectName(QStringLiteral("ComparePrediction"));
    link_toggle_ = new QToolButton(this);
    link_toggle_->setObjectName(QStringLiteral("CompareLinkToggle"));
    link_toggle_->setText(QStringLiteral("联动"));
    link_toggle_->setCheckable(true);
    link_toggle_->setEnabled(false);
    connect(link_toggle_, &QToolButton::toggled, this, [this](bool on) {
        if (on && !set_link_enabled(true)) {
            const QSignalBlocker block(link_toggle_);
            link_toggle_->setChecked(false);
        }
    });
    selectors->addWidget(object_label);
    selectors->addWidget(object_);
    selectors->addWidget(baseline_label);
    selectors->addWidget(baseline_);
    selectors->addWidget(prediction_label);
    selectors->addWidget(prediction_);
    selectors->addStretch(1);
    selectors->addWidget(link_toggle_);
    outer->addLayout(selectors);

    canvas_ = new CompareCanvas(this);
    outer->addWidget(canvas_, 1);

    summary_ = new QLabel(this);
    summary_->setObjectName(QStringLiteral("CompareSummary"));
    outer->addWidget(summary_);

    canvas_->installEventFilter(this);
    for (auto* combo : {object_, baseline_, prediction_}) {
        connect(combo, &QComboBox::currentIndexChanged, this,
                [this](int) { refresh_bands(); });
    }
    reload();
}

void ComparisonView::set_source_provider(std::function<SourceSet()> provider) {
    source_provider_ = std::move(provider);
    reload();
}

void ComparisonView::set_artifact_reader(
    std::function<std::optional<pwb::domain::Json>(const std::string& path)>
        reader) {
    artifact_reader_ = std::move(reader);
    reload();
}

void ComparisonView::set_calibration_provider(
    std::function<bool(const std::string& well_id)> provider) {
    calibration_provider_ = std::move(provider);
    refresh_link_gate();
}

void ComparisonView::reload() {
    rebuild_selectors();
}

void ComparisonView::set_mode(CompareMode mode) {
    mode_ = mode;
    cursor_depth_ = -1.0;
    canvas_->update();
}

bool ComparisonView::set_link_enabled(bool on) {
    if (!on) {
        link_ = false;
        const QSignalBlocker block(link_toggle_);
        link_toggle_->setChecked(false);
        cursor_depth_ = -1.0;
        canvas_->update();
        emit link_changed(false);
        return true;
    }
    const std::string well = selected_well_id().toStdString();
    const bool calibrated =
        calibration_provider_ != nullptr && calibration_provider_(well);
    if (!calibrated) {
        // F:75 — m and ms never couple without a real calibration.
        emit status_message(QStringLiteral(
            "联动不可用：该井无时深标定数据（深度 m 与双程时 ms 不联动）"));
        return false;
    }
    link_ = true;
    canvas_->update();
    emit link_changed(true);
    return true;
}

QString ComparisonView::empty_reason() const {
    const bool has_interp = baseline_->count() > 0;
    const bool has_pred = prediction_->count() > 0;
    if (!has_interp && !has_pred) {
        return QStringLiteral(
            "无对比数据：解释版本在「层序对比」页保存；预测成果在智能预测"
            "工作区运行后生成");
    }
    if (!has_interp) {
        return QStringLiteral("无解释版本：在「层序对比」页保存解释版本后可用");
    }
    if (!has_pred) {
        return QStringLiteral("无预测成果：在智能预测工作区运行预测后可用");
    }
    if (pairs_.empty()) {
        return QStringLiteral("所选对象没有可对比的井段");
    }
    return QString();
}

QString ComparisonView::selected_well_id() const {
    return object_->currentData().toString();
}

void ComparisonView::rebuild_selectors() {
    SourceSet set;
    if (source_provider_ != nullptr) {
        set = source_provider_();
    }
    const QString object_current = object_->currentData().toString();
    const QString baseline_current = baseline_->currentData().toString();
    const QString prediction_current = prediction_->currentData().toString();

    baseline_->clear();
    prediction_->clear();
    for (const auto& interp : set.interpretations) {
        const auto id_it = interp.find("id");
        if (id_it == interp.end() || !id_it->is_string()) continue;
        const auto name_it = interp.find("name");
        baseline_->addItem(
            QString::fromStdString(name_it != interp.end() &&
                                           name_it->is_string()
                                       ? name_it->get<std::string>()
                                       : id_it->get<std::string>()),
            QString::fromStdString(id_it->get<std::string>()));
    }
    for (const auto& task : set.predictions) {
        const auto id_it = task.find("id");
        if (id_it == task.end() || !id_it->is_string()) continue;
        const auto name_it = task.find("name");
        prediction_->addItem(
            QString::fromStdString(name_it != task.end() &&
                                           name_it->is_string()
                                       ? name_it->get<std::string>()
                                       : id_it->get<std::string>()),
            QString::fromStdString(id_it->get<std::string>()));
    }

    const auto restore = [](QComboBox* combo, const QString& id) {
        if (id.isEmpty()) return;
        const int index = combo->findData(id);
        if (index >= 0) combo->setCurrentIndex(index);
    };
    restore(baseline_, baseline_current);
    restore(prediction_, prediction_current);

    // Bands first (artifact read), then the object list from the union of
    // wells on both sides.
    refresh_bands();

    object_->clear();
    QStringList seen;
    auto collect = [this, &seen](const std::vector<CompareBand>& bands) {
        for (const auto& band : bands) {
            const QString id = QString::fromStdString(band.well_id);
            if (id.isEmpty() || seen.contains(id)) continue;
            seen.push_back(id);
            object_->addItem(
                QString::fromStdString(band.well_name.empty() ? band.well_id
                                                              : band.well_name),
                id);
        }
    };
    collect(interpretation_bands_);
    collect(prediction_bands_);
    restore(object_, object_current);

    refresh_bands();
    refresh_link_gate();
}

void ComparisonView::refresh_bands() {
    interpretation_bands_.clear();
    prediction_bands_.clear();
    pairs_.clear();

    SourceSet set;
    if (source_provider_ != nullptr) {
        set = source_provider_();
    }
    const QString baseline_id = baseline_->currentData().toString();
    const QString prediction_id = prediction_->currentData().toString();

    for (const auto& interp : set.interpretations) {
        const auto id_it = interp.find("id");
        if (id_it == interp.end() ||
            QString::fromStdString(id_it->get<std::string>()) !=
                baseline_id) {
            continue;
        }
        pwb::domain::Json scientific;
        const auto path_it = interp.find("artifact_path");
        if (path_it != interp.end() && path_it->is_string() &&
            artifact_reader_ != nullptr) {
            const auto payload = artifact_reader_(path_it->get<std::string>());
            if (payload.has_value()) {
                const auto sci_it = payload->find("scientific");
                scientific = sci_it != payload->end() ? *sci_it : *payload;
            }
        }
        interpretation_bands_ =
            pwb::ui_review::bands_from_interpretation(interp, scientific);
        break;
    }
    for (const auto& task : set.predictions) {
        const auto id_it = task.find("id");
        if (id_it == task.end() ||
            QString::fromStdString(id_it->get<std::string>()) !=
                prediction_id) {
            continue;
        }
        prediction_bands_ = pwb::ui_review::bands_from_prediction(task);
        break;
    }
    pairs_ = pwb::ui_review::pair_bands(interpretation_bands_,
                                        prediction_bands_);

    const auto summary = pwb::ui_review::summarize_pairs(pairs_);
    summary_->setText(QStringLiteral(
        "一致 %1 · 不一致 %2 · 不可比 %3 · 仅解释 %4 · 仅预测 %5")
                          .arg(summary.matched)
                          .arg(summary.mismatched)
                          .arg(summary.incomparable)
                          .arg(summary.interpretation_only)
                          .arg(summary.prediction_only));
    const QString reason = empty_reason();
    summary_->setVisible(reason.isEmpty());
    canvas_->setVisible(reason.isEmpty());
    canvas_->update();
    refresh_link_gate();
}

void ComparisonView::refresh_link_gate() {
    const std::string well = selected_well_id().toStdString();
    const bool calibrated =
        !well.empty() && calibration_provider_ != nullptr &&
        calibration_provider_(well);
    if (link_toggle_->isEnabled() != calibrated) {
        link_toggle_->setEnabled(calibrated);
        emit link_availability_changed(calibrated);
    }
    link_toggle_->setToolTip(
        calibrated
            ? QStringLiteral("深度游标跨列联动（基于该井时深标定）")
            : QStringLiteral(
                  "无该井的时深标定数据——深度 m 与双程时 ms 不联动"));
    if (!calibrated && link_) {
        link_ = false;
        cursor_depth_ = -1.0;
        const QSignalBlocker block(link_toggle_);
        link_toggle_->setChecked(false);
    }
}

bool ComparisonView::eventFilter(QObject* watched, QEvent* event) {
    if (watched == canvas_ && event->type() == QEvent::MouseMove && link_) {
        auto* mouse = static_cast<QMouseEvent*>(event);
        cursor_depth_ =
            static_cast<CompareCanvas*>(canvas_)->depth_at_y(mouse->pos().y());
        canvas_->update();
    }
    return QWidget::eventFilter(watched, event);
}

// ---------------------------------------------------------------------------
// canvas painting
// ---------------------------------------------------------------------------

std::pair<double, double> CompareCanvas::depth_range() const {
    const QString well = view_->selected_well_id();
    double top = 0.0;
    double bottom = 1.0;
    bool any = false;
    auto grow = [&](const std::vector<CompareBand>& bands) {
        for (const auto& band : bands) {
            if (QString::fromStdString(band.well_id) != well) continue;
            if (!any) {
                top = band.top;
                bottom = band.bottom;
                any = true;
            } else {
                top = std::min(top, band.top);
                bottom = std::max(bottom, band.bottom);
            }
        }
    };
    grow(view_->interpretation_bands());
    grow(view_->prediction_bands());
    if (!any || bottom <= top) {
        return {0.0, 1.0};
    }
    return {top, bottom};
}

double CompareCanvas::depth_at_y(int y) const {
    const auto [top, bottom] = depth_range();
    const int h = height() - 8;
    if (h <= 0) {
        return top;
    }
    const double fraction =
        std::clamp((y - 4) / static_cast<double>(h), 0.0, 1.0);
    return top + (bottom - top) * fraction;
}

void CompareCanvas::paintEvent(QPaintEvent* event) {
    QWidget::paintEvent(event);
    QPainter painter(this);
    painter.fillRect(rect(), QColor(0xff, 0xff, 0xff));

    const QString reason = view_->empty_reason();
    if (!reason.isEmpty()) {
        painter.setPen(QColor(0x53, 0x61, 0x6c));
        painter.drawText(rect(), Qt::AlignCenter, reason);
        return;
    }

    const QString well = view_->selected_well_id();
    const auto [depth_min, depth_max] = depth_range();
    const double span = depth_max - depth_min;
    const int axis_w = 56;
    const int w = width() - axis_w - 8;
    const int h = height() - 8;
    auto y_of = [&](double depth) {
        return 4 + static_cast<int>(
                       (depth - depth_min) / span * (h - 8.0));
    };

    painter.setPen(QColor(0xcc, 0xd1, 0xd6));
    painter.setPen(QColor(0x53, 0x61, 0x6c));
    for (int i = 0; i <= 4; ++i) {
        const double depth = depth_min + span * i / 4.0;
        const int y = y_of(depth);
        painter.drawLine(axis_w - 4, y, width() - 4, y);
        painter.drawText(4, y - 6, axis_w - 10, 12,
                         Qt::AlignRight | Qt::AlignVCenter,
                         QString::number(depth, 'f', 0) +
                             QStringLiteral(" m"));
    }

    auto band_rect = [&](const CompareBand& band) {
        const double y0 = static_cast<double>(y_of(band.top));
        const double y1 =
            std::max(y0 + 2.0, static_cast<double>(y_of(band.bottom)));
        return QRectF(0, y0, 0, y1 - y0);
    };
    auto draw_band = [&](double x0, double x1, const CompareBand& band,
                         int alpha) {
        const QRectF r = band_rect(band);
        const QRectF target(x0, r.y(), x1 - x0, r.height());
        const QColor base = class_color(band_label(band));
        QColor fill = base;
        fill.setAlpha(alpha);
        painter.fillRect(target, fill);
        painter.setPen(base.darker(120));
        painter.drawRect(target);
        painter.setPen(QColor(0x25, 0x31, 0x3d));
        painter.drawText(target, Qt::AlignHCenter | Qt::AlignVCenter,
                         band_label(band));
    };

    std::vector<CompareBand> interp;
    std::vector<CompareBand> pred;
    for (const auto& band : view_->interpretation_bands()) {
        if (QString::fromStdString(band.well_id) == well) {
            interp.push_back(band);
        }
    }
    for (const auto& band : view_->prediction_bands()) {
        if (QString::fromStdString(band.well_id) == well) {
            pred.push_back(band);
        }
    }

    auto verdict_color = [](const pwb::ui_review::BandPair& pair) {
        if (!pair.in_prediction || !pair.in_interpretation) {
            return QColor(0xc6, 0x28, 0x28, 140);  // presence mismatch
        }
        if (pair.comparable) {
            return pair.match ? QColor(0x2e, 0x7d, 0x32, 140)
                              : QColor(0xc6, 0x28, 0x28, 140);
        }
        return QColor(0x9a, 0xa4, 0xad, 100);  // incomparable
    };
    auto verdict_text = [](const pwb::ui_review::BandPair& pair) {
        if (!pair.in_prediction) return QStringLiteral("预测缺失");
        if (!pair.in_interpretation) return QStringLiteral("解释缺失");
        if (!pair.comparable) return QStringLiteral("不可比（未标注类别）");
        if (pair.match) return QStringLiteral("一致");
        return QStringLiteral("不一致：%1 ≠ %2")
            .arg(QString::fromStdString(pair.interpreted_class),
                 QString::fromStdString(pair.predicted_class));
    };

    const CompareMode mode = view_->mode();
    if (mode == CompareMode::SideBySide) {
        const double col = w / 3.0;
        painter.setPen(QColor(0x53, 0x61, 0x6c));
        painter.drawText(QRectF(axis_w, 0, col, 14), Qt::AlignHCenter,
                         QStringLiteral("解释"));
        painter.drawText(QRectF(axis_w + col, 0, col, 14), Qt::AlignHCenter,
                         QStringLiteral("预测"));
        painter.drawText(QRectF(axis_w + 2 * col, 0, col, 14),
                         Qt::AlignHCenter, QStringLiteral("差异"));
        for (const auto& band : interp) {
            draw_band(axis_w + 2, axis_w + col - 2, band, 110);
        }
        for (const auto& band : pred) {
            draw_band(axis_w + col + 2, axis_w + 2 * col - 2, band, 160);
        }
        // Difference column: one verdict row per pair; pairs without a
        // prediction extent split the column evenly (honest, visible).
        int unlocated = 0;
        for (const auto& pair : view_->pairs()) {
            if (QString::fromStdString(pair.well_id) != well) continue;
            if (pair.in_prediction && pair.bottom > pair.top) {
                const QRectF row(axis_w + 2 * col + 2, y_of(pair.top),
                                 col - 4,
                                 std::max(2.0, static_cast<double>(y_of(pair.bottom) - y_of(pair.top))));
                painter.fillRect(row, verdict_color(pair));
                painter.setPen(QColor(0x25, 0x31, 0x3d));
                painter.drawText(row, Qt::AlignHCenter | Qt::AlignVCenter,
                                 verdict_text(pair));
            } else {
                ++unlocated;
            }
        }
        if (unlocated > 0) {
            const double slice =
                (h - 8.0) / static_cast<double>(unlocated);
            int index = 0;
            for (const auto& pair : view_->pairs()) {
                if (QString::fromStdString(pair.well_id) != well) continue;
                if (pair.in_prediction && pair.bottom > pair.top) continue;
                const QRectF row(axis_w + 2 * col + 2,
                                 4 + slice * index, col - 4, slice);
                painter.fillRect(row, verdict_color(pair));
                painter.setPen(QColor(0x25, 0x31, 0x3d));
                painter.drawText(row, Qt::AlignHCenter | Qt::AlignVCenter,
                                 verdict_text(pair));
                ++index;
            }
        }
    } else if (mode == CompareMode::Overlay) {
        const double col = w / 2.0;
        painter.setPen(QColor(0x53, 0x61, 0x6c));
        painter.drawText(QRectF(axis_w, 0, col, 14), Qt::AlignHCenter,
                         QStringLiteral("半透明叠加（解释 淡 / 预测 浓）"));
        painter.drawText(QRectF(axis_w + col, 0, col, 14), Qt::AlignHCenter,
                         QStringLiteral("预测为主"));
        for (const auto& band : interp) {
            draw_band(axis_w + 2, axis_w + col - 2, band, 80);
        }
        for (const auto& band : pred) {
            draw_band(axis_w + 2, axis_w + col - 2, band, 130);
        }
        for (const auto& band : pred) {
            draw_band(axis_w + col + 2, axis_w + 2 * col - 2, band, 160);
        }
        for (const auto& band : interp) {
            draw_band(axis_w + col + 2, axis_w + 2 * col - 2, band, 70);
        }
    } else {  // Difference
        painter.setPen(QColor(0x53, 0x61, 0x6c));
        painter.drawText(QRectF(axis_w, 0, w, 14), Qt::AlignHCenter,
                         QStringLiteral("差异：绿=一致 红=不一致/缺失"));
        int unlocated = 0;
        for (const auto& pair : view_->pairs()) {
            if (QString::fromStdString(pair.well_id) != well) continue;
            if (pair.in_prediction && pair.bottom > pair.top) {
                const QRectF row(axis_w + 2, y_of(pair.top), w - 4,
                                 std::max(2.0, static_cast<double>(y_of(pair.bottom) - y_of(pair.top))));
                painter.fillRect(row, verdict_color(pair));
                painter.setPen(QColor(0x25, 0x31, 0x3d));
                painter.drawText(row, Qt::AlignHCenter | Qt::AlignVCenter,
                                 verdict_text(pair));
            } else {
                ++unlocated;
            }
        }
        if (unlocated > 0) {
            const double slice =
                (h - 8.0) / static_cast<double>(unlocated);
            int index = 0;
            for (const auto& pair : view_->pairs()) {
                if (QString::fromStdString(pair.well_id) != well) continue;
                if (pair.in_prediction && pair.bottom > pair.top) continue;
                const QRectF row(axis_w + 2, 4 + slice * index, w - 4,
                                 slice);
                painter.fillRect(row, verdict_color(pair));
                painter.setPen(QColor(0x25, 0x31, 0x3d));
                painter.drawText(row, Qt::AlignHCenter | Qt::AlignVCenter,
                                 verdict_text(pair));
                ++index;
            }
        }
    }

    // Shared depth cursor while linked (m domain only — ms coupling never
    // happens without a calibration, F:75).
    if (view_->link_enabled() && view_->cursor_depth() >= 0.0) {
        const int y = y_of(view_->cursor_depth());
        painter.setPen(QPen(QColor(0x00, 0x78, 0xd4), 1, Qt::DashLine));
        painter.drawLine(axis_w, y, width() - 4, y);
    }
}

}  // namespace pwb::app
