#include <pwb/mapping_document/map_document_session.hpp>

#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <utility>

#include <pwb/mapping_document/composition_session.hpp>  // UnknownElementError

namespace pwb::mapping_document {

namespace {

// The sessions define same-named members; these wrappers reach the CONV-02
// kernel free functions from inside lambdas.
inline void kernel_add_layer(MapDocument& doc, MapLayer layer,
                             std::optional<std::size_t> position) {
    add_layer(doc, std::move(layer), position);
}
inline std::optional<MapLayer> kernel_remove_layer(MapDocument& doc,
                                                   const std::string& layer_id) {
    return remove_layer(doc, layer_id);
}
inline void kernel_reorder_layers(MapDocument& doc,
                                  const std::vector<std::string>& layer_ids) {
    reorder_layers(doc, layer_ids);
}

constexpr std::array<double, 4> kSentinel{0.0, 0.0, 1.0, 1.0};

bool is_point_node(const Json& node) {
    return node.is_array() && node.size() >= 2 && node[0].is_number()
           && node[1].is_number();
}

// geometry_planar._iter_positions: yield [x, y] pairs from arbitrarily
// nested GeoJSON coordinates.
void iter_positions(const Json& node, std::vector<std::pair<double, double>>& out) {
    if (!node.is_array()) return;
    if (is_point_node(node)) {
        out.emplace_back(node[0].get<double>(), node[1].get<double>());
        return;
    }
    for (const Json& child : node) iter_positions(child, out);
}

// math.isclose(a, b) defaults: rel_tol = 1e-9, abs_tol = 0.0.
bool py_isclose(double a, double b) {
    if (std::isnan(a) || std::isnan(b)) return false;
    if (a == b) return true;
    const double diff = std::fabs(a - b);
    return diff <= 1e-9 * std::max(std::fabs(a), std::fabs(b));
}

// Document-level layer/active/extent snapshot for exact structure reverts.
struct StructureState {
    std::array<double, 4> extent;
    bool had_active;
    std::string active_id;
};

StructureState capture_structure(const MapDocument& doc) {
    return {doc.extent, doc.has_active_layer, doc.active_layer_id};
}

void restore_structure(MapDocument& doc, const StructureState& state) {
    doc.has_active_layer = state.had_active;
    doc.active_layer_id = state.active_id;
    doc.extent = state.extent;
}

}  // namespace

bool is_vector_family_layer_type(const std::string& layer_type) {
    return layer_type == "vector" || layer_type == "contour"
           || layer_type == "well_point" || layer_type == "polygon"
           || layer_type == "annotation" || layer_type == "facies"
           || layer_type == "well";
}

std::array<double, 4> recompute_layer_features_extent(const Json& features) {
    double xmin = std::numeric_limits<double>::infinity();
    double ymin = std::numeric_limits<double>::infinity();
    double xmax = -std::numeric_limits<double>::infinity();
    double ymax = -std::numeric_limits<double>::infinity();
    bool found = false;
    if (features.is_array()) {
        for (const Json& feature : features) {
            if (!feature.is_object() || !feature.contains("geometry")) continue;
            const Json& geometry = feature.at("geometry");
            if (!geometry.is_object() || !geometry.contains("coordinates")) continue;
            std::vector<std::pair<double, double>> positions;
            iter_positions(geometry.at("coordinates"), positions);
            for (const auto& [x, y] : positions) {
                found = true;
                xmin = std::min(xmin, x);
                ymin = std::min(ymin, y);
                xmax = std::max(xmax, x);
                ymax = std::max(ymax, y);
            }
        }
    }
    if (!found) return kSentinel;
    const double pad =
        std::max({1.0, std::fabs(xmin), std::fabs(ymin), std::fabs(xmax), std::fabs(ymax)})
        * 1e-6;
    if (py_isclose(xmin, xmax)) {
        xmin -= pad;
        xmax += pad;
    }
    if (py_isclose(ymin, ymax)) {
        ymin -= pad;
        ymax += pad;
    }
    return {xmin, ymin, xmax, ymax};
}

// ---------------------------------------------------------------------------
// MapDocumentEditSession
// ---------------------------------------------------------------------------

MapDocumentEditSession::MapDocumentEditSession(MapDocument& document)
    : document_(&document) {
    install_observer();
}

MapDocumentEditSession::MapDocumentEditSession(MapDocumentEditSession&& other) noexcept
    : document_(other.document_), stack_(std::move(other.stack_)),
      revisions_(other.revisions_), saved_(other.saved_) {
    install_observer();
}

MapDocumentEditSession& MapDocumentEditSession::operator=(
    MapDocumentEditSession&& other) noexcept {
    document_ = other.document_;
    stack_ = std::move(other.stack_);
    revisions_ = other.revisions_;
    saved_ = other.saved_;
    install_observer();
    return *this;
}

void MapDocumentEditSession::install_observer() {
    stack_.set_observer([this](const DocumentCommand& command, bool /*undo*/) {
        // Monotonic per-kind counters: bumped on apply and again on the
        // undo/redo of a command of that kind (a reverted state is still a
        // new state for cache consumers — revisions are never restored).
        bump(command.revision_kind());
    });
}

void MapDocumentEditSession::bump(RevisionKind kind) {
    switch (kind) {
        case RevisionKind::kData: ++revisions_.data; break;
        case RevisionKind::kStyle: ++revisions_.style; break;
        case RevisionKind::kLayout: ++revisions_.layout; break;
    }
}

bool MapDocumentEditSession::is_dirty() const {
    return revisions_.data != saved_.data || revisions_.style != saved_.style
           || revisions_.layout != saved_.layout;
}

MapLayer& MapDocumentEditSession::layer_ref(const std::string& layer_id) {
    if (MapLayer* layer = find_layer(*document_, layer_id)) return *layer;
    // Python has no session on MapDocument; unknown ids to a mutator are a
    // C++ contract: fail loud like the composition session's KeyError.
    throw UnknownElementError("no map layer '" + layer_id + "'");
}

void MapDocumentEditSession::add_layer(MapLayer layer,
                                       std::optional<std::size_t> position) {
    const StructureState old = capture_structure(*document_);
    const std::string id = layer.id;
    stack_.execute(std::make_unique<LambdaCommand>(
        "add_layer", RevisionKind::kLayout,
        // Copy in: redo must be able to re-add the layer after undo removed it.
        [this, layer, position]() { kernel_add_layer(*document_, layer, position); },
        [this, id, old]() {
            kernel_remove_layer(*document_, id);
            restore_structure(*document_, old);
        }));
}

std::optional<MapLayer> MapDocumentEditSession::remove_layer(
    const std::string& layer_id) {
    MapLayer* layer = find_layer(*document_, layer_id);
    if (layer == nullptr) return std::nullopt;
    const std::size_t index =
        static_cast<std::size_t>(layer - document_->layers.data());
    const StructureState old = capture_structure(*document_);
    const MapLayer removed = *layer;  // copy: revert re-inserts it
    stack_.execute(std::make_unique<LambdaCommand>(
        "remove_layer", RevisionKind::kLayout,
        [this, layer_id]() { kernel_remove_layer(*document_, layer_id); },
        [this, removed, index, old]() {
            auto& layers = document_->layers;
            const std::size_t at = std::min(index, layers.size());
            layers.insert(layers.begin() + static_cast<std::ptrdiff_t>(at), removed);
            restore_structure(*document_, old);
        }));
    return removed;
}

void MapDocumentEditSession::reorder_layers(
    const std::vector<std::string>& layer_ids) {
    // The kernel reorder is deterministic on the layer multiset: undo
    // restores the captured prior order, redo re-applies the reorder to it.
    const std::vector<MapLayer> prior = document_->layers;
    stack_.execute(std::make_unique<LambdaCommand>(
        "reorder_layers", RevisionKind::kLayout,
        [this, layer_ids]() { kernel_reorder_layers(*document_, layer_ids); },
        [this, prior]() { document_->layers = prior; }));
}

void MapDocumentEditSession::set_active_layer(const std::string& layer_id) {
    layer_ref(layer_id);  // unknown id refusal before any capture
    const bool old_had = document_->has_active_layer;
    const std::string old_id = document_->active_layer_id;
    stack_.execute(std::make_unique<LambdaCommand>(
        "set_active_layer", RevisionKind::kLayout,
        [this, layer_id]() {
            document_->has_active_layer = true;
            document_->active_layer_id = layer_id;
        },
        [this, old_had, old_id]() {
            document_->has_active_layer = old_had;
            document_->active_layer_id = old_id;
        }));
}

void MapDocumentEditSession::clear_active_layer() {
    const bool old_had = document_->has_active_layer;
    const std::string old_id = document_->active_layer_id;
    stack_.execute(std::make_unique<LambdaCommand>(
        "clear_active_layer", RevisionKind::kLayout,
        [this]() {
            document_->has_active_layer = false;
            document_->active_layer_id.clear();
        },
        [this, old_had, old_id]() {
            document_->has_active_layer = old_had;
            document_->active_layer_id = old_id;
        }));
}

void MapDocumentEditSession::set_layer_visible(const std::string& layer_id,
                                               bool visible) {
    const bool old = layer_ref(layer_id).visible;  // + unknown-id refusal
    stack_.execute(std::make_unique<LambdaCommand>(
        "set_layer_visible", RevisionKind::kStyle,
        [this, layer_id, visible]() {
            MapLayer& target = layer_ref(layer_id);
            target.visible = visible;
            ++target.style_revision;  // layers.py set_visible
        },
        [this, layer_id, old]() {
            MapLayer& target = layer_ref(layer_id);
            target.visible = old;
            ++target.style_revision;  // monotonic: never restored
        }));
}

void MapDocumentEditSession::set_layer_opacity(const std::string& layer_id,
                                               double opacity) {
    layer_ref(layer_id);  // + unknown-id refusal
    const double clamped = std::max(0.0, std::min(1.0, opacity));
    const double old = layer_ref(layer_id).opacity;
    stack_.execute(std::make_unique<LambdaCommand>(
        "set_layer_opacity", RevisionKind::kStyle,
        [this, layer_id, clamped]() {
            MapLayer& target = layer_ref(layer_id);
            target.opacity = clamped;
            ++target.style_revision;  // layers.py set_opacity
        },
        [this, layer_id, old]() {
            MapLayer& target = layer_ref(layer_id);
            target.opacity = old;
            ++target.style_revision;
        }));
}

void MapDocumentEditSession::set_layer_style(const std::string& layer_id,
                                             Json style) {
    MapLayer& layer = layer_ref(layer_id);
    if (!style.is_object() && !style.is_null()) {
        throw std::invalid_argument("layer style must be an object");
    }
    const Json old = layer.style;
    stack_.execute(std::make_unique<LambdaCommand>(
        "set_layer_style", RevisionKind::kStyle,
        [this, layer_id, style]() {
            MapLayer& target = layer_ref(layer_id);
            target.style = style;
            ++target.style_revision;
        },
        [this, layer_id, old]() {
            MapLayer& target = layer_ref(layer_id);
            target.style = old;
            ++target.style_revision;
        }));
}

void MapDocumentEditSession::set_layer_features(const std::string& layer_id,
                                                Json features) {
    MapLayer& layer = layer_ref(layer_id);
    if (!is_vector_family_layer_type(layer.layer_type)) {
        throw std::invalid_argument(
            "set_layer_features requires a vector-family layer, got '"
            + layer.layer_type + "'");
    }
    if (!features.is_array()) {
        throw std::invalid_argument("layer features must be an array");
    }
    const Json old_features = layer.features;
    const auto old_extent = layer.extent;
    const auto new_extent = recompute_layer_features_extent(features);
    stack_.execute(std::make_unique<LambdaCommand>(
        "set_layer_features", RevisionKind::kData,
        [this, layer_id, features, new_extent]() {
            MapLayer& target = layer_ref(layer_id);
            target.features = features;
            target.extent = new_extent;
            ++target.data_revision;  // layers.py set_features
        },
        [this, layer_id, old_features, old_extent]() {
            MapLayer& target = layer_ref(layer_id);
            target.features = old_features;
            target.extent = old_extent;
            ++target.data_revision;  // monotonic: never restored
        }));
}

void MapDocumentEditSession::bump_layer_data_revision(const std::string& layer_id) {
    layer_ref(layer_id);
    stack_.execute(std::make_unique<LambdaCommand>(
        "bump_data_revision", RevisionKind::kData,
        [this, layer_id]() { ++layer_ref(layer_id).data_revision; },
        [this, layer_id]() { ++layer_ref(layer_id).data_revision; }));
}

void MapDocumentEditSession::bump_layer_style_revision(const std::string& layer_id) {
    layer_ref(layer_id);
    stack_.execute(std::make_unique<LambdaCommand>(
        "bump_style_revision", RevisionKind::kStyle,
        [this, layer_id]() { ++layer_ref(layer_id).style_revision; },
        [this, layer_id]() { ++layer_ref(layer_id).style_revision; }));
}

void MapDocumentEditSession::set_title(const std::string& title) {
    const std::string old = document_->title;
    stack_.execute(std::make_unique<LambdaCommand>(
        "set_title", RevisionKind::kLayout,
        [this, title]() { document_->title = title; },
        [this, old]() { document_->title = old; }));
}

void MapDocumentEditSession::set_crs(const std::string& crs) {
    const std::string old = document_->crs;
    stack_.execute(std::make_unique<LambdaCommand>(
        "set_crs", RevisionKind::kLayout,
        [this, crs]() { document_->crs = crs; },
        [this, old]() { document_->crs = old; }));
}

void MapDocumentEditSession::set_extent(const std::array<double, 4>& extent) {
    const auto old = document_->extent;
    stack_.execute(std::make_unique<LambdaCommand>(
        "set_extent", RevisionKind::kLayout,
        [this, extent]() { document_->extent = extent; },
        [this, old]() { document_->extent = old; }));
}

void MapDocumentEditSession::set_metadata(const std::string& key, Json value) {
    const bool had = document_->metadata.is_object()
                     && document_->metadata.contains(key);
    const Json old_entry = had ? document_->metadata.at(key) : Json();
    stack_.execute(std::make_unique<LambdaCommand>(
        "set_metadata", RevisionKind::kLayout,
        [this, key, value]() {
            if (!document_->metadata.is_object()) {
                document_->metadata = Json::object();
            }
            document_->metadata[key] = value;
        },
        [this, key, had, old_entry]() {
            if (!document_->metadata.is_object()) return;
            if (had) {
                document_->metadata[key] = old_entry;
            } else {
                document_->metadata.erase(key);
            }
        }));
}

bool MapDocumentEditSession::undo() { return stack_.undo(); }
bool MapDocumentEditSession::redo() { return stack_.redo(); }
void MapDocumentEditSession::clear_history() { stack_.clear_history(); }
void MapDocumentEditSession::begin_group(const std::string& label) {
    stack_.begin_group(label);
}
void MapDocumentEditSession::end_group() { stack_.end_group(); }
void MapDocumentEditSession::rollback_group() { stack_.rollback_group(); }

}  // namespace pwb::mapping_document
