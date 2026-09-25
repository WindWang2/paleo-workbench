#include <pwb/closure_science/qt/well_seismic_link.hpp>

#include <pwb/ui_wellseis/qt/seismic_prediction_page.hpp>
#include <pwb/ui_wellseis/qt/seismic_view_panel.hpp>
#include <pwb/ui_wellseis/qt/well_log_canvas_panel.hpp>
#include <pwb/ui_wellseis/qt/well_log_prediction_page.hpp>

#include <QPointer>
#include <QString>

#include <algorithm>
#include <cmath>

namespace pwb::closure_science::qt {

using ui_wellseis::qt::SeismicPredictionPage;
using ui_wellseis::qt::WellLogPredictionPage;

namespace {
QString qs(const std::string& text) {
    return QString::fromStdString(text);
}
}  // namespace

pwb::viz::well_tie::WellTieCalibration
WellTimeDepthCalibration::to_calibration() const {
    return pwb::viz::well_tie::WellTieCalibration(depths_m, twt_ms);
}

WellSeismicLinkController::WellSeismicLinkController(QObject* parent)
    : QObject(parent) {}

WellSeismicLinkController::~WellSeismicLinkController() = default;

void WellSeismicLinkController::attach(WellLogPredictionPage* well_page,
                                       SeismicPredictionPage* seismic_page) {
    // Drop any previous attachment first: re-attaching the SAME live pages
    // must not stack duplicate cursor conversions (the old senders' QObject
    // death already cleaned the swapped-page case).
    if (well_page_ != nullptr) {
        disconnect(well_page_, nullptr, this, nullptr);
        if (auto* canvas = well_page_->canvas_panel(); canvas != nullptr) {
            disconnect(canvas, nullptr, this, nullptr);
        }
    }
    if (seismic_page_ != nullptr &&
        seismic_page_->view_panel() != nullptr) {
        disconnect(seismic_page_->view_panel(), nullptr, this, nullptr);
    }
    well_page_ = well_page;
    seismic_page_ = seismic_page;
    if (well_page_ != nullptr) {
        // Focused-well identity: the page's stable selection, resynced on
        // every change (the controller keeps no second selection copy).
        connect(well_page_, &WellLogPredictionPage::well_selection_changed,
                this, [this](const QString& resource_id) {
                    focus_well(resource_id.toStdString());
                });
        if (auto* canvas = well_page_->canvas_panel();
            canvas != nullptr) {
            connect(
                canvas,
                &ui_wellseis::qt::WellLogCanvasPanel::depth_cursor_published,
                this,
                [this](double depth_m) { on_depth_cursor(depth_m); });
        }
        const std::optional<std::string> current =
            well_page_->selected_well_resource_id();
        if (current.has_value()) focus_well(*current);
    }
    if (seismic_page_ != nullptr) {
        if (auto* view = seismic_page_->view_panel(); view != nullptr) {
            connect(
                view, &ui_wellseis::qt::SeismicViewPanel::cursor_published,
                this, [this](double il, double xl, double twt_ms) {
                    on_seismic_cursor(il, xl, twt_ms);
                });
        }
    }
    refresh_availability();
}

void WellSeismicLinkController::set_calibration_provider(
    CalibrationProvider provider) {
    calibration_provider_ = std::move(provider);
    if (focused_well_id_.empty() && well_page_ != nullptr) {
        const std::optional<std::string> current =
            well_page_->selected_well_resource_id();
        if (current.has_value()) focused_well_id_ = *current;
    }
    refresh_availability();
}

bool WellSeismicLinkController::set_enabled(bool on) {
    if (on) {
        if (!is_available()) {
            // Fail closed with the exact reason — never a fake linkage.
            enabled_ = false;
            emit link_enabled_changed(false);
            emit link_status_message(
                QStringLiteral("井震联动不可用: %1").arg(unavailable_reason()));
            return false;
        }
        enabled_ = true;
        const std::string well =
            active_calibration_.has_value() && !active_calibration_->well_name.empty()
                ? active_calibration_->well_name
                : focused_well_id_;
        // Unit honesty: the conversion's depths come from the calibration
        // table (metres); an unknown canvas depth-unit is surfaced as a
        // warning, never silently treated as metres.
        const auto unit_reason =
            well_page_ != nullptr
                ? well_page_->canvas_panel()
                      ->depth_cursor_unavailable_reason()
                : std::nullopt;
        emit link_enabled_changed(true);
        emit link_status_message(
            QStringLiteral("井震联动已开启（井: %1，时深标定 %2 个锚点）%3")
                .arg(qs(well))
                .arg(static_cast<int>(active_calibration_->twt_ms.size()))
                .arg(unit_reason.has_value()
                         ? QStringLiteral("；注意：测井深度单位未知（%1）")
                               .arg(qs(*unit_reason))
                         : QString()));
        return true;
    }
    if (enabled_) {
        enabled_ = false;
        emit link_enabled_changed(false);
        emit link_status_message(QStringLiteral("井震联动已关闭"));
    }
    return false;
}

bool WellSeismicLinkController::is_enabled() const { return enabled_; }

void WellSeismicLinkController::refresh() {
    // Project switch/close: re-anchor on the (new) page's current selection
    // and re-resolve the calibration against the CURRENT provider backing —
    // the previous project's table must not keep a dead link alive.
    if (well_page_ != nullptr) {
        const std::optional<std::string> current =
            well_page_->selected_well_resource_id();
        focused_well_id_ =
            current.has_value() ? *current : std::string();
    } else {
        focused_well_id_.clear();
    }
    const bool was_enabled = enabled_;
    refresh_availability();
    if (was_enabled && !enabled_) {
        // refresh_availability flipped the link off; surface why.
        emit link_status_message(
            QStringLiteral("井震联动已自动关闭: %1").arg(unavailable_reason()));
    }
}

QString WellSeismicLinkController::unavailable_reason() const {
    if (well_page_ == nullptr || seismic_page_ == nullptr) {
        return QStringLiteral("预测页面未装配");
    }
    if (well_page_->canvas_panel() == nullptr ||
        seismic_page_->view_panel() == nullptr) {
        return QStringLiteral("测井/地震画布面板缺失");
    }
    if (focused_well_id_.empty()) {
        return QStringLiteral("未选择井（先在测井页选择一口井）");
    }
    if (!active_calibration_.has_value() ||
        !active_calibration_->valid()) {
        return QStringLiteral(
            "井 %1 没有已记录的时深标定（time_depth_calibrations），"
            "m↔ms 联动按失败关闭处理，不做线性速度伪造")
            .arg(qs(focused_well_id_));
    }
    if (!well_page_->canvas_panel()->depth_cursor_supported()) {
        return QStringLiteral("测井画布不支持深度游标通道");
    }
    return QString();
}

std::optional<WellSeismicLinkController::CursorPair>
WellSeismicLinkController::last_conversion() const {
    return last_conversion_;
}

void WellSeismicLinkController::refresh_availability() {
    if (!focused_well_id_.empty() && calibration_provider_) {
        active_calibration_ = calibration_provider_(focused_well_id_);
        if (active_calibration_.has_value() &&
            !active_calibration_->valid()) {
            active_calibration_.reset();
        }
    } else {
        active_calibration_.reset();
    }
    // The conversion object is built once per resolved table — cursor
    // events (mouse-move frequency) only interpolate.
    active_conversion_.reset();
    if (active_calibration_.has_value()) {
        try {
            active_conversion_ = active_calibration_->to_calibration();
        } catch (const std::exception&) {
            active_calibration_.reset();
        }
    }
    const bool available = is_available();
    if (!available && enabled_) {
        // The world changed under an active link (well switched to one
        // without calibration): fail closed immediately.
        enabled_ = false;
        emit link_enabled_changed(false);
    }
    emit link_availability_changed(available);
}

void WellSeismicLinkController::focus_well(const std::string& resource_id) {
    // Always re-resolve: the provider's backing data (e.g. the project
    // document's calibration section) may have changed under the same
    // well id — a cached table must never outlive its source.
    focused_well_id_ = resource_id;
    refresh_availability();
    if (enabled_ && !is_available()) {
        // refresh_availability already flipped enabled_; surface it.
        emit link_status_message(
            QStringLiteral("井震联动已自动关闭: %1").arg(unavailable_reason()));
    }
}

void WellSeismicLinkController::on_seismic_cursor(double il, double xl,
                                                  double twt_ms) {
    if (!enabled_ || !active_conversion_.has_value()) return;
    if (!std::isfinite(twt_ms)) return;
    const double depth_m = active_conversion_->twt_to_depth(twt_ms);
    if (!std::isfinite(depth_m)) return;
    last_conversion_ = CursorPair{depth_m, twt_ms};
    // Offered through the canvas's own 120 ms gate — the controller
    // adds no second throttle on top of the panels' gates.
    if (well_page_ != nullptr && well_page_->canvas_panel() != nullptr) {
        well_page_->canvas_panel()->offer_depth_cursor(depth_m);
    }
    emit link_status_message(QStringLiteral(
                                "井震联动: inline %1 crossline %2 "
                                "%3 ms ↔ %4 m")
                                .arg(il, 0, 'f', 1)
                                .arg(xl, 0, 'f', 1)
                                .arg(twt_ms, 0, 'f', 1)
                                .arg(depth_m, 0, 'f', 1));
}

void WellSeismicLinkController::on_depth_cursor(double depth_m) {
    if (!enabled_ || !active_conversion_.has_value()) return;
    if (!std::isfinite(depth_m)) return;
    const double twt_ms = active_conversion_->depth_to_twt(depth_m);
    if (!std::isfinite(twt_ms)) return;
    last_conversion_ = CursorPair{depth_m, twt_ms};
    // Echo only: the well does not know its il/xl, so the reverse
    // direction cannot honestly drive the seismic cursor.
    emit link_status_message(QStringLiteral("井震联动: 深度 %1 m ↔ %2 ms")
                                 .arg(depth_m, 0, 'f', 1)
                                 .arg(twt_ms, 0, 'f', 1));
}

}  // namespace pwb::closure_science::qt
