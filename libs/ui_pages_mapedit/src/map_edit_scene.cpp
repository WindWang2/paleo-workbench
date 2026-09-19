#include "pwb/ui_pages_mapedit/map_edit_scene.hpp"

#include "pwb/ui_data_core/json_util.hpp"
#include "pwb/ui_data_core/map_edit_factory.hpp"
#include "pwb/ui_data_core/map_edit_topology.hpp"
#include "pwb/ui_data_qt/map_edit_items.hpp"
#include "pwb/ui_pages_mapedit/document_features.hpp"

#include <QDateTime>
#include <QGraphicsSceneMouseEvent>
#include <QGraphicsView>
#include <QKeyEvent>
#include <QPainter>
#include <QPainterPath>
#include <QStyleOptionGraphicsItem>

#include <algorithm>
#include <cmath>
#include <set>
#include <variant>

namespace pwb::ui_pages_mapedit {
namespace {

using ui_data_core::MapPoint;
using ui_data_core::MapRing;
using ui_data_qt::FaciesPolygonItem;
using ui_data_qt::FeatureItemApi;
using ui_data_qt::LabelItem;
using ui_data_qt::LineItem;
using ui_data_qt::VertexHandleItem;
using ui_data_qt::WellPointItem;

QGraphicsItem* as_graphics(FeatureItemApi* item) {
    return dynamic_cast<QGraphicsItem*>(item);
}

// Default item factory: validate/parse via ui_data_core::item_from_record,
// then wrap the model in the matching ui_data_qt shell (the same dispatch
// map_edit_factory.item_from_record performs in Python).
FeatureItemApi* graphics_item_from_record(const domain::Json& record) {
    auto model = ui_data_core::item_from_record(record);
    if (!model) {
        return nullptr;
    }
    return std::visit(
        [](auto&& m) -> FeatureItemApi* {
            using T = std::decay_t<decltype(m)>;
            if constexpr (std::is_same_v<
                              T, ui_data_core::FaciesPolygonModel>) {
                const domain::Json geometry_coordinates =
                    m.geometry_coordinates();
                const domain::Json coordinates =
                    ui_data_core::ring_to_json(m.coordinates());
                return new FaciesPolygonItem(
                    m.feature_id, coordinates, m.name, m.style, m.extras,
                    m.geometry_type, &geometry_coordinates);
            } else if constexpr (std::is_same_v<
                                     T, ui_data_core::WellPointModel>) {
                return new WellPointItem(m.feature_id, m.x, m.y, m.name);
            } else if constexpr (std::is_same_v<T, ui_data_core::LineModel>) {
                return new LineItem(m.feature_id, m.points, m.name);
            } else {
                return new LabelItem(m.feature_id, m.x, m.y, m.text, m.name);
            }
        },
        std::move(*model));
}

// type(command).__name__ for the audit row's "op" field.
const char* command_op_name(const ui_data_core::EditCommand& command) {
    using namespace ui_data_core;
    if (dynamic_cast<const MoveCommand*>(&command)) return "MoveCommand";
    if (dynamic_cast<const VertexEditCommand*>(&command))
        return "VertexEditCommand";
    if (dynamic_cast<const RingEditCommand*>(&command))
        return "RingEditCommand";
    if (dynamic_cast<const CreateFeatureCommand*>(&command))
        return "CreateFeatureCommand";
    if (dynamic_cast<const DeleteFeatureCommand*>(&command))
        return "DeleteFeatureCommand";
    if (dynamic_cast<const PropertyChangeCommand*>(&command))
        return "PropertyChangeCommand";
    if (dynamic_cast<const BatchVertexEditCommand*>(&command))
        return "BatchVertexEditCommand";
    if (dynamic_cast<const CompositeCommand*>(&command))
        return "CompositeCommand";
    return "EditCommand";
}

// Issue dicts (flat Json objects) → QVariantList for the Qt signal.
QVariant json_to_variant(const domain::Json& value) {
    if (value.is_null()) return QVariant();
    if (value.is_boolean()) return value.get<bool>();
    if (value.is_number_integer() || value.is_number_unsigned())
        return QVariant::fromValue(value.get<long long>());
    if (value.is_number_float()) return value.get<double>();
    if (value.is_string())
        return QString::fromStdString(value.get<std::string>());
    if (value.is_array()) {
        QVariantList out;
        for (const auto& item : value) out.append(json_to_variant(item));
        return out;
    }
    QVariantMap out;
    for (const auto& [k, v] : value.items()) {
        out.insert(QString::fromStdString(k), json_to_variant(v));
    }
    return out;
}

}  // namespace

MapEditScene::MapEditScene(QObject* parent)
    : QGraphicsScene(parent),
      command_stack_(
          kCommandStackMaxDepth,
          [this](const ui_data_core::EditCommand& cmd) {
              append_edit_log(cmd, "do");
          },
          [this](const ui_data_core::EditCommand& cmd) {
              append_edit_log(cmd, "undo");
          },
          [this](const ui_data_core::EditCommand& cmd) {
              append_edit_log(cmd, "redo");
          }),
      draft_manager_(this) {
    setObjectName(QStringLiteral("MapEditScene"));
    setSceneRect(kDefaultSceneRect);
    item_from_record_fn_ = &graphics_item_from_record;
    connect(this, &QGraphicsScene::selectionChanged, this,
            [this]() { on_selection_changed(); });
}

// --- public API ---------------------------------------------------------

ui_data_qt::FeatureItemApi* MapEditScene::item_by_id(
    const std::string& feature_id) const {
    const auto it = items_by_id_.find(feature_id);
    return it != items_by_id_.end() ? it->second : nullptr;
}

void MapEditScene::set_tool(const std::string& tool_id) {
    const std::string prev = tool_;
    tool_ = tool_id.empty() ? "select" : tool_id;
    cancel_drag();
    cancel_vertex_drag();
    if ((prev == "line" || prev == "facies") && tool_ != "line" &&
        tool_ != "facies") {
        cancel_draft();
    } else if (prev != tool_ && (tool_ == "line" || tool_ == "facies")) {
        cancel_draft();
    }
    refresh_vertex_handles();
}

void MapEditScene::set_dirty(bool dirty) {
    if (dirty_ == dirty) {
        return;
    }
    dirty_ = dirty;
    emit document_dirty_changed(dirty_);
}

QStringList MapEditScene::selected_feature_ids() const {
    QStringList ids;
    for (QGraphicsItem* item : selectedItems()) {
        if (auto* api = dynamic_cast<FeatureItemApi*>(item)) {
            ids.append(QString::fromStdString(api->base().feature_id));
        }
    }
    return ids;
}

void MapEditScene::set_layer_visible(const std::string& kind, bool visible) {
    layer_visible_[kind] = visible;
    for (const auto& fid : item_order_) {
        auto* item = items_by_id_[fid];
        if (item->base().kind == kind) {
            if (auto* gi = as_graphics(item)) {
                gi->setVisible(visible);
            }
        }
    }
    // Hidden geometry must leave snap caches so pick/snap stay consistent.
    invalidate_snap_candidates();
}

bool MapEditScene::layer_is_visible(std::string_view kind) const {
    const auto it = layer_visible_.find(std::string(kind));
    return it == layer_visible_.end() ? true : it->second;
}

std::vector<domain::Json> MapEditScene::features_to_records() const {
    std::vector<domain::Json> out;
    out.reserve(item_order_.size());
    for (const auto& fid : item_order_) {
        out.push_back(items_by_id_.at(fid)->to_record());
    }
    return out;
}

std::optional<std::string> MapEditScene::hit_test_at(double x, double y,
                                                     double tolerance) {
    const double tolerance_units = tolerance * units_per_pixel();
    const auto records = hit_query_index_.query(
        x, y, tolerance_units,
        [this](std::string_view kind) { return layer_is_visible(kind); });
    return hit_test(records, x, y, tolerance_units);
}

void MapEditScene::clear_features() {
    cancel_drag();
    cancel_vertex_drag();
    draft_manager_.cancel();
    clear_vertex_handles();
    for (const auto& fid : item_order_) {
        if (auto* gi = as_graphics(items_by_id_[fid])) {
            // The scene owns feature items (removeItem alone would leak —
            // Python relied on GC).
            removeItem(gi);
            delete gi;
        }
    }
    items_by_id_.clear();
    item_order_.clear();
    topology_issue_cache_.clear();
    hit_query_index_.clear();
    invalidate_snap_candidates();
    command_stack_.clear();
    audit_payloads_.clear();
    bound_document_ = nullptr;
    set_dirty(false);
    emit command_stack_changed();
    setSceneRect(kDefaultSceneRect);
}

void MapEditScene::clear() {
    // Python clear(): clear_features() then super().clear() (drops any
    // remaining non-feature items such as a stray draft preview).
    clear_features();
    QGraphicsScene::clear();
}

void MapEditScene::load_document(domain::Json* doc) {
    clear_features();
    if (doc == nullptr) {
        return;
    }
    bound_document_ = doc;
    loading_features_ = true;
    for (const auto& record : features_from_document(*doc)) {
        FeatureItemApi* item = nullptr;
        try {
            item = item_from_record(record);
        } catch (...) {
            continue;  // Python except + continue parity
        }
        if (item == nullptr) {
            continue;
        }
        register_item(item);
    }
    loading_features_ = false;
    std::vector<IndexedItem> indexed;
    indexed.reserve(item_order_.size());
    for (const auto& fid : item_order_) {
        const auto* item = items_by_id_[fid];
        indexed.push_back(
            {item->base().feature_id, item->base().kind, item->to_record()});
    }
    hit_query_index_.rebuild(indexed);
    fit_scene_rect();
}

void MapEditScene::append_edit_log(const ui_data_core::EditCommand& command,
                                   const std::string& action) {
    if (bound_document_ == nullptr || !bound_document_->is_object()) {
        return;
    }
    domain::Json entry = domain::Json::object();
    entry["op"] = command_op_name(command);
    entry["action"] = action;
    entry["ts"] = QDateTime::currentDateTimeUtc()
                      .toString(Qt::ISODateWithMs)
                      .toStdString();
    const auto pit = audit_payloads_.find(&command);
    if (pit != audit_payloads_.end()) {
        // The map key is a raw pointer; confirm the entry still belongs to
        // this command object (addresses are recycled across commands).
        const auto owner = pit->second.owner.lock();
        if (owner && owner.get() == &command && pit->second.payload.is_object()) {
            for (const auto& [k, v] : pit->second.payload.items()) {
                entry[k] = v;
            }
        } else {
            audit_payloads_.erase(pit);
        }
    }
    auto& history = (*bound_document_)["edit_history"];
    if (!history.is_array()) {
        history = domain::Json::array();
    }
    history.push_back(std::move(entry));
    while (history.size() > kEditHistoryMax) {
        history.erase(history.begin());
    }
}

void MapEditScene::translate_features(
    const std::vector<std::string>& feature_ids, double dx, double dy) {
    std::vector<std::string> ids;
    for (const auto& fid : feature_ids) {
        if (items_by_id_.count(fid)) {
            ids.push_back(fid);
        }
    }
    if (ids.empty() || (dx == 0.0 && dy == 0.0)) {
        return;
    }
    auto cmd = std::make_shared<ui_data_core::MoveCommand>(
        ids, dx, dy,
        [this](const std::string& fid, double mx, double my) {
            apply_move_one(fid, mx, my);
        });
    audit_payloads_[cmd.get()] = {
        cmd, {{"feature_ids", ids}, {"dx", dx}, {"dy", dy}}};
    command_stack_.push(cmd);
    invalidate_snap_candidates();
    set_dirty(true);
    emit command_stack_changed();
    refresh_vertex_handles();
}

namespace {
MapRing ring_coords_of(ui_data_qt::FeatureItemApi* item, int part_index,
                       int ring_index) {
    if (auto* facies = dynamic_cast<FaciesPolygonItem*>(item)) {
        return facies->ring_coordinates(part_index, ring_index);
    }
    if (auto* line = dynamic_cast<LineItem*>(item)) {
        return line->coordinates();
    }
    return {};
}
}  // namespace

bool MapEditScene::apply_set_vertex(const std::string& feature_id, int index,
                                    double x, double y, int part_index,
                                    int ring_index) {
    auto* item = item_by_id(feature_id);
    if (!dynamic_cast<FaciesPolygonItem*>(item) &&
        !dynamic_cast<LineItem*>(item)) {
        return false;
    }
    const MapRing old = ring_coords_of(item, part_index, ring_index);
    MapRing updated = old;
    if (!set_vertex(updated, index, x, y)) {
        return false;
    }
    return push_vertex_edit(feature_id, old, updated, part_index, ring_index);
}

bool MapEditScene::apply_insert_vertex(const std::string& feature_id,
                                       int index, double x, double y,
                                       int part_index, int ring_index) {
    auto* item = item_by_id(feature_id);
    if (!dynamic_cast<FaciesPolygonItem*>(item) &&
        !dynamic_cast<LineItem*>(item)) {
        return false;
    }
    const MapRing old = ring_coords_of(item, part_index, ring_index);
    MapRing updated = old;
    if (!insert_vertex(updated, index, x, y)) {
        return false;
    }
    return push_vertex_edit(feature_id, old, updated, part_index, ring_index);
}

bool MapEditScene::apply_delete_vertex(const std::string& feature_id,
                                       int index, int part_index,
                                       int ring_index) {
    auto* item = item_by_id(feature_id);
    if (!dynamic_cast<FaciesPolygonItem*>(item) &&
        !dynamic_cast<LineItem*>(item)) {
        return false;
    }
    const MapRing old = ring_coords_of(item, part_index, ring_index);
    MapRing updated = old;
    if (!delete_vertex(updated, index)) {
        return false;
    }
    return push_vertex_edit(feature_id, old, updated, part_index, ring_index);
}

bool MapEditScene::apply_property_change(const std::string& feature_id,
                                         const std::string& key,
                                         const domain::Json& value) {
    auto* item = item_by_id(feature_id);
    if (item == nullptr || (key != "name" && key != "text")) {
        return false;
    }
    const domain::Json old = item->get_property(key);
    const std::string new_val =
        value.is_null() ? std::string() : ui_data_core::python_str(value);
    if (!old.is_null() && old.is_string() && old.get<std::string>() == new_val) {
        return false;
    }
    auto cmd = std::make_shared<ui_data_core::PropertyChangeCommand>(
        feature_id, key, old, domain::Json(new_val),
        [this](const std::string& fid, const std::string& k,
               const domain::Json& v) { apply_property(fid, k, v); });
    audit_payloads_[cmd.get()] = {
        cmd, {{"feature_id", feature_id}, {"key", key}}};
    command_stack_.push(cmd);
    set_dirty(true);
    emit command_stack_changed();
    return true;
}

std::optional<std::string> MapEditScene::create_feature(
    const domain::Json& record) {
    domain::Json rec = record;
    // Python ``str(rec.get("id") or new_feature_id(rec.get("kind") or
    // "feat"))`` — falsy id (null/0/""/False) mints a fresh id; falsy kind
    // falls back to "feat".
    std::string fid;
    if (const auto it = rec.find("id");
        it != rec.end() && ui_data_core::json_truthy(*it)) {
        fid = ui_data_core::python_str(*it);
    }
    if (fid.empty()) {
        std::string kind;
        if (const auto kit = rec.find("kind");
            kit != rec.end() && ui_data_core::json_truthy(*kit)) {
            kind = ui_data_core::python_str(*kit);
        }
        fid = ui_data_core::new_feature_id(kind.empty() ? "feat" : kind);
    }
    rec["id"] = fid;
    if (items_by_id_.count(fid)) {
        return std::nullopt;
    }
    // Validate constructible before pushing.
    FeatureItemApi* probe = item_from_record(rec);
    if (probe == nullptr) {
        return std::nullopt;
    }
    delete as_graphics(probe);  // probe is heap-built; command re-adds fresh
    auto cmd = std::make_shared<ui_data_core::CreateFeatureCommand>(
        rec,
        [this](const domain::Json& r) { add_feature_from_record(r); },
        [this](const std::string& f) { remove_feature_by_id(f); });
    audit_payloads_[cmd.get()] = {
        cmd,
        {{"feature_id", fid},
         {"record_id", ui_data_core::json_get_string(rec, "id")},
         {"record_kind", ui_data_core::json_get_string(rec, "kind")}},
    };
    command_stack_.push(cmd);
    set_dirty(true);
    emit command_stack_changed();
    return fid;
}

std::optional<std::string> MapEditScene::finish_line_draft() {
    return draft_manager_.finish_line(
        [this](const domain::Json& r) { return create_feature(r); });
}

std::optional<std::string> MapEditScene::finish_facies_draft() {
    return draft_manager_.finish_facies(
        [this](const domain::Json& r) { return create_feature(r); },
        [this](const std::string& fid) { refresh_topology(fid); });
}

void MapEditScene::refresh_topology(const std::string& feature_id) {
    if (feature_id.empty()) {
        topology_issue_cache_.clear();
    } else {
        topology_issue_cache_.erase(feature_id);
    }
    const std::vector<std::string> ids =
        feature_id.empty() ? item_order_ : std::vector{feature_id};
    for (const auto& fid : ids) {
        auto* item = item_by_id(fid);
        if (item == nullptr) {
            continue;
        }
        std::string status = "ok";
        if (auto* facies = dynamic_cast<FaciesPolygonItem*>(item)) {
            const auto issues = facies_geometry_issues(facies);
            if (!issues.empty()) {
                status = "warning";
            }
        }
        // Open polylines keep "ok" (Python V1 comment parity).
        item->base().set_topology_status(std::string_view(status));
    }
    if (feature_id.empty()) {
        apply_adjacency_warnings();
    }
    publish_topology_issues();
}

domain::Json MapEditScene::topology_issues() {
    domain::Json issues = domain::Json::array();
    std::set<std::string> live;
    for (const auto& fid : item_order_) {
        auto* item = items_by_id_[fid];
        auto* facies = dynamic_cast<FaciesPolygonItem*>(item);
        if (facies == nullptr) {
            continue;
        }
        live.insert(facies->base().feature_id);
        const auto item_issues = facies_geometry_issues(facies);
        for (const auto& issue : item_issues) {
            issues.push_back(issue);
        }
    }
    for (auto it = topology_issue_cache_.begin();
         it != topology_issue_cache_.end();) {
        if (!live.count(it->first)) {
            it = topology_issue_cache_.erase(it);
        } else {
            ++it;
        }
    }
    return issues;
}

std::pair<bool, domain::Json> MapEditScene::validate_for_save() {
    const domain::Json issues = topology_issues();
    bool ok = true;
    for (const auto& issue : issues) {
        if (issue.value("severity", "") == "error") {
            ok = false;
            break;
        }
    }
    return {ok, issues};
}

void MapEditScene::apply_adjacency_warnings() {
    std::vector<ui_data_core::FaciesPolygonModel*> facies;
    for (const auto& fid : item_order_) {
        if (auto* item = dynamic_cast<FaciesPolygonItem*>(items_by_id_[fid])) {
            facies.push_back(&item->model());
        }
    }
    // Geometry gate in world units, independent of the pixel snap tolerance.
    ui_data_core::apply_adjacency_warnings(facies, kAdjacencyGapTol);
}

domain::Json MapEditScene::rebuild_topology_forced(
    std::optional<double> snap_tol) {
    // The scene snap tolerance is screen pixels; convert it unless the
    // caller passed an explicit world-unit tolerance.
    const double tol =
        snap_tol ? *snap_tol : snap_manager_.tolerance() * units_per_pixel();
    std::vector<ui_data_core::FaciesPolygonModel*> facies;
    for (const auto& fid : item_order_) {
        if (auto* item = dynamic_cast<FaciesPolygonItem*>(items_by_id_[fid])) {
            facies.push_back(&item->model());
        }
    }
    auto plan = ui_data_core::plan_topology_rebuild(
        facies, tol,
        [this](const std::string& fid, const MapRing& ring) {
            apply_coordinates(fid, ring);
        });
    if (plan.command) {
        command_stack_.push(plan.command);
        set_dirty(true);
        emit command_stack_changed();
        refresh_vertex_handles();
    }
    refresh_topology();
    return plan.report;
}

std::optional<std::string> MapEditScene::merge_selected_facies() {
    const QStringList ids = selected_feature_ids();
    std::vector<FaciesPolygonItem*> facies;
    for (const auto& qid : ids) {
        auto* item = dynamic_cast<FaciesPolygonItem*>(
            item_by_id(qid.toStdString()));
        if (item != nullptr) {
            facies.push_back(item);
        }
    }
    if (facies.size() != 2) {
        return std::nullopt;
    }
    auto plan = ui_data_core::plan_merge_facies(
        facies[0]->model(), facies[1]->model(),
        [this](const domain::Json& r) { add_feature_from_record(r); },
        [this](const std::string& f) { remove_feature_by_id(f); },
        [](const domain::Json& r) { return ui_data_core::item_from_record(r); },
        backend_);
    if (plan.new_id && plan.command) {
        command_stack_.push(plan.command);
        set_dirty(true);
        emit command_stack_changed();
        refresh_topology(*plan.new_id);
        refresh_vertex_handles();
        return plan.new_id;
    }
    return std::nullopt;
}

std::optional<std::vector<std::string>>
MapEditScene::split_selected_facies_by_line() {
    const QStringList ids = selected_feature_ids();
    FaciesPolygonItem* poly_item = nullptr;
    LineItem* line_item = nullptr;
    int facies_count = 0, line_count = 0;
    for (const auto& qid : ids) {
        auto* item = item_by_id(qid.toStdString());
        if (auto* f = dynamic_cast<FaciesPolygonItem*>(item)) {
            poly_item = f;
            ++facies_count;
        } else if (auto* l = dynamic_cast<LineItem*>(item)) {
            line_item = l;
            ++line_count;
        }
    }
    if (facies_count != 1 || line_count != 1) {
        return std::nullopt;
    }
    auto plan = ui_data_core::plan_split_facies(
        poly_item->model(), line_item->model(),
        [this](const domain::Json& r) { add_feature_from_record(r); },
        [this](const std::string& f) { remove_feature_by_id(f); },
        [](const domain::Json& r) { return ui_data_core::item_from_record(r); },
        backend_);
    if (plan.new_ids && plan.command) {
        command_stack_.push(plan.command);
        set_dirty(true);
        emit command_stack_changed();
        for (const auto& nid : *plan.new_ids) {
            refresh_topology(nid);
        }
        refresh_vertex_handles();
        return plan.new_ids;
    }
    return std::nullopt;
}

bool MapEditScene::undo() {
    if (!command_stack_.can_undo()) {
        return false;
    }
    const bool ok = command_stack_.undo();
    if (ok) {
        invalidate_snap_candidates();
        // #894-3: undoing to the baseline clears dirty unless the depth cap
        // already dropped commands.
        set_dirty(command_stack_.can_undo() || command_stack_.overflowed());
        emit command_stack_changed();
        refresh_vertex_handles();
    }
    return ok;
}

bool MapEditScene::redo() {
    if (!command_stack_.can_redo()) {
        return false;
    }
    const bool ok = command_stack_.redo();
    if (ok) {
        invalidate_snap_candidates();
        set_dirty(command_stack_.can_undo() || command_stack_.overflowed());
        emit command_stack_changed();
        refresh_vertex_handles();
    }
    return ok;
}

// --- mouse / key interaction ----------------------------------------------

void MapEditScene::mousePressEvent(QGraphicsSceneMouseEvent* event) {
    const bool left = event->button() == Qt::LeftButton;
    if (left && (tool_ == "line" || tool_ == "facies")) {
        const auto [x, y] =
            snap_xy(event->scenePos().x(), event->scenePos().y());
        draft_manager_.append_point(x, y, tool_);
        event->accept();
        return;
    }
    if (left && tool_ == "label") {
        const auto [x, y] =
            snap_xy(event->scenePos().x(), event->scenePos().y());
        create_feature({{"id", ui_data_core::new_feature_id("label")},
                        {"kind", "label"},
                        {"name", "注记"},
                        {"text", "注记"},
                        {"coordinates", {x, y}}});
        event->accept();
        return;
    }
    if (left && tool_ == "vertex") {
        const QPointF pos = event->scenePos();
        if (auto* handle = handle_at(pos)) {
            active_vertex_index_ = handle->vertex_index;
            active_vertex_part_index_ = handle->part_index;
            active_vertex_ring_index_ = handle->ring_index;
            handle->setSelected(true);
            vertex_drag_ = true;
            vertex_drag_feature_id_ = handle->feature_id;
            vertex_drag_index_ = handle->vertex_index;
            vertex_drag_part_index_ = handle->part_index;
            vertex_drag_ring_index_ = handle->ring_index;
            vertex_drag_origin_ = QPointF(pos);
            auto* item = item_by_id(handle->feature_id);
            const MapRing coords =
                ring_coords_of(item, handle->part_index, handle->ring_index);
            const int idx = handle->vertex_index;
            if (idx >= 0 && idx < static_cast<int>(coords.size())) {
                vertex_drag_start_xy_ = coords[idx];
            } else {
                vertex_drag_start_xy_.reset();
            }
            event->accept();
            return;
        }
        // Click feature to select for vertex editing.
        auto* hit = feature_item_at(pos);
        if (hit != nullptr && (dynamic_cast<FaciesPolygonItem*>(hit) ||
                               dynamic_cast<LineItem*>(hit))) {
            auto* gi = as_graphics(hit);
            if (!gi->isSelected() || selected_feature_ids().size() != 1) {
                clearSelection();
                gi->setSelected(true);
            }
            event->accept();
            return;
        }
    }
    if (left && tool_ == "select") {
        const QPointF pos = event->scenePos();
        // Prefer geometry hit-test over the pure Qt item stack.
        const auto fid =
            hit_test_at(pos.x(), pos.y(), snap_manager_.tolerance());
        if (fid) {
            auto* item = item_by_id(*fid);
            if (auto* gi = as_graphics(item)) {
                const bool multi =
                    event->modifiers() & Qt::ShiftModifier;
                if (!multi) {
                    clearSelection();
                }
                gi->setSelected(true);
                event->accept();
                return;
            }
        } else if (!(event->modifiers() & Qt::ShiftModifier)) {
            clearSelection();
        }
    }
    if (left && tool_ == "move") {
        const QPointF pos = event->scenePos();
        auto* hit = feature_item_at(pos);
        if (hit == nullptr) {
            const auto fid =
                hit_test_at(pos.x(), pos.y(), snap_manager_.tolerance());
            hit = fid ? item_by_id(*fid) : nullptr;
        }
        if (hit != nullptr) {
            auto* gi = as_graphics(hit);
            if (gi != nullptr && !gi->isSelected()) {
                clearSelection();
                gi->setSelected(true);
            }
        }
        const QStringList ids = selected_feature_ids();
        if (!ids.isEmpty()) {
            dragging_ = true;
            drag_origin_ = QPointF(pos);
            drag_last_ = QPointF(pos);
            drag_ids_.clear();
            for (const auto& qid : ids) {
                drag_ids_.push_back(qid.toStdString());
            }
            event->accept();
            return;
        }
    }
    QGraphicsScene::mousePressEvent(event);
}

void MapEditScene::mouseMoveEvent(QGraphicsSceneMouseEvent* event) {
    if ((tool_ == "line" || tool_ == "facies") &&
        !draft_manager_.points().empty()) {
        const auto [x, y] =
            snap_xy(event->scenePos().x(), event->scenePos().y());
        draft_manager_.update_preview(x, y, tool_ == "facies");
        event->accept();
        return;
    }
    if (vertex_drag_ && tool_ == "vertex") {
        const QPointF pos = event->scenePos();
        const auto [x, y] = snap_xy(pos.x(), pos.y());
        auto* item = vertex_drag_feature_id_
                         ? item_by_id(*vertex_drag_feature_id_)
                         : nullptr;
        if ((dynamic_cast<FaciesPolygonItem*>(item) ||
             dynamic_cast<LineItem*>(item)) &&
            vertex_drag_index_) {
            MapRing coords = ring_coords_of(item, vertex_drag_part_index_,
                                            vertex_drag_ring_index_);
            if (set_vertex(coords, *vertex_drag_index_, x, y)) {
                if (auto* facies = dynamic_cast<FaciesPolygonItem*>(item)) {
                    facies->set_ring_coordinates(
                        vertex_drag_part_index_, vertex_drag_ring_index_,
                        ui_data_core::ring_to_json(coords));
                } else if (auto* line = dynamic_cast<LineItem*>(item)) {
                    line->set_coordinates(ui_data_core::ring_to_json(coords));
                }
                sync_handle_positions(item);
                // Visual preview only — index/snap refresh on release.
            }
        }
        event->accept();
        return;
    }
    if (dragging_ && tool_ == "move") {
        const QPointF pos = event->scenePos();
        const double dx = pos.x() - drag_last_.x();
        const double dy = pos.y() - drag_last_.y();
        drag_last_ = QPointF(pos);
        if (dx != 0.0 || dy != 0.0) {
            for (const auto& fid : drag_ids_) {
                auto* item = item_by_id(fid);
                if (auto* gi = as_graphics(item)) {
                    // Visual-only preview via item position; geometry
                    // commits on release.
                    gi->setPos(gi->pos() + QPointF(dx, dy));
                }
            }
        }
        event->accept();
        return;
    }
    QGraphicsScene::mouseMoveEvent(event);
}

void MapEditScene::mouseReleaseEvent(QGraphicsSceneMouseEvent* event) {
    if (vertex_drag_ && event->button() == Qt::LeftButton) {
        const auto fid = vertex_drag_feature_id_;
        const auto idx = vertex_drag_index_;
        const int part_index = vertex_drag_part_index_;
        const int ring_index = vertex_drag_ring_index_;
        const auto start = vertex_drag_start_xy_;
        const QPointF pos = event->scenePos();
        const auto [end_x, end_y] = snap_xy(pos.x(), pos.y());
        vertex_drag_ = false;
        vertex_drag_feature_id_.reset();
        vertex_drag_index_.reset();
        vertex_drag_start_xy_.reset();
        auto* item = fid ? item_by_id(*fid) : nullptr;
        if ((dynamic_cast<FaciesPolygonItem*>(item) ||
             dynamic_cast<LineItem*>(item)) &&
            idx && start) {
            if (end_x != (*start)[0] || end_y != (*start)[1]) {
                // Restore original, then commit via command for undo.
                MapRing restored =
                    ring_coords_of(item, part_index, ring_index);
                if (set_vertex(restored, *idx, (*start)[0], (*start)[1])) {
                    if (auto* facies =
                            dynamic_cast<FaciesPolygonItem*>(item)) {
                        facies->set_ring_coordinates(
                            part_index, ring_index,
                            ui_data_core::ring_to_json(restored));
                    } else if (auto* line = dynamic_cast<LineItem*>(item)) {
                        line->set_coordinates(
                            ui_data_core::ring_to_json(restored));
                    }
                    refresh_hit_entry(item);
                }
                apply_set_vertex(*fid, *idx, end_x, end_y, part_index,
                                 ring_index);
            } else {
                refresh_vertex_handles();
            }
        }
        event->accept();
        return;
    }
    if (dragging_ && event->button() == Qt::LeftButton) {
        const double total_dx = drag_last_.x() - drag_origin_.x();
        const double total_dy = drag_last_.y() - drag_origin_.y();
        const auto ids = drag_ids_;
        reset_drag_positions();
        dragging_ = false;
        drag_ids_.clear();
        if (!ids.empty() && (total_dx != 0.0 || total_dy != 0.0)) {
            translate_features(ids, total_dx, total_dy);
        }
        event->accept();
        return;
    }
    QGraphicsScene::mouseReleaseEvent(event);
}

void MapEditScene::mouseDoubleClickEvent(QGraphicsSceneMouseEvent* event) {
    const bool left = event->button() == Qt::LeftButton;
    if (left && tool_ == "line") {
        // mousePress already added the double-click point; finish the draft.
        finish_line_draft();
        event->accept();
        return;
    }
    if (left && tool_ == "facies") {
        finish_facies_draft();
        event->accept();
        return;
    }
    if (left && tool_ == "vertex") {
        const auto fid = single_editable_feature_id();
        if (fid) {
            auto* item = item_by_id(*fid);
            const bool editable = dynamic_cast<FaciesPolygonItem*>(item) ||
                                  dynamic_cast<LineItem*>(item);
            if (editable) {
                const QPointF pos = event->scenePos();
                // Prefer edge insert when not on an existing handle.
                if (handle_at(pos) == nullptr) {
                    const auto [x, y] = snap_xy(pos.x(), pos.y());
                    const auto edge = closest_edge(
                        ring_coords_of(item, 0, 0), x, y);
                    if (edge) {
                        const double edge_tol2 =
                            std::pow(kEdgeHitTol * units_per_pixel(), 2);
                        if (edge->distance2 <= edge_tol2) {
                            apply_insert_vertex(*fid,
                                                edge->edge_start_index + 1,
                                                edge->proj_x, edge->proj_y);
                            event->accept();
                            return;
                        }
                    }
                }
            }
        }
    }
    QGraphicsScene::mouseDoubleClickEvent(event);
}

void MapEditScene::keyPressEvent(QKeyEvent* event) {
    if (tool_ == "line" || tool_ == "facies") {
        if (event->key() == Qt::Key_Return || event->key() == Qt::Key_Enter) {
            if (tool_ == "line") {
                finish_line_draft();
            } else {
                finish_facies_draft();
            }
            event->accept();
            return;
        }
        if (event->key() == Qt::Key_Escape) {
            cancel_draft();
            event->accept();
            return;
        }
    }
    if (tool_ == "vertex" &&
        (event->key() == Qt::Key_Delete ||
         event->key() == Qt::Key_Backspace)) {
        const auto fid = single_editable_feature_id();
        const auto idx = active_vertex_index_;
        if (fid && idx) {
            if (apply_delete_vertex(*fid, *idx, active_vertex_part_index_,
                                    active_vertex_ring_index_)) {
                active_vertex_index_.reset();
                event->accept();
                return;
            }
        }
    }
    QGraphicsScene::keyPressEvent(event);
}

// --- internals --------------------------------------------------------------

void MapEditScene::on_selection_changed() {
    emit_selection_ids();
    refresh_vertex_handles();
}

void MapEditScene::emit_selection_ids() {
    emit selection_ids_changed(selected_feature_ids());
}

bool MapEditScene::push_vertex_edit(const std::string& feature_id,
                                    const MapRing& old_coords,
                                    const MapRing& new_coords, int part_index,
                                    int ring_index) {
    if (old_coords == new_coords) {
        return false;
    }
    auto* item = item_by_id(feature_id);
    std::shared_ptr<ui_data_core::EditCommand> cmd;
    if (dynamic_cast<FaciesPolygonItem*>(item)) {
        cmd = std::make_shared<ui_data_core::RingEditCommand>(
            feature_id, part_index, ring_index, old_coords, new_coords,
            [this](const std::string& fid, int pi, int ri,
                   const MapRing& ring) {
                apply_ring_coordinates(fid, pi, ri, ring);
            });
    } else {
        cmd = std::make_shared<ui_data_core::VertexEditCommand>(
            feature_id, old_coords, new_coords,
            [this](const std::string& fid, const MapRing& ring) {
                apply_coordinates(fid, ring);
            });
    }
    audit_payloads_[cmd.get()] = {cmd, {{"feature_id", feature_id}}};
    command_stack_.push(cmd);
    invalidate_snap_candidates();
    set_dirty(true);
    emit command_stack_changed();
    refresh_vertex_handles();
    return true;
}

void MapEditScene::apply_coordinates(const std::string& feature_id,
                                     const MapRing& coordinates) {
    auto* item = item_by_id(feature_id);
    if (auto* facies = dynamic_cast<FaciesPolygonItem*>(item)) {
        facies->set_coordinates(ui_data_core::ring_to_json(coordinates));
    } else if (auto* line = dynamic_cast<LineItem*>(item)) {
        line->set_coordinates(ui_data_core::ring_to_json(coordinates));
    } else {
        return;
    }
    refresh_hit_entry(item);
    invalidate_snap_candidates();
    refresh_topology(feature_id);
}

void MapEditScene::apply_ring_coordinates(const std::string& feature_id,
                                          int part_index, int ring_index,
                                          const MapRing& coordinates) {
    auto* item = item_by_id(feature_id);
    if (auto* facies = dynamic_cast<FaciesPolygonItem*>(item)) {
        facies->set_ring_coordinates(part_index, ring_index,
                                     ui_data_core::ring_to_json(coordinates));
        refresh_hit_entry(item);
        invalidate_snap_candidates();
        refresh_topology(feature_id);
    }
}

void MapEditScene::apply_move_one(const std::string& feature_id, double dx,
                                  double dy) {
    auto* item = item_by_id(feature_id);
    if (item == nullptr) {
        return;
    }
    item->translate_by(dx, dy);
    refresh_hit_entry(item);
}

void MapEditScene::apply_property(const std::string& feature_id,
                                  const std::string& key,
                                  const domain::Json& value) {
    auto* item = item_by_id(feature_id);
    if (item == nullptr) {
        return;
    }
    item->set_property(key, value);
}

void MapEditScene::add_feature_from_record(const domain::Json& record) {
    auto* item = item_from_record(record);
    if (item == nullptr) {
        return;
    }
    register_item(item);
}

void MapEditScene::remove_feature_by_id(const std::string& feature_id) {
    const auto it = items_by_id_.find(feature_id);
    FeatureItemApi* item = it != items_by_id_.end() ? it->second : nullptr;
    if (it != items_by_id_.end()) {
        items_by_id_.erase(it);
        item_order_.erase(
            std::remove(item_order_.begin(), item_order_.end(), feature_id),
            item_order_.end());
    }
    topology_issue_cache_.erase(feature_id);
    hit_query_index_.remove(feature_id);
    if (auto* gi = as_graphics(item)) {
        removeItem(gi);
        delete gi;
    }
    invalidate_snap_candidates();
}

void MapEditScene::register_item(FeatureItemApi* item) {
    auto* gi = as_graphics(item);
    if (gi == nullptr) {
        return;
    }
    addItem(gi);
    items_by_id_[item->base().feature_id] = item;
    item_order_.push_back(item->base().feature_id);
    if (!loading_features_) {
        refresh_hit_entry(item);
    }
    invalidate_snap_candidates();
    gi->setVisible(layer_is_visible(item->base().kind));
}

void MapEditScene::refresh_hit_entry(FeatureItemApi* item) {
    hit_query_index_.upsert(
        {item->base().feature_id, item->base().kind, item->to_record()});
}

double MapEditScene::units_per_pixel() const {
    // 1.0 when the scene has no attached view (offscreen tests / headless).
    for (QGraphicsView* view : views()) {
        const double scale = view->transform().m11();
        if (scale > 0.0) {
            return 1.0 / scale;
        }
    }
    return 1.0;
}

std::optional<std::string> MapEditScene::single_editable_feature_id() const {
    const QStringList ids = selected_feature_ids();
    if (ids.size() != 1) {
        return std::nullopt;
    }
    auto* item = item_by_id(ids.first().toStdString());
    if (dynamic_cast<FaciesPolygonItem*>(item) ||
        dynamic_cast<LineItem*>(item)) {
        return ids.first().toStdString();
    }
    return std::nullopt;
}

void MapEditScene::clear_vertex_handles() {
    for (auto* handle : vertex_handles_) {
        removeItem(handle);
        delete handle;
    }
    vertex_handles_.clear();
}

void MapEditScene::refresh_vertex_handles() {
    clear_vertex_handles();
    if (tool_ != "vertex") {
        return;
    }
    const auto fid = single_editable_feature_id();
    if (!fid) {
        return;
    }
    auto* item = item_by_id(*fid);
    struct RingAddress {
        int part_index;
        int ring_index;
        MapRing coords;
    };
    std::vector<RingAddress> addressed;
    if (auto* facies = dynamic_cast<FaciesPolygonItem*>(item)) {
        for (const auto& ra : facies->model().iter_ring_addresses()) {
            addressed.push_back({ra.part_index, ra.ring_index, ra.points});
        }
    } else if (auto* line = dynamic_cast<LineItem*>(item)) {
        addressed.push_back({0, 0, line->coordinates()});
    } else {
        return;
    }
    for (const auto& [part_index, ring_index, coords] : addressed) {
        if (coords.size() < 2) {
            continue;
        }
        const bool closed = coords.front() == coords.back();
        const std::size_t count = closed ? coords.size() - 1 : coords.size();
        for (std::size_t i = 0; i < count; ++i) {
            auto* handle = new VertexHandleItem(
                *fid, static_cast<int>(i), coords[i][0], coords[i][1],
                ui_data_core::kVertexHandleHalf, nullptr, part_index,
                ring_index);
            addItem(handle);
            vertex_handles_.push_back(handle);
        }
    }
}

void MapEditScene::sync_handle_positions(FeatureItemApi* item) {
    for (auto* handle : vertex_handles_) {
        if (handle->feature_id != item->base().feature_id) {
            continue;
        }
        const int idx = handle->vertex_index;
        const MapRing coords = ring_coords_of(item, handle->part_index,
                                              handle->ring_index);
        if (idx >= 0 && idx < static_cast<int>(coords.size())) {
            handle->setPos(coords[idx][0], coords[idx][1]);
        }
    }
}

ui_data_qt::VertexHandleItem* MapEditScene::handle_at(
    const QPointF& pos) const {
    const double radius = kHandlePickTol * units_per_pixel();
    double best_dist2 = radius * radius;
    VertexHandleItem* best = nullptr;
    for (auto* handle : vertex_handles_) {
        const double dx = handle->pos().x() - pos.x();
        const double dy = handle->pos().y() - pos.y();
        const double dist2 = dx * dx + dy * dy;
        if (dist2 <= best_dist2) {
            best = handle;
            best_dist2 = dist2;
        }
    }
    return best;
}

ui_data_qt::FeatureItemApi* MapEditScene::feature_item_at(
    const QPointF& pos) const {
    for (QGraphicsItem* item : items(pos)) {
        if (auto* api = dynamic_cast<FeatureItemApi*>(item)) {
            if (layer_is_visible(api->base().kind)) {
                return api;
            }
        }
    }
    // Slight tolerance for thin edges / small wells (screen pixels).
    const double radius = kFeaturePickTol * units_per_pixel();
    QPainterPath path;
    path.addEllipse(pos, radius, radius);
    for (QGraphicsItem* item : items(path)) {
        if (auto* api = dynamic_cast<FeatureItemApi*>(item)) {
            if (layer_is_visible(api->base().kind)) {
                return api;
            }
        }
    }
    return nullptr;
}

void MapEditScene::reset_drag_positions() {
    for (const auto& fid : drag_ids_) {
        if (auto* gi = as_graphics(item_by_id(fid))) {
            gi->setPos(0.0, 0.0);
        }
    }
}

void MapEditScene::cancel_drag() {
    if (dragging_) {
        reset_drag_positions();
    }
    dragging_ = false;
    drag_ids_.clear();
}

void MapEditScene::cancel_vertex_drag() {
    if (vertex_drag_ && vertex_drag_feature_id_ && vertex_drag_start_xy_) {
        auto* item = item_by_id(*vertex_drag_feature_id_);
        const auto idx = vertex_drag_index_;
        const int part_index = vertex_drag_part_index_;
        const int ring_index = vertex_drag_ring_index_;
        const auto start = *vertex_drag_start_xy_;
        if ((dynamic_cast<FaciesPolygonItem*>(item) ||
             dynamic_cast<LineItem*>(item)) &&
            idx) {
            MapRing restored = ring_coords_of(item, part_index, ring_index);
            if (set_vertex(restored, *idx, start[0], start[1])) {
                if (auto* facies = dynamic_cast<FaciesPolygonItem*>(item)) {
                    facies->set_ring_coordinates(
                        part_index, ring_index,
                        ui_data_core::ring_to_json(restored));
                } else if (auto* line = dynamic_cast<LineItem*>(item)) {
                    line->set_coordinates(
                        ui_data_core::ring_to_json(restored));
                }
                refresh_hit_entry(item);
                invalidate_snap_candidates();
            }
        }
    }
    vertex_drag_ = false;
    vertex_drag_feature_id_.reset();
    vertex_drag_index_.reset();
    vertex_drag_start_xy_.reset();
}

std::pair<double, double> MapEditScene::snap_xy(double x, double y) {
    if (!snap_manager_.enabled()) {
        return {x, y};
    }
    // Candidate preparation happens once per scene generation: the manager
    // rebuilds its cache (bumping build_count) only after geometry,
    // reference-snap, or visibility changes; the grid index follows it.
    const auto candidates =
        snap_manager_.get_candidates(snap_items(), [this](std::string_view k) {
            return layer_is_visible(k);
        });
    const int build = snap_manager_.build_count();
    if (!snap_index_ || snap_index_build_ != build) {
        snap_index_ = SnapCandidateIndex(candidates);
        snap_index_build_ = build;
    }
    const auto& draft = draft_manager_.points();
    const std::vector<MapPoint> extras(draft.begin(), draft.end());
    const double tolerance_units =
        snap_manager_.tolerance() * units_per_pixel();
    const auto [sx, sy] = snap_index_->snap(x, y, tolerance_units, extras);
    return {sx, sy};
}

void MapEditScene::invalidate_snap_candidates() {
    snap_manager_.invalidate_candidates();
    snap_index_.reset();
    snap_index_build_ = -1;
}

std::vector<ui_data_core::SnapItem> MapEditScene::snap_items() const {
    std::vector<ui_data_core::SnapItem> out;
    out.reserve(item_order_.size());
    for (const auto& fid : item_order_) {
        auto* item = items_by_id_.at(fid);
        if (auto* f = dynamic_cast<FaciesPolygonItem*>(item)) {
            out.push_back(&f->model());
        } else if (auto* l = dynamic_cast<LineItem*>(item)) {
            out.push_back(&l->model());
        } else if (auto* w = dynamic_cast<WellPointItem*>(item)) {
            out.push_back(&w->model());
        } else if (auto* lb = dynamic_cast<LabelItem*>(item)) {
            out.push_back(&lb->model());
        }
    }
    return out;
}

std::vector<ui_data_core::MapPoint> MapEditScene::snap_candidates() {
    return snap_manager_.get_candidates(
        snap_items(),
        [this](std::string_view k) { return layer_is_visible(k); },
        &draft_manager_.points());
}

// --- navigation display LOD -------------------------------------------------

void MapEditScene::set_navigation_lod(bool active) {
    if (navigation_lod_ == active) {
        return;
    }
    navigation_lod_ = active;
    update();
}

void MapEditScene::drawItems(QPainter* painter, int numItems,
                             QGraphicsItem* items[],
                             const QStyleOptionGraphicsItem options[],
                             QWidget* widget) {
    if (!navigation_lod_) {
        QGraphicsScene::drawItems(painter, numItems, items, options, widget);
        return;
    }
    bool ok = false;
    const QTransform inverted = painter->combinedTransform().inverted(&ok);
    const QRectF exposed =
        ok ? inverted.mapRect(QRectF(painter->viewport())) : sceneRect();
    for (int i = 0; i < numItems; ++i) {
        QGraphicsItem* item = items[i];
        auto* facies = dynamic_cast<FaciesPolygonItem*>(item);
        auto* line = dynamic_cast<LineItem*>(item);
        if (facies == nullptr && line == nullptr) {
            painter->save();
            painter->setWorldTransform(item->sceneTransform(), true);
            item->paint(painter, &options[i], widget);
            painter->restore();
            continue;
        }
        // Cull against the item's existing bounding rectangle before
        // painting its simplified stand-in geometry.
        if (!item->sceneBoundingRect().intersects(exposed)) {
            continue;
        }
        painter->save();
        painter->setWorldTransform(item->sceneTransform(), true);
        auto* path_item = static_cast<QGraphicsPathItem*>(item);
        painter->setPen(path_item->pen());
        painter->setBrush(path_item->brush());
        painter->drawRect(item->boundingRect());
        painter->restore();
    }
}

// --- item factories -----------------------------------------------------------

ui_data_qt::FeatureItemApi* MapEditScene::item_from_record(
    const domain::Json& record) {
    return item_from_record_fn_ ? item_from_record_fn_(record) : nullptr;
}

domain::Json MapEditScene::facies_geometry_issues(
    const ui_data_qt::FaciesPolygonItem* item) {
    const auto& fid = item->model().feature_id;
    const auto cached = topology_issue_cache_.find(fid);
    if (cached != topology_issue_cache_.end()) {
        return cached->second;
    }
    domain::Json issues =
        ui_data_core::facies_geometry_issues(item->model(), backend_);
    topology_issue_cache_[fid] = issues;
    return issues;
}

void MapEditScene::publish_topology_issues() {
    const domain::Json issues = topology_issues();
    if (last_published_issues_ && *last_published_issues_ == issues) {
        return;
    }
    last_published_issues_ = issues;
    QVariantList payload;
    for (const auto& issue : issues) {
        payload.append(json_to_variant(issue));
    }
    emit topology_issues_changed(payload);
}

void MapEditScene::fit_scene_rect() {
    if (items_by_id_.empty()) {
        setSceneRect(kDefaultSceneRect);
        return;
    }
    const QRectF bounds = itemsBoundingRect();
    if (bounds.isNull() || !bounds.isValid()) {
        setSceneRect(kDefaultSceneRect);
        return;
    }
    setSceneRect(bounds.adjusted(-kScenePad, -kScenePad, kScenePad,
                                 kScenePad));
}

}  // namespace pwb::ui_pages_mapedit
