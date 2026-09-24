#include "comparison_view.hpp"

#include <algorithm>
#include <cmath>
#include <utility>

#include <QComboBox>
#include <QEvent>
#include <QHBoxLayout>
#include <QLabel>
#include <QMouseEvent>
#include <QToolButton>
#include <QVBoxLayout>

#include <pwb/qgis_plot/domain_plots.hpp>
#include <pwb/qgis_plot/numeric_formats.hpp>
#include <pwb/qgis_plot/plot_canvas.hpp>
#include <pwb/qgis_plot/plot_item.hpp>
#include <pwb/qgis_plot/plot_panel.hpp>

namespace pwb::app {

namespace {

using pwb::qgis_plot::PwbIntervalStripPlot;
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

PwbIntervalStripPlot::IntervalBand strip_band(const CompareBand& band,
                                            int alpha) {
    return {band.top, band.bottom, band_label(band),
            class_color(band_label(band)), alpha};
}

QColor verdict_color(const pwb::ui_review::BandPair& pair) {
    if (!pair.in_prediction || !pair.in_interpretation) {
        return QColor(0xc6, 0x28, 0x28, 140);  // presence mismatch
    }
    if (pair.comparable) {
        return pair.match ? QColor(0x2e, 0x7d, 0x32, 140)
                          : QColor(0xc6, 0x28, 0x28, 140);
    }
    return QColor(0x9a, 0xa4, 0xad, 100);  // incomparable
}

QString verdict_text(const pwb::ui_review::BandPair& pair) {
    if (!pair.in_prediction) return QStringLiteral("预测缺失");
    if (!pair.in_interpretation) return QStringLiteral("解释缺失");
    if (!pair.comparable) return QStringLiteral("不可比（未标注类别）");
    if (pair.match) return QStringLiteral("一致");
    return QStringLiteral("不一致：%1 ≠ %2")
        .arg(QString::fromStdString(pair.interpreted_class),
             QString::fromStdString(pair.predicted_class));
}

// One verdict column shared by SideBySide (col 3) and Difference (full
// width): located pairs land on their prediction extent, unlocated pairs
// split the depth range evenly — the same honest fallback as before.
QVector<PwbIntervalStripPlot::IntervalBand> verdict_bands(
    const std::vector<pwb::ui_review::BandPair>& pairs, const QString& well,
    double depth_min, double depth_max) {
    QVector<PwbIntervalStripPlot::IntervalBand> bands;
    int unlocated = 0;
    for (const auto& pair : pairs) {
        if (QString::fromStdString(pair.well_id) != well) continue;
        if (pair.in_prediction && pair.bottom > pair.top) {
            const QColor color = verdict_color(pair);
            bands.push_back({pair.top, pair.bottom, verdict_text(pair),
                             color, color.alpha()});
        } else {
            ++unlocated;
        }
    }
    if (unlocated > 0) {
        const double slice = (depth_max - depth_min) / unlocated;
        int index = 0;
        for (const auto& pair : pairs) {
            if (QString::fromStdString(pair.well_id) != well) continue;
            if (pair.in_prediction && pair.bottom > pair.top) continue;
            const QColor color = verdict_color(pair);
            bands.push_back({depth_min + slice * index,
                             depth_min + slice * (index + 1),
                             verdict_text(pair), color, color.alpha()});
            ++index;
        }
    }
    return bands;
}

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

    canvas_ = new pwb::qgis_plot::PwbPlotPanel(this);
    canvas_->setObjectName(QStringLiteral("CompareCanvas"));
    canvas_->canvas()->viewport()->setMouseTracking(true);
    outer->addWidget(canvas_, 1);

    summary_ = new QLabel(this);
    summary_->setObjectName(QStringLiteral("CompareSummary"));
    outer->addWidget(summary_);

