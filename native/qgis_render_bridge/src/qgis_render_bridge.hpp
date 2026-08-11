#pragma once

#include <array>
#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <vector>

namespace pwb::qgis_render {

struct FeatureSpec {
    std::string id;
    std::string wkt;
};

struct VectorLayerSpec {
    std::string id;
    std::string name;
    std::string crs;
    std::uint64_t data_revision = 0;
    std::uint64_t style_revision = 0;
    bool visible = true;
    double opacity = 1.0;
    std::vector<FeatureSpec> features;
};

struct RenderResult {
    std::uint64_t generation = 0;
    int width = 0;
    int height = 0;
    int stride = 0;
    double render_ms = 0.0;
    std::vector<std::uint8_t> rgba;
};

class QgisRenderBridge {
  public:
    QgisRenderBridge();
    ~QgisRenderBridge();

    QgisRenderBridge(const QgisRenderBridge&) = delete;
    QgisRenderBridge& operator=(const QgisRenderBridge&) = delete;

    void initialize(const std::string& prefix_path = {});
    void set_layer_snapshot(std::vector<VectorLayerSpec> layers, std::string project_crs);
    /// Starts or coalesces a non-blocking QGIS render for the newest generation.
    void request_render(const std::array<double, 4>& extent, int width, int height,
                        double dpi, std::uint64_t generation);
    /// Polls for the newest completed frame. Superseded generations are discarded.
    [[nodiscard]] std::optional<RenderResult> take_completed_frame();
    /// Cancels in-flight work without tearing down the process-global QGIS runtime.
    void cancel_render();
    [[nodiscard]] bool render_active() const noexcept;
    [[nodiscard]] RenderResult render_sync(const std::array<double, 4>& extent,
                                           int width, int height, double dpi) const;
    /// Releases bridge-owned QGIS layers. The QGIS runtime remains process-scoped.
    void shutdown();

    [[nodiscard]] bool initialized() const noexcept;
    [[nodiscard]] std::string version() const;

  private:
    class Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace pwb::qgis_render
