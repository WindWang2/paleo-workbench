#pragma once

// VIZ-B — formation tops preview widget (Qt Widgets half).
// Port of geoviz_cross_well/formation_preview.py: small tops-comparison
// canvas with per-well vertical axes, adjacent-well connection lines,
// wheel zoom + drag pan, hover tooltips. The geometry lives in the
// Qt-free formation_preview.hpp (oracle-frozen); this widget only
// paints and routes events through it.

#include <QString>
#include <QWidget>

#include <string>
#include <utility>
#include <vector>

#include <pwb/viz/cross_well/formation_preview.hpp>
#include <pwb/viz/cross_well/tops_model.hpp>

class QEvent;
class QMouseEvent;
class QPaintEvent;
class QWheelEvent;

namespace pwb::viz::cross_well::qt {

class FormationTopsPreview : public QWidget {
    Q_OBJECT
  public:
    explicit FormationTopsPreview(QWidget* parent = nullptr);

    // Sorted unique well names; per-well tops in input order (the
    // first sighting of a formation per well feeds the connections).
    void set_tops(const std::vector<FormationTop>& tops);
    void clear();

    [[nodiscard]] std::pair<double, double> full_range() const {
        return full_range_;
    }

  signals:
    void hovered_top_changed(const QString& well, const QString& formation,
                             double depth);

  protected:
    void paintEvent(QPaintEvent* event) override;
    void wheelEvent(QWheelEvent* event) override;
    void mousePressEvent(QMouseEvent* event) override;
    void mouseMoveEvent(QMouseEvent* event) override;
    void mouseReleaseEvent(QMouseEvent* event) override;
    void leaveEvent(QEvent* event) override;

  private:
    void rebuild();
    std::vector<FormationTop> tops_;
    std::vector<std::string> well_names_;
    std::vector<std::vector<FormationTop>> tops_per_well_;
    std::vector<pwb::viz::cross_well::PreviewVisiblePoint> visible_points_;
    pwb::viz::cross_well::PreviewLayout layout_;
    std::pair<double, double> full_range_{0.0, 1.0};
    std::string hover_key_;  // well|formation|depth of the last emit
    bool dragging_ = false;
    double drag_start_y_ = 0.0;
};

}  // namespace pwb::viz::cross_well::qt
