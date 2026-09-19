#include <pwb/ui_composite/topology_service.hpp>

#include <pwb/ui_composite/geometry.hpp>
#include <pwb/ui_composite/topology_checker.hpp>

#include <cmath>
#include <set>

namespace pwb::ui_composite {
namespace {

// 送入验证引擎判有效性的几何类型（点/多点不在校验范围）。
bool is_checkable_type(const Json& geometry) {
    if (!geometry.is_object()) {
        return false;
    }
    auto it = geometry.find("type");
    if (it == geometry.end() || !it->is_string()) {
        return false;
    }
    static const std::set<std::string> types = {
        "Polygon", "MultiPolygon", "LineString", "MultiLineString",
    };
    return types.count(it->get<std::string>()) != 0;
}

std::string str_or_empty(const Json& object, const char* key) {
    if (!object.is_object()) {
        return {};
    }
    auto it = object.find(key);
    if (it == object.end() || it->is_null()) {
        return {};
    }
    return it->is_string() ? it->get<std::string>() : it->dump();
}

Json issue_record(const std::string& layer_id,
                  const std::string& feature_id,
                  const std::string& message) {
    return {{"severity", "error"},
            {"layer_id", layer_id},
            {"feature_id", feature_id},
            {"message", message}};
}

}  // namespace

struct TopologyService::Impl {
    std::unique_ptr<TopologyChecker> checker =
        std::make_unique<TopologyChecker>();
    // layer_id → (data_revision, session_revision, count, session 身份)
    std::map<std::string,
             std::tuple<int64_t, int64_t, int, const VectorEditSession*>>
        error_counts;
};

TopologyService::TopologyService(bool enabled_flag)
    : enabled(enabled_flag), impl_(std::make_unique<Impl>()) {}

TopologyService::~TopologyService() = default;
TopologyService::TopologyService(TopologyService&&) noexcept = default;
TopologyService& TopologyService::operator=(TopologyService&&) noexcept =
    default;

TopologyChecker& TopologyService::checker() { return *impl_->checker; }

const TopologyChecker& TopologyService::checker() const {
    return *impl_->checker;
}

void TopologyService::set_validate_fn(GeometryValidateFn fn) {
    validate_ = std::move(fn);
}

void TopologyService::set_validate_many_fn(GeometryValidateManyFn fn) {
    validate_many_ = std::move(fn);
}

void TopologyService::record_validation(const VectorLayer& layer,
                                        int error_count) {
    const VectorEditSession* session = layer.edit_session();
    impl_->error_counts[layer.id()] = std::make_tuple(
        layer.data_revision,
        session != nullptr ? session->revision : int64_t{-1},
        std::max(0, error_count), session);
}

int TopologyService::refresh_error_count(const VectorLayer& layer) {
    const int count = static_cast<int>(validate({&layer}).size());
    record_validation(layer, count);
    return count;
}

int TopologyService::cached_error_count(
    const std::vector<const VectorLayer*>& layers) const {
    int total = 0;
    for (const VectorLayer* layer : layers) {
        if (layer == nullptr) {
            continue;
        }
        const VectorEditSession* session = layer->edit_session();
        if (session == nullptr) {
            continue;
        }
        auto it = impl_->error_counts.find(layer->id());
        if (it != impl_->error_counts.end() &&
            std::get<3>(it->second) == session) {
            total += std::get<2>(it->second);
        }
    }
    return total;
}

void TopologyService::forget_error_count(
    const std::vector<std::string>& layer_ids) {
    for (const std::string& id : layer_ids) {
        impl_->error_counts.erase(id);
    }
}

void TopologyService::forget_all_error_counts() {
    impl_->error_counts.clear();
}

std::vector<Json> TopologyService::validate(
    const std::vector<const VectorLayer*>& layers) const {
    std::vector<Json> issues;
    for (const VectorLayer* layer : layers) {
        if (layer == nullptr) {
            continue;
        }
        const VectorEditSession* session = layer->edit_session();
        const std::vector<VectorFeature> features =
            session != nullptr ? session->features() : layer->features();
        Json records = Json::array();
        for (const VectorFeature& feature : features) {
            records.push_back({
                {"feature_id", feature.feature_id},
                {"geometry",
                 feature.as_record().value("geometry", Json::object())},
            });
        }
        std::vector<Json> recs;
        for (const Json& record : records) {
            recs.push_back(record);
        }
        auto layer_issues = validate_records(layer->id(), recs);
        issues.insert(issues.end(), layer_issues.begin(),
                      layer_issues.end());
    }
    return issues;
}

std::vector<Json> TopologyService::validate_records(
    const std::string& layer_id,
    const std::vector<Json>& records) const {
    std::vector<Json> issues;
    if (!validate_) {
        return {Json{{"severity", "error"},
                     {"layer_id", layer_id},
                     {"feature_id", ""},
                     {"code", "validator_unavailable"},
                     {"message",
                      "拓扑检查需要 QGIS 桥或 Shapely/GEOS，当前均不可用"}}};
    }
    // Batch probe: engine supports validate_many → one call replaces N
    // per-record round-trips; shape mismatch or throw degrades the whole
    // batch to per-record (Python P2-2/P2-6 discipline).
    std::map<size_t, std::vector<std::string>> messages_by_index;
    bool bridge_failed = false;
    if (validate_many_) {
        std::vector<std::pair<size_t, Json>> batch;
        for (size_t i = 0; i < records.size(); ++i) {
            auto it = records[i].find("geometry");
            if (it != records[i].end() && is_checkable_type(*it)) {
                batch.emplace_back(i, *it);
            }
        }
        if (!batch.empty()) {
            try {
                std::vector<Json> geometries;
                for (const auto& [index, geometry] : batch) {
                    geometries.push_back(geometry);
                }
                auto results = validate_many_(geometries);
                if (results.size() != batch.size()) {
                    throw std::runtime_error(
                        "validate_many returned mismatched shape");
                }
                for (size_t i = 0; i < batch.size(); ++i) {
                    messages_by_index[batch[i].first] =
                        std::move(results[i]);
                }
            } catch (...) {
                messages_by_index.clear();
                bridge_failed = true;
            }
        }
    }
    for (size_t index = 0; index < records.size(); ++index) {
        const Json& record = records[index];
        const std::string feature_id = str_or_empty(record, "feature_id");
        auto geom_it = record.find("geometry");
        if (geom_it == record.end() || !geom_it->is_object()) {
            continue;
        }
        const Json& geometry = *geom_it;
        if (is_checkable_type(geometry)) {
            std::vector<std::string> messages;
            auto found = messages_by_index.find(index);
            if (found != messages_by_index.end()) {
                messages = found->second;
            } else if (!bridge_failed) {
                try {
                    messages = validate_(geometry);
                } catch (...) {
                    // 引擎失败必须可诊断且只报一次（P2-2/P2-6）。
                    bridge_failed = true;
                    messages = {"geometry validation engine failed"};
                }
            } else {
                messages = {"geometry validation engine failed"};
            }
            for (const std::string& message : messages) {
                issues.push_back(
                    issue_record(layer_id, feature_id, message));
            }
        }
        auto type_it = geometry.find("type");
        if (type_it != geometry.end() && type_it->is_string() &&
            type_it->get<std::string>() == "Polygon") {
            auto coords_it = geometry.find("coordinates");
            if (coords_it != geometry.end() && coords_it->is_array()) {
                int ring_index = 0;
                for (const Json& ring : *coords_it) {
                    std::vector<MapPoint> points;
                    if (ring.is_array()) {
                        for (const Json& node : ring) {
                            if (auto point = json_point(node)) {
                                points.push_back(*point);
                            }
                        }
                    }
                    if (points.size() < 4 ||
                        points.front() != points.back()) {
                        issues.push_back(issue_record(
                            layer_id, feature_id,
                            "polygon ring " + std::to_string(ring_index) +
                                " is not closed"));
                    }
                    ++ring_index;
                }
            }
        }
    }
    return issues;
}

Json repair_invalid_geometry(const Json& geometry,
                             const GeometryRepairFn& backend) {
    if (!geometry.is_object()) {
        return geometry;
    }
    auto type_it = geometry.find("type");
    if (type_it == geometry.end() || !type_it->is_string()) {
        return geometry;
    }
    const std::string type = type_it->get<std::string>();
    if (type != "Polygon" && type != "MultiPolygon") {
        return geometry;
    }
    Json repaired = geometry;
    // First ensure ring closure in coordinates.
    auto coords_it = repaired.find("coordinates");
    if (type == "Polygon" && coords_it != repaired.end() &&
        coords_it->is_array()) {
        Json fixed = Json::array();
        for (const Json& ring : *coords_it) {
            if (ring.is_array() && ring.size() >= 3) {
                Json r = ring;
                if (r.front() != r.back()) {
                    r.push_back(r.front());
                }
                fixed.push_back(std::move(r));
            } else {
                fixed.push_back(ring);
            }
        }
        repaired["coordinates"] = std::move(fixed);
    }
    if (backend) {
        try {
            return backend(repaired);
        } catch (...) {
            return repaired;
        }
    }
    return repaired;
}

}  // namespace pwb::ui_composite
