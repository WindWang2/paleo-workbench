// export.map_thumbnail — C++ port of examples/provider_plugins/export_map_thumbnail.py.
//
// Renders a real pwb::mapping_document::MapDocument through a native
// software rasterizer (the deterministic core-only counterpart of the
// Python FallbackMapRenderBackend seam: visible layers in order, GeoJSON-like
// feature geometry, fill/stroke from the layer style, painter's algorithm)
// into a workspace-contained PNG (resolve_contained_output, #1177), then
// demonstrates the V2 verify hook by checking the artifact is a real PNG.
#include <pwb/providers/builtin.hpp>

#include <pwb/mapping_document/map_document.hpp>
#include <pwb/providers/context.hpp>
#include <pwb/providers/errors.hpp>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <optional>
#include <vector>

#include "png_writer.hpp"

namespace pwb::providers {

namespace {

constexpr const char* kBuildIdentity = "examples/provider-plugins@2026-09-06";
const std::array<std::uint8_t, 8> kPngMagic{0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A};

// ---------------------------------------------------------------------------
// software rasterizer (RGB, painter's algorithm, deterministic)
// ---------------------------------------------------------------------------

struct Rgb {
    std::uint8_t r = 255, g = 255, b = 255;
};

bool parse_hex_color(const Json& value, Rgb* out) {
    if (!value.is_string()) return false;
    const std::string s = value.get<std::string>();
    if (s.size() != 7 || s[0] != '#') return false;
    const auto hex = [](char c) -> int {
        if (c >= '0' && c <= '9') return c - '0';
        if (c >= 'a' && c <= 'f') return c - 'a' + 10;
        if (c >= 'A' && c <= 'F') return c - 'A' + 10;
        return -1;
    };
    const int r = hex(s[1]) < 0 ? -1 : (hex(s[1]) << 4) | hex(s[2]);
    const int g = hex(s[3]) < 0 ? -1 : (hex(s[3]) << 4) | hex(s[4]);
    const int b = hex(s[5]) < 0 ? -1 : (hex(s[5]) << 4) | hex(s[6]);
    if (r < 0 || g < 0 || b < 0) return false;
    out->r = static_cast<std::uint8_t>(r);
    out->g = static_cast<std::uint8_t>(g);
    out->b = static_cast<std::uint8_t>(b);
    return true;
}

class Canvas {
public:
    Canvas(std::uint32_t width, std::uint32_t height)
        : width_(width), height_(height),
          pixels_(static_cast<std::size_t>(width) * static_cast<std::size_t>(height) * 3u,
                  0xFF) {}

    std::uint32_t width() const { return width_; }
    std::uint32_t height() const { return height_; }
    const std::uint8_t* data() const { return pixels_.data(); }
    std::size_t size() const { return pixels_.size(); }

    void blend(int x, int y, Rgb color, double alpha) {
        if (x < 0 || y < 0 || x >= static_cast<int>(width_) ||
            y >= static_cast<int>(height_) || alpha <= 0.0) {
            return;
        }
        if (alpha >= 1.0) {
            const std::size_t offset =
                (static_cast<std::size_t>(y) * width_ + static_cast<std::size_t>(x)) * 3u;
            pixels_[offset] = color.r;
            pixels_[offset + 1] = color.g;
            pixels_[offset + 2] = color.b;
            return;
        }
        const std::size_t offset =
            (static_cast<std::size_t>(y) * width_ + static_cast<std::size_t>(x)) * 3u;
        for (int c = 0; c < 3; ++c) {
            const double base = static_cast<double>(pixels_[offset + static_cast<std::size_t>(c)]);
            const double src = c == 0 ? color.r : (c == 1 ? color.g : color.b);
            pixels_[offset + static_cast<std::size_t>(c)] =
                static_cast<std::uint8_t>(base * (1.0 - alpha) + src * alpha + 0.5);
        }
    }

    // DDA line, 2px wide for stroke visibility at thumbnail scale. Steps are
    // capped in screen space: world coordinates far outside the extent are
    // clamped by WorldToScreen, so an unbounded loop is impossible.
    void draw_line(double x0, double y0, double x1, double y1, Rgb color, double alpha) {
        int steps = static_cast<int>(std::max(std::abs(x1 - x0), std::abs(y1 - y0)));
        constexpr int kMaxSteps = 16384;
        if (steps > kMaxSteps) steps = kMaxSteps;
        if (steps == 0) {
            blend(static_cast<int>(x0), static_cast<int>(y0), color, alpha);
            return;
        }
        for (int i = 0; i <= steps; ++i) {
            const double t = static_cast<double>(i) / static_cast<double>(steps);
            const int x = static_cast<int>(x0 + (x1 - x0) * t + 0.5);
            const int y = static_cast<int>(y0 + (y1 - y0) * t + 0.5);
            blend(x, y, color, alpha);
            blend(x + 1, y, color, alpha);
        }
    }

