#pragma once

#include <functional>
#include <memory>
#include <string>
#include <thread>
#include <utility>
#include <vector>
#include <QImage>
#include <QWidget>
#include <pwb/viz/seismic_volume.hpp>

namespace pwb::seismic_viewer {

// Amplitudes are trace-major, with exact physical coordinates for every
// trace/sample (unequal polyline segments and nonuniform depth are supported).
struct SectionProfileData {
    std::vector<float> amplitude;
    std::vector<double> distance;
    std::vector<double> samples;
    std::string distance_unit = "m";
    std::string sample_unit = "ms";
};
struct SectionProfileWell {
    std::string name;
    double distance = 0;
    std::vector<std::pair<std::string, double>> tops;
    std::vector<double> curve_z;
    std::vector<double> curve_values;
};

// Raster-only shared arbitrary-line and fence VD view. No GL context required.
class SectionProfileWidget final : public QWidget {
public:
    explicit SectionProfileWidget(QWidget* parent = nullptr);
    ~SectionProfileWidget() override;
    bool set_data(SectionProfileData data);
    void clear(const QString& message = {});
    void set_wells(std::vector<SectionProfileWell> wells);
    void set_probe(double distance, double sample);
    void set_probe_callback(std::function<void(double, double)> callback);
    void set_color_map(const std::string& name);
    [[nodiscard]] const SectionProfileData& data() const;
    [[nodiscard]] const QImage& image() const;
    [[nodiscard]] QString diagnostic() const;
    [[nodiscard]] bool loading() const;
    [[nodiscard]] bool export_csv(const QString& path) const;
    [[nodiscard]] bool export_png(const QString& path);
    // The source must serialize reads shared with other consumers. The worker
    // owns it until cancellation/close and never accesses GUI objects directly.
    void load_polyline(std::shared_ptr<pwb::viz::ISeismicVolume> source,
                       std::vector<std::pair<double, double>> index_vertices);
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
    std::jthread worker_;
};

// Wrap a source once, before sharing it with slice/polyline workers. Geometry
// and lifetime are captured while idle; all subsequent read calls serialize.
std::shared_ptr<pwb::viz::ISeismicVolume> serialized_volume(
    std::shared_ptr<pwb::viz::ISeismicVolume> source);

} // namespace pwb::seismic_viewer
