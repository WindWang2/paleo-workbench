#pragma once

// VIZ-C — 2D ActiveTimeSlice map (time_map_2d.py port): plan-view
// amplitude slice + pierce points + the well-order polyline. Click a
// well point to append it to the fence (well_clicked carries the
// JointWellId). Honest empty state when the scene/volume is not ready.
// 06 closure: the amplitude plane is never read here — the joint host
// reads it on the job worker and injects the colorized image via
// set_prepared_slice; a sample-stale image shows an honest pending note
// instead of blocking the GUI on a cold tile.
#include <QWidget>

#include <pwb/geo3d_viz/joint/joint_scene.hpp>

class QImage;

namespace pwb::app::viz_c {

class VizCTimeSliceMap : public QWidget {
    Q_OBJECT

public:
    explicit VizCTimeSliceMap(QWidget* parent = nullptr);

    void set_scene(pwb::geo3d_viz::joint::WellSeismicScene* scene);
    // Rebuild the cached hits/caption from the scene (cheap, read-free).
    // The amplitude image stays from the last applied prepared slice; a
    // different active sample shows the pending note until the worker
    // payload for the new sample arrives.
    void refresh();
    // Inject a colorized slice prepared by the job runtime (RGBA bytes +
    // shape + the sample index it was read at); empty resets to the
    // honest placeholder.
    void set_prepared_slice(const std::vector<unsigned char>& rgba,
                            std::int64_t n_inline,
                            std::int64_t n_crossline,
                            std::int64_t sample_index);

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
    std::int64_t image_sample_ = -1;
    bool image_pending_ = false;
    std::vector<pwb::geo3d_viz::joint::WellPierce> pierces_;
    std::vector<std::array<double, 2>> hits_;  // widget px per pierce
    std::vector<QString> path_ids_;
    QString caption_;
};

}  // namespace pwb::app::viz_c
