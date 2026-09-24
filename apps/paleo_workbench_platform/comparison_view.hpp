#pragma once

// M5 — 解释 vs 预测对比视图 (design F:72-75): three modes (并排 / 叠加 /
// 差异) over REAL depth bands only (ui_review::compare_core):
//
//   解释版本 = project.correlation_interpretations + artifact payload
//   预测成果 = project.prediction_tasks result_summary.predicted_regions
//
// Honest empty states name what is missing and where to produce it; the
// mode buttons disable without data. The 联动 toggle (深度游标跨列联动)
// is gated on a REAL time-depth calibration for the selected well — with
// none, m and ms never couple (F:75), the toggle disables with the
// reason in its tooltip.

#include <functional>
#include <optional>
#include <utility>
#include <vector>

#include <QPointF>
#include <QVariantMap>
#include <QWidget>

#include <pwb/domain/json.hpp>
#include <pwb/ui_review/compare_core.hpp>

class QComboBox;
class QLabel;
class QToolButton;

namespace pwb::qgis_plot {
class PwbPlotPanel;
}

namespace pwb::app {

class ComparisonView : public QWidget {
    Q_OBJECT
public:
    struct SourceSet {
        std::vector<pwb::domain::Json> interpretations;
        std::vector<pwb::domain::Json> predictions;
    };

    explicit ComparisonView(QWidget* parent = nullptr);

    // Host-injected data seams (bound by the M5 install to the live
    // project document; absent → the honest empty states).
    void set_source_provider(std::function<SourceSet()> provider);
    void set_artifact_reader(
        std::function<std::optional<pwb::domain::Json>(const std::string& path)>
            reader);
    // Time-depth calibration gate (F:75): true only when a real
    // calibration exists for the well — never assumed.
    void set_calibration_provider(
        std::function<bool(const std::string& well_id)> provider);

    void reload();
    void set_mode(pwb::ui_review::CompareMode mode);
    pwb::ui_review::CompareMode mode() const { return mode_; }
    // False (with a status message) when no calibration covers the
    // selected well — the honest refusal, never a silent no-op.
    bool set_link_enabled(bool on);
    bool link_enabled() const { return link_; }

    // Command/test surface.
    QComboBox* object_selector() const { return object_; }
    QComboBox* baseline_selector() const { return baseline_; }
    QComboBox* prediction_selector() const { return prediction_; }
    QWidget* canvas() const;
    QToolButton* link_toggle() const { return link_toggle_; }
    QString empty_reason() const;
    QString selected_well_id() const;
    // Paint-surface accessors (the canvas reads the view's cached state).
    const std::vector<pwb::ui_review::CompareBand>& interpretation_bands()
        const {
        return interpretation_bands_;
    }
    const std::vector<pwb::ui_review::CompareBand>& prediction_bands()
        const {
        return prediction_bands_;
    }
    const std::vector<pwb::ui_review::BandPair>& pairs() const {
        return pairs_;
    }
    double cursor_depth() const { return cursor_depth_; }

signals:
    void status_message(const QString& message);
    void link_changed(bool enabled);
    // Calibration-gate transition (the QAction binding follows this).
    void link_availability_changed(bool available);

protected:
    bool eventFilter(QObject* watched, QEvent* event) override;

private:
    void rebuild_selectors();
    void refresh_bands();
    void refresh_link_gate();
    // Rebuilds the QGIS-plot strip columns for the current mode/selection.
    void rebuild_plot();
    void update_cursor_guide();
    double depth_at_canvas_pos(QPointF canvas_pos) const;
    std::pair<double, double> depth_range() const;

    std::function<SourceSet()> source_provider_;
    std::function<std::optional<pwb::domain::Json>(const std::string& path)>
        artifact_reader_;
    std::function<bool(const std::string& well_id)> calibration_provider_;

    pwb::ui_review::CompareMode mode_ = pwb::ui_review::CompareMode::SideBySide;
    bool link_ = false;

    QComboBox* object_ = nullptr;      // 对象 (井)
    QComboBox* baseline_ = nullptr;    // 基准解释版本
    QComboBox* prediction_ = nullptr;  // 预测成果
    QToolButton* link_toggle_ = nullptr;
    pwb::qgis_plot::PwbPlotPanel* canvas_ = nullptr;
    QLabel* summary_ = nullptr;

    // Cached bands for the current selection (painted by the canvas).
    std::vector<pwb::ui_review::CompareBand> interpretation_bands_;
    std::vector<pwb::ui_review::CompareBand> prediction_bands_;
    std::vector<pwb::ui_review::BandPair> pairs_;
    double cursor_depth_ = -1.0;  // shared depth cursor while linked
};

}  // namespace pwb::app