    canvas_->canvas()->viewport()->installEventFilter(this);
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
    rebuild_plot();
}

bool ComparisonView::set_link_enabled(bool on) {
    if (!on) {
        link_ = false;
        const QSignalBlocker block(link_toggle_);
        link_toggle_->setChecked(false);
        cursor_depth_ = -1.0;
        update_cursor_guide();
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
    update_cursor_guide();
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

QWidget* ComparisonView::canvas() const { return canvas_; }

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
    rebuild_plot();
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
        update_cursor_guide();
        const QSignalBlocker block(link_toggle_);
        link_toggle_->setChecked(false);
    }
}

bool ComparisonView::eventFilter(QObject* watched, QEvent* event) {
    if (watched == canvas_->canvas()->viewport() &&
        event->type() == QEvent::MouseMove && link_) {
        auto* mouse = static_cast<QMouseEvent*>(event);
        const double depth = depth_at_canvas_pos(mouse->position());
        if (depth != cursor_depth_) {
            cursor_depth_ = depth;
            update_cursor_guide();
        }
    }
    return QWidget::eventFilter(watched, event);
}

// ---------------------------------------------------------------------------
// QGIS-plot strip columns
// ---------------------------------------------------------------------------

std::pair<double, double> ComparisonView::depth_range() const {
    const QString well = selected_well_id();
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
    grow(interpretation_bands_);
    grow(prediction_bands_);
    if (!any || bottom <= top) {
        return {0.0, 1.0};
    }
    return {top, bottom};
}

double ComparisonView::depth_at_canvas_pos(QPointF canvas_pos) const {
    const auto items = canvas_->canvas()->plotItems();
    for (auto* item : items) {
        const QRectF area = item->plotArea();
        if (area.isEmpty())
            continue;
        // All columns share the depth axis; clamp so cursor presses in the
        // top/bottom margins still resolve (old depth_at_y clamped too).
        const double cy = std::clamp(canvas_pos.y(), area.top(), area.bottom());
        const auto yr = item->yRange();
        const double plot_y =
            yr.lower() + (area.bottom() - cy) / area.height() *
                             (yr.upper() - yr.lower());
        return -plot_y;  // data y = -depth
    }
    return -1.0;
}

void ComparisonView::update_cursor_guide() {
    canvas_->canvas()->setHorizontalGuide(
        link_ && cursor_depth_ >= 0.0
            ? std::optional<double>(-cursor_depth_)
            : std::nullopt);
}

void ComparisonView::rebuild_plot() {
    auto* canvas = canvas_->canvas();
    canvas->clearPlots();
    cursor_depth_ = -1.0;
    const QString reason = empty_reason();
    if (!reason.isEmpty()) {
        canvas_->showUnavailable(reason);
        return;
    }
    canvas_->showPlot();

    const QString well = selected_well_id();
    const auto [depth_min, depth_max] = depth_range();

    std::vector<CompareBand> interp;
    std::vector<CompareBand> pred;
    for (const auto& band : interpretation_bands_) {
        if (QString::fromStdString(band.well_id) == well) {
            interp.push_back(band);
        }
    }
    for (const auto& band : prediction_bands_) {
        if (QString::fromStdString(band.well_id) == well) {
            pred.push_back(band);
        }
    }

    struct Column {
        QString title;
        QVector<PwbIntervalStripPlot::IntervalBand> bands;
    };
    QList<Column> columns;
    if (mode_ == CompareMode::SideBySide) {
        Column c_interp{QStringLiteral("解释"), {}};
        for (const auto& band : interp) {
            c_interp.bands.push_back(strip_band(band, 110));
        }
        Column c_pred{QStringLiteral("预测"), {}};
        for (const auto& band : pred) {
            c_pred.bands.push_back(strip_band(band, 160));
        }
        columns.push_back(std::move(c_interp));
        columns.push_back(std::move(c_pred));
        columns.push_back({QStringLiteral("差异"),
                           verdict_bands(pairs_, well, depth_min, depth_max)});
    } else if (mode_ == CompareMode::Overlay) {
        Column c_overlay{
            QStringLiteral("半透明叠加（解释 淡 / 预测 浓）"), {}};
        for (const auto& band : interp) {
            c_overlay.bands.push_back(strip_band(band, 80));
        }
        for (const auto& band : pred) {
            c_overlay.bands.push_back(strip_band(band, 130));
        }
        Column c_pred{QStringLiteral("预测为主"), {}};
        for (const auto& band : pred) {
            c_pred.bands.push_back(strip_band(band, 160));
        }
        for (const auto& band : interp) {
            c_pred.bands.push_back(strip_band(band, 70));
        }
        columns.push_back(std::move(c_overlay));
        columns.push_back(std::move(c_pred));
    } else {  // Difference
        columns.push_back(
            {QStringLiteral("差异：绿=一致 红=不一致/缺失"),
             verdict_bands(pairs_, well, depth_min, depth_max)});
    }

    bool first = true;
    for (const Column& column : columns) {
        auto strip = std::make_unique<PwbIntervalStripPlot>();
        strip->setBands(column.bands);
        strip->xAxis().setType(Qgis::PlotAxisType::Categorical);
        strip->yAxis().setNumericFormat(
            new pwb::qgis_plot::PwbDepthNumericFormat());
        strip->yAxis().setLabelSuffix(QStringLiteral(" m"));
        auto* item = canvas->addPlot(std::move(strip));
        // Strip columns are categorical in X; the shared axis is depth
        // (stored negated so shallow renders on top). Bands live outside
        // QgsPlotData, so the full extent is declared explicitly — this is
        // also what makes the panel's Fit action meaningful.
        item->setFullExtent(0.0, 1.0, -depth_max, -depth_min);
        item->setShareX(false);
        item->setShareY(true);
        item->setTopTitle(column.title);
        item->setAxisTitles(QString(),
                            first ? QStringLiteral("深度") : QString());
        first = false;
    }
    canvas->zoomFull();
    update_cursor_guide();
}

}  // namespace pwb::app
