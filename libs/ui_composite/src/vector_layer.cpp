#include "pwb/ui_composite/vector_layer.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <random>
#include <stdexcept>

#include <pwb/domain/sha256.hpp>
#include <pwb/ui_data_core/map_edit_geometry.hpp>

namespace pwb::ui_composite {

namespace {

[[noreturn]] void fail_value(const std::string& message) {
    throw std::invalid_argument(message);
}

[[noreturn]] void fail_key(const std::string& message) {
    throw std::out_of_range(message);
}

bool is_numeric_leaf(const Json& value) {
    return value.is_number() || value.is_boolean();
}

// _point parity (strict): [x, y] finite numbers; throws otherwise.
MapPoint strict_point(const Json& value) {
    if (!value.is_array() || value.size() < 2)
        fail_value("coordinate must contain x and y");
    const Json& jx = value[0];
    const Json& jy = value[1];
    if (jx.is_array() || jy.is_array() ||
        (!is_numeric_leaf(jx)) || (!is_numeric_leaf(jy)))
        fail_value("coordinate must contain x and y");
    double x = jx.is_boolean() ? (jx.get<bool>() ? 1.0 : 0.0)
                               : jx.get<double>();
    double y = jy.is_boolean() ? (jy.get<bool>() ? 1.0 : 0.0)
                               : jy.get<double>();
    if (!std::isfinite(x) || !std::isfinite(y))
        fail_value("coordinate must be finite");
    return {x, y};
}

Json validate_node(const Json& value) {
    // Leaf coordinate pair?
    if (value.is_array() && value.size() >= 2 && !value[0].is_array() &&
        !value[1].is_array()) {
        const MapPoint p = strict_point(value);
        return Json::array({p[0], p[1]});
    }
    if (!value.is_array())
        fail_value("geometry coordinates must be nested arrays");
    Json out = Json::array();
    for (const auto& item : value)
        out.push_back(validate_node(item));
    return out;
}

Json translate_node(const Json& value, double dx, double dy) {
    if (value.is_array() && value.size() >= 2 && !value[0].is_array() &&
        !value[1].is_array()) {
        const MapPoint p = strict_point(value);
        return Json::array({p[0] + dx, p[1] + dy});
    }
    if (!value.is_array())
        fail_value("invalid geometry coordinates");
    Json out = Json::array();
    for (const auto& item : value)
        out.push_back(translate_node(item, dx, dy));
    return out;
}

// _path_parent parity: descend path[:-1], return (parent ref, last index).
// Throws out_of_range for out-of-geometry paths.
Json& path_parent(Json& coordinates, const std::vector<int>& path,
                  bool allow_append, int& index_out) {
    if (path.empty())
        fail_value("vertex path is required");
    Json* current = &coordinates;
    for (size_t depth = 0; depth + 1 < path.size(); ++depth) {
        const int index = path[depth];
        if (!current->is_array() || index < 0 ||
            index >= static_cast<int>(current->size()))
            throw std::out_of_range("vertex path is outside the geometry");
        current = &(*current)[index];
    }
    const int last = path.back();
    const int limit =
        static_cast<int>(current->size()) + (allow_append ? 1 : 0);
    if (!current->is_array() || last < 0 || last >= limit)
        throw std::out_of_range("vertex path is outside the geometry");
    index_out = last;
    return *current;
}

bool closed_ring(const Json& parent) {
    if (!parent.is_array() || parent.size() < 4)
        return false;
    const Json& first = parent[0];
    const Json& last = parent[parent.size() - 1];
    return first.is_array() && first == last;
}

bool is_ring_context(const std::string& kind, const std::vector<int>& path) {
    if (kind == "Polygon")
        return path.size() == 2;
    if (kind == "MultiPolygon")
        return path.size() == 3;
    return false;
}

std::string uuid_hex(size_t digits) {
    static std::mt19937_64 rng(std::random_device{}());
    static const char* kHex = "0123456789abcdef";
    std::string out;
    out.reserve(digits);
    while (out.size() < digits) {
        const uint64_t value = rng();
        for (int nib = 0; nib < 16 && out.size() < digits; ++nib)
            out.push_back(kHex[(value >> (nib * 4)) & 0xF]);
    }
    return out;
}

double now_seconds() {
    return std::chrono::duration<double>(
               std::chrono::system_clock::now().time_since_epoch())
        .count();
}

const std::map<std::string, std::string>& command_operation_table() {
    static const std::map<std::string, std::string> table = {
        {"add_feature", edit_ops::kCreateFeature},
        {"duplicate_feature", edit_ops::kCreateFeature},
        {"move_feature", edit_ops::kMoveFeature},
        {"set_vertex", edit_ops::kMoveVertex},
        {"insert_vertex", edit_ops::kMoveVertex},
        {"delete_vertex", edit_ops::kMoveVertex},
        {"delete_feature", edit_ops::kDeleteFeature},
        {"split_feature", edit_ops::kSplitFeature},
        {"merge_features", edit_ops::kMergeFeatures},
        {"set_geometry", edit_ops::kReplaceGeometry},
        {"add_ring", edit_ops::kReplaceGeometry},
        {"delete_ring", edit_ops::kReplaceGeometry},
        {"fill_ring", edit_ops::kReplaceGeometry},
        {"add_part", edit_ops::kReplaceGeometry},
        {"delete_part", edit_ops::kReplaceGeometry},
        {"move_part", edit_ops::kReplaceGeometry},
        {"change_attribute", edit_ops::kUpdateAttributes},
    };
    return table;
}

}  // namespace

// ---------------------------------------------------------------------------
// VectorFeature
// ---------------------------------------------------------------------------

Json validate_geometry(const Json& geometry) {
    if (!geometry.is_object())
        fail_value("geometry must be an object");
    const std::string kind = geometry.value("type", Json("")).get<std::string>();
    static const std::set<std::string> kinds = {
        "Point",      "MultiPoint",      "LineString",
        "MultiLineString", "Polygon", "MultiPolygon",
    };
    if (!kinds.count(kind))
        fail_value("unsupported geometry type " + kind);
    const auto it = geometry.find("coordinates");
    if (it == geometry.end())
        fail_value("geometry coordinates are required");
    return {{"type", kind}, {"coordinates", validate_node(*it)}};
}

VectorFeature::VectorFeature(std::string fid, Json geom, Json attrs)
    : feature_id(std::move(fid)),
      geometry(validate_geometry(geom)),
      attributes(attrs.is_object() ? std::move(attrs) : Json::object()) {
    if (feature_id.empty())
        fail_value("feature_id is required");
}

Json VectorFeature::as_record() const {
    return {{"id", feature_id},
            {"geometry", geometry},
            {"properties", attributes}};
}

// ---------------------------------------------------------------------------
// EditCommand
// ---------------------------------------------------------------------------

std::vector<std::string> EditCommand::feature_ids() const {
    std::set<std::string> ids;
    for (const auto& [fid, _] : before)
        ids.insert(fid);
    for (const auto& [fid, _] : after)
        ids.insert(fid);
    return {ids.begin(), ids.end()};
}

void EditCommand::apply(std::map<std::string, VectorFeature>& target) const {
    for (const auto& [fid, feature] : after) {
        if (feature.has_value())
            target[fid] = *feature;
        else
            target.erase(fid);
    }
}

void EditCommand::revert(std::map<std::string, VectorFeature>& target) const {
    for (const auto& [fid, feature] : before) {
        if (feature.has_value())
            target[fid] = *feature;
        else
            target.erase(fid);
    }
}

Json EditCommand::audit_record() const {
    Json ids = Json::array();
    for (const auto& fid : feature_ids())
        ids.push_back(fid);
    return {{"command_type", command_type}, {"feature_ids", ids}};
}

namespace {
EditCommand simple_command(const std::string& type,
                           const VectorFeature* before,
                           const VectorFeature* after) {
    EditCommand command;
    command.command_type = type;
    if (before != nullptr)
        command.before[before->feature_id] = *before;
    if (after != nullptr)
        command.after[after->feature_id] = *after;
    return command;
}
}  // namespace

EditCommand add_feature_command(const VectorFeature& feature) {
    EditCommand command;
    command.command_type = "add_feature";
    command.before[feature.feature_id] = std::nullopt;
    command.after[feature.feature_id] = feature;
    return command;
}

EditCommand delete_feature_command(const VectorFeature& feature) {
    EditCommand command;
    command.command_type = "delete_feature";
    command.before[feature.feature_id] = feature;
    command.after[feature.feature_id] = std::nullopt;
    return command;
}

EditCommand move_feature_command(const VectorFeature& before,
                                 const VectorFeature& after) {
    return simple_command("move_feature", &before, &after);
}

EditCommand set_geometry_command(const VectorFeature& before,
                                 const VectorFeature& after) {
    return simple_command("set_geometry", &before, &after);
}

EditCommand set_vertex_command(const VectorFeature& before,
                               const VectorFeature& after) {
    return simple_command("set_vertex", &before, &after);
}

EditCommand insert_vertex_command(const VectorFeature& before,
                                  const VectorFeature& after) {
    return simple_command("insert_vertex", &before, &after);
}

EditCommand delete_vertex_command(const VectorFeature& before,
                                  const VectorFeature& after) {
    return simple_command("delete_vertex", &before, &after);
}

EditCommand change_attribute_command(const VectorFeature& before,
                                     const VectorFeature& after) {
    return simple_command("change_attribute", &before, &after);
}

EditCommand split_feature_command(
    const std::map<std::string, std::optional<VectorFeature>>& before,
    const std::map<std::string, std::optional<VectorFeature>>& after) {
    EditCommand command;
    command.command_type = "split_feature";
    command.before = before;
    command.after = after;
    return command;
}

EditCommand merge_features_command(
    const std::map<std::string, std::optional<VectorFeature>>& before,
    const std::map<std::string, std::optional<VectorFeature>>& after) {
    EditCommand command;
    command.command_type = "merge_features";
    command.before = before;
    command.after = after;
    return command;
}

EditCommand add_ring_command(const VectorFeature& before,
                             const VectorFeature& after) {
    return simple_command("add_ring", &before, &after);
}

EditCommand delete_ring_command(const VectorFeature& before,
                                const VectorFeature& after) {
    return simple_command("delete_ring", &before, &after);
}

EditCommand fill_ring_command(const VectorFeature& before,
                              const VectorFeature& after,
                              const VectorFeature& new_feature) {
    EditCommand command;
    command.command_type = "fill_ring";
    command.before[before.feature_id] = before;
    command.before[new_feature.feature_id] = std::nullopt;
    command.after[before.feature_id] = after;
    command.after[new_feature.feature_id] = new_feature;
    return command;
}

EditCommand duplicate_feature_command(const VectorFeature& feature) {
    EditCommand command;
    command.command_type = "duplicate_feature";
    command.before[feature.feature_id] = std::nullopt;
    command.after[feature.feature_id] = feature;
    return command;
}

EditCommand add_part_command(const VectorFeature& before,
                             const VectorFeature& after) {
    return simple_command("add_part", &before, &after);
}

EditCommand delete_part_command(const VectorFeature& before,
                                const VectorFeature& after) {
    return simple_command("delete_part", &before, &after);
}

EditCommand move_part_command(const VectorFeature& before,
                              const VectorFeature& after) {
    return simple_command("move_part", &before, &after);
}

// ---------------------------------------------------------------------------
// EditDelta
// ---------------------------------------------------------------------------

std::string geometry_hash(const Json& geometry) {
    if (!geometry.is_object())
        return "";
    // json.dumps(sort_keys=True) parity: pwb::domain::Json is ordered_json
    // (insertion order preserved), so round-trip through plain
    // nlohmann::json to sort object keys recursively. Separators differ
    // from Python's default dumps (", "/": "), but the hash only needs to
    // be deterministic within this authority.
    const std::string payload =
        nlohmann::json::parse(geometry.dump()).dump(-1, ' ', true);
    if (payload.empty())
        return "";
    return pwb::domain::Sha256::of_bytes(payload).substr(0, 16);
}

bool EditDelta::from_native_tool() const {
    return source_tool.size() >= 8 &&
           source_tool.compare(source_tool.size() - 8, 8, "(native)") == 0;
}

Json EditDelta::to_dict() const {
    Json selection = Json::array();
    for (const auto& fid : selection_context)
        selection.push_back(fid);
    Json related = Json::array();
    for (const auto& fid : related_feature_ids)
        related.push_back(fid);
    return {
        {"layer_id", layer_id},
        {"feature_id", feature_id},
        {"operation", operation},
        {"session_id", session_id},
        {"order", order},
        {"source_tool", source_tool},
        {"qgis_capability", qgis_capability},
        {"before_geometry_hash",
         before_geometry_hash ? Json(*before_geometry_hash) : Json(nullptr)},
        {"after_geometry",
         after_geometry ? *after_geometry : Json(nullptr)},
        {"attribute_delta",
         attribute_delta ? *attribute_delta : Json(nullptr)},
        {"selection_context", selection},
        {"related_feature_ids", related},
        {"timestamp", timestamp},
        {"contract_version", contract_version},
    };
}

std::optional<EditDelta> delta_from_command(
    const EditCommand& command, const std::string& layer_id,
    const std::string& session_id, int order, const std::string& source_tool,
    const std::string& qgis_capability,
    const std::vector<std::string>& selection_context,
    std::optional<double> timestamp) {
    const auto op_it = command_operation_table().find(command.command_type);
    if (op_it == command_operation_table().end())
        return std::nullopt;
    const std::string& operation = op_it->second;

    const VectorFeature* before_feature = nullptr;
    for (const auto& [_, value] : command.before) {
        if (value.has_value()) {
            before_feature = &*value;
            break;
        }
    }
    const VectorFeature* after_feature = nullptr;
    for (const auto& [_, value] : command.after) {
        if (value.has_value()) {
            after_feature = &*value;
            break;
        }
    }

    std::string primary_id;
    std::vector<std::string> related;
    if (command.command_type == "split_feature") {
        for (const auto& [fid, value] : command.before) {
            if (value.has_value()) {
                primary_id = fid;
                break;
            }
        }
        for (const auto& [fid, value] : command.after) {
            if (value.has_value() && fid != primary_id)
                related.push_back(fid);
        }
    } else if (command.command_type == "merge_features") {
        for (const auto& [fid, value] : command.after) {
            if (value.has_value()) {
                primary_id = fid;
                break;
            }
        }
        for (const auto& [fid, value] : command.before) {
            if (value.has_value() && fid != primary_id)
                related.push_back(fid);
        }
    } else {
        primary_id = after_feature != nullptr   ? after_feature->feature_id
                         : before_feature != nullptr ? before_feature->feature_id
                                                     : "";
    }

    std::optional<Json> after_geometry;
    if (operation != edit_ops::kUpdateAttributes && after_feature != nullptr)
        after_geometry = after_feature->geometry;

    std::optional<Json> attribute_delta;
    if (operation == edit_ops::kUpdateAttributes &&
        before_feature != nullptr && after_feature != nullptr) {
        const Json& before_attrs = before_feature->attributes;
        const Json& after_attrs = after_feature->attributes;
        std::set<std::string> keys;
        if (before_attrs.is_object())
            for (auto it = before_attrs.begin(); it != before_attrs.end(); ++it)
                keys.insert(it.key());
        if (after_attrs.is_object())
            for (auto it = after_attrs.begin(); it != after_attrs.end(); ++it)
                keys.insert(it.key());
        Json delta = Json::object();
        for (const auto& key : keys) {
            const Json before_value = before_attrs.is_object() &&
                                              before_attrs.contains(key)
                                          ? before_attrs[key]
                                          : Json(nullptr);
            const Json after_value =
                after_attrs.is_object() && after_attrs.contains(key)
                    ? after_attrs[key]
                    : Json(nullptr);
            if (before_value != after_value)
                delta[key] = Json::array({before_value, after_value});
        }
        if (!delta.empty())
            attribute_delta = delta;
    }

    EditDelta delta;
    delta.layer_id = layer_id;
    delta.feature_id = primary_id;
    delta.operation = operation;
    delta.session_id = session_id;
    delta.order = order;
    delta.source_tool = source_tool.empty() ? "command" : source_tool;
    delta.qgis_capability =
        qgis_capability.empty() ? "unavailable" : qgis_capability;
    if (before_feature != nullptr)
        delta.before_geometry_hash = geometry_hash(before_feature->geometry);
    delta.after_geometry = after_geometry;
    delta.attribute_delta = attribute_delta;
    delta.selection_context = selection_context;
    if (command.command_type == "split_feature" ||
        command.command_type == "merge_features")
        delta.related_feature_ids = std::move(related);
    delta.timestamp = timestamp.value_or(now_seconds());
    return delta;
}

// ---------------------------------------------------------------------------
// VectorLayer
// ---------------------------------------------------------------------------

VectorLayer::VectorLayer(std::string lid, std::string lname, std::string lcrs,
                         std::string lsource_ref, Json lschema,
                         std::vector<VectorFeature> features, Json lstyle,
                         Json llabels)
    : id_(std::move(lid)),
      name_(std::move(lname)),
      crs_(std::move(lcrs)),
      source_ref_(std::move(lsource_ref)),
      schema_(lschema.is_object() ? std::move(lschema) : Json::object()),
      style_(lstyle.is_object() ? std::move(lstyle) : Json::object()),
      labels_(llabels.is_object() ? std::move(llabels) : Json::object()) {
    if (id_.empty())
        fail_value("vector layer id is required");
    for (const auto& feature : features) {
        if (features_.count(feature.feature_id))
            fail_value("duplicate vector feature id " + feature.feature_id);
        features_[feature.feature_id] = feature;
    }
}

void VectorLayer::set_style(Json style) {
    style_ = style.is_object() ? std::move(style) : Json::object();
}

std::vector<std::string> VectorLayer::feature_ids() const {
    std::vector<std::string> ids;
    ids.reserve(features_.size());
    for (const auto& [fid, _] : features_)
        ids.push_back(fid);
    return ids;
}

std::vector<VectorFeature> VectorLayer::features() const {
    std::vector<VectorFeature> out;
    out.reserve(features_.size());
    for (const auto& [_, feature] : features_)
        out.push_back(feature);
    return out;
}

const VectorFeature& VectorLayer::feature(
    const std::string& feature_id) const {
    const auto it = features_.find(feature_id);
    if (it == features_.end())
        fail_key("unknown feature " + feature_id);
    return it->second;
}

bool VectorLayer::has_feature(const std::string& feature_id) const {
    return features_.count(feature_id) != 0;
}

void VectorLayer::replace_features(std::vector<VectorFeature> features) {
    features_.clear();
    for (const auto& feature : features) {
        if (features_.count(feature.feature_id))
            fail_value("duplicate vector feature id " + feature.feature_id);
        features_[feature.feature_id] = feature;
    }
}

std::set<std::string> VectorLayer::selectable_feature_ids() const {
    std::set<std::string> ids;
    if (edit_session_ != nullptr) {
        for (const auto& feature : edit_session_->features())
            ids.insert(feature.feature_id);
    } else {
        for (const auto& [fid, _] : features_)
            ids.insert(fid);
    }
    return ids;
}

std::set<std::string> VectorLayer::selection() const {
    return selection_;
}

std::set<std::string> VectorLayer::set_selection(
    const std::vector<std::string>& feature_ids) {
    const auto selectable = selectable_feature_ids();
    selection_.clear();
    for (const auto& fid : feature_ids) {
        if (selectable.count(fid))
            selection_.insert(fid);
    }
    return selection_;
}

std::set<std::string> VectorLayer::toggle_selection(
    const std::string& feature_id) {
    if (!selectable_feature_ids().count(feature_id))
        return selection_;
    if (selection_.count(feature_id))
        selection_.erase(feature_id);
    else
        selection_.insert(feature_id);
    return selection_;
}

std::set<std::string> VectorLayer::select_all() {
    const auto selectable = selectable_feature_ids();
    return set_selection({selectable.begin(), selectable.end()});
}

std::set<std::string> VectorLayer::invert_selection() {
    std::vector<std::string> inverted;
    for (const auto& fid : selectable_feature_ids()) {
        if (!selection_.count(fid))
            inverted.push_back(fid);
    }
    return set_selection(inverted);
}

void VectorLayer::set_staged_selection(
    const std::vector<std::string>& feature_ids) {
    staged_selection_ = {feature_ids.begin(), feature_ids.end()};
}

std::set<std::string> VectorLayer::staged_selection() const {
    return staged_selection_;
}

VectorEditSession& VectorLayer::start_editing() {
    if (edit_session_ == nullptr) {
        edit_session_ = std::make_unique<VectorEditSession>(*this);
        if (!staged_selection_.empty()) {
            const auto selectable = selectable_feature_ids();
            std::set<std::string> carried;
            for (const auto& fid : staged_selection_) {
                if (selectable.count(fid))
                    carried.insert(fid);
            }
            selection_ = std::move(carried);
            staged_selection_.clear();
        }
    }
    return *edit_session_;
}

void VectorLayer::commit_working(
    const std::map<std::string, VectorFeature>& working) {
    features_ = working;
    for (auto it = selection_.begin(); it != selection_.end();) {
        if (!features_.count(*it))
            it = selection_.erase(it);
        else
            ++it;
    }
    data_revision += 1;
    edit_session_ = nullptr;
}

void VectorLayer::discard_session(VectorEditSession* session) {
    if (edit_session_.get() == session) {
        edit_session_ = nullptr;
        for (auto it = selection_.begin(); it != selection_.end();) {
            if (!features_.count(*it))
                it = selection_.erase(it);
            else
                ++it;
        }
    }
}

std::vector<Json> VectorLayer::commit_audit() const {
    return commit_journal_;
}

std::vector<Json> VectorLayer::apply_committed_delta(
    const Json& delta, const std::string& session_id,
    const std::string& source_tool, const Json& gestures) {
    std::vector<Json> records;
    std::set<std::string> touched;

    auto record = [&](const std::string& command_type,
                      const std::vector<std::string>& feature_ids) {
        Json ids = Json::array();
        for (const auto& fid : feature_ids)
            ids.push_back(fid);
        Json entry = {{"command_type", command_type},
                      {"feature_ids", ids},
                      {"session_id", session_id},
                      {"source_tool", source_tool}};
        if (gestures.is_array() && !gestures.empty())
            entry["gestures"] = gestures;
        records.push_back(std::move(entry));
    };

    for (const auto& change : delta.value("geometry_changes", Json::array())) {
        const std::string fid = change.value("feature_id", Json("")).get<std::string>();
        const auto it = features_.find(fid);
        if (it == features_.end())
            continue;
        it->second = VectorFeature(
            fid, change.value("geometry", Json::object()), it->second.attributes);
        touched.insert(fid);
        record("set_geometry", {fid});
    }
    for (const auto& change : delta.value("attribute_changes", Json::array())) {
        const std::string fid = change.value("feature_id", Json("")).get<std::string>();
        const auto it = features_.find(fid);
        if (it == features_.end())
            continue;
        Json merged = it->second.attributes;
        const Json changes = change.value("changes", Json::object());
        if (changes.is_object())
            for (auto cit = changes.begin(); cit != changes.end(); ++cit)
                merged[cit.key()] = cit.value();
        it->second = VectorFeature(fid, it->second.geometry, merged);
        touched.insert(fid);
        record("change_attribute", {fid});
    }
    std::vector<std::string> removed;
    for (const auto& value : delta.value("removed", Json::array())) {
        const std::string fid = value.get<std::string>();
        if (features_.erase(fid))
            touched.insert(fid);
        removed.push_back(fid);
    }
    if (!removed.empty())
        record("delete_feature", removed);
    for (const auto& feature : delta.value("added", Json::array())) {
        Json properties = feature.value("properties", Json::object());
        std::string fid = properties.value("__pwb_fid", Json("")).get<std::string>();
        if (fid.empty())
            fid = feature.value("id", Json("")).get<std::string>();
        properties.erase("__pwb_fid");
        if (fid.empty() || features_.count(fid))
            continue;
        features_[fid] = VectorFeature(
            fid, feature.value("geometry", Json::object()), properties);
        touched.insert(fid);
        record("add_feature", {fid});
    }
    if (!touched.empty()) {
        data_revision += 1;
        for (auto it = selection_.begin(); it != selection_.end();) {
            if (!features_.count(*it))
                it = selection_.erase(it);
            else
                ++it;
        }
        commit_journal_.insert(commit_journal_.end(), records.begin(),
                               records.end());
        if (commit_journal_.size() > kCommitJournalLimit)
            commit_journal_.erase(
                commit_journal_.begin(),
                commit_journal_.begin() +
                    static_cast<long>(commit_journal_.size() -
                                      kCommitJournalLimit));
    }
    return records;
}

// ---------------------------------------------------------------------------
// VectorEditSession
// ---------------------------------------------------------------------------

VectorEditSession::VectorEditSession(VectorLayer& host)
    : layer(host), session_id(uuid_hex(32)) {
    working_ = host.features_;
}

VectorEditSession::SourceGuard::SourceGuard(VectorEditSession& session,
                                            std::string source)
    : session_(session), previous_(session.delta_source_tool_.value_or("")) {
    session_.delta_source_tool_ = std::move(source);
}

VectorEditSession::SourceGuard::~SourceGuard() {
    session_.delta_source_tool_ =
        previous_.empty() ? std::nullopt : std::optional(previous_);
}

const VectorFeature& VectorEditSession::feature(
    const std::string& feature_id) const {
    const auto it = working_.find(feature_id);
    if (it == working_.end())
        fail_key("unknown working feature " + feature_id);
    return it->second;
}

std::vector<VectorFeature> VectorEditSession::features() const {
    std::vector<VectorFeature> out;
    out.reserve(working_.size());
    for (const auto& [_, feature] : working_)
        out.push_back(feature);
    return out;
}

bool VectorEditSession::has_feature(const std::string& feature_id) const {
    return working_.count(feature_id) != 0;
}

void VectorEditSession::bump_revision(
    const std::vector<std::string>& touched) {
    revision += 1;
    journal_.emplace_back(revision, touched);
    if (journal_.size() > kSessionJournalLimit)
        journal_.erase(journal_.begin(),
                       journal_.begin() +
                           static_cast<long>(journal_.size() -
                                             kSessionJournalLimit));
}

std::optional<std::vector<std::vector<std::string>>>
VectorEditSession::changes_since(int64_t watermark) const {
    if (watermark > revision)
        return std::nullopt;
    if (watermark == revision)
        return std::vector<std::vector<std::string>>{};
    if (journal_.empty() || journal_.front().first > watermark + 1)
        return std::nullopt;
    std::vector<std::vector<std::string>> out;
    for (const auto& [entry_revision, ids] : journal_) {
        if (entry_revision > watermark)
            out.push_back(ids);
    }
    return out;
}

void VectorEditSession::begin_edit_command() {
    if (open_command_.has_value())
        throw std::runtime_error("an edit command is already open");
    open_command_ = std::vector<EditCommand>{};
    pending_deltas_ = std::vector<EditDelta>{};
}

void VectorEditSession::end_edit_command() {
    if (!open_command_.has_value())
        throw std::runtime_error("no edit command is open");
    const std::vector<EditCommand> commands = *open_command_;
    open_command_ = std::nullopt;
    const std::optional<std::vector<EditDelta>> pending = pending_deltas_;
    pending_deltas_ = std::nullopt;
    if (commands.empty())
        return;
    std::map<std::string, std::optional<VectorFeature>> before;
    std::map<std::string, std::optional<VectorFeature>> after;
    for (const auto& command : commands) {
        for (const auto& [fid, value] : command.before)
            before.emplace(fid, value);
        for (const auto& [fid, value] : command.after)
            after[fid] = value;
    }
    EditCommand compound;
    compound.command_type = "compound";
    compound.before = std::move(before);
    compound.after = std::move(after);
    record(compound, true);
    if (pending.has_value()) {
        delta_journal_.insert(delta_journal_.end(), pending->begin(),
                              pending->end());
        if (delta_journal_.size() > kDeltaJournalLimit)
            delta_journal_.erase(
                delta_journal_.begin(),
                delta_journal_.begin() +
                    static_cast<long>(delta_journal_.size() -
                                      kDeltaJournalLimit));
    }
}

void VectorEditSession::destroy_edit_command() {
    if (!open_command_.has_value())
        throw std::runtime_error("no edit command is open");
    std::set<std::string> touched;
    for (auto it = open_command_->rbegin(); it != open_command_->rend(); ++it) {
        it->revert(working_);
        for (const auto& fid : it->feature_ids())
            touched.insert(fid);
    }
    open_command_ = std::nullopt;
    pending_deltas_ = std::nullopt;
    if (touched.empty())
        return;
    bump_revision({touched.begin(), touched.end()});
}

void VectorEditSession::record_delta(const EditCommand& command) {
    const std::set<std::string>& sel = layer.selection_;
    std::vector<std::string> selection_context(sel.begin(), sel.end());
    auto delta = delta_from_command(
        command, layer.id(), session_id,
        static_cast<int>(delta_order_ + 1),
        delta_source_tool_.value_or("command"), qgis_capability_token,
        selection_context);
    if (!delta.has_value())
        return;
    delta_order_ += 1;
    if (pending_deltas_.has_value()) {
        pending_deltas_->push_back(*delta);
        return;
    }
    delta_journal_.push_back(*delta);
    if (delta_journal_.size() > kDeltaJournalLimit)
        delta_journal_.erase(delta_journal_.begin(),
                             delta_journal_.begin() +
                                 static_cast<long>(delta_journal_.size() -
                                                   kDeltaJournalLimit));
}

void VectorEditSession::record(const EditCommand& command,
                               bool already_applied) {
    if (!already_applied)
        command.apply(working_);
    if (open_command_.has_value()) {
        open_command_->push_back(command);
        record_delta(command);
        return;
    }
    undo_stack_.push_back(command);
    redo_stack_.clear();
    bump_revision(command.feature_ids());
    record_delta(command);
}

void VectorEditSession::add_feature(const VectorFeature& feature) {
    if (working_.count(feature.feature_id))
        fail_value("feature " + feature.feature_id + " already exists");
    record(add_feature_command(feature));
}

void VectorEditSession::delete_feature(const std::string& feature_id) {
    record(delete_feature_command(feature(feature_id)));
}

void VectorEditSession::move_feature(const std::string& feature_id, double dx,
                                     double dy) {
    const VectorFeature before = feature(feature_id);
    const Json moved =
        translate_node(before.geometry["coordinates"], dx, dy);
    const VectorFeature after(
        before.feature_id,
        {{"type", before.geometry["type"]}, {"coordinates", moved}},
        before.attributes);
    record(move_feature_command(before, after));
}

void VectorEditSession::set_geometry(const std::string& feature_id,
                                     const Json& geometry) {
    const VectorFeature before = feature(feature_id);
    const VectorFeature after(before.feature_id, geometry, before.attributes);
    record(set_geometry_command(before, after));
}

void VectorEditSession::set_vertex(const std::string& feature_id,
                                   const std::vector<int>& path,
                                   const Json& coordinate) {
    const VectorFeature before = feature(feature_id);
    Json geometry = before.geometry;
    const std::string kind = geometry.value("type", Json("")).get<std::string>();
    if (path.empty() && kind == "Point") {
        const MapPoint p = strict_point(coordinate);
        geometry["coordinates"] = Json::array({p[0], p[1]});
        const VectorFeature after(before.feature_id, geometry,
                                  before.attributes);
        record(set_vertex_command(before, after));
        return;
    }
    int index = 0;
    Json& parent = path_parent(geometry["coordinates"], path, false, index);
    const bool closed =
        is_ring_context(kind, path) && closed_ring(parent);
    const MapPoint p = strict_point(coordinate);
    parent[index] = Json::array({p[0], p[1]});
    if (closed) {
        if (index == 0)
            parent[parent.size() - 1] = parent[0];
        else if (index == static_cast<int>(parent.size()) - 1)
            parent[0] = parent[parent.size() - 1];
    }
    const VectorFeature after(before.feature_id, geometry, before.attributes);
    record(set_vertex_command(before, after));
}

void VectorEditSession::insert_vertex(const std::string& feature_id,
                                      const std::vector<int>& path,
                                      const Json& coordinate) {
    const VectorFeature before = feature(feature_id);
    Json geometry = before.geometry;
    const std::string kind = geometry.value("type", Json("")).get<std::string>();
    int index = 0;
    Json& parent = path_parent(geometry["coordinates"], path, true, index);
    const MapPoint p = strict_point(coordinate);
    const Json value = Json::array({p[0], p[1]});
    const bool closed =
        is_ring_context(kind, path) && closed_ring(parent);
    if (closed && index >= static_cast<int>(parent.size()) - 1)
        index = static_cast<int>(parent.size()) - 1;
    parent.insert(parent.begin() + index, value);
    if (closed && index == 0)
        parent[parent.size() - 1] = parent[0];
    const VectorFeature after(before.feature_id, geometry, before.attributes);
    record(insert_vertex_command(before, after));
}

void VectorEditSession::delete_vertex(const std::string& feature_id,
                                      const std::vector<int>& path) {
    const VectorFeature before = feature(feature_id);
    Json geometry = before.geometry;
    const std::string kind = geometry.value("type", Json("")).get<std::string>();
    int index = 0;
    Json& parent = path_parent(geometry["coordinates"], path, false, index);
    const bool closed =
        is_ring_context(kind, path) && closed_ring(parent);
    if (closed && index == static_cast<int>(parent.size()) - 1)
        index = static_cast<int>(parent.size()) - 2;
    parent.erase(parent.begin() + index);
    if (closed) {
        if (parent.size() < 4)
            fail_value("a polygon ring must keep at least three vertices");
        parent[parent.size() - 1] = parent[0];
    } else if ((kind == "LineString" || kind == "MultiLineString") &&
               parent.size() < 2) {
        fail_value("a line must keep at least two vertices");
    } else if (kind == "MultiPoint" && parent.empty()) {
        fail_value("a multipoint must keep at least one vertex");
    }
    const VectorFeature after(before.feature_id, geometry, before.attributes);
    record(delete_vertex_command(before, after));
}

void VectorEditSession::change_attribute(const std::string& feature_id,
                                         const std::string& key,
                                         const Json& value) {
    const VectorFeature before = feature(feature_id);
    Json attributes = before.attributes;
    attributes[key] = value;
    const VectorFeature after(before.feature_id, before.geometry, attributes);
    record(change_attribute_command(before, after));
}

void VectorEditSession::add_ring(const std::string& feature_id,
                                 const std::vector<MapPoint>& ring) {
    const VectorFeature before = feature(feature_id);
    if (before.geometry.value("type", Json("")).get<std::string>() != "Polygon")
        fail_value("rings can only be added to Polygon features");
    Json points = Json::array();
    for (const auto& p : ring)
        points.push_back(Json::array({p[0], p[1]}));
    if (points.size() < 3)
        fail_value("a ring needs at least three vertices");
    if (points[0] != points[points.size() - 1])
        points.push_back(points[0]);
    Json geometry = before.geometry;
    geometry["coordinates"].push_back(points);
    const VectorFeature after(before.feature_id, geometry, before.attributes);
    record(add_ring_command(before, after));
}

std::string VectorEditSession::fill_ring(const std::string& feature_id,
                                         int ring_index) {
    const VectorFeature before = feature(feature_id);
    if (before.geometry.value("type", Json("")).get<std::string>() != "Polygon")
        fail_value("rings can only be filled in Polygon features");
    const Json& rings = before.geometry["coordinates"];
    if (ring_index <= 0 || ring_index >= static_cast<int>(rings.size()))
        fail_value("only interior Polygon rings may be filled");
    Json hole = rings[ring_index];
    if (hole.size() < 4)
        fail_value("ring needs at least three vertices");
    if (hole[0] != hole[hole.size() - 1])
        hole.push_back(hole[0]);
    Json geometry = before.geometry;
    geometry["coordinates"].erase(geometry["coordinates"].begin() + ring_index);
    const VectorFeature after(before.feature_id, geometry, before.attributes);
    const VectorFeature new_feature(
        "fill_" + pwb::ui_data_core::new_feature_id("feature"),
        {{"type", "Polygon"}, {"coordinates", Json::array({hole})}},
        before.attributes);
    record(fill_ring_command(before, after, new_feature));
    return new_feature.feature_id;
}

void VectorEditSession::delete_ring(const std::string& feature_id,
                                    int ring_index) {
    const VectorFeature before = feature(feature_id);
    if (before.geometry.value("type", Json("")).get<std::string>() != "Polygon")
        fail_value("rings can only be deleted from Polygon features");
    Json geometry = before.geometry;
    Json& rings = geometry["coordinates"];
    if (ring_index <= 0 || ring_index >= static_cast<int>(rings.size()))
        fail_value("only interior Polygon rings may be deleted");
    rings.erase(rings.begin() + ring_index);
    const VectorFeature after(before.feature_id, geometry, before.attributes);
    record(delete_ring_command(before, after));
}

VectorFeature VectorEditSession::duplicate_feature(
    const std::string& feature_id, const std::string& new_feature_id) {
    const VectorFeature source = feature(feature_id);
    if (!new_feature_id.empty() && working_.count(new_feature_id))
        fail_value("feature " + new_feature_id + " already exists");
    const std::string fid = new_feature_id.empty()
                                ? source.feature_id + "-copy-" + uuid_hex(8)
                                : new_feature_id;
    const VectorFeature duplicate(fid, source.geometry, source.attributes);
    record(duplicate_feature_command(duplicate));
    return duplicate;
}

void VectorEditSession::add_part(const std::string& feature_id,
                                 const Json& geometry) {
    const VectorFeature before = feature(feature_id);
    const VectorFeature after(before.feature_id, geometry, before.attributes);
    record(add_part_command(before, after));
}

void VectorEditSession::delete_part(const std::string& feature_id,
                                    const Json& geometry) {
    const VectorFeature before = feature(feature_id);
    const VectorFeature after(before.feature_id, geometry, before.attributes);
    record(delete_part_command(before, after));
}

void VectorEditSession::move_part(const std::string& feature_id,
                                  int part_index, double dx, double dy) {
    const VectorFeature before = feature(feature_id);
    Json geometry = before.geometry;
    const std::string kind = geometry.value("type", Json("")).get<std::string>();
    if (kind != "MultiPoint" && kind != "MultiLineString" &&
        kind != "MultiPolygon")
        fail_value("moving a part requires a multipart geometry");
    Json& parts = geometry["coordinates"];
    if (part_index < 0 || part_index >= static_cast<int>(parts.size()))
        throw std::out_of_range("part index is outside the geometry");
    if (kind == "MultiPolygon") {
        Json translated = Json::array();
        for (const auto& ring : parts[part_index])
            translated.push_back(translate_node(ring, dx, dy));
        parts[part_index] = translated;
    } else {
        parts[part_index] = translate_node(parts[part_index], dx, dy);
    }
    const VectorFeature after(before.feature_id, geometry, before.attributes);
    record(move_part_command(before, after));
}

void VectorEditSession::split_feature(
    const std::string& feature_id,
    const std::vector<VectorFeature>& replacements) {
    const VectorFeature before_feature = feature(feature_id);
    if (replacements.size() < 2)
        fail_value("splitting requires at least two replacement features");
    std::set<std::string> ids;
    for (const auto& feature : replacements)
        ids.insert(feature.feature_id);
    if (ids.size() != replacements.size())
        fail_value("split replacement feature ids must be unique");
    for (const auto& feature : replacements) {
        if (working_.count(feature.feature_id) &&
            feature.feature_id != feature_id)
            fail_value("split replacement feature id already exists");
    }
    std::map<std::string, std::optional<VectorFeature>> before;
    std::map<std::string, std::optional<VectorFeature>> after;
    before[feature_id] = before_feature;
    after[feature_id] = std::nullopt;
    for (const auto& feature : replacements) {
        before.emplace(feature.feature_id, std::nullopt);
        after[feature.feature_id] = feature;
    }
    record(split_feature_command(before, after));
}

void VectorEditSession::merge_features(
    const std::vector<std::string>& feature_ids,
    const VectorFeature& merged) {
    std::vector<std::string> ids;
    for (const auto& fid : feature_ids) {
        if (std::find(ids.begin(), ids.end(), fid) == ids.end())
            ids.push_back(fid);
    }
    if (ids.size() < 2)
        fail_value("merging requires at least two features");
    std::map<std::string, std::optional<VectorFeature>> before;
    for (const auto& fid : ids)
        before[fid] = feature(fid);
    if (working_.count(merged.feature_id) &&
        !before.count(merged.feature_id))
        fail_value("merged feature id already exists");
    std::map<std::string, std::optional<VectorFeature>> after;
    for (const auto& fid : ids)
        after[fid] = std::nullopt;
    before.emplace(merged.feature_id, std::nullopt);
    after[merged.feature_id] = merged;
    record(merge_features_command(before, after));
}

bool VectorEditSession::undo() {
    if (undo_stack_.empty() || open_command_.has_value())
        return false;
    EditCommand command = undo_stack_.back();
    undo_stack_.pop_back();
    command.revert(working_);
    redo_stack_.push_back(command);
    bump_revision(command.feature_ids());
    for (auto it = layer.selection_.begin(); it != layer.selection_.end();) {
        if (!working_.count(*it))
            it = layer.selection_.erase(it);
        else
            ++it;
    }
    return true;
}

bool VectorEditSession::redo() {
    if (redo_stack_.empty() || open_command_.has_value())
        return false;
    EditCommand command = redo_stack_.back();
    redo_stack_.pop_back();
    command.apply(working_);
    undo_stack_.push_back(command);
    bump_revision(command.feature_ids());
    for (auto it = layer.selection_.begin(); it != layer.selection_.end();) {
        if (!working_.count(*it))
            it = layer.selection_.erase(it);
        else
            ++it;
    }
    return true;
}

void VectorEditSession::commit_changes() {
    if (open_command_.has_value())
        throw std::runtime_error(
            "cannot commit while an edit command is open");
    layer.commit_working(working_);
}

void VectorEditSession::rollback_changes() {
    open_command_ = std::nullopt;
    working_ = layer.features_;
    undo_stack_.clear();
    redo_stack_.clear();
    delta_journal_.clear();
    pending_deltas_ = std::nullopt;
    bump_revision();
    journal_.clear();
    layer.discard_session(this);
}

std::vector<Json> VectorEditSession::audit_history() const {
    std::vector<Json> out;
    out.reserve(undo_stack_.size());
    for (const auto& command : undo_stack_)
        out.push_back(command.audit_record());
    return out;
}

}  // namespace pwb::ui_composite
