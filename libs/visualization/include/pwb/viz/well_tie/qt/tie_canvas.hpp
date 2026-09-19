#pragma once

// VIZ-B — well tie canvas (Qt Widgets half).
// Port of geoviz_well_tie/canvas.py: the 7-track layout contract
// (Depth/TWT, DT/RHOB, AI, RC, Synthetic, Seismic, Correlation) with
// fixed pixel widths [80, 140, 110, 70, 100, 120, 90], 36 px header,
// cream background, hover crosshair. The Python canvas only painted the
// headers + hover line (its data pipeline was wired, tracks were not);
// this port completes the track bodies from the same value pipeline
// (synthetic_generator semantics are NOT used — the canonical kernels
// feed set_tie_data via the dock).

#include <memory>
#include <vector>

#include <QString>
#include <QWidget>

class QEvent;
class QMouseEvent;
class QPaintEvent;

namespace pwb::viz::well_tie::qt {

// Track contract (canvas.py fixed widths, total 710 px).
inline constexpr double kTieHeaderHeightPx = 36.0;
inline constexpr int kTieTrackCount = 7;

class WellTieCanvas : public QWidget {
    Q_OBJECT
  public:
    explicit WellTieCanvas(QWidget* parent = nullptr);
    ~WellTieCanvas() override;

    // depths (m), twt (ms), sonic (µs/m), density (g/cm³), seismic trace
    // (arbitrary grid — resampled onto the TWT axis by the caller), and
    // an optional wavelet (defaults to ricker 30 Hz / 2 ms / 51 samples).
    void set_tie_data(const std::vector<double>& depths,
                      const std::vector<double>& twt,
                      const std::vector<double>& sonic,
                      const std::vector<double>& density,
                      const std::vector<double>& seismic,
                      const std::vector<float>& wavelet = {});

    [[nodiscard]] double correlation_r() const { return correlation_; }
    [[nodiscard]] int lag_samples() const { return lag_samples_; }
    [[nodiscard]] double lag_ms() const { return lag_ms_; }
    [[nodiscard]] std::size_t sample_count() const { return depths_.size(); }

  signals:
    // Python declared cursor_moved(depth, twt, correlation) but never
    // emitted it; the port emits on hover with the interpolated values.
    void cursor_moved(double depth_m, double twt_ms, double correlation);

  protected:
    void paintEvent(QPaintEvent* event) override;
    void mouseMoveEvent(QMouseEvent* event) override;
    void leaveEvent(QEvent* event) override;

  private:
    void recalculate();
    std::vector<double> depths_;
    std::vector<double> twt_;
    std::vector<double> sonic_;
    std::vector<double> density_;
    std::vector<double> seismic_;
    std::vector<float> wavelet_;
    // Derived pipeline (canonical kernels).
    std::vector<double> impedance_;
    std::vector<float> reflectivity_;
    std::vector<float> synthetic_;
    double correlation_ = 0.0;
    int lag_samples_ = 0;
    double lag_ms_ = 0.0;
    bool cache_dirty_ = true;
    bool has_hover_ = false;
    double hover_y_ = 0.0;
};

}  // namespace pwb::viz::well_tie::qt
