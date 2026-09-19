#pragma once

// Port of paleo_workbench/ui/pages/seismic_slice_preview_widget.py (UI-07):
// axis combo (inline/crossline/time), index slider with 16ms render
// debounce, volume-wide stretch range computed once per volume, blue →
// white → red Indexed8 QImage. Slice reads go through
// pwb::viz::ISeismicVolume + map_slice_to_indexed8 — the stretch kernel
// is not reimplemented here.

#include <QImage>
#include <QList>
#include <QPixmap>
#include <QTimer>
#include <QWidget>
#include <memory>
#include <optional>
#include <vector>

class QComboBox;
class QLabel;
class QSlider;

namespace pwb::viz {
class ISeismicVolume;
}

namespace pwb::ui_pages_preview {

struct PreviewSettings;

class SeismicSlicePreviewWidget : public QWidget {
    Q_OBJECT
public:
    explicit SeismicSlicePreviewWidget(QWidget* parent = nullptr);

    // load_seismic(path, revision, volume, message): null volume shows the
    // message fallback and disables controls (#894-4 parity).
    void load_seismic(const QString& path, const QString& revision = QString(),
                      std::shared_ptr<pwb::viz::ISeismicVolume> volume = nullptr,
                      const QString& message = QString());

    void apply_settings(const PreviewSettings& settings);

    QComboBox* type_combo() const { return type_combo_; }
    QSlider* slider() const { return slider_; }
    QLabel* index_label() const { return index_label_; }
    QLabel* image_label() const { return image_label_; }
    QLabel* message_label() const { return image_label_; }  // compat alias

protected:
    void resizeEvent(QResizeEvent* event) override;

private:
    void on_type_changed(int index);
    void on_slider_changed(int value);
    void update_slider_range();
    void render_slice();

    // Volume-wide finite min/max (global_stretch_range parity): reads every
    // slice once on the first rendered frame and caches the range so every
    // slice shares one stable color mapping.
    std::pair<double, double> volume_stretch_range();

    std::shared_ptr<pwb::viz::ISeismicVolume> volume_;
    QString path_;
    QString revision_;
    std::optional<std::pair<double, double>> stretch_range_;

    QComboBox* type_combo_ = nullptr;
    QSlider* slider_ = nullptr;
    QLabel* index_label_ = nullptr;
    QLabel* image_label_ = nullptr;
    QTimer render_timer_;

    QPixmap last_pixmap_;
    std::vector<std::uint8_t> last_norm_;  // keeps the QImage backing alive
    QList<QRgb> color_table_;              // 256-entry B-W-R ramp (lazy)
};

}  // namespace pwb::ui_pages_preview