    void fill_disc(double cx, double cy, int radius, Rgb color, double alpha) {
        for (int dy = -radius; dy <= radius; ++dy) {
            for (int dx = -radius; dx <= radius; ++dx) {
                if (dx * dx + dy * dy <= radius * radius) {
                    blend(safe_int(cx) + dx, safe_int(cy) + dy, color, alpha);
                }
            }
        }
    }

    // Even-odd scanline fill across all rings (outer + holes).
    void fill_polygon_rings(const std::vector<std::vector<std::pair<double, double>>>& rings,
                            Rgb color, double alpha) {
        std::vector<std::pair<double, double>> flat;
        for (const auto& ring : rings) {
            for (const auto& pt : ring) flat.push_back(pt);
        }
        if (flat.size() < 3) return;
        double min_y = flat[0].second, max_y = flat[0].second;
        for (const auto& pt : flat) {
            min_y = std::min(min_y, pt.second);
            max_y = std::max(max_y, pt.second);
        }
        // Clamp in double space BEFORE narrowing: screen coordinates from
        // WorldToScreen are already bounded, but a defensive clamp keeps the
        // int cast well-defined for any input.
        const double floored = std::floor(min_y);
        const double ceiled = std::ceil(max_y);
        const int y_start = std::max(0, static_cast<int>(std::clamp(
                                             floored, -1.0e9, 1.0e9)));
        const int y_end =
            std::min(static_cast<int>(height_) - 1,
                     static_cast<int>(std::clamp(ceiled, -1.0e9, 1.0e9)));
        for (int y = y_start; y <= y_end; ++y) {
            std::vector<double> crossings;
            const double sy = static_cast<double>(y) + 0.5;
            for (const auto& ring : rings) {
                const std::size_t n = ring.size();
                if (n < 2) continue;
                for (std::size_t i = 0; i < n; ++i) {
                    const auto& a = ring[i];
                    const auto& b = ring[(i + 1) % n];
                    if ((a.second <= sy && b.second > sy) || (b.second <= sy && a.second > sy)) {
                        const double t = (sy - a.second) / (b.second - a.second);
                        crossings.push_back(a.first + t * (b.first - a.first));
                    }
                }
            }
            std::sort(crossings.begin(), crossings.end());
            for (std::size_t i = 0; i + 1 < crossings.size(); i += 2) {
                const int x_start = std::max(0, static_cast<int>(std::ceil(crossings[i])));
                const int x_end =
                    std::min(static_cast<int>(width_) - 1,
                             static_cast<int>(std::floor(crossings[i + 1])));
                for (int x = x_start; x <= x_end; ++x) {
                    blend(x, y, color, alpha);
                }
            }
        }
    }

    void draw_ring(const std::vector<std::pair<double, double>>& ring, Rgb color,
                   double alpha) {
        for (std::size_t i = 0; i + 1 < ring.size(); ++i) {
            draw_line(ring[i].first, ring[i].second, ring[i + 1].first, ring[i + 1].second,
                      color, alpha);
        }
    }

private:
    // Bounded narrowing for pixel anchors (inputs are pre-clamped by
    // WorldToScreen; the clamp keeps the cast well-defined regardless).
    static int safe_int(double v) {
        return static_cast<int>(std::clamp(v, -1.0e9, 1.0e9));
    }

    std::uint32_t width_;
    std::uint32_t height_;
    std::vector<std::uint8_t> pixels_;
};

struct WorldToScreen {
    double min_x = 0, min_y = 0, max_x = 1, max_y = 1;
    std::uint32_t width = 1, height = 1;

    // Screen coordinates are clamped to a generous band around the canvas
    // (double space) before any int narrowing happens downstream — feature
    // coordinates far outside the document extent are invisible anyway, and
    // an unclamped cast of a 1e20 world coordinate would be UB.
    static constexpr double kClamp = 1.0e6;

