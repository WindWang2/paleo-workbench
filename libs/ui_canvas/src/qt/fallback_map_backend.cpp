// FallbackMapRenderBackend — mapping/map_render_backend.py lines 678-1953
// parity. Every behaviour note below cites the Python anchor it mirrors.
//
// C++ contract deltas vs Python (frozen in map_render_backend.hpp):
//   * renderer_payload is shared_ptr<void> — the scalar_grid layer carries
//     the resolved mirror file in `source_path` instead of a rasterize()
//     object; the fallback paints it like a raster_source image.
//   * the pyproj transformer is an injected seam (no GeoPandas/pyproj on
//     the native side) — absent → the Python "pyproj 不可用" degradation.
#include <pwb/ui_canvas/qt/fallback_map_backend.hpp>

#include <pwb/ui_canvas/vector_lod.hpp>

#include <QDir>
#include <QFileInfo>
#include <QMutexLocker>
#include <QPainterPath>
#include <QPen>
#include <QPolygonF>
#include <QSvgRenderer>
#include <QVector>
#include <QtMath>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cctype>
#include <cstdlib>
#include <functional>
#include <map>
#include <set>

namespace pwb::ui_canvas::qt {

namespace carto = pwb::cartography;

namespace {

const QColor kBackground("#ffffff");  // _BACKGROUND
constexpr int kCategoryPointCap = 50000;  // _CATEGORY_POINT_CAP
constexpr int kLabelPointCap = 1500;
constexpr int kSymbolLoopCap = 5000;

// ---------------------------------------------------------------------------
// _LIVE_FALLBACKS weakref.WeakSet parity — raw pointers + dtor removal gives
// the same observable semantics (dead backends never receive shutdown).
std::vector<FallbackMapRenderBackend*>& live_fallbacks() {
    static auto* list = new std::vector<FallbackMapRenderBackend*>();
    return *list;
}
std::mutex& live_fallbacks_mutex() {
    static auto* m = new std::mutex();
    return *m;
}

// make_crs_transformer seam (installed by the host; absent → the
// pyproj-missing ValueError degradation).
CrsTransformerFactory& crs_factory() {
    static auto* f = new CrsTransformerFactory();
    return *f;
}

QString& default_pattern_dir() {
    static auto* dir = new QString();
    return *dir;
}

// _normalize_crs_name — "EPSG:4326 / WGS84" → "EPSG:4326".
std::string normalize_crs_name(const std::string& value) {
    const auto first = value.find_first_not_of(" \t\n\r");
    const auto last = value.find_last_not_of(" \t\n\r");
    const std::string text =
        first == std::string::npos ? "" : value.substr(first, last - first + 1);
    if (text.size() >= 5 &&
        (text.substr(0, 5) == "EPSG:" || text.substr(0, 5) == "epsg:")) {
        std::size_t digits = 5;
        while (digits < text.size() &&
               std::isdigit(static_cast<unsigned char>(text[digits]))) {
            ++digits;
        }
        if (digits > 5 &&
            (digits == text.size() ||
             !std::isalnum(static_cast<unsigned char>(text[digits])))) {
            std::string code = text.substr(0, digits);
            for (auto& c : code) c = static_cast<char>(std::toupper(c));
            return code;
        }
    }
    return text;
}

CrsTransformer make_crs_transformer(const std::string& layer_crs,
                                    const std::string& project_crs) {
    auto& factory = crs_factory();
    if (!factory) {
        throw std::invalid_argument(
            "pyproj 不可用,无法进行 CRS 重投影");
    }
    return factory(layer_crs, project_crs);
}

// _as_points — np.asarray(value, float64).reshape(-1, 2): every numeric leaf
// flattens into the vertex stream; the flat count must be even. Empty /
// non-numeric / odd inputs fail (the Python ValueError → None path).
bool flatten_points(const Json& value, std::vector<double>& out) {
    if (value.is_number()) {
        out.push_back(value.get<double>());
        return true;
    }
    if (!value.is_array()) return false;
    for (const Json& v : value) {
        if (!flatten_points(v, out)) return false;
    }
    return true;
}

bool as_points(const Json& value, std::vector<double>& out) {
    if (!value.is_array() || value.size() < 2) return false;
    out.clear();
    if (!flatten_points(value, out)) return false;
    if (out.empty() || out.size() % 2 != 0) return false;
    return true;
}

// _prepare_geometry — GeoJSON dict → (kind, flat parts).
std::optional<std::pair<std::string,
                        std::vector<std::vector<double>>>>
prepare_geometry(const Json& geometry) {
    if (!geometry.is_object()) return std::nullopt;
    const auto type_it = geometry.find("type");
    const std::string type =
        type_it != geometry.end() && type_it->is_string()
            ? type_it->get<std::string>()
            : "";
    const auto coord_it = geometry.find("coordinates");
    const Json& coords =
        coord_it != geometry.end() ? *coord_it : Json();
    std::vector<double> part;
    std::vector<std::vector<double>> parts;
    auto push_if = [&](std::vector<double>&& p, std::size_t min_len) {
        if (p.size() / 2 >= min_len) parts.push_back(std::move(p));
    };
    if (type == "Point") {
        if (as_points(coords, part)) parts.push_back(std::move(part));
        if (parts.empty()) return std::nullopt;
        return std::make_pair("point", std::move(parts));
    }
    if (type == "MultiPoint") {
        if (coords.is_array()) {
            for (const Json& v : coords) {
                if (as_points(v, part)) parts.push_back(std::move(part));
            }
        }
        if (parts.empty()) return std::nullopt;
        return std::make_pair("point", std::move(parts));
    }
    if (type == "LineString") {
        if (as_points(coords, part)) push_if(std::move(part), 2);
        if (parts.empty()) return std::nullopt;
        return std::make_pair("line", std::move(parts));
    }
    if (type == "MultiLineString") {
        if (coords.is_array()) {
            for (const Json& line : coords) {
                if (as_points(line, part)) push_if(std::move(part), 2);
            }
        }
        if (parts.empty()) return std::nullopt;
        return std::make_pair("line", std::move(parts));
    }
    if (type == "Polygon") {
        if (coords.is_array()) {
            for (const Json& ring : coords) {
                if (as_points(ring, part)) push_if(std::move(part), 3);
            }
        }
        if (parts.empty()) return std::nullopt;
        return std::make_pair("polygon", std::move(parts));
    }
    if (type == "MultiPolygon") {
        if (coords.is_array()) {
            for (const Json& polygon : coords) {
                if (!polygon.is_array()) continue;
                for (const Json& ring : polygon) {
                    if (as_points(ring, part)) push_if(std::move(part), 3);
                }
            }
        }
        if (parts.empty()) return std::nullopt;
        return std::make_pair("polygon", std::move(parts));
    }
    if (type == "GeometryCollection") {
        const auto geom_it = geometry.find("geometries");
        std::vector<std::vector<double>> poly, lines, points;
        if (geom_it != geometry.end() && geom_it->is_array()) {
            for (const Json& sub : *geom_it) {
                auto prep = prepare_geometry(sub);
                if (!prep.has_value()) continue;
                auto& target = prep->first == "polygon"
                                   ? poly
                                   : prep->first == "line" ? lines : points;
                for (auto& p : prep->second) {
                    target.push_back(std::move(p));
                }
            }
        }
        if (!poly.empty()) return std::make_pair("polygon", std::move(poly));
        if (!lines.empty()) return std::make_pair("line", std::move(lines));
        if (!points.empty()) {
            return std::make_pair("point", std::move(parts));
        }
        return std::nullopt;
    }
    return std::nullopt;
}

// Python `or ""` truthiness for Json scalars/containers.
bool json_falsy(const Json* v) {
    return v == nullptr || v->is_null() ||
           (v->is_boolean() && !v->get<bool>()) ||
           (v->is_number() && v->get<double>() == 0.0) ||
           (v->is_string() && v->get<std::string>().empty()) ||
           (v->is_array() && v->empty()) ||
           (v->is_object() && v->empty());
}

// str(value) for feature ids / property scalars (numbers keep shortest
// repr; True/False → "True"/"False").
std::string property_str(const Json& value) {
    if (value.is_string()) return value.get<std::string>();
    if (value.is_null()) return "";
    if (value.is_boolean()) return value.get<bool>() ? "True" : "False";
    return value.dump();
}

const Json* property_of(const PreparedFeature& feature,
                        const std::string& field) {
    const auto it = feature.properties.find(field);
    return it != feature.properties.end() ? &*it : nullptr;
}

std::shared_ptr<PreparedLayer> build_prepared(
    const MapLayerSnapshot& layer) {
    auto prepared = std::make_shared<PreparedLayer>();
    prepared->revision = static_cast<std::int64_t>(layer.data_revision);
    prepared->layer_type = layer.layer_type;
    for (const Json& feature : layer.features) {
        const auto geom_it = feature.find("geometry");
        const Json geom =
            geom_it != feature.end() ? *geom_it : Json();
        auto prep = prepare_geometry(geom);
        if (!prep.has_value()) continue;
        PreparedFeature pf;
        const auto id_it = feature.find("id");
        pf.feature_id =
            id_it != feature.end() && !id_it->is_null()
                ? (id_it->is_string() ? id_it->get<std::string>()
                                      : property_str(*id_it))
                : "";
        pf.kind = prep->first;
        for (auto& flat : prep->second) {
            std::vector<std::pair<double, double>> part;
            part.reserve(flat.size() / 2);
            for (std::size_t i = 0; i + 1 < flat.size(); i += 2) {
                part.emplace_back(flat[i], flat[i + 1]);
            }
            pf.parts.push_back(std::move(part));
        }
        Extent box{std::numeric_limits<double>::max(),
                   std::numeric_limits<double>::max(),
                   std::numeric_limits<double>::lowest(),
                   std::numeric_limits<double>::lowest()};
        for (const auto& flat : prep->second) {
            for (std::size_t i = 0; i + 1 < flat.size(); i += 2) {
                box[0] = std::min(box[0], flat[i]);
                box[1] = std::min(box[1], flat[i + 1]);
                box[2] = std::max(box[2], flat[i]);
                box[3] = std::max(box[3], flat[i + 1]);
            }
        }
        pf.bbox = box;
        const auto props_it = feature.find("properties");
        pf.properties = props_it != feature.end() && props_it->is_object()
                            ? *props_it
                            : Json::object();
        prepared->features.push_back(std::move(pf));
    }
    for (std::size_t index = 0; index < prepared->features.size();
         ++index) {
        const PreparedFeature& feature = prepared->features[index];
        if (feature.kind == "point") {
            for (const auto& part : feature.parts) {
                for (const auto& [x, y] : part) {
                    prepared->point_xy.push_back(x);
                    prepared->point_xy.push_back(y);
                }
                prepared->point_feature.push_back(
                    static_cast<int>(index));
            }
            continue;
        }
        for (const auto& part : feature.parts) {
            prepared->path_offsets.push_back(prepared->path_xy.size() / 2);
            for (const auto& [x, y] : part) {
                prepared->path_xy.push_back(x);
                prepared->path_xy.push_back(y);
            }
            prepared->path_feature.push_back(static_cast<int>(index));
            prepared->path_is_ring.push_back(feature.kind == "polygon");
        }
    }
    prepared->path_offsets.push_back(prepared->path_xy.size() / 2);
    prepared->has_points = !prepared->point_xy.empty();
    prepared->has_paths = !prepared->path_xy.empty();
    return prepared;
}

// _category_colors — value→fill for categorized renderers.
std::optional<std::map<std::string, std::string>>
category_colors(const carto::VectorStyle& style) {
    if (style.renderer != "categorized" || style.categories.empty()) {
        return std::nullopt;
    }
    std::map<std::string, std::string> out;
    for (const auto& cat : style.categories) out[cat.value] = cat.fill;
    return out;
}

// _category_patterns — value→pattern-id lookup.
std::optional<std::map<std::string, std::string>>
category_patterns(const carto::VectorStyle& style) {
    if (style.renderer != "categorized" || style.fill_patterns.empty()) {
        return std::nullopt;
    }
    std::map<std::string, std::string> out;
    for (const auto& fp : style.fill_patterns) {
        out[fp.value] = fp.pattern_id;
    }
    return out;
}

// _range_color — first matching (lo <= val <= hi) graduated range fill.
std::optional<std::string> range_color(const Json& value,
                                       const carto::VectorStyle& style) {
    if (style.ranges.empty() || value.is_null()) return std::nullopt;
    double val;
    try {
        if (value.is_string()) {
            val = std::stod(value.get<std::string>());
        } else if (value.is_boolean()) {
            val = value.get<bool>() ? 1.0 : 0.0;
        } else {
            val = value.get<double>();
        }
    } catch (...) {
        return std::nullopt;
    }
    for (const auto& entry : style.ranges) {
        if (entry.lo <= val && val <= entry.hi) return entry.fill;
    }
    return std::nullopt;
}

// _lod_subset_prepared — keep-mask subsetting; part counts recomputed,
// feature-level arrays shared.
std::shared_ptr<PreparedLayer> lod_subset_prepared(
    const std::shared_ptr<const PreparedLayer>& prepared,
    const std::vector<bool>& keep) {
    std::size_t kept_total = 0;
    for (bool k : keep) kept_total += k ? 1 : 0;
    if (kept_total == keep.size()) {
        return std::const_pointer_cast<PreparedLayer>(prepared);
    }
    auto reduced = std::make_shared<PreparedLayer>(*prepared);
    reduced->path_xy.clear();
    reduced->path_offsets.assign(1, 0);
    const std::size_t parts = prepared->path_offsets.size() - 1;
    for (std::size_t p = 0; p < parts; ++p) {
        const std::size_t s = prepared->path_offsets[p];
        const std::size_t e = prepared->path_offsets[p + 1];
        for (std::size_t i = s; i < e; ++i) {
            if (keep[i]) {
                reduced->path_xy.push_back(prepared->path_xy[i * 2]);
                reduced->path_xy.push_back(prepared->path_xy[i * 2 + 1]);
            }
        }
        reduced->path_offsets.push_back(reduced->path_xy.size() / 2);
    }
    return reduced;
}

// _reprojected_prepared_layer — every vertex through the transformer;
// feature bboxes rebuilt from transformed vertices.
std::shared_ptr<PreparedLayer> reprojected_prepared_layer(
    const std::shared_ptr<const PreparedLayer>& prepared,
    const CrsTransformer& transformer) {
    auto out = std::make_shared<PreparedLayer>();
    out->revision = prepared->revision;
    out->layer_type = prepared->layer_type;
    out->point_xy.resize(prepared->point_xy.size());
    for (std::size_t i = 0; i + 1 < prepared->point_xy.size(); i += 2) {
        double x = prepared->point_xy[i], y = prepared->point_xy[i + 1];
        transformer(x, y);
        out->point_xy[i] = x;
        out->point_xy[i + 1] = y;
    }
    out->point_feature = prepared->point_feature;
    out->has_points = prepared->has_points;
    out->path_xy.resize(prepared->path_xy.size());
    for (std::size_t i = 0; i + 1 < prepared->path_xy.size(); i += 2) {
        double x = prepared->path_xy[i], y = prepared->path_xy[i + 1];
        transformer(x, y);
        out->path_xy[i] = x;
        out->path_xy[i + 1] = y;
    }
    out->path_offsets = prepared->path_offsets;
    out->path_feature = prepared->path_feature;
    out->path_is_ring = prepared->path_is_ring;
    out->has_paths = prepared->has_paths;
    std::size_t point_cursor = 0, path_cursor = 0;
    for (const PreparedFeature& feature : prepared->features) {
        PreparedFeature nf;
        nf.feature_id = feature.feature_id;
        nf.kind = feature.kind;
        nf.properties = feature.properties;
        const bool is_point = feature.kind == "point";
        const std::vector<double>& src =
            is_point ? out->point_xy : out->path_xy;
        std::size_t& cursor = is_point ? point_cursor : path_cursor;
        for (const auto& part : feature.parts) {
            std::vector<std::pair<double, double>> np2;
            np2.reserve(part.size());
            for (std::size_t k = 0; k < part.size(); ++k) {
                np2.emplace_back(src[cursor * 2], src[cursor * 2 + 1]);
                ++cursor;
            }
            nf.parts.push_back(std::move(np2));
        }
        if (!nf.parts.empty()) {
            Extent box{std::numeric_limits<double>::max(),
                       std::numeric_limits<double>::max(),
                       std::numeric_limits<double>::lowest(),
                       std::numeric_limits<double>::lowest()};
            for (const auto& part : nf.parts) {
                for (const auto& [x, y] : part) {
                    box[0] = std::min(box[0], x);
                    box[1] = std::min(box[1], y);
                    box[2] = std::max(box[2], x);
                    box[3] = std::max(box[3], y);
                }
            }
            nf.bbox = box;
        } else {
            nf.bbox = feature.bbox;
        }
        out->features.push_back(std::move(nf));
    }
    return out;
}

// _draw_halo_text — stroked-outline halo via QPainterPath::addText.
void draw_halo_text(QPainter& painter, const QPointF& position,
                    const QFont& font, const QString& text,
                    const QColor& halo_color, double halo_pen_width,
                    const QColor& fill_color) {
    QPainterPath path;
    path.addText(position, font, text);
    if (halo_pen_width > 0.0 && halo_color.alpha() > 0) {
        painter.setPen(QPen(halo_color, halo_pen_width, Qt::SolidLine,
                            Qt::RoundCap, Qt::RoundJoin));
        painter.setBrush(Qt::NoBrush);
        painter.drawPath(path);
    }
    painter.fillPath(path, fill_color);
}

int env_budget() {
    // int(os.environ.get(...)) — an invalid value raises like Python.
    const char* raw = std::getenv("PALEO_RENDER_VERTEX_BUDGET");
    if (raw == nullptr) return 150000;
    return std::max(1000, std::stoi(raw));
}

bool env_disabled(const char* name) {
    // str(os.environ.get(name) or "").strip() not in ("", "0")
    const char* raw = std::getenv(name);
    if (raw == nullptr) return false;
    std::string v(raw);
    const auto f = v.find_first_not_of(" \t");
    const auto l = v.find_last_not_of(" \t");
    v = f == std::string::npos ? "" : v.substr(f, l - f + 1);
    return !v.empty() && v != "0";
}

}  // namespace

// ---------------------------------------------------------------------------
// FaciesPatternBrushCache (facies_brush_cache.py) — SVG tiles → texture
// brushes; atlas prebake per scale level, lazy single-tile fallback.
// ---------------------------------------------------------------------------

class FallbackMapRenderBackend::Impl {
public:
    QString pattern_dir;
    int tile_px = 32;
    std::map<std::pair<std::string, int>, QBrush> brushes;
    // tile size → (atlas image, pattern_id → cell rect)
    std::map<int, std::pair<QImage, std::map<std::string, QRectF>>> atlases;

