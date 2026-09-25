// pwb::closure_science::qt — the ws1 well-seismic link (predict.link).
//
// ONE owner for the link state. Real linkage, fail closed:
//   * seismic cursor (il, xl, twt ms, ≤30 ms gated) -> time-depth
//     conversion over the CURRENT well's recorded calibration table ->
//     the well-log canvas depth cursor (offered through its 120 ms gate);
//   * well-log depth cursor -> TWT echo (status only — the reverse
//     direction would need the well's il/xl, which no current surface
//     provides; fabricating a position is not linkage);
//   * m <-> ms conversion ONLY exists when the project records a real
//     time-depth calibration for the focused well — no calibration, no
//     linear-velocity fake; the exact reason is surfaced instead.
//
// Conversion semantics are pwb::viz::well_tie::WellTieCalibration's
// (np.interp: piecewise-linear over ascending anchors, endpoint clamping,
// never extrapolation) — the same authority the well-tie line uses.
#pragma once

#include <pwb/domain/json.hpp>
#include <pwb/viz/well_tie/calibration.hpp>

#include <QObject>
#include <QPointer>
#include <QString>

#include <functional>
#include <optional>
#include <string>

namespace pwb::ui_wellseis::qt {
class SeismicPredictionPage;
class WellLogPredictionPage;
}

namespace pwb::closure_science::qt {

// A recorded time-depth calibration for one well (ascending anchor pairs).
// Fewer than two finite pairs = not a calibration.
struct WellTimeDepthCalibration {
    std::string well_resource_id;
    std::string well_name;
    std::vector<double> depths_m;
    std::vector<double> twt_ms;

    [[nodiscard]] bool valid() const {
        return depths_m.size() == twt_ms.size() && depths_m.size() >= 2;
    }
    // Builds the conversion (throws std::invalid_argument on a malformed
    // table like WellTieCalibration does; valid() tables never throw).
    [[nodiscard]] pwb::viz::well_tie::WellTieCalibration to_calibration()
        const;
};

class WellSeismicLinkController : public QObject {
    Q_OBJECT
public:
    // Resolves the recorded calibration for a well ("" well = nullopt).
    // Production reads ProjectDocument coordinate.time_depth_calibrations;
    // tests inject deterministic tables.
    using CalibrationProvider = std::function<std::optional<
        WellTimeDepthCalibration>(const std::string& well_resource_id)>;

    explicit WellSeismicLinkController(QObject* parent = nullptr);
    ~WellSeismicLinkController() override;

    // Connects the well-log depth cursor + seismic cursor + well selection
    // of the two ws1 pages. Safe to re-attach (old connections die with
    // their senders; the controller parents nothing onto the pages).
    void attach(ui_wellseis::qt::WellLogPredictionPage* well_page,
                ui_wellseis::qt::SeismicPredictionPage* seismic_page);
    void set_calibration_provider(CalibrationProvider provider);

    // Toggle. Returns the effective state: enabling without a usable
    // calibration stays OFF (fail closed) and surfaces the reason via
    // link_status_message / unavailable_reason.
    bool set_enabled(bool on);
    [[nodiscard]] bool is_enabled() const;

    // Re-resolves the focused well's calibration against the CURRENT
    // provider backing (project switch / close: the old project's table
    // must never keep a live link alive — see notify_project_changed).
    void refresh();

    // "" when the link could run right now; otherwise the exact reason
    // (no pages attached / no well selected / no calibration for the well /
    // depth unit unusable on the canvas).
    [[nodiscard]] QString unavailable_reason() const;
    [[nodiscard]] bool is_available() const {
        return unavailable_reason().isEmpty();
    }

    // Last conversion the link performed (depth m, twt ms) — for tests and
    // status surfaces. nullopt until a gated cursor event converts.
    struct CursorPair {
        double depth_m = 0.0;
        double twt_ms = 0.0;
    };
    [[nodiscard]] std::optional<CursorPair> last_conversion() const;

signals:
    void link_status_message(const QString& message);
    void link_availability_changed(bool available);
    void link_enabled_changed(bool enabled);

private:
    void refresh_availability();
    void focus_well(const std::string& resource_id);
    void on_seismic_cursor(double il, double xl, double twt_ms);
    void on_depth_cursor(double depth_m);

    // QPointer: the pages die with the shell like this controller, but the
    // guard makes that lifetime an enforced invariant instead of a lucky
    // assembly fact (a destroyed page reads as null, never a dereference).
    QPointer<ui_wellseis::qt::WellLogPredictionPage> well_page_;
    QPointer<ui_wellseis::qt::SeismicPredictionPage> seismic_page_;
    CalibrationProvider calibration_provider_;
    std::optional<WellTimeDepthCalibration> active_calibration_;
    // Built once per refresh — cursor events must not rebuild it.
    std::optional<pwb::viz::well_tie::WellTieCalibration> active_conversion_;
    std::string focused_well_id_;
    bool enabled_ = false;
    std::optional<CursorPair> last_conversion_;
};

}  // namespace pwb::closure_science::qt
