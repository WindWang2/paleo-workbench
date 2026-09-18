#include <pwb/mapping_document/document_io.hpp>

#include <cerrno>
#include <cstdio>
#include <cstring>
#include <ctime>
#include <stdexcept>
#include <utility>

#if defined(_POSIX_VERSION) || defined(__unix__) || defined(__APPLE__)
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
#define PWB_HAVE_POSIX 1
#endif

#include <pwb/domain/json.hpp>

#include "python_compat.hpp"

namespace pwb::mapping_document {

namespace {

using detail::py_float;
using detail::py_truthy;

bool is_py_list(const Json& value) { return value.is_array(); }

bool is_py_mapping(const Json& value) { return value.is_object(); }

// Python bool-ness of a JSON scalar for `or` chains / isinstance checks.
bool py_scalar_number(const Json& value) {
    return value.is_number() || value.is_boolean();
}

double point_coordinate(const Json& value) { return py_float(value); }

// Python dict(v) copies; JSON assignment deep-copies.
Json dict_copy(const Json& value) {
    return value.is_object() ? value : Json::object();
}

void warn(DocumentIoDiagnostics* diagnostics, const std::string& message) {
    if (diagnostics != nullptr) diagnostics->warnings.push_back(message);
}

std::string json_repr(const Json& value) {
    if (value.is_string()) return "'" + value.get<std::string>() + "'";
    return value.dump();
}

// ---------------------------------------------------------------------------
// geometry_schema helpers
// ---------------------------------------------------------------------------

bool is_point_value(const Json& value) {
    // _is_point: list/tuple of >=2, [0]/[1] not containers, numbers only
    // (Python bools are ints and count).
    if (!value.is_array() || value.size() < 2) return false;
    if (value[0].is_array() || value[0].is_object()) return false;
    if (value[1].is_array() || value[1].is_object()) return false;
    return py_scalar_number(value[0]) && py_scalar_number(value[1]);
}

// _coerce_ring: a ring of [x, y] float pairs, closed; non-point entries
// invalidate the whole ring (→ []).
Json coerce_ring(const Json& value) {
    Json ring = Json::array();
    if (!value.is_array()) return ring;
    for (const Json& point : value) {
        if (!is_point_value(point)) return Json::array();
        Json pair = Json::array();
        pair.push_back(point_coordinate(point[0]));
        pair.push_back(point_coordinate(point[1]));
        ring.push_back(pair);
    }
    if (!ring.empty()) {
        const Json& first = ring[0];
        const Json& last = ring[ring.size() - 1];
        if (first != last) ring.push_back(first);
    }
    return ring;
}

// canonical_facies_geometry: (type, polygons → rings → points).
void canonical_facies_geometry(const Json& raw, std::string& geometry_type,
                               std::vector<Json>& polygons) {
    Json geometry = raw.contains("geometry") && is_py_mapping(raw.at("geometry"))
                        ? raw.at("geometry")
                        : Json::object();
    // Python `geometry.get("coordinates") if geometry else raw.get(...)`: an
    // empty geometry dict is FALSY — coordinates come from the raw record;
    // a non-empty geometry owns the coordinates (missing → []).
    Json coordinates = Json::array();
    if (is_py_mapping(geometry) && !geometry.empty()) {
        if (geometry.contains("coordinates") && !geometry.at("coordinates").is_null()) {
            coordinates = geometry.at("coordinates");
        }
    } else if (raw.contains("coordinates") && !raw.at("coordinates").is_null()) {
        coordinates = raw.at("coordinates");
    }
    // geometry_type: declared value or sniffed shape; Python `str(x or "")`.
    std::string declared;
    if (raw.contains("geometry_type") && py_truthy(raw.at("geometry_type"))) {
        declared = detail::py_str(raw.at("geometry_type"));
    } else if (is_py_mapping(geometry) && geometry.contains("type")
               && py_truthy(geometry.at("type"))) {
        declared = detail::py_str(geometry.at("type"));
    }
    geometry_type = declared;

    const bool coordinates_is_list = is_py_list(coordinates);
    if (geometry_type != "Polygon" && geometry_type != "MultiPolygon") {
        if (coordinates_is_list && !coordinates.empty()) {
            const Json& first = coordinates[0];
            if (is_point_value(first)) {
                geometry_type = "Polygon";
            } else if (first.is_array() && !first.empty() && is_point_value(first[0])) {
                geometry_type = "Polygon";
            } else {
                geometry_type = "MultiPolygon";
            }
        } else {
            geometry_type = "Polygon";
        }
    }

    std::vector<Json> source_polygons;
    if (geometry_type == "Polygon") {
        // Python: source_polygons = [[coordinates]] when the payload is a
        // bare point list (one polygon, the coordinates ARE the single
        // ring); otherwise [[*coordinates]] (one polygon whose rings are
        // the coordinate entries).
        Json polygon = Json::array();
        if (coordinates_is_list && !coordinates.empty()
            && is_point_value(coordinates[0])) {
            polygon.push_back(coordinates);
        } else if (coordinates_is_list) {
            for (const Json& ring : coordinates) polygon.push_back(ring);
        }
        source_polygons.push_back(std::move(polygon));
    } else if (coordinates_is_list) {
        for (const Json& polygon : coordinates) source_polygons.push_back(polygon);
    }

    for (const Json& source_polygon : source_polygons) {
        if (!source_polygon.is_array()) continue;
        Json rings = Json::array();
        for (const Json& source_ring : source_polygon) {
            Json ring = coerce_ring(source_ring);
            if (!ring.empty()) rings.push_back(std::move(ring));
        }
        if (!rings.empty()) polygons.push_back(std::move(rings));
    }
}

// compact_facies_coordinates: keep the historic single-ring shape.
Json compact_facies_coordinates(const std::string& geometry_type,
                                const std::vector<Json>& polygons) {
    Json out = Json::array();
    if (geometry_type == "Polygon") {
        const Json rings = !polygons.empty() ? polygons[0] : Json::array();
        if (rings.size() == 1) {
            for (const Json& point : rings[0]) out.push_back(point);
        } else {
            for (const Json& ring : rings) out.push_back(ring);
        }
        return out;
    }
    for (const Json& polygon : polygons) out.push_back(polygon);
    return out;
}

std::string string_or(const Json& object, const char* key) {
    if (!object.is_object() || !object.contains(key)) return "";
    const Json& value = object.at(key);
    if (value.is_null()) return "";
    if (value.is_string()) return value.get<std::string>();
    return detail::py_str(value);
}

bool has_non_null(const Json& object, const char* key) {
    return object.is_object() && object.contains(key)
           && !object.at(key).is_null();
}

}  // namespace

// ---------------------------------------------------------------------------
// FeatureIdGenerator
// ---------------------------------------------------------------------------

FeatureIdGenerator::FeatureIdGenerator() {
    generator_ = [this](const std::string& prefix) {
        char buffer[32];
        std::snprintf(buffer, sizeof(buffer), "%s_%012llx", prefix.c_str(),
                      static_cast<unsigned long long>(counter_++));
        return std::string(buffer);
    };
}

FeatureIdGenerator::FeatureIdGenerator(
    std::function<std::string(const std::string& prefix)> generator)
    : generator_(std::move(generator)) {}

std::string FeatureIdGenerator::new_id(const std::string& prefix) {
    return generator_(prefix);
}

// ---------------------------------------------------------------------------
// normalize_* ports
// ---------------------------------------------------------------------------

Json normalize_facies_record(const Json& raw, FeatureIdGenerator& ids) {
    if (!is_py_mapping(raw)) {
        throw std::invalid_argument("normalize_facies: record must be an object");
    }
    std::string geometry_type;
    std::vector<Json> polygons;
    canonical_facies_geometry(raw, geometry_type, polygons);

    Json canonical_coordinates = Json::array();
    if (geometry_type == "Polygon" && !polygons.empty()) {
        canonical_coordinates = polygons[0];
    } else {
        for (const Json& polygon : polygons) canonical_coordinates.push_back(polygon);
    }
    const Json props = has_non_null(raw, "properties") && is_py_mapping(raw.at("properties"))
                           ? raw.at("properties")
                           : Json::object();

    // name = raw.name or raw.facies or raw.label or props.* or ""
    std::string name;
    for (const Json* source :
         {raw.contains("name") ? &raw.at("name") : nullptr,
          raw.contains("facies") ? &raw.at("facies") : nullptr,
          raw.contains("label") ? &raw.at("label") : nullptr,
          props.contains("name") ? &props.at("name") : nullptr,
          props.contains("facies") ? &props.at("facies") : nullptr,
          props.contains("label") ? &props.at("label") : nullptr}) {
        if (source == nullptr) continue;
        if (py_truthy(*source)) {
            name = detail::py_str(*source);
            break;
        }
    }

    Json out = Json::object();
    std::string id;
    if (has_non_null(raw, "id") && py_truthy(raw.at("id"))) {
        id = detail::py_str(raw.at("id"));
    } else if (has_non_null(props, "id") && py_truthy(props.at("id"))) {
        id = detail::py_str(props.at("id"));
    } else if (has_non_null(props, "region_id") && py_truthy(props.at("region_id"))) {
        id = detail::py_str(props.at("region_id"));
    } else {
        id = ids.new_id("facies");
    }
    out["id"] = id;
    out["kind"] = "facies";
    out["name"] = name;
    out["coordinates"] = compact_facies_coordinates(geometry_type, polygons);
    out["geometry_type"] = geometry_type;
    Json geometry = Json::object();
    geometry["type"] = geometry_type;
    geometry["coordinates"] = canonical_coordinates;
    out["geometry"] = geometry;

    Json style;
    if (has_non_null(raw, "style") && is_py_mapping(raw.at("style"))) {
        style = raw.at("style");
    } else if (has_non_null(props, "style") && is_py_mapping(props.at("style"))) {
        style = props.at("style");
    } else {
        style = Json::object();
    }
    out["style"] = style;

    // facies = raw.facies or props.facies or name; kept when truthy.
    {
        Json facies;
        bool have = false;
        if (has_non_null(raw, "facies") && py_truthy(raw.at("facies"))) {
            facies = raw.at("facies");
            have = true;
        } else if (has_non_null(props, "facies") && py_truthy(props.at("facies"))) {
            facies = props.at("facies");
            have = true;
        } else if (!name.empty()) {
            facies = name;
            have = true;
        }
        if (have) out["facies"] = facies;
    }
    if (has_non_null(raw, "probability")) {
        out["probability"] = raw.at("probability");
    } else if (has_non_null(props, "probability")) {
        out["probability"] = props.at("probability");
    }
    if (has_non_null(raw, "region_id")) {
        out["region_id"] = raw.at("region_id");
    } else if (has_non_null(props, "region_id")) {
        out["region_id"] = props.at("region_id");
    }
    if (!props.empty()) {
        Json kept = Json::object();
        for (auto it = props.begin(); it != props.end(); ++it) {
            if (it.key() == "style") continue;
            kept[it.key()] = it.value();
        }
        if (!kept.empty()) out["properties"] = kept;
    }
    return out;
}

Json normalize_well_record(const Json& raw, FeatureIdGenerator& ids) {
    if (!is_py_mapping(raw)) {
        throw std::invalid_argument("normalize_well: record must be an object");
    }
    bool have_x = false;
    bool have_y = false;
    double x = 0.0;
    double y = 0.0;
    const bool has_coordinates = raw.contains("coordinates")
                                 && is_py_list(raw.at("coordinates"));
    if (has_coordinates && raw.at("coordinates").size() >= 2) {
        try {
            x = py_float(raw.at("coordinates")[0]);
            y = py_float(raw.at("coordinates")[1]);
            have_x = have_y = true;
        } catch (const std::exception&) {
            have_x = have_y = false;
        }
    }
    if (!have_x || !have_y) {
        // Whole CRS-consistent scalar families: (x, y) → (lng, lat) →
        // (lon, lat). Never cross-paired.
        for (const auto& [x_key, y_key] :
             {std::pair<const char*, const char*>{"x", "y"},
              {"lng", "lat"}, {"lon", "lat"}}) {
            if (!has_non_null(raw, x_key) || !has_non_null(raw, y_key)) continue;
            try {
                x = py_float(raw.at(x_key));
                y = py_float(raw.at(y_key));
                have_x = have_y = true;
                break;
            } catch (const std::exception&) {
                continue;
            }
        }
    }
    if ((!have_x || !have_y) && has_coordinates
        && raw.at("coordinates").size() == 1) {
        try {
            x = py_float(raw.at("coordinates")[0]);
            have_x = true;
        } catch (const std::exception&) {
            have_x = false;
        }
    }
    const bool ok = have_x && have_y;
    Json out = Json::object();
    out["id"] = has_non_null(raw, "id") && py_truthy(raw.at("id"))
                    ? detail::py_str(raw.at("id"))
                    : ids.new_id("well");
    out["kind"] = "well";
    out["name"] = !string_or(raw, "name").empty() ? string_or(raw, "name")
                  : !string_or(raw, "well_name").empty() ? string_or(raw, "well_name")
                                                         : std::string();
    Json coordinates = Json::array();
    coordinates.push_back(have_x ? x : 0.0);
    coordinates.push_back(have_y ? y : 0.0);
    out["coordinates"] = coordinates;
    out["coordinate_status"] = ok ? "ok" : "invalid";
    return out;
}

Json normalize_line_record(const Json& raw, FeatureIdGenerator& ids) {
    if (!is_py_mapping(raw)) {
        throw std::invalid_argument("normalize_line: record must be an object");
    }
    Json coordinates = Json::array();
    if (has_non_null(raw, "coordinates") && is_py_list(raw.at("coordinates"))) {
        for (const Json& point : raw.at("coordinates")) {
            // Python [list(p) for p in coords]: arrays copy, scalars wrap.
            if (point.is_array()) {
                coordinates.push_back(point);
            } else {
                Json single = Json::array();
                single.push_back(point);
                coordinates.push_back(std::move(single));
            }
        }
    }
    Json out = Json::object();
    out["id"] = has_non_null(raw, "id") && py_truthy(raw.at("id"))
                    ? detail::py_str(raw.at("id"))
                    : ids.new_id("line");
    out["kind"] = "line";
    out["name"] = string_or(raw, "name");
    out["coordinates"] = coordinates;
    return out;
}

Json normalize_label_record(const Json& raw, FeatureIdGenerator& ids) {
    if (!is_py_mapping(raw)) {
        throw std::invalid_argument("normalize_label: record must be an object");
    }
    double ax = 0.0;
    double ay = 0.0;
    if (raw.contains("anchor")) {
        const Json& anchor = raw.at("anchor");
        if (!is_py_list(anchor) || anchor.size() < 2) {
            throw std::invalid_argument(
                "label anchor must have >= 2 coordinate elements, got "
                + json_repr(anchor));
        }
        ax = py_float(anchor[0]);
        ay = py_float(anchor[1]);
    } else {
        ax = raw.contains("x") && !raw.at("x").is_null() ? py_float(raw.at("x")) : 0.0;
        ay = raw.contains("y") && !raw.at("y").is_null() ? py_float(raw.at("y")) : 0.0;
    }
    Json out = Json::object();
    out["id"] = has_non_null(raw, "id") && py_truthy(raw.at("id"))
                    ? detail::py_str(raw.at("id"))
                    : ids.new_id("label");
    out["kind"] = "label";
    out["name"] = !string_or(raw, "text").empty() ? string_or(raw, "text")
                                                  : string_or(raw, "name");
    Json coordinates = Json::array();
    coordinates.push_back(ax);
    coordinates.push_back(ay);
    out["coordinates"] = coordinates;
    out["text"] = !string_or(raw, "text").empty() ? string_or(raw, "text")
                                                  : string_or(raw, "name");
    return out;
}

Json features_from_document(const Json& paleo_doc,
                            DocumentIoDiagnostics* diagnostics,
                            FeatureIdGenerator& ids) {
    Json features = Json::array();
    if (!is_py_mapping(paleo_doc)) return features;
    static constexpr std::pair<const char*, const char*> kSections[]{
        {"facies_polygons", "facies"},
        {"well_overlays", "well"},
        {"line_features", "line"},
        {"label_features", "label"},
    };
    for (const auto& [section, kind] : kSections) {
        if (!paleo_doc.contains(section) || !is_py_list(paleo_doc.at(section))) {
            continue;
        }
        for (const Json& raw : paleo_doc.at(section)) {
            Json record = is_py_mapping(raw) ? raw : Json(raw);
            try {
                if (kind == "facies") {
                    features.push_back(normalize_facies_record(record, ids));
                } else if (kind == "well") {
                    features.push_back(normalize_well_record(record, ids));
                } else if (kind == "line") {
                    features.push_back(normalize_line_record(record, ids));
                } else {
                    features.push_back(normalize_label_record(record, ids));
                }
            } catch (const std::exception& error) {
                warn(diagnostics,
                     std::string("Skipping malformed ") + kind
                         + " feature during document import: " + error.what());
            }
        }
    }
    return features;
}

void apply_features_to_document(Json& paleo_doc, const Json& features,
                                DocumentIoDiagnostics* diagnostics,
                                FeatureIdGenerator& ids) {
    Json facies = Json::array();
    Json wells = Json::array();
    Json lines = Json::array();
    Json labels = Json::array();
    if (!is_py_list(features)) {
        throw std::invalid_argument("features must be an array");
    }
    for (const Json& feature : features) {
        if (!is_py_mapping(feature)) continue;
        const std::string kind = string_or(feature, "kind");
        if (kind == "facies") {
            const Json normalized = normalize_facies_record(feature, ids);
            Json record = Json::object();
            record["id"] = string_or(feature, "id");
            record["name"] = string_or(feature, "name");
            record["coordinates"] = normalized.at("coordinates");
            record["geometry_type"] = normalized.at("geometry_type");
            record["geometry"] = normalized.at("geometry");
            record["style"] = has_non_null(feature, "style")
                                  ? dict_copy(feature.at("style"))
                                  : Json::object();
            if (has_non_null(feature, "facies")) {
                record["facies"] = feature.at("facies");
            } else if (feature.contains("name") && py_truthy(feature.at("name"))) {
                record["facies"] = feature.at("name");
            }
            if (has_non_null(feature, "probability")) {
                record["probability"] = feature.at("probability");
            }
            if (has_non_null(feature, "region_id")) {
                record["region_id"] = feature.at("region_id");
            }
            if (has_non_null(feature, "properties")
                && is_py_mapping(feature.at("properties"))
                && !feature.at("properties").empty()) {
                record["properties"] = dict_copy(feature.at("properties"));
            }
            facies.push_back(std::move(record));
        } else if (kind == "well") {
            double x = 0.0;
            double y = 0.0;
            std::string status;
            const bool has_coordinates = feature.contains("coordinates")
                                         && is_py_list(feature.at("coordinates"));
            if (has_coordinates && feature.at("coordinates").size() >= 2) {
                status = "ok";
                try {
                    x = py_float(feature.at("coordinates")[0]);
                    y = py_float(feature.at("coordinates")[1]);
                } catch (const std::exception&) {
                    status = "invalid";
                    warn(diagnostics, "well feature '" + string_or(feature, "id")
                                          + "' has non-numeric coordinates; marked invalid");
                }
            } else {
                status = has_coordinates ? "invalid" : "missing";
                if (has_coordinates) {
                    try {
                        x = py_float(feature.at("coordinates")[0]);
                    } catch (const std::exception&) {
                    }
                }
                warn(diagnostics,
                     "well feature '" + string_or(feature, "id") + "' has "
                         + std::string(status == "invalid" ? "unusable" : "no")
                         + " coordinates; marked " + status);
            }
            // Never silently upgrade a feature already flagged upstream.
            const std::string prior = string_or(feature, "coordinate_status");
            if (!prior.empty() && prior != "ok") status = prior;
            Json record = Json::object();
            record["id"] = string_or(feature, "id");
            record["name"] = string_or(feature, "name");
            record["x"] = x;
            record["y"] = y;
            record["lng"] = feature.contains("lng") ? feature.at("lng") : Json(x);
            record["lat"] = feature.contains("lat") ? feature.at("lat") : Json(y);
            if (status != "ok") record["coordinate_status"] = status;
            wells.push_back(std::move(record));
        } else if (kind == "line") {
            Json record = Json::object();
            record["id"] = string_or(feature, "id");
            record["name"] = string_or(feature, "name");
            record["coordinates"] =
                has_non_null(feature, "coordinates") ? feature.at("coordinates")
                                                     : Json::array();
            lines.push_back(std::move(record));
        } else if (kind == "label") {
            const bool has_coordinates = feature.contains("coordinates")
                                         && is_py_list(feature.at("coordinates"));
            if (!has_coordinates || feature.at("coordinates").size() < 2) {
                warn(diagnostics,
                     "skipping label feature '" + string_or(feature, "id")
                         + "': coordinates must have >= 2 elements");
                continue;
            }
            double ax = 0.0;
            double ay = 0.0;
            try {
                ax = py_float(feature.at("coordinates")[0]);
                ay = py_float(feature.at("coordinates")[1]);
            } catch (const std::exception&) {
                warn(diagnostics,
                     "skipping label feature '" + string_or(feature, "id")
                         + "': non-numeric coordinates");
                continue;
            }
            Json record = Json::object();
            record["id"] = string_or(feature, "id");
            record["text"] = !string_or(feature, "text").empty()
                                 ? string_or(feature, "text")
                                 : string_or(feature, "name");
            Json anchor = Json::array();
            anchor.push_back(ax);
            anchor.push_back(ay);
            record["anchor"] = anchor;
            labels.push_back(std::move(record));
        }
    }
    if (!is_py_mapping(paleo_doc)) paleo_doc = Json::object();
    paleo_doc["facies_polygons"] = facies;
    paleo_doc["well_overlays"] = wells;
    paleo_doc["line_features"] = lines;
    paleo_doc["label_features"] = labels;
}

// ---------------------------------------------------------------------------
// StdFileStore
// ---------------------------------------------------------------------------

namespace {

std::string parent_directory(const std::string& path) {
    const auto slash = path.find_last_of('/');
    if (slash == std::string::npos) return ".";
    if (slash == 0) return "/";
    return path.substr(0, slash);
}

void fsync_path(const std::string& path) {
#if defined(PWB_HAVE_POSIX)
    const int fd = ::open(path.c_str(), O_RDONLY);
    if (fd >= 0) {
        ::fsync(fd);
        ::close(fd);
    }
#else
    (void)path;
#endif
}

class StdFileStore final : public DocumentStore {
public:
    bool read(const std::string& path, std::string& bytes,
              std::string& error) override {
        std::FILE* file = std::fopen(path.c_str(), "rb");
        if (file == nullptr) {
            error = errno == ENOENT ? "missing" : std::strerror(errno);
            return false;
        }
        char buffer[65536];
        std::size_t got = 0;
        while ((got = std::fread(buffer, 1, sizeof(buffer), file)) > 0) {
            bytes.append(buffer, got);
        }
        const bool failed = std::ferror(file) != 0;
        std::fclose(file);
        if (failed) {
            error = "read failed";
            return false;
        }
        return true;
    }