    std::pair<double, double> apply(double x, double y) const {
        const double span_x = max_x - min_x;
        const double span_y = max_y - min_y;
        const double raw_sx =
            span_x != 0.0 ? (x - min_x) / span_x * static_cast<double>(width - 1)
                          : static_cast<double>(width - 1) / 2.0;
        // North up: screen y grows downwards.
        const double raw_sy =
            span_y != 0.0 ? (max_y - y) / span_y * static_cast<double>(height - 1)
                          : static_cast<double>(height - 1) / 2.0;
        const double sx = std::clamp(raw_sx, -kClamp, static_cast<double>(width) + kClamp);
        const double sy = std::clamp(raw_sy, -kClamp, static_cast<double>(height) + kClamp);
        return {sx, sy};
    }
};

std::optional<std::pair<double, double>> coord_xy(const Json& coord) {
    if (!coord.is_array() || coord.size() < 2 || !coord[0].is_number() ||
        !coord[1].is_number()) {
        return std::nullopt;
    }
    return std::make_pair(coord[0].get<double>(), coord[1].get<double>());
}

std::vector<std::pair<double, double>> parse_ring(const Json& coordinates) {
    std::vector<std::pair<double, double>> ring;
    if (!coordinates.is_array()) return ring;
    for (const auto& c : coordinates) {
        if (auto xy = coord_xy(c)) ring.push_back(*xy);
    }
    return ring;
}

void draw_geometry(const Json& geometry, const WorldToScreen& transform, Canvas& canvas,
                   Rgb fill, Rgb stroke, double alpha) {
    if (!geometry.is_object()) return;
    const auto type_it = geometry.find("type");
    const auto coords_it = geometry.find("coordinates");
    if (type_it == geometry.end() || coords_it == geometry.end()) return;
    const std::string type = type_it->is_string() ? type_it->get<std::string>() : "";

    if (type == "Point") {
        if (auto xy = coord_xy(*coords_it)) {
            const auto [sx, sy] = transform.apply(xy->first, xy->second);
            canvas.fill_disc(sx, sy, 3, fill, alpha);
        }
    } else if (type == "MultiPoint") {
        if (!coords_it->is_array()) return;
        for (const auto& c : *coords_it) {
            if (auto xy = coord_xy(c)) {
                const auto [sx, sy] = transform.apply(xy->first, xy->second);
                canvas.fill_disc(sx, sy, 3, fill, alpha);
            }
        }
    } else if (type == "LineString") {
        const auto ring = parse_ring(*coords_it);
        for (std::size_t i = 0; i + 1 < ring.size(); ++i) {
            const auto [x0, y0] = transform.apply(ring[i].first, ring[i].second);
            const auto [x1, y1] = transform.apply(ring[i + 1].first, ring[i + 1].second);
            canvas.draw_line(x0, y0, x1, y1, stroke, alpha);
        }
    } else if (type == "MultiLineString") {
        if (!coords_it->is_array()) return;
        for (const auto& part : *coords_it) {
            const auto ring = parse_ring(part);
            for (std::size_t i = 0; i + 1 < ring.size(); ++i) {
                const auto [x0, y0] = transform.apply(ring[i].first, ring[i].second);
                const auto [x1, y1] = transform.apply(ring[i + 1].first, ring[i + 1].second);
                canvas.draw_line(x0, y0, x1, y1, stroke, alpha);
            }
        }
    } else if (type == "Polygon") {
        std::vector<std::vector<std::pair<double, double>>> rings;
        if (coords_it->is_array()) {
            for (const auto& ring_coords : *coords_it) {
                rings.push_back(parse_ring(ring_coords));
            }
        }
        std::vector<std::vector<std::pair<double, double>>> screen_rings;
        for (const auto& ring : rings) {
            std::vector<std::pair<double, double>> screen;
            for (const auto& [wx, wy] : ring) {
                screen.push_back(transform.apply(wx, wy));
            }
            screen_rings.push_back(std::move(screen));
        }
        canvas.fill_polygon_rings(screen_rings, fill, alpha);
        for (const auto& ring : screen_rings) canvas.draw_ring(ring, stroke, alpha);
    } else if (type == "MultiPolygon") {
        if (!coords_it->is_array()) return;
        for (const auto& polygon : *coords_it) {
            std::vector<std::vector<std::pair<double, double>>> screen_rings;
            if (polygon.is_array()) {
                for (const auto& ring_coords : polygon) {
                    std::vector<std::pair<double, double>> screen;
                    for (const auto& [wx, wy] : parse_ring(ring_coords)) {
                        screen.push_back(transform.apply(wx, wy));
                    }
                    screen_rings.push_back(std::move(screen));
                }
            }
            canvas.fill_polygon_rings(screen_rings, fill, alpha);
            for (const auto& ring : screen_rings) canvas.draw_ring(ring, stroke, alpha);
        }
    }
}

// Render the visible layers in painter order onto a white background.
std::vector<std::uint8_t> render_document(const pwb::mapping_document::MapDocument& doc,
                                          std::uint32_t width, std::uint32_t height) {
    Canvas canvas(width, height);
    WorldToScreen transform;
    transform.min_x = doc.extent[0];
    transform.min_y = doc.extent[1];
    transform.max_x = doc.extent[2];
    transform.max_y = doc.extent[3];
    transform.width = width;
    transform.height = height;

    for (const auto& layer : doc.layers) {
        if (!layer.visible) continue;
        Rgb fill;    // Python layers.py default fill="#22b8a7"
        Rgb stroke;  // renderer default stroke="#26364d"
        if (layer.style.is_object()) {
            if (layer.style.contains("fill")) parse_hex_color(layer.style.at("fill"), &fill);
            if (layer.style.contains("stroke")) {
                parse_hex_color(layer.style.at("stroke"), &stroke);
            }
        }
        const double alpha = std::clamp(layer.opacity, 0.0, 1.0);
        if (!layer.features.is_array()) continue;
        for (const auto& feature : layer.features) {
            if (!feature.is_object() || !feature.contains("geometry")) continue;
            draw_geometry(feature.at("geometry"), transform, canvas, fill, stroke, alpha);
        }
    }
    return std::vector<std::uint8_t>(canvas.data(), canvas.data() + canvas.size());
}

}  // namespace

MapThumbnailProvider::MapThumbnailProvider() {
    descriptor_.provider_id = "export.map_thumbnail";
    descriptor_.family = ProviderFamily::Exporter;
    descriptor_.version = "1.0.0";
    descriptor_.build_identity = kBuildIdentity;
    descriptor_.display_name = "图件缩略图导出（示例）";
    descriptor_.description =
        "Render a MapDocument through the native software rasterizer to a "
        "workspace-contained PNG thumbnail; verifies the artifact is a real "
        "PNG after render.";
    descriptor_.capabilities = {"export", "thumbnail"};
    descriptor_.input_types = {"MapDocumentRef", "MapDocument"};
    descriptor_.output_types = {"PathRef"};
    Json output_path;
    output_path["type"] = "string";
    output_path["description"] = "PNG 输出路径（工作区内相对路径）";
    Json width;
    width["type"] = "integer";
    width["minimum"] = 64;
    width["maximum"] = 4096;
    Json height = width;
    descriptor_.parameters_schema = Json::object();
    descriptor_.parameters_schema["type"] = "object";
    descriptor_.parameters_schema["properties"] = Json::object();
    descriptor_.parameters_schema["properties"]["output_path"] = output_path;
    descriptor_.parameters_schema["properties"]["width"] = width;
    descriptor_.parameters_schema["properties"]["height"] = height;
    descriptor_.parameters_schema["required"] = Json::array({"output_path"});
    descriptor_.parameters_schema["additionalProperties"] = false;
    descriptor_.resource_profile.estimated_cpu_cores = 1.0;
    descriptor_.resource_profile.estimated_ram_bytes = 256LL * 1024 * 1024;
    descriptor_.resource_profile.io_weight = 1.0;
    descriptor_.resource_profile.category = "export";
    descriptor_.threading_model = "worker_thread";
    descriptor_.deterministic = true;
}

ProviderResult MapThumbnailProvider::execute(const ProviderInputs& inputs,
                                             const Json& parameters,
                                             ProviderContext& context) {
    const TypedInput* document_input = inputs.find("document");
    std::optional<TypedInput> resolved_storage;
    if (document_input != nullptr && document_input->type_name == "MapDocumentRef") {
        // The input named "document" may still arrive as a ref: resolve it
        // through the context's document table like "map_document".
        std::string document_id;
        if (document_input->payload.is_object() &&
            document_input->payload.contains("document_id") &&
            document_input->payload.at("document_id").is_string()) {
            document_id = document_input->payload.at("document_id").get<std::string>();
        }
        if (context.extras.is_object() && context.extras.contains("map_documents") &&
            context.extras.at("map_documents").is_object() &&
            context.extras.at("map_documents").contains(document_id)) {
            resolved_storage =
                TypedInput{"MapDocument", context.extras.at("map_documents").at(document_id)};
            document_input = &*resolved_storage;
        }
    }
    if (document_input == nullptr) {
        const TypedInput* ref_input = inputs.find("map_document");
        if (ref_input != nullptr) {
            std::string document_id;
            if (ref_input->payload.is_object() &&
                ref_input->payload.contains("document_id") &&
                ref_input->payload.at("document_id").is_string()) {
                document_id = ref_input->payload.at("document_id").get<std::string>();
            }
            if (context.extras.is_object() && context.extras.contains("map_documents") &&
                context.extras.at("map_documents").is_object() &&
                context.extras.at("map_documents").contains(document_id)) {
                resolved_storage = TypedInput{
                    "MapDocument", context.extras.at("map_documents").at(document_id)};
                document_input = &*resolved_storage;
            }
        }
    }
    if (document_input == nullptr || document_input->type_name != "MapDocument" ||
        !document_input->payload.is_object()) {
        const std::string actual =
            document_input != nullptr ? document_input->type_name : "NoneType";
        throw ProviderRejectedInputError(
            descriptor().provider_id,
            "input 'document' must be a MapDocument or MapDocumentRef, got " + actual);
    }

    const std::string output_path = parameters.at("output_path").get<std::string>();
    const std::filesystem::path out_path =
        resolve_contained_output(context, output_path, descriptor().provider_id);
    std::error_code ec;
    std::filesystem::create_directories(out_path.parent_path(), ec);

    const pwb::mapping_document::MapDocument document =
        pwb::mapping_document::parse_map_document(document_input->payload);
    const int width = parameters.contains("width") && parameters.at("width").is_number()
                          ? parameters.at("width").get<int>()
                          : 640;
    const int height = parameters.contains("height") && parameters.at("height").is_number()
                           ? parameters.at("height").get<int>()
                           : 480;

    const std::vector<std::uint8_t> raster =
        render_document(document, static_cast<std::uint32_t>(width),
                        static_cast<std::uint32_t>(height));
    std::string error;
    if (!png::write_rgb(out_path, static_cast<std::uint32_t>(width),
                        static_cast<std::uint32_t>(height), raster.data(), raster.size(),
                        &error)) {
        throw ProviderRejectedInputError(descriptor().provider_id,
                                         "PNG encoder could not write " +
                                             out_path.filename().generic_string() +
                                             " (" + error + ")");
    }

    ProviderResult result;
    ArtifactRef artifact;
    artifact.name = out_path.filename().generic_string();
    artifact.kind = "file";
    artifact.path = out_path.generic_string();
    artifact.metadata = Json::object();
    artifact.metadata["width"] = width;
    artifact.metadata["height"] = height;
    result.artifacts.push_back(std::move(artifact));
    std::uint64_t bytes = 0;
    if (std::filesystem::exists(out_path, ec)) {
        bytes = static_cast<std::uint64_t>(std::filesystem::file_size(out_path, ec));
    }
    result.diagnostics = Json::object();
    result.diagnostics["bytes"] = bytes;
    return result;
}

std::optional<Verification> MapThumbnailProvider::verify(const ProviderResult& result,
                                                         ProviderContext& /*context*/) {
    // Fail-closed: the artifact must be a real, non-empty PNG.
    if (result.artifacts.empty()) {
        Verification v;
        v.verdict = "fail";
        v.reasons = {"no artifact produced"};
        return v;
    }
    for (const auto& artifact : result.artifacts) {
        if (!artifact.path.has_value()) {
            Verification v;
            v.verdict = "fail";
            v.reasons = {"thumbnail artifact has no path"};
            return v;
        }
        const std::filesystem::path path(*artifact.path);
        std::error_code ec;
        if (!std::filesystem::exists(path, ec) ||
            std::filesystem::file_size(path, ec) < kPngMagic.size() + 8) {
            Verification v;
            v.verdict = "fail";
            v.reasons = {artifact.name + " is not a plausible PNG"};
            return v;
        }
        std::ifstream in(path, std::ios::binary);
        std::array<char, 8> head{};
        in.read(head.data(), static_cast<std::streamsize>(head.size()));
        const auto as_unsigned = [](char c) {
            return static_cast<unsigned char>(c);
        };
        if (!std::equal(head.begin(), head.end(), kPngMagic.begin(),
                        [as_unsigned](char a, std::uint8_t b) {
                            return as_unsigned(a) == b;
                        })) {
            Verification v;
            v.verdict = "fail";
            v.reasons = {artifact.name + " lacks the PNG signature"};
            return v;
        }
    }
    return Verification{};
}

}  // namespace pwb::providers
