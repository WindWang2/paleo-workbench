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
    /// Host MarkerSymbol enum value ("circle" | "well" | ...). Only "well"
    /// is special-cased today (filled ring + dark centre dot, matching the
    /// fallback renderer); every other value keeps the plain circle.
    std::string marker = "circle";
    /// Host LinePattern enum value ("solid" | "dash" | "dot" | "dash_dot").
    /// Legacy path only (#922): mapped onto the simple-line ``line_style``
    /// property so dashed fault lines stay dashed on the QGIS path.
    std::string line_pattern = "solid";
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
    /// Bold label font (host TextStyle.bold).
    bool label_bold = false;
    /// #1102: label buffer (halo) colour, same wire format as label_color
    /// ("#rrggbb" or a named colour). Empty keeps the white default.
    std::string label_buffer_color;
    /// #1052: per-feature data-defined label properties (attribute field
    /// names; empty disables the override). Rotation is degrees clockwise,
    /// size is points, colour is any QColor-parseable string — QGIS PAL
    /// evaluates them per feature and they override the fixed format.
    std::string label_rotation_field;
    std::string label_size_field;
    std::string label_color_field;
    /// Authoritative QGIS labeling payload (PAL configuration). Empty keeps
    /// the simple field-based labeling above.
    std::string labeling_xml;
    std::uint64_t data_revision = 0;
    std::uint64_t style_revision = 0;
    bool visible = true;
    double opacity = 1.0;
    /// Scale visibility (1:denominator range) — audit #929: the fallback
    /// renderer honours VectorStyle.scale_range while the QGIS wire dropped
    /// it, so scale-dependent layers were always visible. 0 disables a bound.
    bool has_scale_range = false;
    double scale_range_min_denom = 0.0;
    double scale_range_max_denom = 0.0;
    std::vector<FeatureSpec> features;
    /// #932: incremental payload. When present the host omitted ``features``
    /// and expects the existing mirror at ``base_revision`` to be updated in
    /// place (changed = added-or-modified full specs; removed = host ids).
    /// The bridge validates the base revision before mutating any mirror.
    struct FeatureDelta {
        std::uint64_t base_revision = 0;
        std::vector<FeatureSpec> changed;
        std::vector<std::string> removed_ids;
    };
    std::optional<FeatureDelta> delta;
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
    ///
    /// Threading contract (#938-5): the underlying QGIS parallel job reports
    /// completion via queued signals on the thread that created the bridge
    /// (the GUI thread).  Callers must pump that thread's event loop (e.g.
    /// via the host's frame poll timer) or use :meth:`render_sync` for
    /// synchronous rendering.  Without an event loop ``render_active()`` stays
    /// true indefinitely and ``take_completed_frame()`` never delivers.
    void request_render(const std::array<double, 4>& extent, int width, int height,
                        double dpi, std::uint64_t generation);
    /// Polls for the newest completed frame. Superseded generations are discarded.
    [[nodiscard]] std::optional<RenderResult> take_completed_frame();
    /// Cancels in-flight work without tearing down the process-global QGIS runtime.
    void cancel_render();
    /// Whether a render job is currently active.  Guard: when no QGIS event
    /// loop is running, this remains true until :meth:`cancel_render` or
    /// :meth:`shutdown` is called (#938-5).
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
        /// #932: incremental feature-delta applications on live mirrors.
        std::uint64_t feature_deltas = 0;
        std::uint64_t delta_changed_features = 0;
        std::uint64_t delta_removed_features = 0;
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