    bool write_atomic(const std::string& path, const std::string& bytes,
                      std::string& error) override {
        // project/manager.py _write_payload: temp file in the target
        // directory, flush + fsync, main → bak, temp → main, dir fsync.
        const std::string dir = parent_directory(path);
        const std::string name = path.substr(path.find_last_of('/') + 1);
        const std::string tmp = dir + "/.pwb-" + name + "-"
                                + std::to_string(static_cast<long long>(::getpid()))
                                + "-" + std::to_string(++sequence_) + ".tmp";
        const std::string bak = path + ".bak";
        std::FILE* file = std::fopen(tmp.c_str(), "wb");
        if (file == nullptr) {
            error = "cannot create temp file " + tmp + ": " + std::strerror(errno);
            return false;
        }
        const std::size_t written = std::fwrite(bytes.data(), 1, bytes.size(), file);
        const bool flush_failed = std::fflush(file) != 0;
#if defined(PWB_HAVE_POSIX)
        if (!flush_failed) {
            const int fd = ::fileno(file);
            if (fd >= 0 && ::fsync(fd) != 0) error = "fsync failed";
        }
#endif
        std::fclose(file);
        if (written != bytes.size() || flush_failed || !error.empty()) {
            ::remove(tmp.c_str());
            if (error.empty()) error = "short write";
            return false;
        }
        // Preserve one good revision before replacing the main file.
        if (::rename(path.c_str(), bak.c_str()) != 0 && errno != ENOENT) {
            error = std::string("backup rename failed: ") + std::strerror(errno);
            ::remove(tmp.c_str());
            return false;
        }
        if (::rename(tmp.c_str(), path.c_str()) != 0) {
            error = std::string("replace failed: ") + std::strerror(errno);
            // Roll the backup forward so the main file never disappears.
            if (errno == ENOENT) ::rename(bak.c_str(), path.c_str());
            return false;
        }
        fsync_path(dir);
        return true;
    }

