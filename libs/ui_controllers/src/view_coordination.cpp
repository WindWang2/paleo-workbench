#include <pwb/ui_controllers/view_coordination.hpp>

#include <cctype>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <filesystem>

namespace pwb::ui_controllers {

namespace {

double monotonic_ms_wall() {
    return std::chrono::duration<double, std::milli>(
               std::chrono::steady_clock::now().time_since_epoch())
        .count();
}

constexpr double kLinkCursorMinIntervalMs = 30.0;
constexpr double kDockDepthMinIntervalMs = 120.0;

// _survey_axis_range parity — [start, stop, step], nullopt when unusable.
std::optional<std::tuple<double, double, double>> survey_axis_range(
    const domain::Json& values) {
    if (!values.is_array() || values.size() < 3) return std::nullopt;
    double start, stop, step;
    try {
        start = values.at(0).get<double>();
        stop = values.at(1).get<double>();
        step = values.at(2).get<double>();
    } catch (const std::exception&) {
        return std::nullopt;
    }
    if (step == 0.0) return std::nullopt;
    return std::make_tuple(start, stop, step);
}

std::string json_str(const domain::Json& object, const char* key) {
    if (!object.is_object()) return {};
    const auto it = object.find(key);
    if (it == object.end() || !it->is_string()) return {};
    return it->get<std::string>();
}

std::optional<double> json_num(const domain::Json& object, const char* key) {
    if (!object.is_object()) return std::nullopt;
    const auto it = object.find(key);
    if (it == object.end() || !it->is_number()) return std::nullopt;
    return it->get<double>();
}

std::vector<domain::Json> json_array(const domain::Json& object,
                                     const char* key) {
    std::vector<domain::Json> rows;
    if (!object.is_object()) return rows;
    const auto it = object.find(key);
    if (it == object.end() || !it->is_array()) return rows;
    rows.reserve(it->size());
    for (const auto& row : *it) rows.push_back(row);
    return rows;
}

}  // namespace

ViewCoordinationCore::ViewCoordinationCore(
    SelectionBus& bus, CoordinateHubApi* hub,
    std::function<double()> monotonic_ms)
    : bus_(bus),
      hub_(hub),
      monotonic_ms_(std::move(monotonic_ms)) {
    if (!monotonic_ms_) monotonic_ms_ = &monotonic_ms_wall;
}

void ViewCoordinationCore::attach_to_bus() {
    bus_.subscribe([this](const SelectionState& state) {
        on_selection_changed(state);
    });
}

double ViewCoordinationCore::now_ms_() const { return monotonic_ms_(); }

// ---------------------------------------------------------------------------
// Sinks
// ---------------------------------------------------------------------------

void ViewCoordinationCore::set_seismic_sink(
    std::function<void(int, int, std::optional<double>)> sink) {
    seismic_sink_ = std::move(sink);
}
void ViewCoordinationCore::set_spatial_cursor_sink(
    std::function<void(double, double)> sink) {
    spatial_cursor_sink_ = std::move(sink);
}
void ViewCoordinationCore::set_seismic_focus_sink(
    std::function<void(int, int, double)> sink) {
    seismic_focus_sink_ = std::move(sink);
}
void ViewCoordinationCore::set_horizon_sink(
    std::function<void(std::string)> sink) {
    horizon_sink_ = std::move(sink);
}
void ViewCoordinationCore::set_well_dock_sink(
    std::function<void(std::string)> sink) {
    well_dock_sink_ = std::move(sink);
}
void ViewCoordinationCore::set_section_cursor_sink(
    std::function<void(std::string)> sink) {
    section_cursor_sink_ = std::move(sink);
}
void ViewCoordinationCore::set_link_cursor_sink(
    std::function<void(std::optional<std::string>, std::optional<double>)>
        sink) {
    link_cursor_sink_ = std::move(sink);
}
void ViewCoordinationCore::set_well_log_select_sink(
    std::function<void(std::string)> sink) {
    well_log_select_sink_ = std::move(sink);
}
void ViewCoordinationCore::set_geomodel_highlight_sink(
    std::function<void(std::string)> sink) {
    geomodel_highlight_sink_ = std::move(sink);
}
void ViewCoordinationCore::set_map_select_well_sink(
    std::function<void(std::string)> sink) {
    map_select_well_sink_ = std::move(sink);
}

// ---------------------------------------------------------------------------
// Project lifecycle
// ---------------------------------------------------------------------------

void ViewCoordinationCore::bind_project(const domain::Json& project_root,
                                        CatalogPortApi* catalog,
                                        const TimeDepthParseFn& parse_td) {
    clear_project();
    for (const auto& well : json_array(project_root, "wells")) {
        // _index_well_identity + _register_project_well parity.
        const std::string name = json_str(well, "name");
        const std::string entity_id = json_str(well, "id");
        if (!name.empty() && !entity_id.empty()) {
            well_name_by_id_[entity_id] = name;
            well_id_by_name_[name] = entity_id;
        }
        if (name.empty()) continue;
        auto x = json_num(well, "project_x");
        auto y = json_num(well, "project_y");
        if (!x || !y) {
            x = json_num(well, "surface_x");
            y = json_num(well, "surface_y");
        }
        if (!x || !y) continue;  // no usable pair — never fabricate
        const double kb = json_num(well, "kb").value_or(0.0);
        const double td = json_num(well, "td").value_or(0.0);
        // metadata.survey_stations — lenient (MD, inc, az) triples.
        std::optional<WellStations> stations;
        const auto meta_it = well.find("metadata");
        if (meta_it != well.end() && meta_it->is_object()) {
            const auto st_it = meta_it->find("survey_stations");
            if (st_it != meta_it->end() && st_it->is_array() &&
                !st_it->empty()) {
                WellStations parsed;
                bool ok = true;
                for (const auto& st : *st_it) {
                    if (!st.is_array() || st.size() < 3) {
                        ok = false;
                        break;
                    }
                    try {
                        parsed.emplace_back(st.at(0).get<double>(),
                                            st.at(1).get<double>(),
                                            st.at(2).get<double>());
                    } catch (const std::exception&) {
                        ok = false;
                        break;
                    }
                }
                if (ok && !parsed.empty()) stations = std::move(parsed);
            }
        }
        if (hub_ == nullptr) continue;
        try {
            hub_->register_well(name, *x, *y, kb, td, stations);
        } catch (const std::exception&) {
            continue;
        }
        bound_well_ids_.insert(name);
    }
    // _first_seismic_survey + _configure_hub_seismic_geometry parity.
    for (const auto& survey : json_array(project_root, "seismic_surveys")) {
        const auto ext_it = survey.find("extent");
        if (ext_it == survey.end() || !ext_it->is_array() ||
            ext_it->size() < 3)
            continue;
        std::vector<std::pair<double, double>> extent;
        bool ok = true;
        for (const auto& corner : *ext_it) {
            if (!corner.is_array() || corner.size() < 2) {
                ok = false;
                break;
            }
            try {
                extent.emplace_back(corner.at(0).get<double>(),
                                    corner.at(1).get<double>());
            } catch (const std::exception&) {
                ok = false;
                break;
            }
        }
        if (!ok || extent.size() < 3) continue;
        const auto il = survey_axis_range(survey.value("inline_range",
                                                       domain::Json()));
        const auto xl = survey_axis_range(survey.value("crossline_range",
                                                       domain::Json()));
        if (!il || !xl) continue;
        const auto [il_start, il_stop, il_step] = *il;
        const auto [xl_start, xl_stop, xl_step] = *xl;
        (void)il_step;
        (void)xl_step;
        const double dil = il_stop - il_start;
        const double dxl = xl_stop - xl_start;
        if (dil == 0.0 || dxl == 0.0) continue;
        const auto il_vec = std::make_pair(extent[2].first - extent[1].first,
                                           extent[2].second - extent[1].second);
        const auto xl_vec = std::make_pair(extent[1].first - extent[0].first,
                                           extent[1].second - extent[0].second);
        if (hub_ == nullptr) break;
        try {
            hub_->configure_seismic_grid(
                extent[0],
                {il_vec.first / dil, il_vec.second / dil},
                {xl_vec.first / dxl, xl_vec.second / dxl},
                static_cast<int>(std::lround(il_start)),
                static_cast<int>(std::lround(xl_start)));
        } catch (const std::exception&) {
            // geometry rejected — non-fatal
        }
        break;  // first parseable survey only
    }
    register_time_depth_calibrations_(project_root, catalog, parse_td);
}

void ViewCoordinationCore::clear_project() {
    bound_well_ids_.clear();
    well_name_by_id_.clear();
    well_id_by_name_.clear();
    if (hub_ != nullptr) {
        try {
            hub_->clear_all_wells();
        } catch (const std::exception&) {
        }
        try {
            hub_->reset_seismic_grid();
        } catch (const std::exception&) {
        }
    }
    link_cursor_set_ = false;
    last_snapshot_ = SelectionState{};
    bus_.clear();
}

std::pair<std::optional<std::string>, std::optional<std::string>>
ViewCoordinationCore::resolve_well_key(const std::string& value) const {
    if (value.empty()) return {std::nullopt, std::nullopt};
    if (const auto it = well_id_by_name_.find(value);
        it != well_id_by_name_.end()) {
        return {value, it->second};
    }
    if (const auto it = well_name_by_id_.find(value);
        it != well_name_by_id_.end()) {
        return {it->second, value};
    }
    return {std::nullopt, std::nullopt};
}

int ViewCoordinationCore::register_time_depth_calibrations_(
    const domain::Json& project_root, CatalogPortApi* catalog,
    const TimeDepthParseFn& parse_td) {
    if (hub_ == nullptr || !parse_td) return 0;
    int registered = 0;
    std::set<std::string> seen_paths;
    struct Entry {
        std::string well_name;
        std::string path;
        std::optional<std::string> version_id;
        std::optional<std::string> fingerprint;
        domain::Json metadata = domain::Json::object();
    };
    std::vector<Entry> entries;
    // Entity-linked time_depth assets first (well entity name via link).
    for (const auto& link : json_array(project_root, "entity_asset_links")) {
        if (json_str(link, "role") != "time_depth") continue;
        const auto unresolved_it = link.find("unresolved");
        if (unresolved_it != link.end() && unresolved_it->is_boolean() &&
            unresolved_it->get<bool>())
            continue;
        std::string well_name;
        const std::string entity_id = json_str(link, "entity_id");
        for (const auto& well : json_array(project_root, "wells")) {
            if (json_str(well, "id") == entity_id) {
                well_name = json_str(well, "name");
                break;
            }
        }
        if (well_name.empty()) continue;
        if (catalog == nullptr) continue;
        // _resolve_asset_version parity — current version payload + identity.
        try {
            const std::string asset_id = json_str(link, "asset_id");
            const auto& doc = catalog->document();
            for (const auto& asset : doc.assets) {
                if (asset.id.str() != asset_id || !asset.current_version_id)
                    continue;
                for (const auto& version : doc.versions) {
                    if (version.id != *asset.current_version_id) continue;
                    Entry entry;
                    entry.well_name = well_name;
                    entry.path = catalog->resolve_path(version).string();
                    entry.version_id = version.id.str();
                    if (version.metadata.is_object()) {
                        const auto fp = version.metadata.find("fingerprint");
                        if (fp != version.metadata.end() &&
                            fp->is_string())
                            entry.fingerprint = fp->get<std::string>();
                        entry.metadata = version.metadata;
                    }
                    if (entry.path.empty() ||
                        seen_paths.count(entry.path))
                        continue;
                    seen_paths.insert(entry.path);
                    entries.push_back(std::move(entry));
                    break;
                }
            }
        } catch (const std::exception&) {
            continue;
        }
    }
    // Legacy ResourceItem companions (type time_depth, keyed by stem).
    for (const auto& resource : json_array(project_root, "resources")) {
        if (json_str(resource, "type") != "time_depth") continue;
        const std::string path = json_str(resource, "path");
        if (path.empty() || seen_paths.count(path)) continue;
        seen_paths.insert(path);
        Entry entry;
        entry.path = path;
        entry.well_name = json_str(resource, "name");
        if (entry.well_name.empty()) {
            entry.well_name =
                std::filesystem::path(path).stem().string();
        }
        entries.push_back(std::move(entry));
    }
    for (const auto& entry : entries) {
        std::optional<std::vector<std::pair<double, double>>> pairs;
        try {
            pairs = parse_td(std::filesystem::path(entry.path),
                             entry.well_name);
        } catch (const std::exception&) {
            continue;
        }
        if (!pairs || pairs->empty()) continue;
        TimeDepthCalibrationSlice cal;
        cal.well_name = entry.well_name;
        cal.pairs = *pairs;
        cal.provenance = "td-table:" +
                         std::filesystem::path(entry.path)
                             .filename()
                             .string();
        cal.version_id = entry.version_id;
        cal.fingerprint = entry.fingerprint;
        cal.metadata = entry.metadata;
        try {
            hub_->set_time_depth_calibration(cal);
            ++registered;
        } catch (const std::exception&) {
            continue;  // non-monotonic etc. — skipped, never guessed
        }
    }
    return registered;
}

// ---------------------------------------------------------------------------
// Routing (changed-field only — _on_selection_changed parity)
// ---------------------------------------------------------------------------

void ViewCoordinationCore::on_selection_changed(
    const SelectionState& selection) {
    const SelectionState previous = last_snapshot_;
    last_snapshot_ = selection;
    const auto& source = selection.source_widget_id;

    if (selection.active_well_id &&
        selection.active_well_id != previous.active_well_id) {
        route_well_selection_(*selection.active_well_id, source);
    }
    if (selection.seismic_cursor &&
        selection.seismic_cursor != previous.seismic_cursor) {
        route_seismic_cursor_(*selection.seismic_cursor);
    }
    if (selection.active_horizon_id &&
        selection.active_horizon_id != previous.active_horizon_id) {
        route_horizon_selection_(*selection.active_horizon_id, source);
    }
    if (selection.spatial_cursor &&
        selection.spatial_cursor != previous.spatial_cursor &&
        (!source || *source != SOURCE_MAP)) {
        if (spatial_cursor_sink_) {
            try {
                spatial_cursor_sink_(selection.spatial_cursor->x,
                                     selection.spatial_cursor->y);
            } catch (const std::exception&) {
            }
        }
    }
}

void ViewCoordinationCore::route_well_selection_(
    const std::string& well_id, const std::optional<std::string>& source) {
    // Map → Well Log (auto-switch; never echo back into the log page).
    if ((!source || *source != SOURCE_WELL_LOG) && well_log_select_sink_) {
        try {
            well_log_select_sink_(well_id);
        } catch (const std::exception&) {
        }
    }
    // Any view → workstation well dock (case A).
    if (well_dock_sink_) {
        try {
            well_dock_sink_(well_id);
        } catch (const std::exception&) {
        }
    }
    // Map/Well Log → 3D trajectory highlight.
    if ((!source || *source != SOURCE_3D) && geomodel_highlight_sink_) {
        try {
            geomodel_highlight_sink_(well_id);
        } catch (const std::exception&) {
        }
    }
    // 3D/Well Log → Map highlight (emit=False parity lives in the sink).
    if ((!source || *source != SOURCE_MAP) && map_select_well_sink_) {
        try {
            map_select_well_sink_(well_id);
        } catch (const std::exception&) {
        }
    }
    // Any view → Seismic locate (scenario A).
    if (!source || *source != SOURCE_SEISMIC) {
        locate_well_in_seismic_(well_id);
    }
}

bool ViewCoordinationCore::locate_well_in_seismic_(
    const std::string& well_id) {
    if (!seismic_sink_ || hub_ == nullptr) return false;
    try {
        const auto [x, y, tvd] = hub_->well_depth_to_map(well_id, 0.0);
        (void)tvd;
        const auto [il, xl] = hub_->map_to_seismic_xy(x, y);
        seismic_sink_(static_cast<int>(il), static_cast<int>(xl),
                      std::nullopt);  // TWT only with a calibration — never invented
        return true;
    } catch (const std::exception&) {
        return false;
    }
}

void ViewCoordinationCore::route_horizon_selection_(
    const std::string& horizon_id,
    const std::optional<std::string>& /*source*/) {
    if (!horizon_sink_) return;
    try {
        horizon_sink_(horizon_id);
    } catch (const std::exception&) {
    }
}

void ViewCoordinationCore::update_bus_custom_attributes_(
    const std::map<std::string, domain::Json>& attrs) {
    SelectionPatch patch;
    patch.custom_attributes = attrs;
    bus_.update(std::move(patch));  // no source tag — internal update
}

void ViewCoordinationCore::route_seismic_cursor_(
    const SeismicCursorState& cursor) {
    if (hub_ == nullptr) {
        clear_link_cursor_once_();
        return;
    }
    std::string well_id;
    std::optional<double> md;
    try {
        const auto resolved = hub_->seismic_to_well(
            static_cast<int>(cursor.inline_coord),
            static_cast<int>(cursor.crossline_coord), cursor.time_depth);
        well_id = resolved.first;
        md = resolved.second;
    } catch (const std::exception&) {
        clear_link_cursor_once_();
        return;
    }
    if (well_id.empty()) {
        // No authority can produce an MD here — a previously shown link
        // cursor must not survive as a stale depth hint (review R1-M3).
        clear_link_cursor_once_();
        return;
    }
    std::optional<CalibratedMd> calibrated;
    try {
        calibrated = hub_->calibrated_md(well_id, cursor.time_depth);
    } catch (const std::exception&) {
    }
    if (calibrated) {
        update_bus_custom_attributes_({
            {"seismic_well_id", well_id},
            {"seismic_well_md", calibrated->md},
            {"seismic_well_md_is_approximate", false},
            {"seismic_well_md_authority",
             std::string("time-depth:") + calibrated->provenance},
        });
    } else if (md) {
        double velocity = 0.0;
        try {
            velocity = hub_->velocity_assumption();
        } catch (const std::exception&) {
        }
        char authority[128];
        std::snprintf(authority, sizeof(authority),
                      "velocity-assumption:%g m/s", velocity);
        update_bus_custom_attributes_({
            {"seismic_well_id", well_id},
            {"seismic_well_md", *md},
            {"seismic_well_md_is_approximate", true},
            {"seismic_well_md_authority", std::string(authority)},
        });
    } else {
        update_bus_custom_attributes_({
            {"seismic_well_id", domain::Json()},
            {"seismic_well_md", domain::Json()},
            {"seismic_well_md_is_approximate", domain::Json()},
            {"seismic_well_md_authority", domain::Json()},
        });
    }
    if (well_log_select_sink_) {
        try {
            well_log_select_sink_(well_id);
        } catch (const std::exception&) {
        }
    }
    if (link_cursor_sink_) {
        try {
            if (calibrated) {
                throttled_link_cursor_write_(well_id, calibrated->md);
            } else {
                clear_link_cursor_once_(well_id);
            }
        } catch (const std::exception&) {
        }
    }
    if (seismic_focus_sink_) {
        try {
            seismic_focus_sink_(static_cast<int>(cursor.inline_coord),
                                static_cast<int>(cursor.crossline_coord),
                                cursor.time_depth);
        } catch (const std::exception&) {
        }
    }
}

void ViewCoordinationCore::throttled_link_cursor_write_(
    const std::string& well_id, double md) {
    const double now = now_ms_();
    if (link_cursor_last_write_ms_ &&
        now - *link_cursor_last_write_ms_ < kLinkCursorMinIntervalMs)
        return;
    link_cursor_last_write_ms_ = now;
    link_cursor_sink_(well_id, md);
    link_cursor_set_ = true;
}

void ViewCoordinationCore::clear_link_cursor_once_(
    const std::optional<std::string>& well_id) {
    if (!link_cursor_set_ || !link_cursor_sink_) return;
    try {
        link_cursor_sink_(well_id, std::nullopt);
    } catch (const std::exception&) {
    }
    link_cursor_set_ = false;
}

// ---------------------------------------------------------------------------
// Publishing
// ---------------------------------------------------------------------------

void ViewCoordinationCore::publish_well_selection(
    const std::string& well_id, const std::string& source) {
    if (well_id.empty()) return;
    const auto [canonical, entity_id] = resolve_well_key(well_id);
    const std::string key = canonical.value_or(well_id);
    const auto& current = bus_.state();
    if (current.active_well_id == key && current.source_widget_id == source)
        return;  // identical (well, source) publication — drop
    auto attrs = current.custom_attributes;
    if (entity_id) {
        attrs["well_entity_id"] = *entity_id;
    } else {
        attrs.erase("well_entity_id");
    }
    SelectionPatch patch;
    patch.active_well_id = key;
    patch.custom_attributes = std::move(attrs);
    bus_.update(std::move(patch), source);
}

void ViewCoordinationCore::publish_seismic_cursor(int il, int xl, double twt) {
    std::optional<SpatialCursorState> spatial;
    if (hub_ != nullptr) {
        try {
            const auto [x, y] = hub_->seismic_to_map_xy(il, xl);
            spatial = SpatialCursorState{x, y, std::nullopt};
        } catch (const std::exception&) {
        }
    }
    SelectionPatch patch;
    patch.seismic_cursor = SeismicCursorState{
        static_cast<double>(il), static_cast<double>(xl), twt};
    patch.spatial_cursor = spatial;
    bus_.update(std::move(patch), std::string(SOURCE_SEISMIC));
}

void ViewCoordinationCore::publish_horizon_selection(
    const std::string& horizon_id, const std::string& source) {
    if (horizon_id.empty()) return;
    SelectionPatch patch;
    patch.active_horizon_id = horizon_id;
    bus_.update(std::move(patch), source);
}

void ViewCoordinationCore::publish_fault_selection(
    const std::string& fault_id, const std::string& source) {
    if (fault_id.empty()) return;
    SelectionPatch patch;
    patch.active_fault_id = fault_id;
    bus_.update(std::move(patch), source);
}

void ViewCoordinationCore::publish_interpretation_selection(
    const std::string& interpretation_id, const std::string& source) {
    if (interpretation_id.empty()) return;
    SelectionPatch patch;
    patch.active_interpretation_id = interpretation_id;
    bus_.update(std::move(patch), source);
}

void ViewCoordinationCore::publish_layer_selection(
    const std::string& layer_id, const std::string& source) {
    if (layer_id.empty()) return;
    const auto& current = bus_.state();
    if (current.selected_layer_id == layer_id &&
        current.source_widget_id == source)
        return;
    SelectionPatch patch;
    patch.selected_layer_id = layer_id;
    bus_.update(std::move(patch), source);
}

void ViewCoordinationCore::publish_active_layer(
    const std::optional<std::string>& layer_id, const std::string& source) {
    SelectionPatch patch;
    patch.active_layer_id = layer_id;
    bus_.update(std::move(patch), source);
}

void ViewCoordinationCore::publish_edit_target(
    const std::optional<std::string>& layer_id, const std::string& source) {
    SelectionPatch patch;
    patch.edit_target_layer_id = layer_id;
    bus_.update(std::move(patch), source);
}

void ViewCoordinationCore::publish_asset_selection(
    const std::optional<std::string>& asset_id,
    const std::optional<std::string>& version_id, const std::string& source) {
    const auto& current = bus_.state();
    if (current.selected_asset_id == asset_id &&
        current.selected_version_id == version_id &&
        current.source_widget_id == source)
        return;  // (asset, version, source) duplicate guard
    SelectionPatch patch;
    patch.selected_asset_id = asset_id;
    patch.selected_version_id = version_id;
    bus_.update(std::move(patch), source);
}

void ViewCoordinationCore::publish_survey_selection(
    const std::optional<std::string>& survey_id, const std::string& source) {
    SelectionPatch patch;
    patch.active_survey_id = survey_id;
    bus_.update(std::move(patch), source);
}

void ViewCoordinationCore::publish_task_selection(
    const std::optional<std::string>& task_id, const std::string& source) {
    SelectionPatch patch;
    patch.active_task_id = task_id;
    bus_.update(std::move(patch), source);
}

void ViewCoordinationCore::publish_stage(
    const std::optional<std::string>& stage, const std::string& source) {
    SelectionPatch patch;
    patch.workflow_stage = stage;
    bus_.update(std::move(patch), source);
}

bool ViewCoordinationCore::publish_depth_cursor(
    const std::string& well_id, double md, const std::string& source) {
    if (well_id.empty()) return false;
    SelectionPatch patch;
    patch.depth_cursor = std::make_pair(well_id, md);
    bus_.update(std::move(patch), source);
    if (hub_ == nullptr) return false;
    std::optional<std::tuple<double, double, double>> cursor;
    try {
        cursor = hub_->well_md_to_seismic_cursor(well_id, md);
    } catch (const std::exception&) {
        return false;
    }
    if (!cursor) return false;  // refused — no calibration covers the depth
    if (source != SOURCE_SEISMIC && seismic_focus_sink_) {
        try {
            const auto [il, xl, twt] = *cursor;
            seismic_focus_sink_(static_cast<int>(il), static_cast<int>(xl),
                                twt);
        } catch (const std::exception&) {
        }
    }
    return true;
}

void ViewCoordinationCore::publish_section_cursor(
    const std::string& well_name, const std::string& /*source*/) {
    std::string name = well_name;
    // strip parity
    while (!name.empty() && std::isspace(name.back())) name.pop_back();
    while (!name.empty() && std::isspace(name.front())) name.erase(0, 1);
    if (name.empty()) {
        if (section_cursor_set_ && section_cursor_sink_) {
            section_cursor_set_ = false;
            section_cursor_last_.clear();
            section_cursor_sink_(std::string{});
        }
        return;
    }
    if (!section_cursor_sink_) return;
    if (name == section_cursor_last_ && section_cursor_set_) return;
    section_cursor_last_ = name;
    section_cursor_set_ = true;
    section_cursor_sink_(name);
}

void ViewCoordinationCore::on_well_log_task_selected(
    const std::string& well_name) {
    // _on_well_log_row_selected parity — the Qt shell resolves row→name
    // (semantic task_selected signal, never raw currentRowChanged).
    if (well_name.empty()) return;
    publish_well_selection(well_name, SOURCE_WELL_LOG);
}

void ViewCoordinationCore::on_well_depth_cursor(
    const std::string& well_name, double md) {
    if (well_name.empty()) return;
    publish_depth_cursor(well_name, md, SOURCE_WELL_LOG);
}

void ViewCoordinationCore::on_dock_depth_cursor(
    const std::string& well_name, double md) {
    const double now = now_ms_();
    if (dock_depth_last_pub_ms_ &&
        now - *dock_depth_last_pub_ms_ < kDockDepthMinIntervalMs)
        return;
    dock_depth_last_pub_ms_ = now;
    if (well_name.empty()) return;
    publish_depth_cursor(well_name, md, SOURCE_WELL_LOG);
}

}  // namespace pwb::ui_controllers
