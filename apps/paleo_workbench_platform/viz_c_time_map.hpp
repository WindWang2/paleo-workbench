#pragma once

// VIZ-C — 2D ActiveTimeSlice map (time_map_2d.py port): plan-view
// amplitude slice + pierce points + the well-order polyline. Click a
// well point to append it to the fence (well_clicked carries the
// JointWellId). Honest empty state when the scene/volume is not ready.
#include <QWidget>

#include <pwb/geo3d_viz/joint/joint_scene.hpp>

class QImage;

namespace pwb::app::viz_c {

class VizCTimeSliceMap : public QWidget {
    Q_OBJECT

public:
    explicit VizCTimeSliceMap(QWidget* parent = nullptr);

    void set_scene(pwb::geo3d_viz::joint::WellSeismicScene* scene);
    // Rebuild the cached image/hits from the scene (cheap; the amplitude
    // slice itself is prepared off the GUI thread and injected).
    void refresh();
    // Inject a colorized slice prepared by the job runtime (RGBA bytes +
    // shape); empty resets to the honest placeholder.
    void set_prepared_slice(const std::vector<unsigned char>& rgba,
                            std::int64_t n_inline,
                            std::int64_t n_crossline);

signals:
    void well_clicked(const QString& well_id);

protected:
    void paintEvent(QPaintEvent* event) override;
    void resizeEvent(QResizeEvent* event) override;
    void mousePressEvent(QMouseEvent* event) override;

private:
    void recompute_hits();

    pwb::geo3d_viz::joint::WellSeismicScene* scene_ = nullptr;
    QImage* image_ = nullptr;
    std::vector<pwb::geo3d_viz::joint::WellPierce> pierces_;
    std::vector<std::array<double, 2>> hits_;  // widget px per pierce
    std::vector<QString> path_ids_;
    QString caption_;
};

}  // namespace pwb::app::viz_c