    QString path_for(const std::string& pattern_id) const {
        if (pattern_id.empty() || pattern_dir.isEmpty()) return {};
        const QString p = pattern_dir + "/" +
                          QString::fromStdString(pattern_id) + ".svg";
        return QFileInfo::exists(p) ? p : QString();
    }

    std::vector<std::string> pattern_ids() const {
        std::vector<std::string> ids;
        const QDir dir(pattern_dir);
        for (const auto& e :
             dir.entryList({"*.svg"}, QDir::Files, QDir::Name)) {
            ids.push_back(e.left(e.size() - 4).toStdString());
        }
        return ids;
    }

    int prebake() {
        const auto ids = pattern_ids();
        if (ids.empty()) return 0;
        int levels = 0;
        for (const double scale : {1.0, 2.0, 3.0}) {
            const int size =
                std::max(1, static_cast<int>(std::lround(tile_px * scale)));
            std::map<std::string, QRectF> cells;
            const int cols = std::max(
                1, static_cast<int>(std::ceil(std::sqrt(ids.size()))));
            const int rows = static_cast<int>(
                std::ceil(static_cast<double>(ids.size()) / cols));
            QImage atlas(cols * size, rows * size,
                         QImage::Format_ARGB32_Premultiplied);
            atlas.fill(Qt::transparent);
            QPainter painter(&atlas);
            for (std::size_t index = 0; index < ids.size(); ++index) {
                const QString path = path_for(ids[index]);
                if (path.isEmpty()) continue;
                QSvgRenderer renderer(path);
                if (!renderer.isValid()) continue;
                const auto cx = static_cast<qreal>(index % cols) * size;
                const auto cy = static_cast<qreal>(index / cols) * size;
                const QRectF target(cx, cy, size, size);
                painter.save();
                painter.setClipRect(target.toRect());
                renderer.render(&painter, target);
                painter.restore();
                cells[ids[index]] = target;
            }
            painter.end();
            if (!cells.empty()) {
                atlases[size] = {atlas, cells};
                ++levels;
            }
        }
        return levels;
    }

