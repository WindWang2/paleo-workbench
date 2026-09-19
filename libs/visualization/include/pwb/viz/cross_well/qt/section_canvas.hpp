#pragma once

// VIZ-B — multi-well cross-section canvas (Qt Widgets half).
// Port of geoviz_cross_well/canvas.py + the geoviz_well_log
// CrossWellWidget/ConnectionOverlay composition: one depth-synchronized
// column per well, tops/picks overlays, bezier correlation ties, TWT
// axis, cursor, pick interaction (add/connect/delete, dtw accept/
// reject), wheel zoom + drag pan on the shared viewport.
//
// Screen and export share ONE painting entry: paint_section(QPainter&,
// SectionScene&) — the same parity Python keeps between the overlay and
// _paint_composite. The scene is a value snapshot (no model pointers
// cross the paint boundary).

#include <limits>
#include <memory>
#include <optional>
#include <string>
#include <vector>

#include <QImage>
#include <QString>
#include <QWidget>

#include <pwb/viz/cross_well/picks_model.hpp>
#include <pwb/viz/cross_well/section_geometry.hpp>
#include <pwb/viz/cross_well/seismic_tie.hpp>
#include <pwb/viz/cross_well/tops_model.hpp>

class QPainter;
class QMouseEvent;
class QPaintEvent;
class QWheelEvent;
class QEvent;

namespace pwb::viz::cross_well::qt {

// Layout contract (Python constants): header 56 px inside each column,
// 28 px well-name band above the content, 180 px column width, 150 px
// inter-well spacing, depth ruler 64 px on the right.
inline constexpr double kColumnNameBandPx = 28.0;
inline constexpr double kColumnWidthPx = 180.0;
inline constexpr double kWellSpacingPx = 150.0;
inline constexpr double kDepthRulerWidthPx = 64.0;
inline constexpr double kLeftMarginPx = 20.0;

struct SectionView {
    double depth_top = 0.0;
    double depth_bottom = 100.0;
    [[nodiscard]] double span() const { return depth_bottom - depth_top; }
};

// A paintable snapshot of the whole section.
struct SectionScene {
    std::vector<WellColumnData> wells;       // display order
    std::vector<FormationTop> tops;          // resolved colours
    std::vector<HorizonPick> picks;          // copies
    std::string selected_pick;
    std::string hover_pick;
    SectionView view;
    bool show_tops = true;
    bool show_cursor = false;
    double cursor_depth = 0.0;
    std::string depth_domain = "MD";  // "MD" | "TWT"
    SeismicTie tie;                   // TWT axis source
    double hover_snap_depth = std::numeric_limits<double>::quiet_NaN();
    double hover_snap_value = std::numeric_limits<double>::quiet_NaN();
    int hover_well_index = -1;
};

// Paint the whole scene into painter (0,0,width,height). Pure function —
// used by the live widget, the offscreen export and the report layout.
void paint_section(QPainter* painter, const SectionScene& scene,
                   double width_px, double height_px);

// Composite export (cross_well_widget.export_composite parity): natural
// size = sum of columns + spacing + ruler; optional width rescale (all
// formats) and PDF page fit ("A4"/"LETTER", landscape when wide).
bool export_section_composite(const SectionScene& scene, const QString& path,
                              const QString& fmt, int dpi,
                              const std::optional<int>& width_px,
                              const std::optional<QString>& page_size);

class SectionCanvas : public QWidget {
    Q_OBJECT
  public:
    explicit SectionCanvas(QWidget* parent = nullptr);
    ~SectionCanvas() override;

    // Column order == display order; display_curve per column is chosen
    // with extract_curve(preferred) unless the caller pre-fills it.
    void set_wells(const std::vector<WellColumnData>& wells);
    void set_models(FormationTopsModel* tops, HorizonPicksModel* picks);
    void set_seismic_tie(const SeismicTie& tie);
    void set_pick_mode(bool on);
    void set_active_formation(const QString& formation);
    void set_snap(pwb::viz::cross_well::SnapType type, double window_m);
    void set_show_tops(bool show);
    void set_depth_domain(const QString& domain);  // "MD" | "TWT"
    void zoom_full();
    [[nodiscard]] SectionScene build_scene() const;
    [[nodiscard]] std::vector<std::string> well_names() const;

    [[nodiscard]] std::optional<double> cursor_depth() const {
        return cursor_depth_;
    }

  signals:
    // Any interaction that changed the picks/tops models (the dock
    // persists on this).
    void interaction_changed();
    void cursor_moved(double depth_m);
    // Right-edge context action emitted for the dock to schedule the
    // JobCenter DTW propagation (never run inline).
    void dtw_propagation_requested(const QString& ref_well,
                                   double ref_depth);

  protected:
    void paintEvent(QPaintEvent* event) override;
    void mouseMoveEvent(QMouseEvent* event) override;
    void mousePressEvent(QMouseEvent* event) override;
    void mouseReleaseEvent(QMouseEvent* event) override;
    void wheelEvent(QWheelEvent* event) override;
    void leaveEvent(QEvent* event) override;

  private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
    std::optional<double> cursor_depth_;
};

}  // namespace pwb::viz::cross_well::qt