    bool rename(const std::string& from, const std::string& to,
                std::string& error) override {
        if (::rename(from.c_str(), to.c_str()) != 0) {
            error = std::string("rename failed: ") + std::strerror(errno);
            return false;
        }
        return true;
    }

    bool remove(const std::string& path, std::string& error) override {
        if (::remove(path.c_str()) != 0 && errno != ENOENT) {
            error = std::string("remove failed: ") + std::strerror(errno);
            return false;
        }
        return true;
    }

    bool exists(const std::string& path) override {
#if defined(PWB_HAVE_POSIX)
        struct ::stat st{};
        return ::stat(path.c_str(), &st) == 0;
#else
        std::FILE* probe = std::fopen(path.c_str(), "rb");
        if (probe == nullptr) return false;
        std::fclose(probe);
        return true;
#endif
    }

private:
    long long sequence_ = 0;
};

}  // namespace

std::unique_ptr<DocumentStore> make_std_file_store() {
    return std::make_unique<StdFileStore>();
}

// ---------------------------------------------------------------------------
// File-level load/save with recovery
// ---------------------------------------------------------------------------

LoadResult load_document_file(DocumentStore& store, const std::string& path,
                              DocumentIoDiagnostics* diagnostics) {
    const std::string bak = path + ".bak";
    std::string bytes;
    std::string error;
    if (!store.read(path, bytes, error)) {
        if (error == "missing") {
            // Interrupted save: main→bak completed, tmp→main did not.
            std::string bak_bytes;
            std::string bak_error;
            if (store.read(bak, bak_bytes, bak_error)) {
                try {
                    LoadResult result;
                    result.status = LoadStatus::kRecoveredFromBackup;
                    result.payload = Json::parse(bak_bytes);
                    if (diagnostics != nullptr) {
                        diagnostics->recovery_source = "backup-interrupted-save";
                        diagnostics->last_recovery =
                            "main file missing; recovered from " + bak;
                    }
                    return result;
                } catch (const std::exception&) {
                }
            }
            LoadResult result;
            result.status = LoadStatus::kCorrupt;
            result.error = "main file missing and no usable backup";
            return result;
        }
        // Permission/OSError: never fall back to the backup — an old .bak
        // must not masquerade as the newer locked main file.
        LoadResult result;
        result.status = LoadStatus::kUnreadable;
        result.error = error;
        return result;
    }
    try {
        LoadResult result;
        result.status = LoadStatus::kOk;
        result.payload = Json::parse(bytes);
        return result;
    } catch (const std::exception& parse_error) {
        std::string bak_bytes;
        std::string bak_error;
        if (!store.read(bak, bak_bytes, bak_error)) {
            LoadResult result;
            result.status = LoadStatus::kCorrupt;
            result.error = parse_error.what();
            return result;
        }
        Json recovered;
        try {
            recovered = Json::parse(bak_bytes);
        } catch (const std::exception&) {
            LoadResult result;
            result.status = LoadStatus::kCorrupt;
            result.error = parse_error.what();
            return result;
        }
        // Quarantine the corrupt main for forensics, then restore the backup.
        const std::string quarantined =
            path + ".corrupt-" + std::to_string(static_cast<long long>(::time(nullptr)));
        std::string move_error;
        store.rename(path, quarantined, move_error);
        store.rename(bak, path, move_error);
        LoadResult result;
        result.status = LoadStatus::kRecoveredCorrupt;
        result.payload = std::move(recovered);
        if (diagnostics != nullptr) {
            diagnostics->recovery_source = "backup-corrupt-main";
            diagnostics->last_recovery =
                "main file was corrupt (" + std::string(parse_error.what())
                + "); quarantined to " + quarantined + "; restored from " + bak;
        }
        return result;
    }
}

bool save_document_file(DocumentStore& store, const std::string& path,
                        const Json& payload, std::string& error) {
    return store.write_atomic(path, pwb::domain::dump_json_python_compatible(payload),
                              error);
}

// ---------------------------------------------------------------------------
// Typed wrappers + unknown-field diagnostics
// ---------------------------------------------------------------------------

namespace {

const std::vector<const char*>& composition_top_keys() {
    static const std::vector<const char*> keys{
        "id",       "title", "paper_size", "orientation", "width_mm",
        "height_mm", "dpi",   "schema_version", "elements", "metadata"};
    return keys;
}

const std::vector<const char*>& composition_element_keys() {
    static const std::vector<const char*> keys{
        "id",   "element_type", "x_mm",  "y_mm",      "width_mm",
        "height_mm", "z_index", "visible", "locked", "properties"};
    return keys;
}

const std::vector<const char*>& map_document_top_keys() {
    static const std::vector<const char*> keys{
        "id", "title", "crs", "extent", "layers", "metadata",
        "active_layer_id"};
    return keys;
}

const std::vector<const char*>& map_layer_keys() {
    static const std::vector<const char*> keys{
        "id",       "name",     "layer_type", "extent",  "crs",
        "data_revision", "style_revision", "visible", "opacity",
        "scale_range", "style", "metadata", "source_version_id",
        "features", "annotations"};
    return keys;
}

bool in_keys(const std::vector<const char*>& keys, const std::string& key) {
    for (const char* candidate : keys) {
        if (key == candidate) return true;
    }
    return false;
}

}  // namespace

void warn_unknown_fields(const Json& payload, DocumentIoDiagnostics* diagnostics) {
    if (diagnostics == nullptr || !payload.is_object()) return;
    const bool composition_like =
        payload.contains("elements") || payload.contains("paper_size");
    const std::vector<const char*>& top_keys =
        composition_like ? composition_top_keys() : map_document_top_keys();
    for (auto it = payload.begin(); it != payload.end(); ++it) {
        if (!in_keys(top_keys, it.key())) {
            warn(diagnostics, "unknown top-level key '" + it.key()
                                  + "' preserved in extras");
        }
    }
    if (composition_like) {
        if (payload.contains("elements") && payload.at("elements").is_array()) {
            for (const Json& element : payload.at("elements")) {
                if (!element.is_object()) continue;
                for (auto it = element.begin(); it != element.end(); ++it) {
                    if (!in_keys(composition_element_keys(), it.key())) {
                        warn(diagnostics,
                             "unknown element field '" + it.key()
                                 + "' preserved in extras");
                    }
                }
            }
        }
        return;
    }
    if (payload.contains("layers") && payload.at("layers").is_array()) {
        for (const Json& layer : payload.at("layers")) {
            if (!layer.is_object()) continue;
            for (auto it = layer.begin(); it != layer.end(); ++it) {
                if (!in_keys(map_layer_keys(), it.key())) {
                    warn(diagnostics, "unknown layer field '" + it.key()
                                          + "' preserved in extras");
                }
            }
        }
    }
}

LoadResult load_composition_file(DocumentStore& store, const std::string& path,
                                 Composition& out,
                                 DocumentIoDiagnostics* diagnostics) {
    LoadResult raw = load_document_file(store, path, diagnostics);
    if (raw.status == LoadStatus::kOk || raw.status == LoadStatus::kRecoveredFromBackup
        || raw.status == LoadStatus::kRecoveredCorrupt) {
        try {
            out = parse_composition(raw.payload);
            warn_unknown_fields(raw.payload, diagnostics);
        } catch (const std::exception& error) {
            raw.status = LoadStatus::kCorrupt;
            raw.error = error.what();
            raw.payload = Json();
        }
    }
    return raw;
}

bool save_composition_file(DocumentStore& store, const std::string& path,
                           const Composition& doc, std::string& error) {
    return save_document_file(store, path, dump_composition(doc), error);
}

LoadResult load_map_document_file(DocumentStore& store, const std::string& path,
                                  MapDocument& out,
                                  DocumentIoDiagnostics* diagnostics) {
    LoadResult raw = load_document_file(store, path, diagnostics);
    if (raw.status == LoadStatus::kOk || raw.status == LoadStatus::kRecoveredFromBackup
        || raw.status == LoadStatus::kRecoveredCorrupt) {
        try {
            out = parse_map_document(raw.payload);
            warn_unknown_fields(raw.payload, diagnostics);
        } catch (const std::exception& error) {
            raw.status = LoadStatus::kCorrupt;
            raw.error = error.what();
            raw.payload = Json();
        }
    }
    return raw;
}

bool save_map_document_file(DocumentStore& store, const std::string& path,
                            const MapDocument& doc, std::string& error) {
    return save_document_file(store, path, dump_map_document(doc), error);
}

}  // namespace pwb::mapping_document
