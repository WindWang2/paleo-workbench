#pragma once

// UI-16 — honest Qt port of proto_dual_volume_overlay.py
// ([NON-PRODUCTION] design exploration prototype, zero production
// references — the port keeps the same status: a standalone widget +
// host window, no engine seams because the synthetic volumes are
// generated in-memory exactly like the Python).
//
// DualVolumeOverlayWidget: slice extraction + variant blending (the
// Qt-free dual_volume.hpp core) rendered to a QPixmap with the
// prototype's state-readout overlay.
// ProtoDualVolumeWindow: the MainWindow port — control bar (axis /
// slice / opacity / threshold), canvas, bottom variant switcher.

#include <QMainWindow>
#include <QPixmap>
#include <QWidget>

#include <pwb/ui_visualqa/dual_volume.hpp>

class QButtonGroup;
class QComboBox;
class QSlider;

namespace pwb::ui_visualqa::qt {

class DualVolumeOverlayWidget : public QWidget {
    Q_OBJECT
public:
    DualVolumeOverlayWidget(const ScalarVolume& amp_vol,
                            const ScalarVolume& coh_vol,
                            QWidget* parent = nullptr);

    // set_variant / set_slice / set_opacity / set_threshold parity —
    // each triggers update_render() like the Python setters.
    void set_variant(const QString& variant_label);
    void set_slice(int axis, int idx);
    void set_opacity(double value);
    void set_threshold(double value);

    // update_render parity: rebuild the RGBA image (records
    // last_render_ms) then schedule a repaint.
    void update_render();

    // Readout accessors (the paintEvent state block's facts).
    [[nodiscard]] QString variant_label() const { return variant_label_; }
    [[nodiscard]] int axis() const { return axis_; }
    [[nodiscard]] int slice_index() const { return slice_idx_; }
    [[nodiscard]] double opacity() const { return opacity_; }
    [[nodiscard]] double threshold() const { return threshold_; }
    [[nodiscard]] double last_render_ms() const { return last_render_ms_; }

protected:
    void paintEvent(QPaintEvent* event) override;

private:
    ScalarVolume amp_vol_;
    ScalarVolume coh_vol_;
    OverlayVariant variant_ = OverlayVariant::AlphaBlending;
    QString variant_label_;
    int axis_ = kAxisTime;
    int slice_idx_ = 0;
    double opacity_ = 0.5;
    double threshold_ = 0.6;
    double last_render_ms_ = 0.0;
    QPixmap pixmap_;
};

class ProtoDualVolumeWindow : public QMainWindow {
    Q_OBJECT
public:
    explicit ProtoDualVolumeWindow(QWidget* parent = nullptr);

    // Test/inspection accessors (the Python attribute parity).
    [[nodiscard]] DualVolumeOverlayWidget* canvas() const {
        return canvas_;
    }
    [[nodiscard]] QComboBox* axis_combo() const { return axis_combo_; }
    [[nodiscard]] QSlider* slice_slider() const { return slice_slider_; }
    [[nodiscard]] QSlider* opacity_slider() const { return opacity_slider_; }
    [[nodiscard]] QSlider* threshold_slider() const { return thresh_slider_; }

private:
    DualVolumeOverlayWidget* canvas_ = nullptr;
    QComboBox* axis_combo_ = nullptr;
    QSlider* slice_slider_ = nullptr;
    QSlider* opacity_slider_ = nullptr;
    QSlider* thresh_slider_ = nullptr;
    QButtonGroup* var_group_ = nullptr;
};

}  // namespace pwb::ui_visualqa::qt