    std::optional<QBrush> brush_for(const std::string& pattern_id,
                                    double scale) {
        if (pattern_id.empty()) return std::nullopt;
        const int size = std::max(
            1, static_cast<int>(
                   std::lround(tile_px * std::max(0.05, scale))));
        const auto key = std::make_pair(pattern_id, size);
        const auto it = brushes.find(key);
        if (it != brushes.end()) return it->second;
        auto brush = atlas_brush(pattern_id, size);
        if (!brush.has_value()) brush = render_brush(pattern_id, size);
        if (brush.has_value()) brushes[key] = *brush;
        return brush;
    }

    std::optional<QBrush> atlas_brush(const std::string& pattern_id,
                                      int size) {
        const auto it = atlases.find(size);
        if (it == atlases.end()) return std::nullopt;
        const auto cell = it->second.second.find(pattern_id);
        if (cell == it->second.second.end()) return std::nullopt;
        const QImage tile = it->second.first.copy(cell->second.toRect());
        if (tile.isNull()) return std::nullopt;
        QBrush brush;
        brush.setTextureImage(tile);
        return brush;
    }

    std::optional<QBrush> render_brush(const std::string& pattern_id,
                                       int size) {
        const QString path = path_for(pattern_id);
        if (path.isEmpty()) return std::nullopt;
        QSvgRenderer renderer(path);
        if (!renderer.isValid()) return std::nullopt;
        QImage tile(size, size, QImage::Format_ARGB32_Premultiplied);
        tile.fill(Qt::transparent);
        {
            QPainter painter(&tile);
            renderer.render(&painter, QRectF(0.0, 0.0, size, size));
        }
        if (tile.isNull()) return std::nullopt;
        QBrush brush;
        brush.setTextureImage(tile);
        return brush;
    }
};

// ---------------------------------------------------------------------------
// Backend
// ---------------------------------------------------------------------------

FallbackMapRenderBackend::FallbackMapRenderBackend(bool threaded)
    : threaded_(threaded),
      vertex_budget_(env_budget()),
      vector_lod_disabled_(env_disabled("PWB_DISABLE_VECTOR_LOD")),
      facies_batch_disabled_(env_disabled("PWB_DISABLE_FACIES_BATCH")),
      facies_patterns_(std::make_unique<Impl>()) {
    facies_patterns_->pattern_dir = default_pattern_dir();
    facies_patterns_->prebake();
    std::lock_guard<std::mutex> lock(live_fallbacks_mutex());
    live_fallbacks().push_back(this);
}

FallbackMapRenderBackend::~FallbackMapRenderBackend() {
    shutdown();
    std::lock_guard<std::mutex> lock(live_fallbacks_mutex());
    auto& list = live_fallbacks();
    list.erase(std::remove(list.begin(), list.end(), this), list.end());
}

void FallbackMapRenderBackend::set_crs_transformer_factory(
    CrsTransformerFactory factory) {
    crs_factory() = std::move(factory);
}

void FallbackMapRenderBackend::set_facies_pattern_dir(const QString& dir) {
    default_pattern_dir() = dir;
}

// -- diagnostics helper -------------------------------------------------------

void FallbackMapRenderBackend::diag_add(const char* key, double delta) {
    std::lock_guard<std::mutex> lock(diag_mutex_);
    diagnostics_[key] += delta;
}

void FallbackMapRenderBackend::diag_set(const char* key, double value) {
    std::lock_guard<std::mutex> lock(diag_mutex_);
    diagnostics_[key] = value;
}

// -- frame key / cache ------------------------------------------------------

FallbackMapRenderBackend::FrameKey
FallbackMapRenderBackend::frame_key() const {
    FrameKey key;
    key.extent = extent();
    const auto size = output_size();
    key.width = size.first;
    key.height = size.second;
    key.dpi = dpi();
    key.project_crs = snapshot().project_crs;
    for (const MapLayerSnapshot& layer : snapshot().layers) {
        LayerKey lk;
        lk.id = layer.id;
        lk.layer_type = layer.layer_type;
        lk.data_revision = static_cast<std::int64_t>(layer.data_revision);
        lk.style_revision = static_cast<std::int64_t>(layer.style_revision);
        lk.visible = layer.visible;
        // round(float, 6) — banker's via nearbyint on the scaled value.
        lk.opacity = std::nearbyint(layer.opacity * 1e6) / 1e6;
        lk.scale_range = layer.scale_range;
        lk.crs = layer.crs;
        key.layers.push_back(std::move(lk));
    }
    return key;
}

const RenderFrame* FallbackMapRenderBackend::cached_frame() const {
    if (frame_cache_.has_value() && frame_cache_->first == frame_key()) {
        return &frame_cache_->second;
    }
    return nullptr;
}

// -- render entry points ----------------------------------------------------

RenderFrame FallbackMapRenderBackend::render_sync() {
    if (!initialized()) initialize();
    if (const RenderFrame* cached = cached_frame()) {
        diag_add("frames_from_cache", 1.0);
        RenderFrame frame = *cached;
        frame.generation = next_generation();
        return frame;
    }
    RasterizeResult result = rasterize_frame_offthread();
    const std::uint64_t gen = next_generation();
    FrameKey key = result.key;
    RenderFrame frame = finalize_frame(std::move(result), gen);
    frame_cache_ = std::make_pair(std::move(key), frame);
    return frame;
}

bool FallbackMapRenderBackend::render_to_painter(QPainter& painter,
                                                 int width, int height,
                                                 double dpi_value) {
    if (!initialized()) initialize();
    painter.fillRect(QRectF(0.0, 0.0, width, height), kBackground);
    paint_composition(painter, width, height,
                      dpi_value > 0.0 ? dpi_value : dpi(), nullptr);
    return true;
}

std::uint64_t FallbackMapRenderBackend::request_render() {
    if (!initialized()) initialize();
    const std::uint64_t generation = next_generation();
    if (const RenderFrame* cached = cached_frame()) {
        diag_add("frames_from_cache", 1.0);
        RenderFrame copy = *cached;
        copy.generation = generation;
        store_completed(std::move(copy));
        return generation;
    }
    cancel_completed();
    if (!threaded_) {
        RasterizeResult result = rasterize_frame_offthread();
        FrameKey key = result.key;
        RenderFrame frame = finalize_frame(std::move(result), generation);
        frame_cache_ = std::make_pair(std::move(key), frame);
        store_completed(std::move(frame));
        return generation;
    }
    if (render_future_.has_value() &&
        render_future_->wait_for(std::chrono::seconds(0)) !=
            std::future_status::ready) {
        // In-flight generation is stale — it is discarded on arrival and
        // the newest state renders as soon as the worker frees.
        render_pending_ = true;
        return next_generation();
    }
    ensure_worker();
    // Worker: the FULL frame rasterisation minus text (#822). QPainter on
    // a privately-owned QImage is thread-safe for geometry primitives;
    // label placements travel back as plain data and paint on the GUI
    // thread during finalisation.
    submit_render_job();
    render_generation_ = generation;
    return generation;
}

std::optional<RenderFrame>
FallbackMapRenderBackend::take_completed_frame() {
    if (auto frame = MapRenderBackend::take_completed_frame()) {
        return frame;
    }
    if (render_future_.has_value() &&
        render_future_->wait_for(std::chrono::seconds(0)) ==
            std::future_status::ready) {
        // Python clears the future + generation BEFORE reading result().
        auto future = std::move(*render_future_);
        render_future_.reset();
        const auto generation = render_generation_.value_or(0);
        render_generation_.reset();
        RasterizeResult result;
        try {
            result = future.get();
        } catch (...) {
            // A failed frame must never crash polling.
            diag_add("render_errors", 1.0);
            maybe_submit_pending();
            return std::nullopt;
        }
        if (generation != this->generation()) {
            maybe_submit_pending();
            return std::nullopt;
        }
        FrameKey key = result.key;
        RenderFrame frame;
        try {
            frame = finalize_frame(std::move(result), generation);
        } catch (...) {
            diag_add("render_errors", 1.0);
            maybe_submit_pending();
            return std::nullopt;
        }
        frame_cache_ = std::make_pair(std::move(key), frame);
        return frame;
    }
    return std::nullopt;
}

void FallbackMapRenderBackend::ensure_worker() {
    std::lock_guard<std::mutex> lock(worker_mutex_);
    if (worker_started_) return;
    worker_started_ = true;
    worker_stop_ = false;
    worker_ = std::thread([this] { worker_loop(); });
}

void FallbackMapRenderBackend::worker_loop() {
    for (;;) {
        std::packaged_task<RasterizeResult()> task;
        {
            std::unique_lock<std::mutex> lock(worker_mutex_);
            worker_cv_.wait(lock, [&] {
                return worker_stop_ || !worker_queue_.empty();
            });
            if (worker_stop_ || worker_queue_.empty()) return;
            task = std::move(worker_queue_.front());
            worker_queue_.pop_front();
        }
        task();
    }
}

void FallbackMapRenderBackend::submit_render_job() {
    std::packaged_task<RasterizeResult()> task(
        [this] { return rasterize_frame_offthread(); });
    render_future_ = task.get_future();
    {
        std::lock_guard<std::mutex> lock(worker_mutex_);
        worker_queue_.push_back(std::move(task));
    }
    worker_cv_.notify_one();
}

void FallbackMapRenderBackend::maybe_submit_pending() {
    if (!render_pending_ || !worker_started_) return;
    if (render_future_.has_value() &&
        render_future_->wait_for(std::chrono::seconds(0)) !=
            std::future_status::ready) {
        return;
    }
    render_pending_ = false;
    render_generation_ = next_generation();
    submit_render_job();
}

bool FallbackMapRenderBackend::render_active() const {
    return render_future_.has_value() &&
           render_future_->wait_for(std::chrono::seconds(0)) !=
               std::future_status::ready;
}

void FallbackMapRenderBackend::cancel_render() {
    MapRenderBackend::cancel_render();
    next_generation();  // discard the still-running frame on arrival
    // Dropping the packaged_task future is non-blocking (Python parity:
    // the worker is cooperative and cannot be interrupted).
    render_future_.reset();
    render_pending_ = false;
}

void FallbackMapRenderBackend::shutdown() {
    render_future_.reset();
    render_pending_ = false;
    {
        std::lock_guard<std::mutex> lock(worker_mutex_);
        worker_queue_.clear();  // cancel_futures=True parity
        worker_stop_ = true;
    }
    worker_cv_.notify_all();
    if (worker_.joinable()) worker_.join();
    worker_started_ = false;
    {
        std::lock_guard<std::mutex> lock(prepared_mutex_);
        prepared_.clear();
        reprojected_.clear();
        scalar_images_.clear();
    }
    frame_cache_.reset();
    MapRenderBackend::shutdown();
}

std::map<std::string, double>
FallbackMapRenderBackend::render_diagnostics() const {
    std::lock_guard<std::mutex> lock(diag_mutex_);
    auto out = diagnostics_;
    // Python: result["threaded"] = self._executor is not None — the
    // worker is created lazily on the first threaded request.
    out["threaded"] = worker_started_ ? 1.0 : 0.0;
    out["render_active"] = render_active() ? 1.0 : 0.0;
    return out;
}

std::map<std::string, double>
FallbackMapRenderBackend::fallback_diagnostics() const {
    // Legacy counter surface (map-perf #461): rasterization_count /
    // frame_cache_hits / strip_reuse_count (always 0 in the v2 renderer) /
    // culled_feature_count.
    std::lock_guard<std::mutex> lock(diag_mutex_);
    return {
        {"rasterization_count", diagnostics_.at("frames_rendered")},
        {"frame_cache_hits", diagnostics_.at("frames_from_cache")},
        {"strip_reuse_count", 0.0},
        {"culled_feature_count",
         std::max(0.0, diagnostics_.at("features_total") -
                           diagnostics_.at("features_drawn"))},
    };
}

// -- frame pipeline ---------------------------------------------------------

void FallbackMapRenderBackend::prepare_layers() {
    for (const MapLayerSnapshot& layer : snapshot().layers) {
        if (!layer.visible || layer.opacity <= 0.0) continue;
        if (layer.layer_type != "scalar_grid" &&
            layer.layer_type != "grid" &&
            layer.layer_type != "raster_source" &&
            layer.features.is_array() && !layer.features.empty()) {
            prepared_layer(layer);
        }
    }
}

FallbackMapRenderBackend::RasterizeResult
FallbackMapRenderBackend::rasterize_frame_offthread() {
    RasterizeResult result;
    result.key = frame_key();
    prepare_layers();
    const auto size = output_size();
    QImage image(size.first, size.second, QImage::Format_RGBA8888);
    image.fill(kBackground);
    const auto started = std::chrono::steady_clock::now();
    {
        QPainter painter(&image);
        painter.setRenderHint(QPainter::Antialiasing, true);
        paint_composition(painter, size.first, size.second, dpi(),
                          &result.specs);
    }
    result.image = std::move(image);
    result.elapsed_ms = std::chrono::duration<double, std::milli>(
                            std::chrono::steady_clock::now() - started)
                            .count();
    diag_add("frames_rendered", 1.0);
    diag_set("last_render_ms", result.elapsed_ms);
    return result;
}

RenderFrame FallbackMapRenderBackend::finalize_frame(
    RasterizeResult&& result, std::uint64_t generation) {
    if (!result.specs.empty()) {
        QPainter painter(&result.image);
        paint_label_specs(painter, result.specs);
        painter.end();
    }
    RenderFrame frame;
    frame.generation = generation;
    frame.width = result.image.width();
    frame.height = result.image.height();
    frame.stride = result.image.bytesPerLine();
    frame.rgba.assign(
        result.image.constBits(),
        result.image.constBits() +
            static_cast<std::size_t>(frame.stride) * frame.height);
    frame.render_ms = result.elapsed_ms;
    return frame;
}

double FallbackMapRenderBackend::scale_denominator(int width) const {
    const auto size = output_size();
    const Extent fitted =
        fit_extent_to_aspect(extent(), width, size.second);
    const double units_per_pixel =
        (fitted[2] - fitted[0]) / std::max(1, width);
    return units_per_pixel / (0.0254 / dpi());
}

// -- composition ------------------------------------------------------------

void FallbackMapRenderBackend::paint_composition(
    QPainter& painter, int width, int height, double dpi_value,
    std::vector<LabelSpec>* label_specs) {
    // label_specs nullptr (export/render_to_painter): collect locally and
    // paint AFTER all geometry (V12 I-2 layering parity).
    std::vector<LabelSpec> own_specs;
    if (label_specs == nullptr) label_specs = &own_specs;
    const Extent fitted = fit_extent_to_aspect(extent(), width, height);
    const double xmin = fitted[0], ymin = fitted[1];
    const double span_x = fitted[2] - fitted[0];
    const double span_y = fitted[3] - fitted[1];
    if (span_x <= 0.0 || span_y <= 0.0) return;
    const double scale_denom = scale_denominator(width);
    // RenderContext.device_px_per_logical_px: dpi/96, floored at 0.05.
    const double dpi_scale = std::max(0.05, dpi_value / 96.0);
    diag_set("features_total", 0.0);
    diag_set("features_drawn", 0.0);
    diag_set("points_drawn", 0.0);
    diag_set("vertices_simplified", 0.0);
    const std::string project_crs = snapshot().project_crs;
    {
        std::lock_guard<std::mutex> lock(diag_mutex_);
        crs_warnings_.clear();
    }
    std::set<std::string> seen_layers;
    for (const MapLayerSnapshot& layer : snapshot().layers) {
        seen_layers.insert(layer.id);
        if (!layer.visible || layer.opacity <= 0.0) continue;
        if (layer.scale_range.has_value() &&
            !(layer.scale_range->first <= scale_denom &&
              scale_denom <= layer.scale_range->second)) {
            continue;
        }
        painter.save();
        painter.setOpacity(std::max(0.0, std::min(1.0, layer.opacity)));
        const bool has_features =
            layer.features.is_array() && !layer.features.empty();
        if (layer.layer_type == "scalar_grid" ||
            layer.layer_type == "raster_source") {
            warn_raster_unprojected(layer, project_crs);
            draw_image_layer(painter, layer);
        } else if (layer.layer_type != "grid" && has_features) {
            paint_vector_layer(painter, layer, xmin, ymin, span_x,
                               span_y, width, height, dpi_scale,
                               label_specs);
        }
        painter.restore();
    }
    {
        std::lock_guard<std::mutex> lock(prepared_mutex_);
        prepared_.prune(seen_layers);
        reprojected_.prune(seen_layers);
        lod_cache_.prune(seen_layers);
        scalar_images_.prune(seen_layers);
    }
    if (!own_specs.empty()) {
        paint_label_specs(painter, own_specs);
    }
}

void FallbackMapRenderBackend::warn_raster_unprojected(
    const MapLayerSnapshot& layer, const std::string& project_crs) {
    const std::string target = normalize_crs_name(project_crs);
    const std::string layer_crs = [&] {
        const std::string n = normalize_crs_name(layer.crs);
        return n.empty() ? target : n;
    }();
    if (target.empty() || layer_crs.empty() || layer_crs == target) {
        return;
    }
    const std::string name =
        !layer.name.empty() ? layer.name : layer.id;
    const char* kind =
        layer.layer_type == "scalar_grid" ? "标量格网图层" : "栅格图层";
    std::lock_guard<std::mutex> lock(diag_mutex_);
    crs_warnings_.push_back(
        std::string(kind) + "“" + name + "”的 CRS(" + layer_crs +
        ")与工程 CRS(" + target + ")不同且未重投影,输出可能存在坐标混绘");
}

// -- prepared-layer caches ----------------------------------------------------

std::shared_ptr<const PreparedLayer>
FallbackMapRenderBackend::prepared_layer(const MapLayerSnapshot& layer) {
    const auto revision = static_cast<std::int64_t>(layer.data_revision);
    {
        std::lock_guard<std::mutex> lock(prepared_mutex_);
        if (const auto* cached = prepared_.get(layer.id, revision)) {
            diag_add("prepared_cache_hits", 1.0);
            return *cached;
        }
    }
    auto built = build_prepared(layer);
    {
        std::lock_guard<std::mutex> lock(prepared_mutex_);
        if (const auto* existing = prepared_.get(layer.id, revision)) {
            diag_add("prepared_cache_hits", 1.0);
            return *existing;
        }
        prepared_.store(layer.id, revision, built);
    }
    diag_add("prepared_cache_misses", 1.0);
    std::size_t cached_layers;
    {
        std::lock_guard<std::mutex> lock(prepared_mutex_);
        cached_layers = prepared_.size();
    }
    diag_set("prepared_layers", static_cast<double>(cached_layers));
    return built;
}

std::shared_ptr<const PreparedLayer>
FallbackMapRenderBackend::reprojected_prepared(
    std::shared_ptr<const PreparedLayer> prepared,
    const MapLayerSnapshot& layer) {
    const std::string project_crs = snapshot().project_crs;
    std::string layer_crs = layer.crs;
    const auto f = layer_crs.find_first_not_of(" \t");
    const auto l = layer_crs.find_last_not_of(" \t");
    layer_crs =
        f == std::string::npos ? "" : layer_crs.substr(f, l - f + 1);
    if (layer_crs.empty()) layer_crs = project_crs;
    if (project_crs.empty() || layer_crs.empty()) return prepared;
    const std::string source_name = normalize_crs_name(layer_crs);
    const std::string target_name = normalize_crs_name(project_crs);
    if (source_name.empty() || target_name.empty() ||
        source_name == target_name) {
        return prepared;
    }
    const ReprojectKey key{
        static_cast<std::int64_t>(layer.data_revision), source_name,
        target_name};
    {
        std::lock_guard<std::mutex> lock(prepared_mutex_);
        if (const auto* cached = reprojected_.get(layer.id, key)) {
            return *cached;
        }
    }
    std::shared_ptr<const PreparedLayer> reprojected;
    try {
        CrsTransformer transformer =
            make_crs_transformer(layer_crs, project_crs);
        reprojected = transformer == nullptr
                          ? prepared
                          : reprojected_prepared_layer(prepared,
                                                       transformer);
    } catch (const std::exception& exc) {
        const std::string name =
            !layer.name.empty() ? layer.name : layer.id;
        {
            std::lock_guard<std::mutex> lock(diag_mutex_);
            crs_warnings_.push_back(
                "矢量图层“" + name + "”(" + layer_crs +
                ")无法重投影到工程 CRS(" + project_crs + "):" +
                exc.what() +
                ";已按图层原坐标降级绘制,输出可能存在坐标混绘");
        }
        return prepared;
    }
    {
        std::lock_guard<std::mutex> lock(prepared_mutex_);
        reprojected_.store(layer.id, key, reprojected);
    }
    return reprojected;
}

std::shared_ptr<const PreparedLayer>
FallbackMapRenderBackend::lod_prepared(
    std::shared_ptr<const PreparedLayer> prepared,
    const MapLayerSnapshot& layer, double mupp) {
    if (vector_lod_disabled_ || !prepared->has_paths) return prepared;
    const std::size_t total = prepared->path_xy.size() / 2;
    if (total < vector_lod::kMinVertexCount) return prepared;
    const double bucket = vector_lod::scale_bucket_mupp(mupp);
    const double tolerance = vector_lod::tolerance_area(mupp);
    if (bucket <= 0.0 || tolerance <= 0.0) return prepared;
    const std::string project_crs = snapshot().project_crs;
    const LodKey key{static_cast<std::int64_t>(layer.data_revision),
                     bucket, project_crs};
    {
        std::lock_guard<std::mutex> lock(prepared_mutex_);
        if (const auto* cached = lod_cache_.get(layer.id, key)) {
            return *cached;
        }
    }
    const std::size_t n = prepared->path_xy.size() / 2;
    std::vector<double> xs(n), ys(n);
    for (std::size_t i = 0; i < n; ++i) {
        xs[i] = prepared->path_xy[i * 2];
        ys[i] = prepared->path_xy[i * 2 + 1];
    }
    const std::vector<std::size_t> starts(prepared->path_offsets.begin(),
                                          prepared->path_offsets.end() - 1);
    std::vector<bool> keep = vector_lod::visvalingam_keep_mask(
        xs, ys, starts, prepared->path_is_ring, tolerance);
    auto reduced = lod_subset_prepared(prepared, keep);
    diag_add("lod_vertices_total", static_cast<double>(total));
    std::size_t kept_n = 0;
    for (bool k : keep) kept_n += k ? 1 : 0;
    diag_add("lod_vertices_kept", static_cast<double>(kept_n));
    {
        std::lock_guard<std::mutex> lock(prepared_mutex_);
        lod_cache_.store(layer.id, key, reduced);
    }
    return reduced;
}

// -- vector painting ----------------------------------------------------------

void FallbackMapRenderBackend::paint_vector_layer(
    QPainter& painter, const MapLayerSnapshot& layer, double xmin,
    double ymin, double span_x, double span_y, int width, int height,
    double dpi_scale, std::vector<LabelSpec>* label_specs) {
    const carto::VectorStyle style =
        carto::VectorStyle::from_dict(layer.style);
    const double scale_x = width / span_x;
    const double scale_y = height / span_y;
    const double marker_radius =
        std::max(0.5, style.marker_size * dpi_scale / 2.0);
    const double stroke_width =
        std::max(0.0, style.stroke_width * dpi_scale);
    const double pad_x = (marker_radius + stroke_width) / scale_x;
    const double pad_y = (marker_radius + stroke_width) / scale_y;
    const Extent view{xmin - pad_x, ymin - pad_y,
                      xmin + span_x + pad_x, ymin + span_y + pad_y};
    QPen pen(color_of(style.stroke, "#26364d"),
             std::max(0.5, stroke_width));
    const std::vector<double> dash =
        carto::dash_pattern(style.line_pattern);
    if (!dash.empty()) {
        pen.setDashPattern(QVector<qreal>(dash.begin(), dash.end()));
    } else if (stroke_width <= 0.0) {
        pen.setStyle(Qt::NoPen);
    }
    painter.setPen(pen);
    const QColor fill = color_of(style.fill, "#6c8ebf");
    const bool transparent_fill =
        style.fill == "transparent" || fill.alpha() == 0;
    painter.setBrush(transparent_fill ? QBrush(Qt::NoBrush)
                                      : QBrush(fill));
    auto prepared = prepared_layer(layer);
    prepared = reprojected_prepared(prepared, layer);
    const double mupp = width > 0 ? span_x / width : 0.0;
    prepared = lod_prepared(prepared, layer, mupp);
    diag_add("features_total",
             static_cast<double>(prepared->features.size()));
    // _cull_features: per-feature bbox vs view.
    std::vector<bool> visible(prepared->features.size(), false);
    std::size_t visible_count = 0;
    for (std::size_t i = 0; i < prepared->features.size(); ++i) {
        const Extent& b = prepared->features[i].bbox;
        visible[i] = b[2] >= view[0] && b[0] <= view[2] &&
                     b[3] >= view[1] && b[1] <= view[3];
        visible_count += visible[i] ? 1 : 0;
    }
    diag_add("features_drawn", static_cast<double>(visible_count));
    if (visible_count == 0) return;
    if (prepared->has_paths) {
        paint_layer_paths(painter, *prepared, visible, style, xmin,
                          ymin, scale_x, scale_y, width, height,
                          marker_radius, stroke_width, transparent_fill,
                          fill, dpi_scale);
    }
    if (prepared->has_points) {
        paint_layer_points(painter, *prepared, visible, style, xmin,
                           ymin, scale_x, scale_y, width, height,
                           marker_radius, stroke_width, transparent_fill,
                           fill, dpi_scale, label_specs);
    }
}

void FallbackMapRenderBackend::paint_layer_paths(
    QPainter& painter, const PreparedLayer& prepared,
    const std::vector<bool>& visible_features,
    const carto::VectorStyle& style, double xmin, double ymin,
    double scale_x, double scale_y, int width, int height,
    double marker_radius, double stroke_width, bool transparent_fill,
    const QColor& fill, double dpi_scale) {
    const std::size_t vertex_count = prepared.path_xy.size() / 2;
    // world → screen transform over the flat array.
    std::vector<double> screen(prepared.path_xy.size());
    for (std::size_t i = 0; i < vertex_count; ++i) {
        screen[i * 2] = (prepared.path_xy[i * 2] - xmin) * scale_x;
        screen[i * 2 + 1] =
            height - (prepared.path_xy[i * 2 + 1] - ymin) * scale_y;
    }
    const std::size_t part_count = prepared.path_offsets.size() - 1;
    const std::size_t* offsets = prepared.path_offsets.data();
    // Per-part feature visibility then screen-space bbox culling.
    const double pad_px = marker_radius + stroke_width + 1.0;
    std::vector<bool> in_view(part_count, false);
    std::size_t visible_vertices = 0;
    std::vector<std::size_t> part_indices;
    for (std::size_t p = 0; p < part_count; ++p) {
        if (!visible_features[prepared.path_feature[p]]) continue;
        const std::size_t s = offsets[p], e = offsets[p + 1];
        double min_x = std::numeric_limits<double>::max();
        double max_x = std::numeric_limits<double>::lowest();
        double min_y = min_x, max_y = max_x;
        for (std::size_t i = s; i < e; ++i) {
            min_x = std::min(min_x, screen[i * 2]);
            max_x = std::max(max_x, screen[i * 2]);
            min_y = std::min(min_y, screen[i * 2 + 1]);
            max_y = std::max(max_y, screen[i * 2 + 1]);
        }
        in_view[p] = max_x >= -pad_px && min_x <= width + pad_px &&
                     max_y >= -pad_px && min_y <= height + pad_px;
        if (in_view[p]) {
            part_indices.push_back(p);
            visible_vertices += e - s;
        }
    }
    if (part_indices.empty()) return;
    // Adaptive pixel-grid LOD (grid coarsens with vertex pressure).
    double tolerance = 1.0;
    if (visible_vertices > 400000) tolerance = 2.0;
    if (visible_vertices > 1200000) tolerance = 3.0;
    std::vector<bool> keep(vertex_count, false);
    if (vertex_count > 2) {
        for (std::size_t i = 0; i + 1 < vertex_count; ++i) {
            const auto qx0 = static_cast<std::int64_t>(
                std::floor(screen[i * 2] / tolerance));
            const auto qy0 = static_cast<std::int64_t>(
                std::floor(screen[i * 2 + 1] / tolerance));
            const auto qx1 = static_cast<std::int64_t>(
                std::floor(screen[(i + 1) * 2] / tolerance));
            const auto qy1 = static_cast<std::int64_t>(
                std::floor(screen[(i + 1) * 2 + 1] / tolerance));
            if (qx0 != qx1 || qy0 != qy1) {
                keep[i] = true;
                keep[i + 1] = true;
            }
        }
    }
    for (std::size_t p = 0; p < part_count; ++p) {
        keep[offsets[p]] = true;
        keep[offsets[p + 1] - 1] = true;
    }
    // Hard vertex budget: stride-decimate LINE parts only (rings exempt —
    // a global stride can collapse a small ring to two endpoints and
    // cracks shared edges).
    if (visible_vertices >
        static_cast<std::size_t>(vertex_budget_)) {
        std::size_t line_budget = visible_vertices;
        for (std::size_t p : part_indices) {
            if (prepared.path_is_ring[p]) {
                line_budget -= offsets[p + 1] - offsets[p];
            }
        }
        int stride = 1;
        if (line_budget > 0) {
            stride = static_cast<int>(std::ceil(
                static_cast<double>(line_budget) / vertex_budget_));
        }
        if (stride > 1) {
            for (std::size_t i = 0; i < vertex_count; ++i) {
                std::size_t part = 0;
                while (part + 1 < part_count &&
                       offsets[part + 1] <= i) {
                    ++part;
                }
                if (!prepared.path_is_ring[part]) {
                    keep[i] = keep[i] && (i % stride == 0);
                }
            }
            for (std::size_t p = 0; p < part_count; ++p) {
                keep[offsets[p]] = true;
                keep[offsets[p + 1] - 1] = true;
            }
        }
    }
    std::vector<std::size_t> kept_index;
    for (std::size_t i = 0; i < vertex_count; ++i) {
        if (keep[i]) kept_index.push_back(i);
    }
    const auto kept_slice = [&](std::size_t part)
        -> std::pair<std::size_t, std::size_t> {
        const auto lo = std::lower_bound(kept_index.begin(),
                                         kept_index.end(), offsets[part]);
        const auto hi =
            std::lower_bound(kept_index.begin(), kept_index.end(),
                             offsets[part + 1]);
        return {static_cast<std::size_t>(lo - kept_index.begin()),
                static_cast<std::size_t>(hi - kept_index.begin())};
    };

    std::size_t drawn_vertices = 0;
    const auto categories = category_colors(style);
    const auto patterns = category_patterns(style);

    // Lines: stroke-only pass.
    painter.save();
    painter.setBrush(Qt::NoBrush);
    for (std::size_t p : part_indices) {
        if (prepared.path_is_ring[p]) continue;
        const auto [s, e] = kept_slice(p);
        drawn_vertices += e - s;
        if (e - s < 2) continue;
        QPainterPath path;
        path.moveTo(screen[kept_index[s] * 2],
                    screen[kept_index[s] * 2 + 1]);
        for (std::size_t i = s + 1; i < e; ++i) {
            path.lineTo(screen[kept_index[i] * 2],
                        screen[kept_index[i] * 2 + 1]);
        }
        painter.drawPath(path);
    }
    painter.restore();

    // Polygons: per-feature paths (OddEvenFill keeps holes correct) then
    // grouped by category colour / pattern (Ticket-4 batching).
    int current_feature = -1;
    QPainterPath path;
    std::map<std::string, QPainterPath> color_paths;
    QPainterPath plain_path;
    bool has_plain = false;
    std::map<std::string, QPainterPath> pattern_paths;
    std::vector<std::pair<QPainterPath, QColor>> late_paths;

    auto draw_immediate = [&](QPainterPath& feature_path,
                              const std::string& color_name,
                              const std::string& pattern_id) {
        painter.save();
        painter.setBrush(
            QBrush(color_of(color_name, style.fill.c_str())));
        painter.drawPath(feature_path);
        painter.restore();
        if (!pattern_id.empty()) {
            const auto pattern_brush =
                facies_patterns_->brush_for(pattern_id, dpi_scale);
            if (pattern_brush.has_value()) {
                painter.save();
                painter.setPen(Qt::NoPen);
                painter.setBrush(*pattern_brush);
                painter.drawPath(feature_path);
                painter.restore();
            }
        }
    };

    std::function<void()> flush_polygon = [&]() {
        if (!path.isEmpty()) {
            if (categories.has_value() && current_feature >= 0) {
                const PreparedFeature& feature =
                    prepared.features[current_feature];
                const Json* v = property_of(feature, style.field);
                const std::string key =
                    json_falsy(v) ? "" : property_str(*v);
                const auto it = categories->find(key);
                if (it != categories->end()) {
                    if (facies_batch_disabled_) {
                        const std::string pattern_id =
                            patterns.has_value()
                                ? ([&] {
                                      const auto p =
                                          patterns->find(key);
                                      return p != patterns->end()
                                                 ? p->second
                                                 : std::string();
                                  })()
                                : std::string();
                        draw_immediate(path, it->second, pattern_id);
                        path = QPainterPath();
                        current_feature = -1;
                        return;
                    }
                    auto& group = color_paths[it->second];
                    group.setFillRule(Qt::OddEvenFill);
                    group.addPath(path);
                    if (patterns.has_value()) {
                        const auto p = patterns->find(key);
                        const std::string pattern_id =
                            p != patterns->end() ? p->second : "";
                        if (!pattern_id.empty()) {
                            auto& merged = pattern_paths[pattern_id];
                            merged.setFillRule(Qt::OddEvenFill);
                            merged.addPath(path);
                        }
                    }
                    path = QPainterPath();
                    current_feature = -1;
                    return;
                }
            } else if (!style.ranges.empty() && current_feature >= 0) {
                const PreparedFeature& feature =
                    prepared.features[current_feature];
                const Json* v = property_of(feature, style.field);
                if (json_falsy(v)) v = property_of(feature, "value");
                const auto color_name =
                    v != nullptr ? range_color(*v, style)
                                 : std::nullopt;
                if (color_name.has_value()) {
                    late_paths.emplace_back(
                        path,
                        color_of(*color_name, style.fill.c_str()));
                    path = QPainterPath();
                    current_feature = -1;
                    return;
                }
            }
            if (!path.isEmpty()) {
                plain_path.addPath(path);
                has_plain = true;
            }
        }
        path = QPainterPath();
        current_feature = -1;
    };

    for (std::size_t p : part_indices) {
        if (!prepared.path_is_ring[p]) continue;
        auto [s, e] = kept_slice(p);
        if (e - s < 3) {
            // A ring collapsed below three kept vertices would vanish —
            // fall back to its unsimplified vertex range (raw indices).
            s = offsets[p];
            e = offsets[p + 1];
            drawn_vertices += e - s;
            const auto feature =
                static_cast<int>(prepared.path_feature[p]);
            if (feature != current_feature) {
                flush_polygon();
                current_feature = feature;
                path = QPainterPath();
                path.setFillRule(Qt::OddEvenFill);
            }
            path.moveTo(screen[s * 2], screen[s * 2 + 1]);
            for (std::size_t i = s + 1; i < e; ++i) {
                path.lineTo(screen[i * 2], screen[i * 2 + 1]);
            }
            continue;
        }
        drawn_vertices += e - s;
        const auto feature =
            static_cast<int>(prepared.path_feature[p]);
        if (feature != current_feature) {
            flush_polygon();
            current_feature = feature;
            path = QPainterPath();
            path.setFillRule(Qt::OddEvenFill);
        }
        path.moveTo(screen[kept_index[s] * 2],
                    screen[kept_index[s] * 2 + 1]);
        for (std::size_t i = s + 1; i < e; ++i) {
            path.lineTo(screen[kept_index[i] * 2],
                        screen[kept_index[i] * 2 + 1]);
        }
    }
    flush_polygon();

    for (auto& [color_name, group] : color_paths) {
        painter.save();
        painter.setBrush(
            QBrush(color_of(color_name, style.fill.c_str())));
        painter.drawPath(group);
        painter.restore();
    }
    if (has_plain) painter.drawPath(plain_path);
    for (auto& [late_path, late_color] : late_paths) {
        painter.save();
        painter.setBrush(QBrush(late_color));
        painter.drawPath(late_path);
        painter.restore();
    }
    for (auto& [pattern_id, group] : pattern_paths) {
        const auto pattern_brush =
            facies_patterns_->brush_for(pattern_id, dpi_scale);
        if (!pattern_brush.has_value()) continue;
        painter.save();
        painter.setPen(Qt::NoPen);
        painter.setBrush(*pattern_brush);
        painter.drawPath(group);
        painter.restore();
    }
    diag_add("vertices_simplified",
             static_cast<double>(visible_vertices) -
                 static_cast<double>(drawn_vertices));
}

void FallbackMapRenderBackend::paint_layer_points(
    QPainter& painter, const PreparedLayer& prepared,
    const std::vector<bool>& visible_features,
    const carto::VectorStyle& style, double xmin, double ymin,
    double scale_x, double scale_y, int width, int height,
    double marker_radius, double stroke_width, bool transparent_fill,
    const QColor& fill, double dpi_scale,
    std::vector<LabelSpec>* label_specs) {
    const std::size_t count_xy = prepared.point_xy.size() / 2;
    const double pad_px = marker_radius + stroke_width + 1.0;
    std::vector<QPointF> points;
    std::vector<int> feature_indices;
    points.reserve(count_xy);
    feature_indices.reserve(count_xy);
    for (std::size_t i = 0; i < count_xy; ++i) {
        if (!visible_features[prepared.point_feature[i]]) continue;
        const double sx =
            (prepared.point_xy[i * 2] - xmin) * scale_x;
        const double sy =
            height - (prepared.point_xy[i * 2 + 1] - ymin) * scale_y;
        if (sx >= -pad_px && sx <= width + pad_px && sy >= -pad_px &&
            sy <= height + pad_px) {
            points.emplace_back(sx, sy);
            feature_indices.push_back(prepared.point_feature[i]);
        }
    }
    std::size_t count = points.size();
    if (count == 0) return;
    // Grid de-duplication LOD: sub-1.5px markers collapse coincident dots
    // (np.unique axis=0 keeps FIRST occurrence; sorted indices restore
    // order).
    if (marker_radius < 1.5 && count > 4000) {
        std::map<std::pair<std::int64_t, std::int64_t>, std::size_t>
            first_at;
        for (std::size_t i = 0; i < count; ++i) {
            const auto key = std::make_pair(
                static_cast<std::int64_t>(std::floor(points[i].x())),
                static_cast<std::int64_t>(std::floor(points[i].y())));
            first_at.emplace(key, i);
        }
        std::vector<std::size_t> unique_at;
        for (const auto& [key, i] : first_at) unique_at.push_back(i);
        std::sort(unique_at.begin(), unique_at.end());
        std::vector<QPointF> up;
        std::vector<int> uf;
        for (std::size_t i : unique_at) {
            up.push_back(points[i]);
            uf.push_back(feature_indices[i]);
        }
        points = std::move(up);
        feature_indices = std::move(uf);
        count = points.size();
    }
    diag_add("points_drawn", static_cast<double>(count));
    const auto categorized =
        count <= static_cast<std::size_t>(kCategoryPointCap)
            ? category_colors(style)
            : std::nullopt;
    const bool has_graduated =
        count <= static_cast<std::size_t>(kCategoryPointCap) &&
        !style.ranges.empty();
    const bool batch_dots =
        marker_radius < 1.0 ||
        (style.marker == carto::MarkerSymbol::Circle &&
         marker_radius <= 4.0);
    const bool symbol_loop =
        !batch_dots && count <= static_cast<std::size_t>(kSymbolLoopCap);

    auto draw_group = [&](const std::vector<std::size_t>& positions) {
        if (symbol_loop) {
            for (std::size_t pos : positions) {
                draw_point_symbol(painter, points[pos], marker_radius,
                                  style.marker);
            }
        } else {
            std::vector<QPointF> selected;
            selected.reserve(positions.size());
            for (std::size_t pos : positions) {
                selected.push_back(points[pos]);
            }
            draw_dots(painter, selected, marker_radius);
        }
    };

    if (categorized.has_value() && !transparent_fill) {
        // Group ORDER = first appearance (Python dict setdefault parity).
        std::vector<std::string> order;
        std::map<std::string, std::vector<std::size_t>> groups;
        for (std::size_t position = 0; position < feature_indices.size();
             ++position) {
            const PreparedFeature& feature =
                prepared.features[feature_indices[position]];
            const Json* v = property_of(feature, style.field);
            const std::string key =
                json_falsy(v) ? "" : property_str(*v);
            if (groups.emplace(key, std::vector<std::size_t>{}).second) {
                order.push_back(key);
            }
            groups[key].push_back(position);
        }
        painter.save();
        QPen symbol_pen(painter.pen());
        symbol_pen.setStyle(Qt::SolidLine);
        symbol_pen.setWidthF(std::max(1.0, stroke_width));
        painter.setPen(symbol_pen);
        for (const std::string& key : order) {
            const auto it = categorized->find(key);
            painter.setBrush(
                it != categorized->end()
                    ? QBrush(color_of(it->second, style.fill.c_str()))
                    : QBrush(fill));
            draw_group(groups[key]);
        }
        painter.restore();
        return;
    }
    if (has_graduated && !transparent_fill) {
        std::vector<std::string> order;
        std::map<std::string, std::vector<std::size_t>> groups;
        for (std::size_t position = 0; position < feature_indices.size();
             ++position) {
            const PreparedFeature& feature =
                prepared.features[feature_indices[position]];
            const Json* v = property_of(feature, style.field);
            if (json_falsy(v)) v = property_of(feature, "value");
            const auto color_name =
                v != nullptr ? range_color(*v, style) : std::nullopt;
            const std::string key =
                color_name.has_value() ? *color_name : style.fill;
            if (groups.emplace(key, std::vector<std::size_t>{}).second) {
                order.push_back(key);
            }
            groups[key].push_back(position);
        }
        painter.save();
        QPen symbol_pen(painter.pen());
        symbol_pen.setStyle(Qt::SolidLine);
        symbol_pen.setWidthF(std::max(1.0, stroke_width));
        painter.setPen(symbol_pen);
        for (const std::string& key : order) {
            painter.setBrush(QBrush(color_of(key, style.fill.c_str())));
            draw_group(groups[key]);
        }
        painter.restore();
        return;
    }

    if (symbol_loop) {
        painter.save();
        QPen symbol_pen(painter.pen());
        symbol_pen.setStyle(Qt::SolidLine);
        symbol_pen.setWidthF(std::max(1.0, stroke_width));
        painter.setPen(symbol_pen);
        for (const QPointF& p : points) {
            draw_point_symbol(painter, p, marker_radius, style.marker);
        }
        painter.restore();
    } else {
        draw_dots(painter, points, marker_radius);
    }
    // Labels: style.labels, else the annotation-layer default.
    carto::VectorStyle effective = style;
    if (!effective.labels.has_value() &&
        prepared.layer_type == "annotation") {
        carto::TextStyle labels;
        labels.field = "text";
        labels.size = 10.0;
        labels.color = "#1f2937";
        effective.labels = labels;
    }
    if (effective.labels.has_value() && effective.labels->visible &&
        count <= static_cast<std::size_t>(kLabelPointCap)) {
        const std::string field = !effective.labels->field.empty()
                                      ? effective.labels->field
                                      : "text";
        for (std::size_t position = 0; position < points.size();
             ++position) {
            const PreparedFeature& feature =
                prepared.features[feature_indices[position]];
            draw_label_text(painter, points[position], feature, field,
                            effective, dpi_scale, label_specs);
        }
    }
}

void FallbackMapRenderBackend::draw_dots(
    QPainter& painter, const std::vector<QPointF>& points,
    double radius) {
    painter.save();
    QPen dot_pen(painter.pen());
    dot_pen.setStyle(Qt::SolidLine);
    dot_pen.setWidthF(std::max(1.0, radius * 2.0));
    dot_pen.setCapStyle(Qt::RoundCap);
    painter.setPen(dot_pen);
    painter.drawPoints(
        QPolygonF(QVector<QPointF>(points.begin(), points.end())));
    painter.restore();
}

void FallbackMapRenderBackend::draw_point_symbol(
    QPainter& painter, const QPointF& centre, double radius,
    carto::MarkerSymbol marker) {
    switch (marker) {
        case carto::MarkerSymbol::Square:
            painter.drawRect(QRectF(centre.x() - radius,
                                    centre.y() - radius, radius * 2,
                                    radius * 2));
            break;
        case carto::MarkerSymbol::Triangle:
            painter.drawPolygon(QPolygonF(
                {centre + QPointF(0, -radius * 1.2),
                 centre + QPointF(-radius, radius),
                 centre + QPointF(radius, radius)}));
            break;
        case carto::MarkerSymbol::Diamond:
            painter.drawPolygon(
                QPolygonF({centre + QPointF(0, -radius),
                           centre + QPointF(radius, 0),
                           centre + QPointF(0, radius),
                           centre + QPointF(-radius, 0)}));
            break;
        case carto::MarkerSymbol::Cross:
            painter.drawLine(centre + QPointF(-radius, -radius),
                             centre + QPointF(radius, radius));
            painter.drawLine(centre + QPointF(radius, -radius),
                             centre + QPointF(-radius, radius));
            break;
        case carto::MarkerSymbol::Star: {
            QPolygonF star;
            for (int index = 0; index < 10; ++index) {
                const double angle = -M_PI / 2 + index * M_PI / 5;
                const double length =
                    index % 2 == 0 ? radius : radius * 0.45;
                star.append(centre + QPointF(length * std::cos(angle),
                                             length * std::sin(angle)));
            }
            painter.drawPolygon(star);
            break;
        }
        case carto::MarkerSymbol::Well:
            painter.drawEllipse(centre, radius, radius);
            painter.drawPoint(centre);
            break;
        case carto::MarkerSymbol::Circle:
        default:
            painter.drawEllipse(centre, radius, radius);
            break;
    }
}

void FallbackMapRenderBackend::draw_label_text(
    QPainter& painter, const QPointF& anchor,
    const PreparedFeature& feature, const std::string& field,
    const carto::VectorStyle& style, double dpi_scale,
    std::vector<LabelSpec>* label_specs) {
    // str(props.get(field) or props.get("name") or props.get("text") or "")
    const Json* v = property_of(feature, field);
    if (json_falsy(v)) v = property_of(feature, "name");
    if (json_falsy(v)) v = property_of(feature, "text");
    std::string text = json_falsy(v) ? "" : property_str(*v);
    const auto f = text.find_first_not_of(" \t\n\r");
    const auto l = text.find_last_not_of(" \t\n\r");
    text = f == std::string::npos ? "" : text.substr(f, l - f + 1);
    if (text.empty() || !style.labels.has_value()) return;
    const QPointF position =
        anchor + QPointF(std::max(4.0, style.marker_size * dpi_scale /
                                            2.0 + 2.0),
                         -4.0 * dpi_scale);
    const carto::TextStyle& cfg = *style.labels;
    if (label_specs != nullptr) {
        LabelSpec spec;
        spec.x = position.x();
        spec.y = position.y();
        spec.text = text;
        spec.size = cfg.size;
        spec.bold = cfg.bold;
        spec.family = cfg.font_family;
        spec.color = cfg.color;
        spec.halo_color = cfg.halo_color;
        spec.halo_width = cfg.halo_width;
        spec.dpi_scale = dpi_scale;
        label_specs->push_back(std::move(spec));
        return;
    }
    painter.save();
    QFont font = painter.font();
    font.setPixelSize(std::max(
        8, static_cast<int>(std::lround(cfg.size * dpi_scale))));
    font.setBold(cfg.bold);
    if (!cfg.font_family.empty()) {
        font.setFamily(QString::fromStdString(cfg.font_family));
    }
    painter.setFont(font);
    draw_halo_text(painter, position, font,
                   QString::fromStdString(text),
                   QColor(QString::fromStdString(cfg.halo_color)),
                   cfg.halo_width * dpi_scale * 2.0,
                   QColor(QString::fromStdString(cfg.color)));
    painter.restore();
}

void FallbackMapRenderBackend::paint_label_specs(
    QPainter& painter, const std::vector<LabelSpec>& specs) {
    painter.setRenderHint(QPainter::Antialiasing, true);
    painter.save();
    QFont font = painter.font();
    for (const LabelSpec& spec : specs) {
        font.setPixelSize(std::max(
            8,
            static_cast<int>(std::lround(spec.size * spec.dpi_scale))));
        font.setBold(spec.bold);
        if (!spec.family.empty()) {
            font.setFamily(QString::fromStdString(spec.family));
        }
        painter.setFont(font);
        draw_halo_text(painter, QPointF(spec.x, spec.y), font,
                       QString::fromStdString(spec.text),
                       QColor(QString::fromStdString(spec.halo_color)),
                       spec.halo_width * spec.dpi_scale * 2.0,
                       QColor(QString::fromStdString(spec.color)));
    }
    painter.restore();
}

// -- raster layers -------------------------------------------------------------

void FallbackMapRenderBackend::draw_image_layer(
    QPainter& painter, const MapLayerSnapshot& layer) {
    // C++ contract parity: scalar_grid/raster_source both carry the
    // resolved mirror file in source_path (the Python rasterize()
    // payload is resolved to a file by the mirror caches upstream).
    if (layer.source_path.empty()) return;
    const ScalarKey key{layer.source_path,
                        static_cast<std::int64_t>(layer.data_revision),
                        static_cast<std::int64_t>(layer.style_revision)};
    QImage image;
    {
        std::lock_guard<std::mutex> lock(prepared_mutex_);
        if (const ScalarImageEntry* entry =
                scalar_images_.get(layer.id, key);
            entry != nullptr) {
            diag_add("scalar_cache_hits", 1.0);
            image = entry->image;
        }
    }
    if (image.isNull()) {
        image = QImage(QString::fromStdString(layer.source_path));
        if (image.isNull()) return;
        std::lock_guard<std::mutex> lock(prepared_mutex_);
        scalar_images_.store(layer.id, key,
                             ScalarImageEntry{image});
        diag_add("scalar_cache_misses", 1.0);
    }
    const auto top_left =
        screen_point(layer.extent[0], layer.extent[3]);
    const auto bottom_right =
        screen_point(layer.extent[2], layer.extent[1]);
    if (top_left.has_value() && bottom_right.has_value()) {
        painter.drawImage(
            QRectF(*top_left, *bottom_right).normalized(), image);
    }
}

std::optional<QPointF> FallbackMapRenderBackend::screen_point(
    double x, double y) const {
    const auto size = output_size();
    const Extent fitted =
        fit_extent_to_aspect(extent(), size.first, size.second);
    const double dx = fitted[2] - fitted[0];
    const double dy = fitted[3] - fitted[1];
    if (dx == 0.0 || dy == 0.0) return std::nullopt;
    return QPointF((x - fitted[0]) * size.first / dx,
                   size.second - (y - fitted[1]) * size.second / dy);
}

QColor FallbackMapRenderBackend::color_of(const std::string& value,
                                          const char* fallback) {
    const QColor color(
        QString::fromStdString(value.empty() ? fallback : value));
    return color.isValid() ? color : QColor(fallback);
}

// -- registry / factory ---------------------------------------------------------

void shutdown_live_fallback_backends() {
    std::lock_guard<std::mutex> lock(live_fallbacks_mutex());
    for (FallbackMapRenderBackend* backend : live_fallbacks()) {
        if (backend != nullptr) backend->shutdown();
    }
}

void install_fallback_backend_factory() {
    // Idempotent — callers (canvas ctor, export worker) install
    // unconditionally; static-library TUs only link when referenced, so
    // a load-time registrar cannot be relied on here.
    static bool installed = false;
    if (installed) return;
    installed = true;
    register_backend_factory(
        []() -> std::shared_ptr<MapRenderBackend> {
            return std::make_shared<FallbackMapRenderBackend>();
        },
        /*is_qgis=*/false);
}

}  // namespace pwb::ui_canvas::qt
