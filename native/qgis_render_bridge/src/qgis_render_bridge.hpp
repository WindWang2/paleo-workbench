#pragma once

// NOTE: this header must stay Qt-free. It is included by bindings.cpp before
// pybind11, and Qt's `slots` macro corrupts Python.h (PyType_Spec).

#include <array>
#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <utility>
#include <vector>

namespace pwb::qgis_render {

struct FeatureSpec {
    std::string id;
    std::string wkt;
    std::vector<std::pair<std::string, std::string>> attributes;
};

struct CategorySpec {
    std::string value;
    std::string color;
    std::string label;
};

struct RangeSpec {
    double lower = 0.0;
    double upper = 0.0;
    std::string color;
    std::string label;
};

/// One attribute-driven rule for a QgsRuleBasedRenderer (legacy path).
struct RuleSpec {
    std::string name;
    std::string expression;
    std::string label;
    std::string fill;
    std::string stroke;
    double stroke_width = 1.0;
    double marker_size = 6.0;
};

struct VectorLayerSpec {
    enum class Kind : std::uint8_t { Vector, Raster };

    std::string id;
    std::string name;
    std::string crs;
    Kind kind = Kind::Vector;
    std::string source_path;
    std::string fill = "#6c8ebf";
    std::string stroke = "#26364d";
    double stroke_width = 1.0;
    double marker_size = 6.0;
    std::string renderer_kind = "single";
    /// Authoritative QGIS symbology payload. When non-empty it replaces every
    /// legacy style field below after parsing; parse failure fails the
    /// snapshot (previous mirrors stay live).
    std::string renderer_xml;
    /// Attribute-driven rules for the rule-based renderer legacy path.
    std::vector<RuleSpec> rules;    std::string classification_field;
    std::vector<CategorySpec> categories;
    std::vector<RangeSpec> ranges;
    bool labels_enabled = false;
    std::string label_field;
    std::string label_font_family;
    double label_size = 10.0;
    std::string label_color = "#ffffff";
    double label_buffer_size = 0.0;
    /// Authoritative QGIS labeling payload (PAL configuration). Empty keeps
    /// the simple field-based labeling above.
    std::string labeling_xml;
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

    /// An empty prefix selects the owned runtime; any other prefix is rejected.
    void initialize(const std::string& requested_prefix = {});
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

    struct Diagnostics {
        std::uint64_t mirror_builds = 0;
        std::uint64_t mirror_reuses = 0;
        std::uint64_t style_reapplies = 0;
    };
    [[nodiscard]] Diagnostics diagnostics() const;

    /// Export the current snapshot through the same QGIS renderer configuration
    /// into a vector file ("svg" or "pdf").  Runs synchronously; returns the
    /// bytes written (0 on failure).  Screen and export share one style path.
    std::size_t export_vector(const std::string& path, const std::string& format,
                              const std::array<double, 4>& extent, int width,
                              int height, double dpi) const;

  private:
    class Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace pwb::qgis_render
