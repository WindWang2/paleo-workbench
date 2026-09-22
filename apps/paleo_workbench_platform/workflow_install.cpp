// workflow_install.cpp — UI-14 composition-root wiring for the native
// product shell (workflow_controller.py / app_shell host parity).
//
// One WorkflowBinding per window owns:
//   * qt::WorkflowController with EVERY seam bound — the injected service
//     bag resolves to the real workflow_runtime services (dashboard_state /
//     home_workflow_steps / build_affected_products_plan), the real
//     closure_workflow compilers (compile_map_draft / compile_map_production
//     with the catalog rail + model-version trust resolver), the shared
//     factor grid store + process-global generation counter (#834) and the
//     real prepare/commit kernels (factor_prepare_production);
//   * the per-project catalog closure — InstalledCatalogClosure (the deep
//     CatalogServiceApi/CatalogPortApi surface) feeding
//     CatalogRuntimeApi; the workflow_runtime::CatalogRepository rail is
//     the SAME shared instance the mapping closure opened (SQLite-first,
//     JSON fail-closed fallback) so factor prep, compile and product
//     assembly write through ONE provenance rail;
//   * the composite stage-action dispatch (stage_actions.py parity:
//     horizon gate + dispatch-key handlers → status_message);
//   * the map-factor shelf routing (contour draft / create map / map
//     product / overlay / fault entries → real hosts);
//   * the page-update fan-out onto the real AppShell pages (typed slice
//     collection on the GUI thread — pages keep their seam signatures).
//
// Honesty: a missing project unbinds every seam surface (pages show their
// empty states); an action with no production service reports
// "阶段动作未接入" through the dispatcher instead of pretending to run.

#include "workflow_install.hpp"

#include "app_context.hpp"
#include "app_shell.hpp"
#include "closure_mapping_document.hpp"
#include "closure_mapping_install.hpp"
#include "job_center.hpp"

#if defined(PWB_WITH_FACTOR_KERNEL)
#include "factor_prepare_production.hpp"
#endif
#if defined(PWB_WITH_CATALOG_CLOSURE)
#include "closure_catalog_install.hpp"
#endif
#if defined(PWB_WITH_CLOSURE_PREVIEW)
#include "closure_preview_install.hpp"
#endif

#include <pwb/application/adapters/data_store.hpp>
#if defined(PWB_WITH_CLOSURE_WORKFLOW)
#include <pwb/closure_workflow/map_compile.hpp>
#include <pwb/closure_workflow/map_product.hpp>
#endif
#include <pwb/project/version_models.hpp>
#include <pwb/ui_composite/composite_document.hpp>
#include <pwb/ui_controllers/qt/workflow_controller.hpp>
#include <pwb/ui_data_core/asset_view.hpp>
#include <pwb/ui_map/mapping_page.hpp>
#include <pwb/ui_pages_data/module_map.hpp>
#include <pwb/ui_pages_data/qt/data_workspace.hpp>
#include <pwb/ui_pages_data/qt/home_page.hpp>
#include <pwb/ui_pages_data/qt/preparation_page.hpp>
#include <pwb/ui_pages_mapedit/map_factor_shelf.hpp>
#include <pwb/ui_pages_mapedit/map_workbench_bottom.hpp>
#include <pwb/ui_review/qt/review_export_page.hpp>
#include <pwb/ui_seqviz/qt/correlation_page.hpp>
#include <pwb/ui_seqviz/qt/sequence_framework_page.hpp>
#include <pwb/ui_seqviz/qt/visualization_page.hpp>
#include <pwb/ui_seqviz/sequence_state.hpp>
#include <pwb/ui_seqviz/viz_page_state.hpp>
#include <pwb/ui_shell/navigation.hpp>
#include <pwb/ui_wellseis/qt/geological_modeling_3d_page.hpp>
#include <pwb/ui_wellseis/qt/seismic_prediction_page.hpp>
#include <pwb/ui_wellseis/qt/well_log_prediction_page.hpp>
#include <pwb/ui_wellseis/slices.hpp>
#include <pwb/ui_workers/correlation_load.hpp>
#include <pwb/ui_workers/worker_common.hpp>
#include <pwb/ui_workstation/explorer_panel.hpp>
#include <pwb/ui_workstation/explorer_spec.hpp>
#include <pwb/ui_workstation/stage_actions.hpp>
#include <pwb/ui_workstation/workstation_frame.hpp>
#include <pwb/workflow_runtime/map_qa_rules.hpp>
#include <pwb/workflow_runtime/qc.hpp>
#include <pwb/workflow_runtime/service.hpp>

// Stage-action orchestration (Python stage_actions.py parity) — the
// handlers below are thin coordinators; every scientific call routes to
// the same domain services/kernels the Python originals used.
#include <pwb/data/entity_identity.hpp>
#include <pwb/domain/diagnostics.hpp>
#include <pwb/domain/ids.hpp>
#include <pwb/factor_host/canonical_json.hpp>
#include <pwb/factor_fusion/factor_grid.hpp>
#include <pwb/mapping/representative_facies.hpp>
#include <pwb/prediction/spatial_result.hpp>
#include <pwb/ui_composite/composite_controller.hpp>
#include <pwb/ui_composite/constraints_sync.hpp>
#include <pwb/ui_composite/factor_group_layers.hpp>
#include <pwb/ui_composite/layer_group_controller.hpp>
#include <pwb/ui_composite/layer_manager_panel.hpp>
#include <pwb/ui_composite/map_styles.hpp>
#include <pwb/ui_composite/roles.hpp>
#include <pwb/ui_composite/vector_layer.hpp>
#include <pwb/ui_data_core/map_edit_geometry.hpp>
#include <pwb/ui_widgets/core/facies_patterns.hpp>
#include <pwb/workflow_graph/evidence.hpp>
#include <pwb/workspace/mutations.hpp>
#include <pwb/workspace/state.hpp>
#include <pwb/workspace/state_ops.hpp>
#if defined(PWB_WITH_CLOSURE_WORKFLOW)
#include <pwb/closure_workflow/grid_seams.hpp>
#include <pwb/closure_workflow/integrated_compilation.hpp>
#endif
// The Qt-free interpretation headers are linked whenever the
// CONV-32 slice is in the build (see the CMake conditional); the
// science/catalog blocks below consume them in every shape.
#include <pwb/workflow_interpretation/compilation.hpp>
#include <pwb/workflow_interpretation/dependencies.hpp>
#include <pwb/workflow_interpretation/integrated_interpretation.hpp>
#include <pwb/workflow_interpretation/revision.hpp>
// workflow_runtime is unconditionally linked; the constraint
// commit block below (FACTOR_KERNEL guard) needs it in every shape.
#include <pwb/workflow_runtime/constraint_versions.hpp>
#include <pwb/mapping/contouring.hpp>
#include <pwb/mapping/factor_grid_io.hpp>
#include <pwb/mapping/interpolator.hpp>
#include <pwb/mapping/polygonization.hpp>
#include <pwb/project/paths.hpp>
#include <pwb/ui_seqviz/factor_state.hpp>
#include <pwb/ui_seqviz/qt/factor_panels.hpp>
#include <pwb/ui_workers/synthetic_points.hpp>
#include <pwb/workflow_interpretation/constraint_capabilities.hpp>
#include <pwb/workflow_interpretation/fault_lifecycle.hpp>
#if defined(PWB_WITH_CLOSURE_SCIENCE)
#include <pwb/closure_science/inference_service.hpp>
#include <pwb/closure_science/model_seed.hpp>
#include <pwb/closure_science/providers.hpp>
#endif
// Pwb::Cartography links unconditionally on the platform target.
#include <pwb/cartography/cartographic_qa.hpp>

#include <QDockWidget>
#include <QInputDialog>
#include <QMainWindow>
#include <QLabel>
#include <QLineEdit>
#include <QMessageBox>
#include <QMetaObject>
#include <QStatusBar>
#include <QVariant>

#include <algorithm>
#include <cmath>
#include <random>
#include <set>
#include <sstream>
#include <utility>

namespace pwb::app::workflow_wiring {
namespace {

using pwb::domain::Json;

// ------------------------------------------------------------ Json reads --

const Json* jfield(const Json& j, const char* key) {
    if (!j.is_object()) return nullptr;
    const auto it = j.find(key);
    return it != j.end() ? &*it : nullptr;
}

std::string jstr(const Json& j, const char* key,
                 const std::string& fallback = "") {
    const Json* v = jfield(j, key);
    if (v != nullptr && v->is_string()) return v->get<std::string>();
    return fallback;
}

std::vector<std::string> jstrlist(const Json& j, const char* key) {
    std::vector<std::string> out;
    const Json* v = jfield(j, key);
    if (v != nullptr && v->is_array()) {
        for (const auto& item : *v) {
            if (item.is_string()) out.push_back(item.get<std::string>());
        }
    }
    return out;
}

std::optional<double> jnum(const Json& j, const char* key) {
    const Json* v = jfield(j, key);
    if (v != nullptr && v->is_number()) return v->get<double>();
    return std::nullopt;
}

// -------------------------------------------------- slice collectors ------
// GUI-thread Json -> typed page slices. Fields mirror the Python attribute
// reads each page performs (see each slice header for the field contract);
// absent keys stay at their honest defaults — never guessed.

std::vector<ui_data_core::ResourceItem> collect_resource_items(
    const Json& root) {
    std::vector<ui_data_core::ResourceItem> out;
    const Json* rows = jfield(root, "resources");
    if (rows == nullptr || !rows->is_array()) return out;
    for (const auto& row : *rows) {
        if (!row.is_object()) continue;
        ui_data_core::ResourceItem item;
        item.id = jstr(row, "id");
        item.name = jstr(row, "name");
        item.path = jstr(row, "path");
        item.type = jstr(row, "type");
        item.format = jstr(row, "format");
        if (const Json* crs = jfield(row, "crs");
            crs != nullptr && crs->is_string()) {
            item.crs = crs->get<std::string>();
        }
        if (const Json* status = jfield(row, "status");
            status != nullptr && status->is_string()) {
            item.status = status->get<std::string>();
        }
        item.tags = jstrlist(row, "tags");
        item.source = jstr(row, "source", "local");
        if (const Json* summary = jfield(row, "parsed_summary");
            summary != nullptr && summary->is_object()) {
            item.parsed_summary = *summary;
        }
        if (const Json* checksum = jfield(row, "checksum");
            checksum != nullptr && checksum->is_string()) {
            item.checksum = checksum->get<std::string>();
        }
        if (const Json* external = jfield(row, "external");
            external != nullptr && external->is_boolean()) {
            item.external = external->get<bool>();
        }
        if (const Json* role = jfield(row, "artifact_role");
            role != nullptr && role->is_string()) {
            item.artifact_role = role->get<std::string>();
        }
        out.push_back(std::move(item));
    }
    return out;
}

std::vector<ui_workers::ResourceSlice> collect_resource_slices(
    const Json& root) {
    std::vector<ui_workers::ResourceSlice> out;
    const Json* rows = jfield(root, "resources");
    if (rows == nullptr || !rows->is_array()) return out;
    for (const auto& row : *rows) {
        if (!row.is_object()) continue;
        ui_workers::ResourceSlice item;
        item.id = jstr(row, "id");
        item.name = jstr(row, "name");
        item.path = jstr(row, "path");
        item.type = jstr(row, "type");
        item.format = jstr(row, "format");
        out.push_back(std::move(item));
    }
    return out;
}

std::vector<ui_wellseis::WellSlice> collect_well_slices(const Json& root) {
    std::vector<ui_wellseis::WellSlice> out;
    const Json* rows = jfield(root, "wells");
    if (rows == nullptr || !rows->is_array()) return out;
    for (const auto& row : *rows) {
        if (!row.is_object()) continue;
        ui_wellseis::WellSlice well;
        well.id = jstr(row, "id");
        well.name = jstr(row, "name");
        well.uwi = jstr(row, "uwi");
        well.surface_x = jnum(row, "surface_x");
        well.surface_y = jnum(row, "surface_y");
        well.project_x = jnum(row, "project_x");
        well.project_y = jnum(row, "project_y");
        well.coordinate_status =
            jstr(row, "coordinate_status", "untransformed");
        well.spatial_scope = jstr(row, "spatial_scope", "workarea");
        out.push_back(std::move(well));
    }
    return out;
}

std::vector<ui_wellseis::SurveySlice> collect_survey_slices(
    const Json& root) {
    std::vector<ui_wellseis::SurveySlice> out;
    const Json* rows = jfield(root, "seismic_surveys");
    if (rows == nullptr || !rows->is_array()) return out;
    for (const auto& row : *rows) {
        if (!row.is_object()) continue;
        ui_wellseis::SurveySlice survey;
        survey.id = jstr(row, "id");
        survey.name = jstr(row, "name");
        survey.crs = jstr(row, "crs");
        if (const Json* extent = jfield(row, "extent");
            extent != nullptr && extent->is_array()) {
            for (const auto& corner : *extent) {
                if (corner.is_array() && corner.size() >= 2
                    && corner[0].is_number() && corner[1].is_number()) {
                    survey.extent.emplace_back(corner[0].get<double>(),
                                               corner[1].get<double>());
                }
            }
        }
        out.push_back(std::move(survey));
    }
    return out;
}

// prediction_tasks -> ui_wellseis task slices (id/name/status/adapter_kind
// + the Json sub-objects the task panels read verbatim).
std::vector<ui_wellseis::PredictionTaskSlice> collect_prediction_tasks(
    const Json& root) {
    std::vector<ui_wellseis::PredictionTaskSlice> out;
    const Json* rows = jfield(root, "prediction_tasks");
    if (rows == nullptr || !rows->is_array()) return out;
    for (const auto& row : *rows) {
        if (!row.is_object()) continue;
        ui_wellseis::PredictionTaskSlice task;
        task.id = jstr(row, "id");
        task.name = jstr(row, "name");
        task.status = jstr(row, "status");
        task.adapter_kind = jstr(row, "adapter_kind");
        if (const Json* seed = jfield(row, "seed");
            seed != nullptr && seed->is_number_integer()) {
            task.seed = static_cast<int64_t>(seed->get<long long>());
        }
        if (const Json* refs = jfield(row, "input_refs");
            refs != nullptr && refs->is_object()) {
            for (auto it = refs->begin(); it != refs->end(); ++it) {
                if (!it.value().is_array()) continue;
                std::vector<std::string> ids;
                for (const auto& v : it.value()) {
                    if (v.is_string()) ids.push_back(v.get<std::string>());
                }
                task.input_refs[it.key()] = std::move(ids);
            }
        }
        if (const Json* v = jfield(row, "result_summary");
            v != nullptr && v->is_object()) {
            task.result_summary = *v;
        }
        if (const Json* v = jfield(row, "model_metadata");
            v != nullptr && v->is_object()) {
            task.model_metadata = *v;
        }
        if (const Json* v = jfield(row, "probability_summary");
            v != nullptr && v->is_object()) {
            task.probability_summary = *v;
        }
        out.push_back(std::move(task));
    }
    return out;
}

std::string project_crs_of(const Json& root) {
    const Json* coordinate = jfield(root, "coordinate");
    if (coordinate == nullptr || !coordinate->is_object()) return "";
    return jstr(*coordinate, "project_crs");
}

std::string project_root_of(const Json& root) {
    const Json* meta = jfield(root, "meta");
    if (meta == nullptr || !meta->is_object()) return "";
    return jstr(*meta, "project_root");
}

// ------------------------------------------------ stage-action helpers --
// Python well_prediction_surface.py POINTS/SURFACE_LAYER_TASK_ID verbatim.
constexpr const char* kPointsLayerTaskId = "well_facies_points";
constexpr const char* kSurfaceLayerTaskId = "well_facies_point_to_surface";

// (geometry, properties) pair — the _create_role_layer feature wire form.
using FeaturePairs = std::vector<std::pair<Json, Json>>;

// str(x or "").strip() parity for facies attribute reads.
std::string clean_str(const Json& object, const char* key) {
    const Json* v = jfield(object, key);
    if (v == nullptr || v->is_null()) return "";
    if (v->is_string()) {
        const std::string s = v->get<std::string>();
        const auto start = s.find_first_not_of(" \t\r\n");
        if (start == std::string::npos) return "";
        const auto end = s.find_last_not_of(" \t\r\n");
        return s.substr(start, end - start + 1);
    }
    if (v->is_boolean()) return v->get<bool>() ? "True" : "False";
    if (v->is_number_integer())
        return std::to_string(v->get<long long>());
    if (v->is_number()) {
        std::ostringstream out;
        out << v->get<double>();
        return out.str();
    }
    return "";
}

// Descriptor feature arrays arrive in two wire forms (both Python-parity):
// GeoJSON feature dicts {geometry, properties} and (geometry, properties)
// 2-tuples (integrated_compilation's classification_features). Accept
// both; never fabricate a geometry.
FeaturePairs feature_pairs_from_json(const Json& features) {
    FeaturePairs out;
    if (!features.is_array()) return out;
    for (const Json& item : features) {
        if (item.is_object()) {
            const Json* geometry = jfield(item, "geometry");
            if (geometry == nullptr || !geometry->is_object()) continue;
            Json properties = Json::object();
            if (const Json* props = jfield(item, "properties");
                props != nullptr && props->is_object()) {
                properties = *props;
            } else if (const Json* attrs = jfield(item, "attributes");
                       attrs != nullptr && attrs->is_object()) {
                properties = *attrs;
            }
            out.emplace_back(*geometry, std::move(properties));
        } else if (item.is_array() && item.size() == 2
                   && item[0].is_object() && item[1].is_object()) {
            out.emplace_back(item[0], item[1]);
        }
    }
    return out;
}

Json feature_array(const FeaturePairs& features) {
    Json out = Json::array();
    for (const auto& [geometry, properties] : features) {
        Json pair = Json::array();
        pair.push_back(geometry);
        pair.push_back(properties);
        out.push_back(std::move(pair));
    }
    return out;
}

// _categorized_facies_style parity (stage_actions.py L90-168): categorized
// fill style with SVG patterns; {} when no usable facies field. The dict
// form of categories is the surviving-layer wire format (list form crashes
// canvas publishing — Python V12 note).
Json categorized_facies_style(const FeaturePairs& features,
                              const std::string& forced_field = "") {
    std::vector<const Json*> buckets;
    for (const auto& item : features) {
        if (item.second.is_object()) buckets.push_back(&item.second);
    }
    const auto& blank = ui_workstation::blank_facies_values();
    const auto hits = [&](const char* key) {
        int count = 0;
        for (const Json* props : buckets) {
            if (blank.count(clean_str(*props, key)) == 0) ++count;
        }
        return count;
    };
    std::string field = forced_field;
    std::string other;
    if (!field.empty()) {
        // 相带分级图层：按目标级别字段分类，不与 facies_name 交叉回退。
        bool any = false;
        for (const Json* props : buckets) {
            if (blank.count(clean_str(*props, field.c_str())) == 0) {
                any = true;
                break;
            }
        }
        if (!any) return Json();
        other = "";
    } else {
        const int name_hits = hits("facies_name");
        const int facies_hits = hits("facies");
        if (name_hits == 0 && facies_hits == 0) return Json();
        field = name_hits >= facies_hits ? "facies_name" : "facies";
        other = field == "facies_name" ? "facies" : "facies_name";
    }

    std::vector<std::string> values;
    std::set<std::string> seen;
    std::map<std::string, std::string> first_color;
    for (const Json* props : buckets) {
        std::string value = clean_str(*props, field.c_str());
        if (value.empty()) value = clean_str(*props, other.c_str());
        if (blank.count(value) != 0 || value.empty()) continue;
        if (seen.insert(value).second) values.push_back(value);
        const std::string color = clean_str(*props, "color");
        if (!color.empty() && first_color.count(value) == 0) {
            first_color[value] = color;
        }
    }
    if (values.empty()) return Json();

    std::map<std::string, std::string> known_fills;
    for (const auto& [name, fill] :
         ui_widgets::core::facies_class_fills()) {
        known_fills[name] = fill;
    }
    ui_composite::VectorStyle style;
    style.fill = "#b0bec5";
    style.stroke = "#26364d";
    style.stroke_width = 0.6;
    style.renderer = "categorized";
    style.field = field;
    Json categories_dict = Json::object();
    for (const std::string& value : values) {
        const auto it = first_color.find(value);
        const std::string fill = ui_workstation::facies_category_color(
            value, it != first_color.end() ? it->second : "", known_fills);
        style.categories.emplace_back(value, fill, value);
        categories_dict[value] = fill;
        if (auto pattern = ui_widgets::core::pattern_id_for_facies(value)) {
            style.fill_patterns.emplace_back(value, *pattern);
        }
    }
    ui_composite::TextStyle labels;
    labels.field = field;
    labels.size = 9.0;
    labels.color = "#1f2937";
    labels.halo_color = "#f8f9fa";
    labels.halo_width = 1.0;
    style.labels = labels;
    Json dict = style.to_dict();
    dict["categories"] = std::move(categories_dict);
    return dict;
}


ui_seqviz::VizPageProjectSlice collect_viz_slice(
    const Json& root, project::ProjectDocument* document) {
    ui_seqviz::VizPageProjectSlice slice;
    slice.resources = collect_resource_items(root);
    if (const Json* docs = jfield(root, "paleomap_documents");
        docs != nullptr && docs->is_array()) {
        for (const auto& doc : *docs) {
            if (!doc.is_object()) continue;
            ui_seqviz::MapDocSlice entry;
            entry.id = jstr(doc, "id");
            entry.name = jstr(doc, "name");
            entry.raw = doc;
            slice.map_documents.push_back(std::move(entry));
        }
    }
    if (const Json* tasks = jfield(root, "prediction_tasks");
        tasks != nullptr && tasks->is_array()) {
        for (const auto& row : *tasks) {
            if (!row.is_object()) continue;
            ui_seqviz::PredictionTaskSlice entry;
            entry.id = jstr(row, "id");
            entry.name = jstr(row, "name");
            if (const Json* refs = jfield(row, "input_refs");
                refs != nullptr && refs->is_object()) {
                entry.input_refs = *refs;
            }
            entry.raw = row;
            slice.prediction_tasks.push_back(std::move(entry));
        }
    }
    slice.project_root = project_root_of(root);
    slice.comparison_crs = project_crs_of(root);
    if (document != nullptr) slice.raw = document;
    return slice;
}

ui_seqviz::StratigraphyProjectSlice collect_stratigraphy_slice(
    const Json& root) {
    ui_seqviz::StratigraphyProjectSlice slice;
    const Json* stratigraphy = jfield(root, "stratigraphy");
    if (stratigraphy != nullptr && stratigraphy->is_object()) {
        slice.stratigraphy.target_horizon =
            jstr(*stratigraphy, "target_horizon");
        slice.stratigraphy.interpretation_version =
            jstr(*stratigraphy, "interpretation_version", "v1");
        slice.stratigraphy.systems_tract_scheme =
            jstr(*stratigraphy, "systems_tract_scheme");
        slice.stratigraphy.applicable_wells =
            jstrlist(*stratigraphy, "applicable_wells");
        slice.stratigraphy.applicable_seismic_ranges =
            jstrlist(*stratigraphy, "applicable_seismic_ranges");
        slice.stratigraphy.sequence_boundaries =
            jstrlist(*stratigraphy, "sequence_boundaries");
    }
    if (const Json* runs = jfield(root, "compilation_runs");
        runs != nullptr && runs->is_array()) {
        for (const auto& run : *runs) {
            if (!run.is_object()) continue;
            ui_seqviz::CompilationRunSlice entry;
            entry.target_horizon = jstr(run, "target_horizon");
            entry.sequence_scheme_ref = jstr(run, "sequence_scheme_ref");
            slice.compilation_runs.push_back(std::move(entry));
        }
    }
    if (const Json* docs = jfield(root, "paleomap_documents");
        docs != nullptr && docs->is_array()) {
        for (const auto& doc : *docs) {
            if (!doc.is_object()) continue;
            ui_seqviz::PaleoMapDocumentSlice entry;
            entry.linked_target_horizon =
                jstr(doc, "linked_target_horizon");
            slice.paleomap_documents.push_back(std::move(entry));
        }
    }
    if (const Json* tasks = jfield(root, "factor_map_tasks");
        tasks != nullptr && tasks->is_array()) {
        for (const auto& task : *tasks) {
            if (!task.is_object()) continue;
            ui_seqviz::FactorTaskHorizonSlice entry;
            entry.name = jstr(task, "name");
            entry.target_horizon = jstr(task, "target_horizon");
            slice.factor_map_tasks.push_back(std::move(entry));
        }
    }
    return slice;
}

ui_workers::CorrelationProjectSlice collect_correlation_slice(
    const Json& root) {
    ui_workers::CorrelationProjectSlice slice;
    slice.resources = collect_resource_slices(root);
    slice.project_root = project_root_of(root);
    if (const Json* tasks = jfield(root, "prediction_tasks");
        tasks != nullptr && tasks->is_array() && !tasks->empty()) {
        slice.prediction_task = tasks->back();
    }
    return slice;
}

// --------------------------------------------------------------- binding --

class WorkflowBinding final : public QObject {
public:
    WorkflowBinding(QMainWindow* window, AppShell* shell,
                    AppContext* context, JobCenter* jobs)
        : QObject(window),
          window_(window), shell_(shell), context_(context) {
        controller_ = new ui_controllers::qt::WorkflowController(
            jobs->scheduler(), this);
        controller_->bind_dialogs(window_);
        bind_pages_();
        bind_services_();
        bind_grid_and_generation_();
        wire_signals_();
        install_factor_shelf_();
        notify_project_changed();
    }

    void notify_project_changed() {
        reopen_catalog_();
        push_project_to_pages_();
        controller_->rebind();
        controller_->core().refresh_home_steps();
    }

    ui_controllers::qt::WorkflowController* controller() const {
        return controller_;
    }

private:
    std::shared_ptr<application::PwbDataStore> store() const {
        return context_ != nullptr ? context_->projectStore() : nullptr;
    }

    project::ProjectDocument* document() const {
        const auto s = store();
        return s != nullptr ? &s->document() : nullptr;
    }

    // The shared workflow_runtime rail the mapping closure owns (SQLite
    // adapter preferred, JSON PersistentRuntimeCatalog fallback). Re-read
    // per call — notify_project_changed swaps the instance.
    workflow_runtime::CatalogRepository* runtime_catalog() const {
#if defined(PWB_WITH_FACTOR_KERNEL)
        return closure_mapping::factor_catalog(window_).get();
#else
        return nullptr;
#endif
    }

    ui_pages_mapedit::MapFactorShelf* factor_shelf() const {
        auto* page = shell_ != nullptr ? shell_->mapping_page() : nullptr;
        if (page == nullptr) return nullptr;
        auto* bottom = dynamic_cast<ui_pages_mapedit::MapWorkbenchBottom*>(
            page->bottom_workbench());
        return bottom != nullptr ? bottom->factor_shelf : nullptr;
    }

    void status(const std::string& message) const {
        if (message.empty()) return;
        if (window_ != nullptr && window_->statusBar() != nullptr) {
            window_->statusBar()->showMessage(
                QString::fromStdString(message), 8000);
        }
    }

    // --------------------------------------------------------- seam bags --

    void bind_pages_() {
        auto& pages = controller_->page_api();
        pages.document = [this]() -> project::ProjectDocument* {
            return document();
        };
        pages.navigate_to = [this](int hub, const std::string& submodule) {
            if (shell_ != nullptr) {
                shell_->navigate_to(
                    hub, QString::fromStdString(submodule));
            }
        };
        pages.update_home_page = [this](const Json& state,
                                        const Json& steps) {
            auto* page = shell_ != nullptr ? shell_->home_page() : nullptr;
            if (page == nullptr) return;
            std::vector<ui_pages_data::StepLike> step_list;
            if (steps.is_array()) {
                for (const auto& step : steps) {
                    if (!step.is_object()) continue;
                    step_list.push_back({jstr(step, "step_type"),
                                         jstr(step, "status")});
                }
            }
            page->update_state(state, step_list, document());
        };
        pages.update_data_page =
            [](const Json& state, const Json& resources,
               const Json& export_artifacts) {
            (void)state; (void)resources; (void)export_artifacts;
            // The unified data page refreshes from the live store through
            // the preview closure's refresh registry (asset rows +
            // re-identify); the section Jsons are already carried inside.
#if defined(PWB_WITH_CLOSURE_PREVIEW)
            closure_preview::notify_project_store_changed();
#endif
        };
        pages.update_review_export_page =
            [this](const Json& reports, const Json& paleomap_documents,
                   const Json& export_artifacts) {
            auto* page =
                shell_ != nullptr ? shell_->review_page() : nullptr;
            if (page == nullptr) return;
            page->update_state(reports, paleomap_documents,
                               export_artifacts);
        };
        pages.update_seismic_prediction_page =
            [this](const Json& prediction_tasks) {
            (void)prediction_tasks;
            auto* page =
                shell_ != nullptr ? shell_->seismic_page() : nullptr;
            const auto s = store();
            if (page == nullptr || s == nullptr) return;
            wellseis_slice_ = collect_wellseis_slice_(
                s->document().root());
            page->set_project(&wellseis_slice_);
            page->update_state(
                collect_prediction_tasks(s->document().root()),
                &wellseis_slice_);
        };
        pages.update_well_log_prediction_page =
            [this](const Json& prediction_tasks) {
            (void)prediction_tasks;
            auto* page =
                shell_ != nullptr ? shell_->well_log_page() : nullptr;
            const auto s = store();
            if (page == nullptr || s == nullptr) return;
            wellseis_slice_ = collect_wellseis_slice_(
                s->document().root());
            page->set_project(&wellseis_slice_);
            page->update_state(
                collect_prediction_tasks(s->document().root()),
                &wellseis_slice_);
        };
        pages.update_visualization_page =
            [this](const Json&, const Json&, const Json&) {
            push_visualization_();
        };
        pages.update_mapping_page =
            [this](const Json& paleomap_documents,
                   const Json& factor_map_tasks,
                   const std::string& project_crs) {
            (void)project_crs;
            auto* bank = closure_mapping::document_bank(window_);
            auto* page =
                shell_ != nullptr ? shell_->mapping_page() : nullptr;
            if (bank != nullptr && page != nullptr) {
                page->update_state(bank->documents(),
                                   bank->active_id());
            } else if (page != nullptr && paleomap_documents.is_array()) {
                page->update_state(
                    std::vector<Json>(paleomap_documents.begin(),
                                      paleomap_documents.end()),
                    "");
            }
            if (auto* shelf = factor_shelf();
                shelf != nullptr && factor_map_tasks.is_array()) {
                shelf->update_state(std::vector<Json>(
                    factor_map_tasks.begin(), factor_map_tasks.end()));
            }
        };
        pages.update_preparation_page = [this](const Json& tasks) {
            auto* page = closure_mapping::preparation_page(window_);
            if (page != nullptr) page->update_state(tasks);
        };
        pages.update_sequence_framework_page =
            [this](const Json& stratigraphy) {
            (void)stratigraphy;
            auto* page =
                shell_ != nullptr ? shell_->sequence_page() : nullptr;
            const auto s = store();
            if (page == nullptr || s == nullptr) return;
            stratigraphy_slice_ =
                collect_stratigraphy_slice(s->document().root());
            page->set_project(&stratigraphy_slice_);
            page->update_state(stratigraphy_slice_.stratigraphy);
        };
        pages.update_stratigraphy_correlation_page = [this]() {
            auto* page =
                shell_ != nullptr ? shell_->stratigraphy_page() : nullptr;
            const auto s = store();
            if (page == nullptr || s == nullptr) return;
            correlation_slice_ =
                collect_correlation_slice(s->document().root());
            project::ProjectDocument* doc = document();
            page->set_project(doc != nullptr
                                  ? std::any(doc)
                                  : std::any(),
                              correlation_slice_, doc);
            page->update_state();
        };
        pages.prep_summary_text = [this](const std::string& text) {
            auto* page = closure_mapping::preparation_page(window_);
            if (page == nullptr) return;
            if (auto* panel = page->task_panel();
                panel != nullptr && panel->summary_label() != nullptr) {
                panel->summary_label()->setText(
                    QString::fromStdString(text));
            }
        };
        pages.update_prep_state = [this](const Json& tasks) {
            auto* page = closure_mapping::preparation_page(window_);
            if (page != nullptr) page->update_state(tasks);
        };
        pages.mapping_is_dirty = [this]() -> bool {
            if (auto* bank = closure_mapping::document_bank(window_);
                bank != nullptr) {
                return bank->is_dirty();
            }
            auto* page =
                shell_ != nullptr ? shell_->mapping_page() : nullptr;
            return page != nullptr && page->is_dirty();
        };
        pages.mapping_save_draft = [this]() -> bool {
            std::string error;
            return closure_mapping::save_documents(window_, &error);
        };
        pages.mapping_set_project = [this]() {
            auto* bank = closure_mapping::document_bank(window_);
            auto* page =
                shell_ != nullptr ? shell_->mapping_page() : nullptr;
            if (bank != nullptr && page != nullptr) {
                page->update_state(bank->documents(),
                                   bank->active_id());
            }
        };
        pages.open_viz_ref = [this](const std::string& ref) {
            auto* page =
                shell_ != nullptr ? shell_->visualization_page()
                                  : nullptr;
            if (page == nullptr) return;
            ui_workers::VizRefSlice slice;
            const auto colon = ref.find(':');
            if (colon == std::string::npos) {
                slice.id = ref;
            } else {
                slice.kind = ref.substr(0, colon);
                slice.id = ref.substr(colon + 1);
            }
            page->open_ref(slice);
        };
        pages.select_well_resource =
            [this](const std::string& resource_id) -> bool {
            auto* page =
                shell_ != nullptr ? shell_->well_log_page() : nullptr;
            return page != nullptr
                   && page->select_well_resource(resource_id);
        };
        pages.select_seismic_resource =
            [this](const std::string& resource_id) -> bool {
            auto* page =
                shell_ != nullptr ? shell_->seismic_page() : nullptr;
            return page != nullptr
                   && page->select_seismic_resource(resource_id);
        };
        pages.set_source_import_status = [this](const std::string& text) {
            auto* page =
                shell_ != nullptr ? shell_->well_log_page() : nullptr;
            if (page != nullptr) {
                page->set_source_import_status(
                    QString::fromStdString(text));
            }
        };
        pages.refresh_shell = [this]() { push_project_to_pages_(); };
        // post_to_gui is bound by bind_dialogs (queued QMetaObject hop).
        // preview_settings*/begin_import_well_log_paths stay unset —
        // the menu/toolbar paths carry those surfaces already (honest
        // seam-absent degrade, Python getattr parity).
    }

    void bind_services_() {
        auto& services = controller_->services();
        services.dashboard_state = [](const Json& root) -> Json {
            return workflow_runtime::dashboard_state(root);
        };
        // home_workflow_steps writes the active-run progress back into
        // project.workflow_steps (service parity); the seam hands in the
        // live root as const — the underlying document is mutable.
        services.home_workflow_steps = [](const Json& root) -> Json {
            Json steps = Json::array();
            for (const auto& step : workflow_runtime::home_workflow_steps(
                     const_cast<Json&>(root))) {
                steps.push_back(step.to_dict());
            }
            return steps;
        };
        services.active_quality_reports = [](const Json& root) -> Json {
            Json reports = Json::array();
            for (const auto& report :
                 workflow_runtime::active_quality_reports(root)) {
                reports.push_back(report.to_dict());
            }
            return reports;
        };
        services.build_affected_plan =
            [this](const Json& root) -> workflow_runtime::RecomputePlan {
            return workflow_runtime::build_affected_products_plan(
                root, std::nullopt, runtime_catalog());
        };
#if defined(PWB_WITH_CLOSURE_WORKFLOW)
        services.compile_map_draft = [](Json& root, int seed) {
            closure_workflow::compile_map_draft(root, std::nullopt,
                                                std::nullopt, seed);
        };
        services.compile_map_production =
            [this](Json& root, const std::string& prediction_task_id,
                   const Json& prediction_payload,
                   ui_controllers::CatalogServiceApi* catalog_service,
                   const std::optional<std::string>&
                       prediction_version_id) {
            closure_workflow::ProductionMapCompileOptions options;
            if (!prediction_task_id.empty()) {
                options.prediction_task_id = prediction_task_id;
            }
            if (!prediction_payload.is_null()) {
                options.prediction_payload = &prediction_payload;
            }
            options.catalog = runtime_catalog();
            options.prediction_version_id = prediction_version_id;
            if (catalog_service != nullptr) {
                // get_model_version_by_id parity: a promoted (Output)
                // version is the only production-trusted one; the demo
                // flag rides the version metadata like the Python model
                // dict's demo_only.
                options.model_version_resolver =
                    [catalog_service](const std::string& version_id)
                    -> std::optional<
                        closure_workflow::ModelVersionTrust> {
                    try {
                        const auto version =
                            catalog_service->get_version(version_id);
                        closure_workflow::ModelVersionTrust trust;
                        trust.status =
                            version.stage == domain::DataStage::Output
                                ? "production"
                                : "review";
                        const Json* flag = jfield(version.metadata,
                                                  "demo_only");
                        trust.demo_only =
                            flag != nullptr && flag->is_boolean()
                                && flag->get<bool>();
                        return trust;
                    } catch (const std::exception&) {
                        return std::nullopt;
                    }
                };
            }
            closure_workflow::compile_map_production(root, options);
        };
#endif  // PWB_WITH_CLOSURE_WORKFLOW
#if defined(PWB_WITH_FACTOR_KERNEL)
        services.prepare_slice =
            [](const project::ProjectDocument& doc)
            -> ui_workers::PrepareProjectSlice {
            return factor_production::build_prepare_slice(doc.root());
        };
        services.commit_prepare =
            [this](project::ProjectDocument& doc,
                   const ui_workers::FactorPrepareBatchResult& result,
                   int expected_generation) -> int {
            if (grids_ == nullptr) return 0;
            const auto report =
                factor_production::commit_prepare_batch_result(
                    doc.root(), result, expected_generation, *grids_,
                    runtime_catalog(), project_crs_of(doc.root()));
            return static_cast<int>(report.discarded.size());
        };
#endif
    }

    void bind_grid_and_generation_() {
#if defined(PWB_WITH_FACTOR_KERNEL)
        grids_ = closure_mapping::factor_grid_store(window_);
        if (grids_ == nullptr) {
            grids_ =
                std::make_shared<factor_production::LiveFactorGridStore>();
        }
        auto grids = grids_;

        auto& generation = controller_->generation_api();
        generation.next =
            &factor_production::next_factor_prepare_generation;
        generation.current =
            &factor_production::current_factor_prepare_generation;

        auto& grid_api = controller_->grids_api();
        grid_api.store = [grids](const std::string& task_id,
                                 std::any grid) {
            if (auto* entry =
                    std::any_cast<factor_production::LiveGridEntry>(
                        &grid);
                entry != nullptr) {
                grids->store(task_id, *entry);
            }
        };
        grid_api.fingerprint =
            [](const std::any& grid) -> std::optional<std::string> {
            const auto* entry =
                std::any_cast<factor_production::LiveGridEntry>(&grid);
            if (entry == nullptr || entry->result_fingerprint.empty()) {
                return std::nullopt;
            }
            return entry->result_fingerprint;
        };
        grid_api.clear_if_fingerprint =
            [grids](const std::string& task_id,
                    const std::string& fingerprint) -> bool {
            return grids->clear_if_fingerprint(task_id, fingerprint);
        };

        controller_->prepare_seams() =
            factor_production::make_factor_prepare_seams(grids, {});

        auto& recompute = controller_->factor_recompute();
        recompute.interpolate_fn =
            [this, grids](Json& staged_task, const Json& project_root) {
            // Reuse the real batch kernel for a single staged task: slice
            // the task (same field reads as build_prepare_slice), run the
            // bound batch seam, write the patched task JSON back (#919 —
            // the task's own recorded algorithm parameters).
            ui_workers::FactorTaskSlice task;
            task.id = jstr(staged_task, "id");
            task.name = jstr(staged_task, "name");
            task.status = jstr(staged_task, "status", "pending");
            task.target_horizon = jstr(staged_task, "target_horizon");
            task.factor_type = jstr(staged_task, "factor_type");
            task.method = jstr(staged_task, "method");
            task.source_kind = jstr(staged_task, "source_kind", "mock");
            task.input_snapshot_hash =
                jstr(staged_task, "input_snapshot_hash");
            task.grid_artifact_path =
                jstr(staged_task, "grid_artifact_path");
            if (const Json* seed = jfield(staged_task, "seed");
                seed != nullptr && seed->is_number_integer()) {
                task.seed = static_cast<int>(seed->get<long long>());
            }
            if (const Json* params = jfield(staged_task, "parameters");
                params != nullptr && params->is_object()) {
                if (const Json* points = jfield(*params, "sample_points");
                    points != nullptr && points->is_array()) {
                    task.parameters["sample_points"] =
                        std::vector<std::map<std::string, std::any>>();
                    auto& out = std::any_cast<
                        std::vector<std::map<std::string, std::any>>&>(
                        task.parameters["sample_points"]);
                    for (const auto& point : *points) {
                        if (!point.is_object()) continue;
                        std::map<std::string, std::any> row;
                        for (auto it = point.begin(); it != point.end();
                             ++it) {
                            const Json& v = it.value();
                            if (v.is_number()) {
                                row[it.key()] = v.get<double>();
                            } else if (v.is_string()) {
                                row[it.key()] = v.get<std::string>();
                            } else if (v.is_boolean()) {
                                row[it.key()] = v.get<bool>();
                            }
                        }
                        out.push_back(std::move(row));
                    }
                }
            }
            task.source_json = staged_task;

            // The exec context references must outlive the batch call —
            // stage them on the binding's scratch members.
            ctx_coordinate_ = Json::object();
            if (const Json* c = jfield(project_root, "coordinate");
                c != nullptr && c->is_object()) ctx_coordinate_ = *c;
            ctx_stratigraphy_ = Json::object();
            if (const Json* s = jfield(project_root, "stratigraphy");
                s != nullptr && s->is_object()) ctx_stratigraphy_ = *s;
            ctx_constraints_.clear();
            if (const Json* layers = jfield(project_root,
                                            "constraint_layers");
                layers != nullptr && layers->is_array()) {
                for (const auto& layer : *layers) {
                    ctx_constraints_.emplace_back(layer);
                }
            }
            const std::string crs =
                jstr(ctx_coordinate_, "project_crs");
            ctx_crs_ = crs.empty()
                           ? std::optional<std::string>()
                           : std::optional<std::string>(crs);
            ui_workers::PrepareExecContext live_ctx{
                ctx_coordinate_, ctx_stratigraphy_, ctx_constraints_,
                ctx_crs_,
                task.method.empty() ? "IDW" : task.method, 50, 2.0, 0,
                task.target_horizon};

            auto seams =
                factor_production::make_factor_prepare_seams(grids, {});
            if (!seams.batch_fn) {
                throw std::runtime_error(
                    "插值内核未接入 — 无法重算因子图");
            }
            std::vector<ui_workers::FactorTaskSlice> tasks{task};
            ui_workers::FingerprintMemo memo;
            ui_workers::FactorPrepareSeams::BatchArgs args{
                tasks, live_ctx, /*force=*/true, &memo};
            job::CancellationToken token;
            seams.batch_fn(args, token);
            if (!tasks.empty() && tasks.front().source_json.has_value()) {
                staged_task = *tasks.front().source_json;
            }
        };
        recompute.grid_peek_fn =
            [grids](const std::string& task_id) -> std::any {
            if (auto entry = grids->peek(task_id)) {
                return std::any(*entry);
            }
            return std::any();
        };
#endif
    }

    void reopen_catalog_() {
#if defined(PWB_WITH_CATALOG_CLOSURE)
        const auto s = store();
        if (s == nullptr) {
            // No project: detach both surfaces (a closed adapter is not a
            // service — the controllers' degrade paths key on null).
            catalog_closure_.reset();
            controller_->catalog_api() = {};
            return;
        }
        closure_catalog::CatalogProjectIdentity identity;
        identity.project_path = s->project_file();
        const Json& root = s->document().root();
        // project_id is optional (空 = 未提供); meta.name is the display id.
        if (const Json* meta = jfield(root, "meta");
            meta != nullptr && meta->is_object()) {
            identity.project_id = jstr(*meta, "id");
            identity.project_name = jstr(*meta, "name");
        }
        auto installed = closure_catalog::InstalledCatalogClosure::install(
            identity.project_path, identity);
        if (!installed.is_ok()) {
            catalog_closure_.reset();
            controller_->catalog_api() = {};
            return;
        }
        // Final-home rule: emplace BEFORE make_runtime — the bag lambdas
        // capture the closure's `this`.
        catalog_closure_.emplace(std::move(installed.value()));
        controller_->catalog_api() = catalog_closure_->make_runtime();
#else
        controller_->catalog_api() = {};
#endif
    }

    void push_project_to_pages_() {
        auto& core = controller_->core();
        core.refresh_home_steps();
        core.refresh_data_page();
        core.on_qc_reports_updated();
        core.on_factor_maps_updated();
        core.on_stratigraphy_updated();
        core.on_well_log_prediction_updated();
        core.on_seismic_prediction_updated();
        core.on_contour_drafts_updated();
        push_visualization_();
        push_explorer_facts_();
    }

    // 资源管理器事实投影（原型左栏对象树）：工程文档 → ExplorerFacts →
    // explorer.set_facts —— 与 push_project_to_pages_ 同一刷新周期，
    // 工程打开/切换/写回后树随文档同步；无工程时给出诚实空态。
    void push_explorer_facts_() {
        auto* frame = shell_ != nullptr ? shell_->workstation() : nullptr;
        auto* explorer =
            frame != nullptr ? frame->explorer() : nullptr;
        if (explorer == nullptr) return;
        ui_workstation::ExplorerFacts facts;
        const auto s = store();
        facts.project_open = s != nullptr;
        if (s == nullptr) {
            explorer->set_facts(facts);
            return;
        }
        const Json& root = s->document().root();
        const auto array_len = [](const Json& obj, const char* key) -> int {
            const Json* v = jfield(obj, key);
            return (v != nullptr && v->is_array())
                       ? static_cast<int>(v->size())
                       : 0;
        };
        if (const Json* meta = jfield(root, "meta");
            meta != nullptr && meta->is_object()) {
            facts.project_name = jstr(*meta, "name");
        }
        if (const Json* area = jfield(root, "workarea");
            area != nullptr && area->is_object()) {
            facts.workarea_name = jstr(*area, "name");
        }
        if (const Json* stratigraphy = jfield(root, "stratigraphy");
            stratigraphy != nullptr && stratigraphy->is_object()) {
            facts.target_horizon =
                jstr(*stratigraphy, "target_horizon");
        }
        if (const Json* wells = jfield(root, "wells");
            wells != nullptr && wells->is_array()) {
            for (const auto& well : *wells) {
                if (!well.is_object()) continue;
                ui_workstation::ExplorerWellFact fact;
                fact.id = jstr(well, "id");
                fact.name = jstr(well, "name");
                facts.wells.push_back(std::move(fact));
            }
        }
        if (const Json* resources = jfield(root, "resources");
            resources != nullptr && resources->is_array()) {
            for (const auto& row : *resources) {
                if (!row.is_object()) continue;
                ui_workstation::ExplorerResourceFact fact;
                fact.id = jstr(row, "id");
                fact.name = jstr(row, "name");
                fact.type = jstr(row, "type");
                fact.path = jstr(row, "path");
                fact.format = jstr(row, "format");
                fact.status = jstr(row, "status");
                facts.resources.push_back(std::move(fact));
            }
        }
        if (const Json* entities = jfield(root, "geological_entities");
            entities != nullptr && entities->is_array()) {
            for (const auto& entity : *entities) {
                if (!entity.is_object()) continue;
                ui_workstation::ExplorerEntityFact fact;
                fact.name = jstr(entity, "name");
                facts.geological_entities.push_back(std::move(fact));
            }
        }
        if (const Json* layers = jfield(root, "user_vector_layers");
            layers != nullptr && layers->is_array()) {
            for (const auto& layer : *layers) {
                if (!layer.is_object()) continue;
                ui_workstation::ExplorerUserLayerFact fact;
                fact.id = jstr(layer, "id");
                fact.name = jstr(layer, "name", "编修图层");
                fact.geometry_kind = jstr(layer, "geometry_kind", "line");
                fact.feature_count = array_len(layer, "features");
                facts.user_layers.push_back(std::move(fact));
            }
        }
        if (const Json* docs = jfield(root, "paleomap_documents");
            docs != nullptr && docs->is_array()) {
            for (const auto& doc : *docs) {
                if (!doc.is_object()) continue;
                ui_workstation::ExplorerMapDocumentFact fact;
                fact.id = jstr(doc, "id");
                fact.name = jstr(doc, "name");
                fact.line_features = array_len(doc, "line_features");
                fact.facies_polygons = array_len(doc, "facies_polygons");
                fact.label_features = array_len(doc, "label_features");
                fact.reference_layers = array_len(doc, "reference_layers");
                facts.map_documents.push_back(std::move(fact));
            }
        }
        // 解释成果 = 层位解释 + 连井/地层对比解释（原型「解释要素」）。
        for (const char* key :
             {"horizon_interpretations", "correlation_interpretations"}) {
            const Json* rows = jfield(root, key);
            if (rows == nullptr || !rows->is_array()) continue;
            for (const auto& row : *rows) {
                if (!row.is_object()) continue;
                ui_workstation::ExplorerInterpretationFact fact;
                fact.id = jstr(row, "id");
                fact.name = jstr(row, "name");
                fact.current_version_id =
                    jstr(row, "current_version_id");
                facts.interpretations.push_back(std::move(fact));
            }
        }
        // 约束与单因素图 = 单因素图任务 + 约束图层组（原型分组）。
        for (const auto& [key, type] :
             {std::pair{"factor_map_tasks", "factor_map"},
              std::pair{"constraint_layers", "constraint_group"}}) {
            const Json* rows = jfield(root, key);
            if (rows == nullptr || !rows->is_array()) continue;
            for (const auto& row : *rows) {
                if (!row.is_object()) continue;
                ui_workstation::ExplorerResourceFact fact;
                fact.id = jstr(row, "id");
                fact.name = jstr(row, "name");
                fact.type = type;
                facts.factor_maps.push_back(std::move(fact));
            }
        }
        if (const Json* artifacts = jfield(root, "export_artifacts");
            artifacts != nullptr && artifacts->is_array()) {
            for (const auto& row : *artifacts) {
                if (!row.is_object()) continue;
                ui_workstation::ExplorerExportFact fact;
                fact.id = jstr(row, "id");
                fact.name = jstr(row, "name");
                fact.output_path = jstr(row, "output_path");
                facts.export_artifacts.push_back(std::move(fact));
            }
        }
        explorer->set_facts(facts);
    }

    void push_visualization_() {
        auto* page =
            shell_ != nullptr ? shell_->visualization_page() : nullptr;
        const auto s = store();
        if (page == nullptr) return;
        if (s == nullptr) {
            page->update_state(ui_seqviz::VizPageProjectSlice{});
            return;
        }
        page->set_project_path(s->project_file().string());
        viz_slice_ =
            collect_viz_slice(s->document().root(), document());
        page->update_state(viz_slice_);
    }

    ui_wellseis::ProjectSlice collect_wellseis_slice_(
        const Json& root) const {
        ui_wellseis::ProjectSlice slice;
        slice.resources = collect_resource_slices(root);
        slice.wells = collect_well_slices(root);
        slice.seismic_surveys = collect_survey_slices(root);
        slice.project_crs = project_crs_of(root);
        slice.project_root = project_root_of(root);
        if (const Json* stratigraphy = jfield(root, "stratigraphy");
            stratigraphy != nullptr && stratigraphy->is_object()) {
            slice.stratigraphy_target_horizon =
                jstr(*stratigraphy, "target_horizon");
        }
        if (const Json* boundary = jfield(root, "workarea_boundary");
            boundary != nullptr && boundary->is_array()) {
            for (const auto& corner : *boundary) {
                if (corner.is_array() && corner.size() >= 2
                    && corner[0].is_number() && corner[1].is_number()) {
                    slice.workarea_boundary.emplace_back(
                        corner[0].get<double>(), corner[1].get<double>());
                }
            }
        }
        slice.workarea_boundary_crs =
            jstr(root, "workarea_boundary_crs");
        return slice;
    }

    // ---------------------------------------------------- signal wiring --

    void wire_signals_() {
        if (shell_ == nullptr) return;
        controller_->wire_home_page(shell_->home_page());
        controller_->wire_data_visualization_jump(
            shell_->data_workspace());
        controller_->wire_mapping_page(shell_->mapping_page());
        controller_->wire_preparation_page(
            closure_mapping::preparation_page(window_));
        controller_->wire_sequence_page(shell_->sequence_page());
        controller_->wire_seismic_page(shell_->seismic_page());
        controller_->wire_well_log_page(shell_->well_log_page());
        controller_->wire_geomodel_page(shell_->geomodel_page());
        controller_->wire_review_page(shell_->review_page());

        // The typed-payload signals the string-connect wire_* cannot
        // reach (Python parity: integrator binds them directly).
        if (auto* page = shell_->well_log_page(); page != nullptr) {
            connect(
                page,
                &ui_wellseis::qt::WellLogPredictionPage::
                    well_log_import_requested,
                controller_,
                [this](const QStringList& paths) {
                    std::vector<std::filesystem::path> out;
                    out.reserve(static_cast<std::size_t>(paths.size()));
                    for (const auto& p : paths) {
                        out.emplace_back(p.toStdString());
                    }
                    controller_->core().on_well_log_import_requested(
                        out);
                });
        }

        auto* composite =
            shell_ != nullptr ? shell_->composite() : nullptr;
        if (composite != nullptr) {
            connect(
                composite,
                &ui_composite::CompositeDocument::
                    stage_action_requested,
                this,
                [this](const QString& /*stage*/,
                       const QString& action) {
                    status(dispatch_stage_action_(
                        action.toStdString()));
                });
            connect(
                composite,
                &ui_composite::CompositeDocument::
                    status_message,
                this, [this](const QString& message) {
                    status(message.toStdString());
                });
            connect(
                composite,
                &ui_composite::CompositeDocument::
                    hub_page_requested,
                this, [this](const QString& page_id) {
                    // Hub ids follow the page-stack keys (Python
                    // hub_page_requested parity) — navigation resolves
                    // the submodule inside the mapping hub.
                    if (shell_ != nullptr) {
                        shell_->navigate_to(ui_shell::kPageIndexMapping,
                                            page_id);
                    }
                });
        }
    }

    // --------------------------------------------------- stage actions --

    std::string dispatch_stage_action_(const std::string& action_id) {
        std::map<std::string, ui_workstation::StageActionHandler>
            handlers;
        handlers["stage_save"] = [this] { stage_save_(); };
        handlers["open_factor_workbench"] = [this] {
            if (shell_ != nullptr) {
                shell_->navigate_to(ui_shell::kPageIndexMapping,
                                    QStringLiteral("preparation"));
            }
        };
        handlers["run_qa"] = [this] { run_map_qa_(); };
        handlers["assemble_map_product"] = [this] {
            assemble_map_product_();
        };
        handlers["load_initial_facies"] = [this] {
            load_initial_facies_();
        };
        handlers["run_well_facies_mock"] = [this] {
            run_mock_prediction_("well");
        };
        handlers["run_seismic_facies_mock"] = [this] {
            run_mock_prediction_("seismic");
        };
        handlers["add_well_prediction_overlay"] = [this] {
            add_well_prediction_overlay_();
        };
        handlers["add_seismic_prediction_overlay"] = [this] {
            overlay_polygon_predictions_("seismic", /*emit=*/true);
        };
        handlers["well_prediction_point_to_surface"] = [this] {
            well_prediction_point_to_surface_();
        };
        handlers["toggle_prediction_confidence"] = [this] {
            toggle_prediction_confidence_();
        };
        handlers["create_facies_draft"] = [this] {
            create_facies_draft_();
        };
        handlers["overlay_factor_results"] = [this] {
            overlay_factor_results_();
        };
        handlers["commit_constraints"] = [this] {
            commit_constraints_();
        };
        handlers["select_evidence"] = [this] { select_evidence_(); };
        handlers["freeze_evidence_set"] = [this] {
            freeze_evidence_set_();
        };
        handlers["create_integrated_draft"] = [this] {
            create_integrated_draft_();
        };
        handlers["create_integrated_boundary"] = [this] {
            create_integrated_boundary_();
        };
        handlers["run_fusion"] = [this] { run_fusion_(); };
        handlers["commit_interpretation"] = [this] {
            commit_interpretation_();
        };
        const auto s = store();
        std::string horizon;
        if (s != nullptr) {
            if (const Json* stratigraphy =
                    jfield(s->document().root(), "stratigraphy");
                stratigraphy != nullptr) {
                horizon = jstr(*stratigraphy, "target_horizon");
            }
        }
        return ui_workstation::dispatch_stage_action(
            action_id, !horizon.empty(), handlers);
    }

    // ---------------------------------------------- workspace / composite --

    ui_composite::CompositeDocument* composite() const {
        return shell_ != nullptr ? shell_->composite() : nullptr;
    }

    ui_composite::CompositeEditController* edit_controller_() const {
        auto* doc = composite();
        return doc != nullptr ? doc->edit_controller : nullptr;
    }

    // The LIVE workspace authority (main_window.cpp applyLayerControlForOpen
    // publishes it per project open — the same state instance the save path
    // persists; a second authority would be clobbered on save).
    workspace::MappingWorkspaceState* workspace_state() const {
        if (window_ == nullptr) return nullptr;
        return static_cast<workspace::MappingWorkspaceState*>(
            window_->property("pwb.layer_workspace").value<void*>());
    }

    ui_composite::LayerGroupController* layer_groups_() const {
        if (window_ == nullptr) return nullptr;
        return static_cast<ui_composite::LayerGroupController*>(
            window_->property("pwb.layer_groups").value<void*>());
    }

    workspace::MappingWorkspaceState& require_workspace_() const {
        auto* state = workspace_state();
        if (state == nullptr) {
            throw std::runtime_error(
                "工作区状态不可用（图层控制面未接入本窗口）");
        }
        return *state;
    }

    ui_composite::LayerGroupController& require_groups_() const {
        auto* groups = layer_groups_();
        if (groups == nullptr) {
            throw std::runtime_error(
                "图层组控制器不可用（图层控制面未接入本窗口）");
        }
        return *groups;
    }

    // _sync_workspace_state_to_project parity: serialize the live state
    // into the project tree's mapping_workspace section (the store save
    // persists it right after).
    void sync_workspace_state_() {
        const auto s = store();
        auto* state = workspace_state();
        if (s == nullptr || state == nullptr) return;
        workspace::write_mapping_workspace(s->document().root(), *state);
    }

    // The workspace-state Json for the evidence/freshness seams (nullptr
    // when the live state is absent — Python workspace_state=None).
    Json workspace_json_() const {
        auto* state = workspace_state();
        return state != nullptr ? state->to_json() : Json();
    }

    Json* workspace_json_ptr_(Json& storage) const {
        auto* state = workspace_state();
        if (state == nullptr) return nullptr;
        storage = state->to_json();
        return &storage;
    }

    workflow_graph::WorkspaceView workspace_view_() const {
        auto* state = workspace_state();
        workflow_graph::WorkspaceView view;
        if (state == nullptr) return view;
        view.membership = [state](
                              const std::string&
                                  layer_id) -> std::optional<
            workflow_graph::WorkspaceMembership> {
            const auto* binding =
                workspace::membership(*state, layer_id);
            if (binding == nullptr) return std::nullopt;
            workflow_graph::WorkspaceMembership membership;
            membership.source_version_id = binding->source_version_id;
            return membership;
        };
        view.layers_with_role = [state](const std::string& role) {
            return workspace::layers_with_role(*state, role);
        };
        return view;
    }

    static FeaturePairs layer_feature_pairs_(
        const ui_composite::VectorLayer* layer) {
        FeaturePairs out;
        if (layer == nullptr) return out;
        for (const auto& feature : layer->features()) {
            out.emplace_back(feature.geometry, feature.attributes);
        }
        return out;
    }

    // Document-shaped layer record for the revision/interpretation domain
    // functions ({"id", "name", "features":[{"id","geometry","attributes"}]}).
    static Json layer_json_(const ui_composite::VectorLayer* layer) {
        Json features = Json::array();
        for (const auto& feature : layer->features()) {
            features.push_back(
                Json{{"id", feature.feature_id},
                     {"geometry", feature.geometry},
                     {"attributes", feature.attributes}});
        }
        return Json{{"id", layer->id()},
                    {"name", layer->name()},
                    {"features", std::move(features)}};
    }

    // --------------------------------------------- _create_role_layer etc --

    std::optional<std::string> create_role_layer_(
        const std::string& name, const std::string& kind,
        const std::string& role, const std::string& geo_template = "",
        const std::string& constraint_kind_value = "",
        const std::string& factor_task_id = "",
        const std::string& source_version_id = "",
        const FeaturePairs& features = {}) {
        auto* edit = edit_controller_();
        auto* groups = layer_groups_();
        if (edit == nullptr || groups == nullptr) {
            status("创建图层失败：图层控制面不可用（" + name + "）");
            return std::nullopt;
        }
        ui_composite::VectorLayer& layer = [&]() -> ui_composite::VectorLayer& {
            return edit->create_layer(name, kind, geo_template, role);
        }();
        const std::string layer_id = layer.id();
        groups->register_layer(layer_id, role, factor_task_id,
                               constraint_kind_value, source_version_id);
        try {
            if (auto hint = edit->apply_capture_spec(layer_id)) {
                status(*hint);
            }
        } catch (const std::exception&) {
            // V9 W9 hint is best-effort — a failing capture spec never
            // blocks layer creation.
        }
        if (!features.empty()) {
            // 可信导入通道（领域建稿 = 数据初始落盘，非用户编辑）。
            std::vector<ui_composite::VectorFeature> records;
            records.reserve(features.size());
            for (const auto& [geometry, properties] : features) {
                records.emplace_back(domain::make_id("f"), geometry,
                                     properties);
            }
            edit->import_layer_features(layer_id, records);
        }
        if (auto* doc = composite(); doc != nullptr) {
            doc->sync_composition(true);
        }
        return layer_id;
    }

    void remove_role_layer_(const std::string& layer_id) {
        auto* edit = edit_controller_();
        auto* groups = layer_groups_();
        if (groups != nullptr) groups->unregister_layer(layer_id);
        if (edit != nullptr) edit->remove_layer(layer_id);
    }

    // _apply_categorized_facies_style parity: style failure never blocks
    // layer creation (the layer IS the contract, style is enhancement).
    void apply_categorized_facies_style_(const std::string& layer_id,
                                         const FeaturePairs& features) {
        auto* edit = edit_controller_();
        if (edit == nullptr) return;
        try {
            const Json style = categorized_facies_style(features);
            if (style.is_null() || style.empty()) return;
            edit->set_layer_style(layer_id, style);
        } catch (const std::exception&) {
            // logger.exception parity — visible failure, no block.
        }
    }

    std::optional<std::string> stage_role_layer_(
        const std::string& role) {
        auto* state = workspace_state();
        auto* edit = edit_controller_();
        if (state == nullptr || edit == nullptr) return std::nullopt;
        for (const std::string& layer_id :
             workspace::layers_with_role(*state, role)) {
            if (edit->layer(layer_id) != nullptr) return layer_id;
        }
        return std::nullopt;
    }

    // ---------------------------------------------------------- Phase 1 --

    // _default_blank_facies_features parity: one closed workarea ring
    // polygon when the boundary has >= 3 finite vertices.
    FeaturePairs default_blank_facies_features_() const {
        const auto s = store();
        if (s == nullptr) return {};
        FeaturePairs out;
        Json ring = Json::array();
        const Json* boundary =
            jfield(s->document().root(), "workarea_boundary");
        if (boundary == nullptr || !boundary->is_array()) return out;
        for (const Json& vertex : *boundary) {
            if (!vertex.is_array() || vertex.size() < 2) continue;
            if (!vertex[0].is_number() || !vertex[1].is_number()) continue;
            const double x = vertex[0].get<double>();
            const double y = vertex[1].get<double>();
            if (!std::isfinite(x) || !std::isfinite(y)) continue;
            ring.push_back(Json::array({x, y}));
        }
        if (ring.size() < 3) return out;
        if (ring.front() != ring.back()) ring.push_back(ring.front());
        Json geometry = Json::object();
        geometry["type"] = "Polygon";
        geometry["coordinates"] = Json::array({ring});
        Json properties = Json::object();
        properties["facies"] = "空白相";
        properties["source"] = "workarea_default";
        out.emplace_back(std::move(geometry), std::move(properties));
        return out;
    }

    void load_initial_facies_() {
        const auto s = store();
        if (s == nullptr) throw std::runtime_error("请先打开工程");
        require_workspace_();
        if (stage_role_layer_(
                std::string(ui_composite::layer_role::kInitialFaciesSource))
                .has_value()) {
            status("初始相图已在图层树（01 初始沉积相）");
            return;
        }
        const Json& root = s->document().root();
        const Json* docs = jfield(root, "paleomap_documents");
        const Json* candidate = nullptr;
        if (docs != nullptr && docs->is_array()) {
            for (const Json& doc : *docs) {
                const Json* polygons = jfield(doc, "facies_polygons");
                if (polygons != nullptr && polygons->is_array()
                    && !polygons->empty()) {
                    candidate = &doc;
                    break;
                }
            }
        }
        if (candidate == nullptr) {
            FeaturePairs features = default_blank_facies_features_();
            if (features.empty()) {
                status("工程中没有初始沉积相图——先在编图页生成或导入相图文档");
                return;
            }
            auto layer_id = create_role_layer_(
                "初始相图（工区默认空白相）", "polygon",
                std::string(ui_composite::layer_role::kInitialFaciesSource),
                "", "", "", "", std::move(features));
            if (layer_id.has_value()) {
                // 默认空白相只是占位底：淡色半透明（#AARRGGBB 约 10%）
                // 只示意范围，不压住基础层。
                ui_composite::VectorStyle style;
                style.fill = "#1a64748b";
                style.stroke = "#94a3b8";
                style.stroke_width = 1.0;
                if (auto* edit = edit_controller_(); edit != nullptr) {
                    edit->set_layer_style(*layer_id, style.to_dict());
                }
                status("工程未指定初始相图，已按工区范围默认生成空白相"
                       "（1 个相面，RAW 不可编辑——用「创建解释草稿」开始校正）");
            }
            return;
        }
        FeaturePairs features;
        const Json& polygons = (*candidate)["facies_polygons"];
        for (const Json& polygon : polygons) {
            const Json* geometry = jfield(polygon, "geometry");
            if (geometry == nullptr || !geometry->is_object()) continue;
            Json properties = Json::object();
            if (const Json* props = jfield(polygon, "properties");
                props != nullptr && props->is_object()) {
                properties = *props;
            }
            if (!properties.contains("facies")
                || properties["facies"].is_null()) {
                properties["facies"] = jstr(polygon, "facies");
            }
            features.emplace_back(*geometry, std::move(properties));
        }
        if (features.empty()) {
            status("初始相图没有有效相面几何");
            return;
        }
        auto layer_id = create_role_layer_(
            jstr(*candidate, "name") + "（原始）", "polygon",
            std::string(ui_composite::layer_role::kInitialFaciesSource),
            "", "", "", "", std::move(features));
        if (layer_id.has_value()) {
            apply_categorized_facies_style_(*layer_id, features);
            status("已叠加初始相图（" + std::to_string(features.size())
                   + " 个相面，RAW 不可编辑——用「创建解释草稿」开始校正）");
        }
    }

    // -------------------------------------------------- mock predictions --

    void run_mock_prediction_(const std::string& kind) {
        const auto s = store();
        if (s == nullptr) throw std::runtime_error("请先打开工程");
        require_workspace_();
#if defined(PWB_WITH_CATALOG_CLOSURE) && defined(PWB_WITH_CLOSURE_SCIENCE)
        pwb::catalog::CatalogServiceCore* core = deep_catalog_core_();
        if (core == nullptr) {
            status("数据编目不可用——无法运行 mock 预测（预测结果必须落编目建血缘）");
            return;
        }
        const Json& root = s->document().root();
        std::string horizon;
        if (const Json* stratigraphy = jfield(root, "stratigraphy");
            stratigraphy != nullptr && stratigraphy->is_object()) {
            horizon = jstr(*stratigraphy, "target_horizon");
        }
        auto save = [core](const pwb::catalog::DirtySet& dirty) {
            return core->save(dirty);
        };
        auto seeded =
            closure_science::ensure_mock_facies_models(core->document(),
                                                       save);
        if (!seeded.is_ok()) {
            status(std::string("mock 模型注册失败：") + seeded.error().message);
            return;
        }
        const std::string model_version =
            kind == "well" ? seeded.value().first : seeded.value().second;

        Json parameters;
        try {
            parameters = mock_run_parameters_(root, horizon, kind);
        } catch (const std::runtime_error& exc) {
            status(exc.what());
            return;
        }
        std::random_device device;
        std::uniform_int_distribution<int> draw(0, 2147483647);
        parameters["seed"] = draw(device);
        const std::string operation = kind == "well" ? "well_facies_mock"
                                                     : "seismic_facies_mock";

        // resolve_prediction_inputs parity: the model's input version ids
        // from the project resources (the page binding's resource slice).
        std::vector<closure_science::ResourceRef> resources =
            catalog_resources_(root);
        auto inputs = closure_science::resolve_model_inputs(
            core->document(), resources, model_version);
        if (!inputs.is_ok()) {
            status(std::string("预测输入解析失败：") + inputs.error().message);
            return;
        }
        closure_science::StartInferenceRequest request;
        request.model_version_id = model_version;
        request.input_version_ids = inputs.value();
        request.parameters = parameters;
        request.operation = operation;
        auto started = closure_science::start_inference(core->document(),
                                                        save, request);
        if (!started.is_ok()) {
            status(std::string("mock 预测失败：") + started.error().message);
            return;
        }
        const std::string run_id = started.value().id.str();

        closure_science::ProviderRegistry providers;
        providers.register_provider(
            std::string(closure_science::kProviderMockWellFacies),
            closure_science::make_mock_well_facies_provider());
        providers.register_provider(
            std::string(closure_science::kProviderMockSeismicFacies),
            closure_science::make_mock_seismic_facies_provider());
        closure_science::ExecuteRunDeps deps;
        deps.save = save;
        deps.providers = &providers;
        const std::filesystem::path project_file = s->project_file();
        deps.project_dir = project_file.parent_path();
        deps.artifacts_root =
            deps.project_dir / (project_file.stem().string() + ".artifacts");
        auto executed = closure_science::execute_run(
            core->document(), deps, run_id);
        if (!executed.is_ok() || executed.value().cancelled
            || executed.value().payload.is_null()
            || executed.value().payload.empty()) {
            // execute_run 已把 run 置 failed（诚实失败）；此处只负责可见性。
            std::string detail;
            for (const auto& run : core->document().runs) {
                if (run.id.str() != run_id) continue;
                const Json* error = jfield(run.parameters, "error");
                if (error != nullptr && error->is_string()) {
                    detail = "：" + error->get<std::string>();
                }
                break;
            }
            status("mock 预测失败" + detail);
            return;
        }
        Json payload = executed.value().payload;
        try {
            register_mock_intermediates_(run_id, payload, kind);
        } catch (const std::exception& exc) {
            // 中间登记失败不得 orphan 主结果：task 照建，只明示缺失。
            status(std::string("中间文件登记失败（主结果已保留）：")
                   + exc.what());
        }

        // input_refs 按 kind 只记本类输入（Task 2 分类语义看键值非空）。
        std::vector<std::string> well_ids;
        std::vector<std::string> seismic_ids;
        if (const Json* rows = jfield(root, "resources");
            rows != nullptr && rows->is_array()) {
            for (const Json& row : *rows) {
                const std::string type = jstr(row, "type");
                if (type == "well_log") {
                    well_ids.push_back(jstr(row, "id"));
                } else if (type == "seismic") {
                    seismic_ids.push_back(jstr(row, "id"));
                }
            }
        }
        closure_science::PredictionTaskOptions options;
        options.name_prefix = kind == "well" ? "测井相预测（mock）"
                                             : "地震相面预测（mock）";
        options.workflow = operation;
        options.target_horizon = horizon;
        options.well_log_resource_ids = kind == "well" ? well_ids
                                                       : std::vector<std::string>{};
        options.seismic_resource_ids = kind == "seismic"
                                           ? seismic_ids
                                           : std::vector<std::string>{};
        options.run_id = run_id;
        options.output_version_id = executed.value().output_version_id;
        Json task = closure_science::materialize_prediction_task(
            core->document(), payload, options);
        if (jstr(task, "id").empty()) {
            task["id"] = domain::make_id("task_");
        }
        {
            Json& tasks = s->document().root()["prediction_tasks"];
            if (!tasks.is_array()) tasks = Json::array();
            tasks.push_back(task);
        }
        try {
            // link_run_to_domain_task parity: the public update_run_status
            // surface over the shared provenance rail (same catalog store).
            std::string run_status = "completed";
            for (const auto& run : core->document().runs) {
                if (run.id.str() == run_id) {
                    run_status = run.status;
                    break;
                }
            }
            if (auto* catalog = runtime_catalog(); catalog != nullptr) {
                Json extra = Json::object();
                extra["_domain_task_id"] = jstr(task, "id");
                catalog->update_run_status(run_id, run_status, extra);
            } else {
                throw std::runtime_error("目录服务不可用");
            }
        } catch (const std::exception&) {
            task["model_metadata"]["link_failed"] = true;
        }
        const Json* summary = jfield(task, "result_summary");
        if (kind == "well") {
            drop_stale_well_points_layer_();
            add_well_prediction_overlay_();
            int count = 0;
            if (summary != nullptr && summary->is_object()) {
                if (const Json* regions = jfield(*summary, "predicted_regions");
                    regions != nullptr && regions->is_array()) {
                    count = static_cast<int>(regions->size());
                }
            }
            status("已生成 " + std::to_string(count)
                   + " 口井的预测沉积相（mock，层位 " + horizon
                   + "），已叠加井点显示");
        } else {
            overlay_polygon_predictions_("seismic", /*emit=*/true);
            int count = 0;
            if (summary != nullptr && summary->is_object()) {
                if (const Json* spatial = jfield(*summary, "spatial");
                    spatial != nullptr && spatial->is_object()) {
                    if (const Json* features = jfield(*spatial, "features");
                        features != nullptr && features->is_array()) {
                        count = static_cast<int>(features->size());
                    }
                }
            }
            status("已生成面状沉积相（mock，层位 " + horizon + "）："
                   + std::to_string(count) + " 个相区，已叠加显示");
        }
        controller_->core().on_seismic_prediction_updated();
        controller_->core().on_well_log_prediction_updated();
#else
        (void)kind;
        throw std::runtime_error(
            "mock 预测服务未接入（编目/预测内核未启用）");
#endif
    }

#if defined(PWB_WITH_CATALOG_CLOSURE) && defined(PWB_WITH_CLOSURE_SCIENCE)
    // The deep core over the SAME catalog.sqlite the workflow rail reads
    // (closure_catalog_service.hpp documents this exact stage-action use).
    pwb::catalog::CatalogServiceCore* deep_catalog_core_() const {
        if (!catalog_closure_.has_value() || !catalog_closure_->active()) {
            return nullptr;
        }
        return catalog_closure_->adapter()->mutable_core();
    }

    static std::vector<closure_science::ResourceRef> catalog_resources_(
        const Json& root) {
        std::vector<closure_science::ResourceRef> out;
        const Json* rows = jfield(root, "resources");
        if (rows == nullptr || !rows->is_array()) return out;
        for (const Json& row : *rows) {
            if (!row.is_object()) continue;
            closure_science::ResourceRef ref;
            ref.id = jstr(row, "id");
            ref.type = jstr(row, "type");
            ref.path = jstr(row, "path");
            ref.catalog_asset_id = [&]() -> std::string {
                const Json* parsed = jfield(row, "parsed_summary");
                if (parsed == nullptr || !parsed->is_object()) return "";
                const Json* bridged =
                    jfield(*parsed, "catalog_asset_id");
                return bridged != nullptr && bridged->is_string()
                           ? bridged->get<std::string>()
                           : "";
            }();
            out.push_back(std::move(ref));
        }
        return out;
    }

    // _mock_run_parameters parity. Throws std::runtime_error on missing
    // inputs (InferenceInputError parity — the caller shows the message).
    Json mock_run_parameters_(const Json& root, const std::string& horizon,
                              const std::string& kind) const {
        if (kind == "well") {
            const Json* wells = jfield(root, "wells");
            if (wells == nullptr || !wells->is_array() || wells->empty()) {
                throw std::runtime_error("工程中没有井，无法生成测井相预测");
            }
            Json rows = Json::array();
            for (const Json& well : *wells) {
                Json row = Json::object();
                row["well_id"] = jstr(well, "id");
                row["well_name"] = jstr(well, "name");
                if (const Json* td = jfield(well, "td");
                    td != nullptr && td->is_number()) {
                    row["td"] = *td;
                } else {
                    row["td"] = nullptr;
                }
                rows.push_back(std::move(row));
            }
            Json parameters = Json::object();
            parameters["target_horizon"] = horizon;
            parameters["_wells"] = rows;
            parameters["wells"] = rows;
            return parameters;
        }
        // 面状相：工区边界 bbox（带 clip ring）→ 井位 bbox +10% → 地震工区。
        Json extent;
        Json ring;
        std::string extent_source;
        std::vector<std::pair<double, double>> corners;
        const Json* boundary = jfield(root, "workarea_boundary");
        if (boundary != nullptr && boundary->is_array()) {
            for (const Json& vertex : *boundary) {
                if (!vertex.is_array() || vertex.size() < 2) continue;
                if (!vertex[0].is_number() || !vertex[1].is_number()) {
                    continue;
                }
                const double x = vertex[0].get<double>();
                const double y = vertex[1].get<double>();
                if (std::isfinite(x) && std::isfinite(y)) {
                    corners.emplace_back(x, y);
                }
            }
        }
        if (corners.size() >= 3) {
            ring = Json::array();
            for (const auto& [x, y] : corners) {
                ring.push_back(Json::array({x, y}));
            }
            extent_source = "workarea_boundary";
        } else {
            corners.clear();
            const Json* wells = jfield(root, "wells");
            if (wells != nullptr && wells->is_array()) {
                for (const Json& well : *wells) {
                    const Json* px = jfield(well, "project_x");
                    const Json* py = jfield(well, "project_y");
                    if (px == nullptr || py == nullptr
                        || !px->is_number() || !py->is_number()) {
                        continue;
                    }
                    const double x = px->get<double>();
                    const double y = py->get<double>();
                    if (std::isfinite(x) && std::isfinite(y)) {
                        corners.emplace_back(x, y);
                    }
                }
            }
            if (!corners.empty()) {
                extent_source = "well_bbox";
            } else {
                corners.clear();
                const Json* surveys = jfield(root, "seismic_surveys");
                if (surveys != nullptr && surveys->is_array()) {
                    for (const Json& survey : *surveys) {
                        const Json* points = jfield(survey, "extent");
                        if (points == nullptr || !points->is_array()) continue;
                        for (const Json& point : *points) {
                            if (!point.is_array() || point.size() < 2) continue;
                            if (!point[0].is_number()
                                || !point[1].is_number()) {
                                continue;
                            }
                            const double x = point[0].get<double>();
                            const double y = point[1].get<double>();
                            if (std::isfinite(x) && std::isfinite(y)) {
                                corners.emplace_back(x, y);
                            }
                        }
                    }
                }
                if (corners.size() < 3) {
                    throw std::runtime_error(
                        "无可用平面范围（工区边界 / 井位 / 地震工区均为空），"
                        "无法生成面状沉积相");
                }
                extent_source = "seismic_survey";
            }
        }
        double xmin = corners.front().first;
        double ymin = corners.front().second;
        double xmax = xmin;
        double ymax = ymin;
        for (const auto& [x, y] : corners) {
            xmin = std::min(xmin, x);
            ymin = std::min(ymin, y);
            xmax = std::max(xmax, x);
            ymax = std::max(ymax, y);
        }
        if (extent_source == "well_bbox") {
            const double pad_x = std::max((xmax - xmin) * 0.1, 1.0);
            const double pad_y = std::max((ymax - ymin) * 0.1, 1.0);
            xmin -= pad_x;
            ymin -= pad_y;
            xmax += pad_x;
            ymax += pad_y;
        }
        extent = Json::array({xmin, ymin, xmax, ymax});
        const std::string crs = project_crs_of(root);
        Json parameters = Json::object();
        parameters["target_horizon"] = horizon;
        parameters["_extent"] = extent;
        parameters["extent"] = extent;
        parameters["_clip_ring"] = ring;
        parameters["clip_ring"] = ring;
        parameters["_crs"] = crs;
        parameters["crs"] = crs;
        parameters["grid_n"] = 80;
        parameters["extent_source"] = extent_source;
        return parameters;
    }

    // _register_mock_intermediates parity: INTERMEDIATE versions of the
    // same run through the shared provenance rail (payload transport is
    // the canonical text — the catalog_seam documented divergence).
    void register_mock_intermediates_(const std::string& run_id,
                                      Json& payload,
                                      const std::string& kind) {
        auto* catalog = runtime_catalog();
        if (catalog == nullptr) {
            throw std::runtime_error("目录服务不可用");
        }
        const Json asset_metadata =
            Json{{"kind", "prediction_intermediate"}};
        const Json version_metadata =
            Json{{"kind", "prediction_intermediate"}, {"mock", true}};
        if (kind == "well") {
            const auto it = payload.find("well_detail");
            if (it == payload.end() || it->is_null()) return;
            Json document = Json::object();
            document["wells"] = *it;
            payload.erase("well_detail");
            catalog->register_result_asset(
                "测井相预测（mock）逐井明细", "prediction_intermediate",
                "json", asset_metadata, document.dump(), "intermediate",
                run_id, version_metadata);
            return;
        }
        const auto it = payload.find("mock_grid");
        if (it == payload.end() || it->is_null()) return;
        factor_fusion::FactorGrid grid;
        const Json& source = *it;
        auto fill_axis = [](const Json& axis, std::vector<double>& out) {
            out.clear();
            if (!axis.is_array()) return;
            for (const Json& value : axis) {
                if (value.is_number()) out.push_back(value.get<double>());
            }
        };
        fill_axis(source["grid_x"], grid.grid_x);
        fill_axis(source["grid_y"], grid.grid_y);
        grid.width = static_cast<int>(grid.grid_x.size());
        grid.height = static_cast<int>(grid.grid_y.size());
        if (const Json* cells = jfield(source, "grid_z");
            cells != nullptr && cells->is_array()) {
            grid.grid_z.reserve(cells->size());
            for (const Json& cell : *cells) {
                if (cell.is_number()) {
                    grid.grid_z.push_back(cell.get<double>());
                }
            }
        }
        if (grid.grid_z.empty() || grid.width == 0 || grid.height == 0) {
            return;
        }
        grid.factor_name = "地震相面预测（mock）中间栅格";
        grid.algorithm_id = "mock_nearest_neighbor";
        grid.algorithm_parameters = Json{{"grid_n", 80}};
        if (const Json* crs = jfield(source, "crs");
            crs != nullptr && crs->is_string()) {
            grid.crs = crs->get<std::string>();
        }
        payload.erase("mock_grid");
#if defined(PWB_WITH_CLOSURE_WORKFLOW)
        const std::string text = closure_workflow::encode_grid_artifact(
            grid, "地震相面预测（mock）中间栅格");
#else
        const std::string text = source.dump();
#endif
        catalog->register_result_asset(
            "地震相面预测（mock）中间栅格", "prediction_intermediate",
            "json", asset_metadata, text, "intermediate", run_id,
            version_metadata);
    }
#endif  // CATALOG_CLOSURE && CLOSURE_SCIENCE

    // ----------------------------------------------- prediction overlays --

    struct OverlayCounts {
        int added = 0;
        int already = 0;
        int unmatched = 0;
    };

    void add_well_prediction_overlay_() {
        const auto s = store();
        if (s == nullptr) throw std::runtime_error("请先打开工程");
        require_workspace_();
        const OverlayCounts poly = overlay_polygon_predictions_(
            "well", /*emit=*/false);
        const OverlayCounts points = overlay_well_prediction_points_();
        std::vector<std::string> parts;
        if (points.added > 0) {
            parts.push_back("已叠加 " + std::to_string(points.added)
                            + " 个测井预测井点");
        } else if (points.already > 0) {
            parts.push_back("测井预测井点已在图层树");
        }
        if (poly.added > 0) {
            parts.push_back("已叠加 " + std::to_string(poly.added)
                            + " 个测井预测相面（不可编辑）");
        } else if (poly.already > 0) {
            parts.push_back(std::to_string(poly.already)
                            + " 个测井预测相面此前已叠加");
        }
        if (parts.empty()) {
            std::string detail =
                "没有可叠加的测井相预测结果（需要井位坐标 + 预测区间，"
                "或 VECTOR_POLYGONS）";
            if (points.unmatched > 0) {
                detail += "；" + std::to_string(points.unmatched)
                          + " 个测井任务缺少井位，未落点";
            }
            if (poly.unmatched > 0) {
                detail += "；" + std::to_string(poly.unmatched)
                          + " 个任务无法判别井/震类别";
            }
            status(detail);
            return;
        }
        if (points.unmatched > 0) {
            parts.push_back(std::to_string(points.unmatched)
                            + " 个测井任务缺少井位，未落点");
        }
        status(join_parts_(parts));
    }

    static std::string join_parts_(const std::vector<std::string>& parts) {
        std::string out;
        for (const std::string& part : parts) {
            if (!out.empty()) out += "；";
            out += part;
        }
        return out;
    }

    void drop_stale_well_points_layer_() {
        auto* state = workspace_state();
        auto* edit = edit_controller_();
        if (state == nullptr || edit == nullptr) return;
        for (const std::string& layer_id : workspace::layers_with_role(
                 *state,
                 std::string(ui_composite::layer_role::kWellFaciesPrediction))) {
            const auto* binding = workspace::membership(*state, layer_id);
            if (binding == nullptr
                || binding->factor_task_id != kPointsLayerTaskId) {
                continue;
            }
            if (edit->layer(layer_id) == nullptr) continue;
            remove_role_layer_(layer_id);
        }
    }

    // well_xy parity: 工程 CRS 坐标优先，源坐标其次；井表行列回退。
    static std::optional<std::pair<double, double>> well_xy_(
        const Json& well, const Json& root) {
        const auto number = [](const char* key,
                               const Json& object) -> std::optional<double> {
            const Json* v = jfield(object, key);
            if (v == nullptr || !v->is_number()) return std::nullopt;
            const double value = v->get<double>();
            return std::isfinite(value) ? std::optional<double>(value)
                                        : std::nullopt;
        };
        auto x = number("project_x", well);
        auto y = number("project_y", well);
        if (!x.has_value() || !y.has_value()) {
            x = number("surface_x", well);
            y = number("surface_y", well);
        }
        if (x.has_value() && y.has_value()) return std::make_pair(*x, *y);
        std::set<std::string> want;
        for (const char* key : {"id", "name"}) {
            const std::string value = jstr(well, key);
            if (!value.empty()) {
                want.insert(pwb::data::normalize_well_name(value));
            }
        }
        want.erase("");
        if (want.empty()) return std::nullopt;
        const Json* tables = jfield(root, "well_tables");
        if (tables == nullptr || !tables->is_array()) return std::nullopt;
        for (const Json& table : *tables) {
            const Json* rows = jfield(table, "rows");
            if (rows == nullptr || !rows->is_array()) continue;
            for (const Json& row : *rows) {
                bool overlap = false;
                for (const char* key : {"well_id", "name"}) {
                    const std::string value = jstr(row, key);
                    if (value.empty()) continue;
                    if (want.count(pwb::data::normalize_well_name(value))
                        != 0) {
                        overlap = true;
                        break;
                    }
                }
                if (!overlap) continue;
                const auto rx = number("x", row);
                const auto ry = number("y", row);
                if (rx.has_value() && ry.has_value()) {
                    return std::make_pair(*rx, *ry);
                }
            }
        }
        return std::nullopt;
    }

    static const Json* find_well_(const Json& root, const std::string& key) {
        const Json* wells = jfield(root, "wells");
        if (wells == nullptr || !wells->is_array()) return nullptr;
        const std::string normalized = pwb::data::normalize_well_name(key);
        for (const Json& well : *wells) {
            if (jstr(well, "id") == key || jstr(well, "name") == key) {
                return &well;
            }
        }
        for (const Json& well : *wells) {
            if (pwb::data::normalize_well_name(jstr(well, "id")) == normalized
                || pwb::data::normalize_well_name(jstr(well, "name"))
                       == normalized) {
                return &well;
            }
        }
        return nullptr;
    }

    // well_facies_points parity (spatial Point 优先，否则区间 + 井位).
    std::vector<mapping::WellFaciesPoint> well_facies_points_() const {
        std::vector<mapping::WellFaciesPoint> points;
        const auto s = store();
        if (s == nullptr) return points;
        const Json& root = s->document().root();
        std::string horizon;
        if (const Json* stratigraphy = jfield(root, "stratigraphy");
            stratigraphy != nullptr && stratigraphy->is_object()) {
            horizon = jstr(*stratigraphy, "target_horizon");
        }
        const Json* tasks = jfield(root, "prediction_tasks");
        if (tasks == nullptr || !tasks->is_array()) return points;
        for (const Json& task : *tasks) {
            if (ui_composite::classify_prediction_task(task) != "well") {
                continue;
            }
            const std::string task_id = jstr(task, "id");
            const Json* summary = jfield(task, "result_summary");
            if (summary != nullptr && summary->is_object()) {
                auto spatial =
                    mapping::spatial_point_features(*summary, task_id);
                if (!spatial.empty()) {
                    points.insert(points.end(), spatial.begin(),
                                  spatial.end());
                    continue;
                }
            }
            // _points_from_intervals parity: regions × well registry.
            if (summary == nullptr || !summary->is_object()) continue;
            Json regions = mapping::task_regions(*summary);
            if (!regions.is_array() || regions.empty()) continue;
            // _wells_for_task bounded port: wells referenced through
            // input_refs (resource ids → resource name/id → well rows).
            std::vector<const Json*> wells_for_task;
            std::set<std::string> seen_wells;
            const auto add_well = [&](const Json& well) {
                const std::string id = jstr(well, "id");
                if (id.empty() || seen_wells.count(id) != 0) return;
                seen_wells.insert(id);
                wells_for_task.push_back(&well);
            };
            if (const Json* refs = jfield(task, "input_refs");
                refs != nullptr && refs->is_object()) {
                for (const char* key : {"well_log_resource_ids",
                                        "well_logs", "well", "wells"}) {
                    const Json* values = jfield(*refs, key);
                    if (values == nullptr) continue;
                    std::vector<std::string> ids;
                    if (values->is_string()) {
                        ids.push_back(values->get<std::string>());
                    } else if (values->is_array()) {
                        for (const Json& value : *values) {
                            if (value.is_string()) {
                                ids.push_back(value.get<std::string>());
                            }
                        }
                    }
                    for (const std::string& resource_id : ids) {
                        if (resource_id.empty()) continue;
                        if (const Json* well = find_well_(root, resource_id)) {
                            add_well(*well);
                            continue;
                        }
                        const Json* rows = jfield(root, "resources");
                        if (rows == nullptr || !rows->is_array()) continue;
                        for (const Json& row : *rows) {
                            if (jstr(row, "id") != resource_id) continue;
                            if (const Json* by_name =
                                    find_well_(root, jstr(row, "name"))) {
                                add_well(*by_name);
                            }
                            break;
                        }
                    }
                }
            }
            // group regions by well key (insertion order preserved).
            std::vector<std::pair<std::string, std::vector<Json>>> grouped;
            std::map<std::string, std::size_t> index;
            for (const Json& record : regions) {
                if (!record.is_object()) continue;
                std::string key;
                for (const char* candidate :
                     {"well_id", "well_name", "well"}) {
                    key = clean_str(record, candidate);
                    if (!key.empty()) break;
                }
                const auto it = index.find(key);
                if (it == index.end()) {
                    index[key] = grouped.size();
                    grouped.emplace_back(key,
                                         std::vector<Json>{record});
                } else {
                    grouped[it->second].second.push_back(record);
                }
            }
            const auto emit_point =
                [&](const Json& well,
                    const std::vector<Json>& records) {
                const auto xy = well_xy_(well, root);
                const auto picked =
                    mapping::representative_facies(Json(records), horizon);
                if (!xy.has_value() || !picked.has_value()) return;
                mapping::WellFaciesPoint point;
                point.x = xy->first;
                point.y = xy->second;
                point.facies = picked->facies;
                point.well_id = jstr(well, "id");
                point.well_name = jstr(well, "name");
                point.probability = picked->mean_probability;
                point.task_id = task_id;
                if (picked->thickness > 0.0) {
                    point.thickness = picked->thickness;
                }
                points.push_back(std::move(point));
            };
            if (grouped.size() == 1 && grouped.front().first.empty()
                && wells_for_task.size() == 1) {
                emit_point(*wells_for_task.front(),
                           grouped.front().second);
                continue;
            }
            for (const auto& [key, records] : grouped) {
                const Json* well =
                    key.empty() ? nullptr : find_well_(root, key);
                if (well == nullptr && wells_for_task.size() == 1) {
                    well = wells_for_task.front();
                }
                if (well != nullptr) emit_point(*well, records);
            }
        }
        return points;
    }

    OverlayCounts overlay_well_prediction_points_() {
        OverlayCounts out;
        auto* state = workspace_state();
        auto* edit = edit_controller_();
        if (state == nullptr || edit == nullptr) return out;
        bool existing = false;
        for (const std::string& layer_id : workspace::layers_with_role(
                 *state,
                 std::string(ui_composite::layer_role::kWellFaciesPrediction))) {
            const auto* binding = workspace::membership(*state, layer_id);
            if (binding != nullptr
                && binding->factor_task_id == kPointsLayerTaskId
                && edit->layer(layer_id) != nullptr) {
                existing = true;
            }
        }
        auto points = well_facies_points_();
        int well_tasks = 0;
        if (const auto s = store()) {
            if (const Json* tasks =
                    jfield(s->document().root(), "prediction_tasks");
                tasks != nullptr && tasks->is_array()) {
                for (const Json& task : *tasks) {
                    if (ui_composite::classify_prediction_task(task)
                        == "well") {
                        ++well_tasks;
                    }
                }
            }
        }
        std::set<std::string> tasked;
        for (const auto& point : points) {
            if (!point.task_id.empty()) tasked.insert(point.task_id);
        }
        out.unmatched =
            std::max(0, well_tasks - static_cast<int>(tasked.size()));
        if (existing) {
            out.already = points.empty() ? 1 : static_cast<int>(points.size());
            return out;
        }
        if (points.empty()) return out;
        std::string horizon;
        if (const auto s = store()) {
            if (const Json* stratigraphy =
                    jfield(s->document().root(), "stratigraphy");
                stratigraphy != nullptr && stratigraphy->is_object()) {
                horizon = jstr(*stratigraphy, "target_horizon");
            }
        }
        FeaturePairs features = mapping::point_features(points);
        for (auto& [geometry, properties] : features) {
            if (!horizon.empty()) properties["horizon"] = horizon;
        }
        std::string title = "测井预测相（井点）";
        if (!horizon.empty()) title += " · " + horizon;
        auto created = create_role_layer_(
            title, "point",
            std::string(ui_composite::layer_role::kWellFaciesPrediction),
            "", "", kPointsLayerTaskId, "", features);
        out.added = created.has_value()
                        ? static_cast<int>(points.size())
                        : 0;
        return out;
    }

    OverlayCounts overlay_polygon_predictions_(const std::string& prefer,
                                               bool emit_message) {
        OverlayCounts out;
        const auto s = store();
        auto* state = workspace_state();
        auto* edit = edit_controller_();
        if (s == nullptr || state == nullptr || edit == nullptr) {
            return out;
        }
        const std::string wanted =
            prefer == "well" ? "well" : "seismic";
        const std::string role =
            wanted == "well"
                ? std::string(ui_composite::layer_role::kWellFaciesPrediction)
                : std::string(
                      ui_composite::layer_role::kSeismicFaciesPrediction);
        const Json& root = s->document().root();
        std::string horizon;
        if (const Json* stratigraphy = jfield(root, "stratigraphy");
            stratigraphy != nullptr && stratigraphy->is_object()) {
            horizon = jstr(*stratigraphy, "target_horizon");
        }
        const Json* tasks = jfield(root, "prediction_tasks");
        if (tasks != nullptr && tasks->is_array()) {
            for (const Json& task : *tasks) {
                const std::string category =
                    ui_composite::classify_prediction_task(task);
                if (category != wanted) {
                    if (category == "unknown") ++out.unmatched;
                    continue;
                }
                // 幂等：该任务在该角色下已有叠加图层则跳过（防连点堆积）。
                const std::string task_marker = jstr(task, "id");
                bool already = false;
                for (const std::string& layer_id :
                     workspace::layers_with_role(*state, role)) {
                    const auto* binding =
                        workspace::membership(*state, layer_id);
                    if (binding != nullptr
                        && binding->factor_task_id == task_marker
                        && edit->layer(layer_id) != nullptr) {
                        already = true;
                        break;
                    }
                }
                if (already) {
                    ++out.already;
                    continue;
                }
                const Json* summary = jfield(task, "result_summary");
                Json features_json = Json();
                if (summary != nullptr && summary->is_object()) {
                    if (const Json* spatial = jfield(*summary, "spatial");
                        spatial != nullptr && spatial->is_object()) {
                        const Json* raw = jfield(*spatial, "features");
                        if (raw != nullptr && raw->is_array()
                            && !raw->empty()) {
                            features_json = *raw;
                        }
                    }
                }
                if (features_json.is_null()) {
                    Json payload = Json::object();
                    if (summary != nullptr) {
                        payload["result_summary"] = *summary;
                    }
                    try {
                        features_json =
                            prediction::extract_polygon_features(payload);
                    } catch (const std::exception&) {
                        features_json = Json::array();
                    }
                }
                FeaturePairs features;
                for (const Json& record : features_json) {
                    if (!record.is_object()) continue;
                    const Json* geometry = jfield(record, "geometry");
                    if (geometry == nullptr || !geometry->is_object()) {
                        continue;
                    }
                    const std::string gtype = jstr(*geometry, "type");
                    if (gtype != "Polygon" && gtype != "MultiPolygon") {
                        continue;
                    }
                    Json properties = Json::object();
                    if (const Json* props = jfield(record, "properties");
                        props != nullptr && props->is_object()) {
                        properties = *props;
                    }
                    if (!horizon.empty()) properties["horizon"] = horizon;
                    features.emplace_back(*geometry,
                                          std::move(properties));
                }
                if (features.empty()) continue;
                const std::string kind_label =
                    wanted == "well" ? "测井" : "地震";
                std::string title =
                    jstr(task, "name").empty() ? "预测相"
                                               : jstr(task, "name");
                title += "（" + kind_label + "预测）";
                if (!horizon.empty()) title += " · " + horizon;
                auto created = create_role_layer_(title, "polygon", role,
                                                  "", "", task_marker, "",
                                                  features);
                if (created.has_value()) {
                    apply_categorized_facies_style_(*created, features);
                    ++out.added;
                }
            }
        }
        if (emit_message) {
            const std::string label = wanted == "well" ? "测井" : "地震";
            if (out.added == 0) {
                std::vector<std::string> parts{
                    "没有可叠加的" + label
                    + "预测空间结果（需要 VECTOR_POLYGONS 预测任务）"};
                if (out.unmatched > 0) {
                    parts.push_back(
                        std::to_string(out.unmatched)
                        + " 个任务无法判别井/震类别（经 input_refs/任务名），未叠加");
                }
                status(join_parts_(parts));
            } else {
                std::string message = "已叠加 " + std::to_string(out.added)
                                      + " 个" + label
                                      + "预测结果图层（不可编辑）";
                if (out.already > 0) {
                    message += "；" + std::to_string(out.already)
                               + " 个此前已叠加，跳过";
                }
                status(message);
            }
        }
        return out;
    }

    void well_prediction_point_to_surface_() {
        const auto s = store();
        if (s == nullptr) throw std::runtime_error("请先打开工程");
        auto& state = require_workspace_();
        auto* edit = edit_controller_();
        if (edit == nullptr) {
            throw std::runtime_error("图层控制面不可用");
        }
        std::vector<std::string> existing;
        for (const std::string& layer_id : workspace::layers_with_role(
                 state,
                 std::string(ui_composite::layer_role::kWellFaciesPrediction))) {
            const auto* binding = workspace::membership(state, layer_id);
            if (binding != nullptr
                && binding->factor_task_id == kSurfaceLayerTaskId
                && edit->layer(layer_id) != nullptr) {
                existing.push_back(layer_id);
            }
        }
        auto points = well_facies_points_();
        if (points.empty()) {
            status("没有可做点到面的测井预测井点——需要测井相预测结果，"
                   "且井位要有坐标");
            return;
        }
        const Json& root = s->document().root();
        std::vector<mapping::Point> boundary;
        if (const Json* ring = jfield(root, "workarea_boundary");
            ring != nullptr && ring->is_array()) {
            for (const Json& vertex : *ring) {
                if (!vertex.is_array() || vertex.size() < 2) continue;
                if (!vertex[0].is_number() || !vertex[1].is_number()) {
                    continue;
                }
                const double x = vertex[0].get<double>();
                const double y = vertex[1].get<double>();
                if (std::isfinite(x) && std::isfinite(y)) {
                    boundary.push_back(mapping::Point{x, y});
                }
            }
        }
        auto extent = mapping::extent_from_workarea_boundary(boundary);
        std::vector<mapping::Point> clip_ring;
        if (extent.has_value()) {
            clip_ring = mapping::clip_ring_from_boundary(boundary);
        } else {
            extent = mapping::extent_from_points(points);
        }
        FeaturePairs features = mapping::point_to_surface_features(
            points, *extent, /*grid_n=*/80, clip_ring, project_crs_of(root));
        if (features.empty()) {
            status("点到面未生成相面（井点不足或工区范围无效）");
            return;
        }
        std::string horizon;
        if (const Json* stratigraphy = jfield(root, "stratigraphy");
            stratigraphy != nullptr && stratigraphy->is_object()) {
            horizon = jstr(*stratigraphy, "target_horizon");
        }
        if (!horizon.empty()) {
            for (auto& [geometry, properties] : features) {
                properties["horizon"] = horizon;
            }
        }
        for (const std::string& layer_id : existing) {
            remove_role_layer_(layer_id);
        }
        std::string title = "测井预测相（点到面）";
        if (!horizon.empty()) title += " · " + horizon;
        auto created = create_role_layer_(
            title, "polygon",
            std::string(ui_composite::layer_role::kWellFaciesPrediction),
            "", "", kSurfaceLayerTaskId, "", features);
        if (created.has_value()) {
            const std::string scope =
                horizon.empty() ? "" : "（层位 " + horizon + "）";
            status("已由 " + std::to_string(points.size())
                   + " 个测井预测井点生成点到面相面" + scope + "（"
                   + std::to_string(features.size())
                   + " 个相多边形，不可编辑）");
        } else {
            status("测井点到面图层创建失败");
        }
    }

    void toggle_prediction_confidence_() {
        const auto s = store();
        if (s == nullptr) throw std::runtime_error("请先打开工程");
        auto& state = require_workspace_();
        auto* edit = edit_controller_();
        if (edit == nullptr) {
            throw std::runtime_error("图层控制面不可用");
        }
        const std::string roles[] = {
            std::string(ui_composite::layer_role::kWellFaciesConfidence),
            std::string(ui_composite::layer_role::kSeismicFaciesConfidence)};
        std::vector<std::string> existing;
        for (const auto& role : roles) {
            for (const std::string& layer_id :
                 workspace::layers_with_role(state, role)) {
                if (edit->layer(layer_id) != nullptr) {
                    existing.push_back(layer_id);
                }
            }
        }
        if (!existing.empty()) {
            for (const std::string& layer_id : existing) {
                remove_role_layer_(layer_id);
            }
            if (auto* doc = composite(); doc != nullptr) {
                doc->sync_composition(true);
            }
            status("已移除 " + std::to_string(existing.size())
                   + " 个预测置信度叠加图层");
            return;
        }
        const Json& root = s->document().root();
        int added = 0;
        if (const Json* tasks = jfield(root, "prediction_tasks");
            tasks != nullptr && tasks->is_array()) {
            for (const Json& task : *tasks) {
                for (const Json& descriptor :
                     ui_composite::confidence_overlay_layers(root, task)) {
                    if (!descriptor.is_object()) continue;
                    Json metadata = Json::object();
                    if (const Json* meta = jfield(descriptor, "metadata");
                        meta != nullptr && meta->is_object()) {
                        metadata = *meta;
                    }
                    auto created = create_role_layer_(
                        jstr(descriptor, "title"),
                        jstr(descriptor, "geometry_kind"),
                        jstr(descriptor, "role"), "", "",
                        jstr(metadata, "prediction_task_id"), "",
                        feature_pairs_from_json(
                            descriptor.contains("features")
                                ? descriptor["features"]
                                : Json()));
                    if (created.has_value()) ++added;
                }
            }
        }
        if (added == 0) {
            status("没有可叠加的预测置信度结果（需要带 probability 字段的 "
                   "VECTOR_POLYGONS 预测任务）");
        } else {
            status("已叠加 " + std::to_string(added)
                   + " 个预测置信度图层（不可编辑）");
        }
    }

    void create_facies_draft_() {
        const auto s = store();
        if (s == nullptr) throw std::runtime_error("请先打开工程");
        auto& state = require_workspace_();
        if (stage_role_layer_(
                std::string(ui_composite::layer_role::kInitialFaciesDraft))
                .has_value()) {
            status("解释草稿已存在（05 人工解释与修编）");
            return;
        }
        auto* edit = edit_controller_();
        if (edit == nullptr) {
            throw std::runtime_error("图层控制面不可用");
        }
        FeaturePairs source_features;
        std::string source_name = "初始相图";
        std::string source_version;
        const auto raw = stage_role_layer_(
            std::string(ui_composite::layer_role::kInitialFaciesSource));
        if (raw.has_value()) {
            auto* layer = edit->layer(*raw);
            source_name = layer->name() + " 校正稿";
            source_features = layer_feature_pairs_(layer);
            if (const auto* binding =
                    workspace::membership(state, *raw);
                binding != nullptr) {
                source_version = binding->source_version_id;
            }
        } else {
            const Json& root = s->document().root();
            const Json* docs = jfield(root, "paleomap_documents");
            const Json* candidate = nullptr;
            if (docs != nullptr && docs->is_array()) {
                for (const Json& doc : *docs) {
                    const Json* polygons = jfield(doc, "facies_polygons");
                    if (polygons != nullptr && polygons->is_array()
                        && !polygons->empty()) {
                        candidate = &doc;
                        break;
                    }
                }
            }
            if (candidate != nullptr) {
                source_name = jstr(*candidate, "name") + " 校正稿";
                for (const Json& polygon :
                     (*candidate)["facies_polygons"]) {
                    const Json* geometry = jfield(polygon, "geometry");
                    if (geometry == nullptr || !geometry->is_object()) {
                        continue;
                    }
                    Json properties = Json::object();
                    if (const Json* props = jfield(polygon, "properties");
                        props != nullptr && props->is_object()) {
                        properties = *props;
                    }
                    if (!properties.contains("facies")
                        || properties["facies"].is_null()) {
                        properties["facies"] = jstr(polygon, "facies");
                    }
                    source_features.emplace_back(*geometry,
                                                 std::move(properties));
                }
            } else {
                source_features = default_blank_facies_features_();
                if (!source_features.empty()) {
                    source_name = "初始相图（工区默认空白相）校正稿";
                }
            }
        }
        if (source_features.empty()) {
            status("没有可校正的初始相图——先加载初始相图（RAW）");
            return;
        }
        auto layer_id = create_role_layer_(
            source_name, "polygon",
            std::string(ui_composite::layer_role::kInitialFaciesDraft), "",
            "", "", source_version, source_features);
        if (!layer_id.has_value()) return;
        apply_categorized_facies_style_(*layer_id, source_features);
        state.artifact_maturity["phase1_draft:" + *layer_id] = "draft";
        edit->set_active_layer(*layer_id);
        if (auto* doc = composite(); doc != nullptr && doc->layer_manager != nullptr) {
            doc->layer_manager->select_layer(*layer_id);
        }
        status("已创建解释草稿（DERIVED）——RAW 保持不变，编辑保存在草稿上");
    }

    // ---------------------------------------------------------- Phase 2 --

    void overlay_factor_results_() {
#if defined(PWB_WITH_FACTOR_KERNEL)
        const auto s = store();
        if (s == nullptr) throw std::runtime_error("请先打开工程");
        auto& state = require_workspace_();
        auto& groups = require_groups_();
        auto* edit = edit_controller_();
        if (edit == nullptr) {
            throw std::runtime_error("图层控制面不可用");
        }
        const Json& root = s->document().root();
        std::vector<const Json*> tasks;
        if (const Json* rows = jfield(root, "factor_map_tasks");
            rows != nullptr && rows->is_array()) {
            for (const Json& task : *rows) {
                if (jstr(task, "status") == "complete") {
                    tasks.push_back(&task);
                }
            }
        }
        if (tasks.empty()) {
            status("没有已完成的单因素任务可叠加");
            return;
        }
        int vector_added = 0;
        int raster_registered = 0;
        int empty_children = 0;
        int no_grid_tasks = 0;
        for (const Json* task : tasks) {
            const std::string task_id = jstr(*task, "id");
            // peek_live_factor_grid parity — the live cache only; a
            // missing grid leaves derived children honestly empty.
            std::optional<factor_production::LiveGridEntry> entry;
            mapping::FactorGrid grid;
            if (grids_ != nullptr) {
                entry = grids_->peek(task_id);
            }
            ui_composite::FactorGroupGridView view;
            if (entry.has_value()) {
                grid.grid_x = entry->grid_x;
                grid.grid_y = entry->grid_y;
                grid.grid_z = entry->grid_z;
                grid.variance_grid = entry->variance_grid;
                view.live = &grid;
                view.metadata = entry->metadata;
            } else {
                ++no_grid_tasks;
                if (const Json* meta = jfield(*task, "grid_metadata");
                    meta != nullptr && meta->is_object()) {
                    view.metadata = *meta;
                }
            }
            for (const Json& descriptor :
                 ui_composite::factor_group_layers(root, *task, view)) {
                if (!descriptor.is_object()) continue;
                const std::string role = jstr(descriptor, "role");
                const std::string layer_id =
                    jstr(descriptor, "layer_id");
                // 格网衍生子层钉住任务的产品格网版本（井点输入层除外）。
                const std::string grid_version_id =
                    role == std::string(ui_composite::layer_role::kFactorInput)
                        ? ""
                        : jstr(*task, "grid_artifact_version_id");
                if (jstr(descriptor, "geometry_kind") == "raster") {
                    // descriptor-only 登记（画布标量发布路径不在本动作内）。
                    if (workspace::membership(state, layer_id) != nullptr) {
                        continue;
                    }
                    groups.register_layer(layer_id, role, task_id, "",
                                          grid_version_id);
                    ++raster_registered;
                    continue;
                }
                bool present = false;
                for (const std::string& lid :
                     workspace::layers_with_role(state, role)) {
                    const auto* binding = workspace::membership(state, lid);
                    if (binding != nullptr
                        && binding->factor_task_id == task_id
                        && edit->layer(lid) != nullptr) {
                        present = true;
                        break;
                    }
                }
                if (present) continue;
                FeaturePairs features = feature_pairs_from_json(
                    descriptor.contains("features") ? descriptor["features"]
                                                   : Json());
                if (features.empty()) {
                    // 空矢量子层不建空图层；缺失原因由 QC 子层诚实报告。
                    ++empty_children;
                    continue;
                }
                auto created = create_role_layer_(
                    jstr(descriptor, "title"),
                    jstr(descriptor, "geometry_kind"), role, "", "",
                    task_id, grid_version_id, features);
                if (created.has_value()) ++vector_added;
            }
        }
        std::string message =
            "已叠加单因素组：矢量子层 " + std::to_string(vector_added)
            + "，标量子层登记 " + std::to_string(raster_registered)
            + "（descriptor-only，画布标量发布待接入）";
        if (no_grid_tasks > 0) {
            message += "；" + std::to_string(no_grid_tasks)
                       + " 个任务无 live 网格（等值线/分级/不确定性子层留空，"
                         "打开制备页加载后可叠加）";
        }
        if (empty_children > 0) {
            message += "；" + std::to_string(empty_children)
                       + " 个矢量子层无内容（详见 QC 子层）";
        }
        status(message);
#else
        throw std::runtime_error("单因素叠加服务未接入（因子内核未启用）");
#endif
    }

    void commit_constraints_() {
        const auto s = store();
        if (s == nullptr) {
            status("未打开工程");
            return;
        }
        auto* catalog = runtime_catalog();
        if (catalog == nullptr) {
            status("目录服务不可用——无法提交约束版本（不伪称已提交）");
            return;
        }
        Json& root = s->document().root();
        std::vector<workflow_runtime::ConstraintCommitReport> reports;
        try {
            reports = workflow_runtime::commit_all_constraints(
                *catalog, root, "workstation");
        } catch (const std::exception& exc) {
            status(std::string("约束提交失败：") + exc.what());
            return;
        }
        std::vector<std::string> committed_versions;
        int unchanged = 0;
        int no_content = 0;
        for (const auto& report : reports) {
            if (report.committed) {
                committed_versions.push_back(
                    report.version_id.value_or("?"));
            } else if (report.reason == "unchanged") {
                ++unchanged;
            } else if (report.reason == "no_content") {
                ++no_content;
            }
        }
        if (!committed_versions.empty()) {
            std::string versions;
            for (const std::string& version : committed_versions) {
                if (!versions.empty()) versions += ", ";
                versions += version;
            }
            status("已提交 " + std::to_string(committed_versions.size())
                   + " 个约束组新版本（" + versions + "）；"
                   + std::to_string(unchanged) + " 组内容未变，"
                   + std::to_string(no_content) + " 组无内容");
            sync_workspace_state_();
        } else if (!reports.empty()) {
            status("无新版本：" + std::to_string(unchanged)
                   + " 组内容未变，" + std::to_string(no_content)
                   + " 组无内容");
        } else {
            status("工程内没有约束组");
        }
    }

    // ---------------------------------------------------------- Phase 3 --

    void select_evidence_() {
        const auto s = store();
        if (s == nullptr) return;
        auto* state = workspace_state();
        auto view = workspace_view_();
        std::vector<workflow_graph::EvidenceResolution> resolutions =
            workflow_graph::available_evidence(
                s->document().root(), state != nullptr ? &view : nullptr,
                constraint_resolver_());
        if (resolutions.empty()) {
            status("没有可选证据——先完成上阶段成果");
            return;
        }
        std::map<std::string, std::string> status_tag = {
            {"resolved", ""}, {"floating", "（当前内容）"},
            {"unpinned", "（未钉版本）"}, {"stale", "（已过期）"},
            {"missing", "（缺失）"}, {"unknown", "（未知）"}};
        std::vector<std::string> labels;
        std::vector<std::pair<std::string, std::string>> entries;
        for (const auto& resolution : resolutions) {
            std::string label = resolution.display;
            const auto tag = status_tag.find(
                workflow_graph::evidence_status_value(resolution.status));
            if (tag != status_tag.end()) label += tag->second;
            entries.emplace_back(resolution.selector.str(),
                                 workflow_graph::evidence_status_value(
                                     resolution.status));
            labels.push_back(label);
        }
        Json ws_storage;
        std::vector<std::string> existing;
        {
            const Json* ws = workspace_json_ptr_(ws_storage);
            std::set<std::string> seen;
            for (const auto& [label, selector] :
                 workflow_interpretation::evidence_view(
                     s->document().root(), ws)) {
                if (seen.insert(selector).second) {
                    existing.push_back(selector);
                }
            }
        }
        std::sort(existing.begin(), existing.end());
        if (!existing.empty()) {
            labels.push_back("〔移除证据〕…");
        }
        QStringList choices;
        for (const std::string& label : labels) {
            choices << QString::fromStdString(label);
        }
        bool ok = false;
        const QString chosen = QInputDialog::getItem(
            window_, QStringLiteral("选择证据版本"),
            QStringLiteral(
                "综合编图输入证据（可多选经重复执行本动作累积；选末项移除）："),
            choices, 0, false, &ok);
        if (!ok || chosen.trimmed().isEmpty()) return;
        const std::string chosen_text = chosen.toStdString();
        if (chosen_text == "〔移除证据〕…") {
            remove_evidence_(existing);
            return;
        }
        const auto index =
            std::find(labels.begin(), labels.end(), chosen_text);
        if (index == labels.end()) return;
        const auto& [selector, status_value] =
            entries[static_cast<std::size_t>(index - labels.begin())];
        Json& root = s->document().root();
        // 旧视图（dependencies/存档兼容）+ 结构化输入集（权威）双写。
        if (state != nullptr) {
            state->compilation_input_set[chosen_text] = selector;
        }
        auto input_set = workflow_interpretation::active_input_set(root);
        if (!input_set.has_value() && state != nullptr) {
            input_set = workflow_interpretation::
                create_input_set_shell_from_legacy(root,
                                                   state->to_json(),
                                                   "workstation");
        }
        if (input_set.has_value()
            && input_set->entry_for_selector(selector) == nullptr) {
            workflow_interpretation::CompilationInputSetEntry entry;
            entry.selector = selector;
            entry.label = chosen_text;
            entry.evidence_kind = selector.substr(
                0, selector.find(':'));
            entry.status_at_add = status_value;
            entry.added_by = "workstation";
            input_set->entries.push_back(std::move(entry));
            workflow_interpretation::persist_input_set(root,
                                                       *input_set);
        }
        sync_workspace_state_();
        status("已加入证据集：" + chosen_text);
    }

    void remove_evidence_(const std::vector<std::string>& existing) {
        if (existing.empty()) {
            status("证据集为空——无可移除项");
            return;
        }
        QStringList choices;
        for (const std::string& item : existing) {
            choices << QString::fromStdString(item);
        }
        bool ok = false;
        const QString chosen = QInputDialog::getItem(
            window_, QStringLiteral("移除证据"),
            QStringLiteral("选择要移除的证据："), choices, 0, false, &ok);
        if (!ok || chosen.trimmed().isEmpty()) return;
        const std::string chosen_text = chosen.toStdString();
        const auto s = store();
        auto* state = workspace_state();
        if (s == nullptr) return;
        // legacy dict：按值删（显示名键随状态漂移，值才是身份）。
        if (state != nullptr) {
            for (auto it = state->compilation_input_set.begin();
                 it != state->compilation_input_set.end();) {
                if (it->second == chosen_text) {
                    it = state->compilation_input_set.erase(it);
                } else {
                    ++it;
                }
            }
        }
        // 结构化集（权威载体）：按选择器删。
        try {
            Json& root = s->document().root();
            auto input_set =
                workflow_interpretation::active_input_set(root);
            if (input_set.has_value()) {
                std::vector<
                    workflow_interpretation::CompilationInputSetEntry>
                    kept;
                for (const auto& entry : input_set->entries) {
                    if (entry.selector != chosen_text) kept.push_back(entry);
                }
                input_set->entries = std::move(kept);
                workflow_interpretation::persist_input_set(root,
                                                           *input_set);
            }
        } catch (const std::exception&) {
            // 结构化删除失败不阻断 legacy 删除。
        }
        sync_workspace_state_();
        status("已移除证据：" + chosen_text);
    }

    workflow_graph::ConstraintResolver constraint_resolver_() const {
        auto* catalog = runtime_catalog();
        return [catalog](const Json& document,
                         const std::string& ref) -> Json {
            return workflow_runtime::resolve_constraint_ref(document,
                                                            catalog, ref);
        };
    }

    void freeze_evidence_set_() {
        const auto s = store();
        if (s == nullptr) return;
        Json& root = s->document().root();
        auto input_set = workflow_interpretation::active_input_set(root);
        if (!input_set.has_value()) {
            status("没有激活的证据集——先选择证据版本");
            return;
        }
        auto* catalog = runtime_catalog();
        workflow_interpretation::ResolveContext ctx =
            workflow_interpretation::ResolveContext::for_repository(
                catalog);
        auto view = workspace_view_();
        if (workspace_state() != nullptr) ctx.workspace = &view;
        try {
            workflow_interpretation::freeze_input_set(*input_set, root,
                                                      ctx);
        } catch (const std::exception& exc) {
            status(std::string("冻结失败：") + exc.what());
            return;
        }
        workflow_interpretation::persist_input_set(root, *input_set,
                                                   true);
        sync_workspace_state_();
        status("已冻结证据集（" + std::to_string(input_set->entries.size())
               + " 条）");
    }

    void create_integrated_draft_() {
        const auto s = store();
        if (s == nullptr) throw std::runtime_error("请先打开工程");
        auto& state = require_workspace_();
        auto* edit = edit_controller_();
        if (edit == nullptr) {
            throw std::runtime_error("图层控制面不可用");
        }
        if (stage_role_layer_(
                std::string(ui_composite::layer_role::kIntegratedFacies))
                .has_value()) {
            status("综合解释草稿已存在（02 综合解释）");
            return;
        }
        if (state.compilation_input_set.empty()) {
            status("先选择证据版本（Compilation Input Set 为空）");
            return;
        }
        FeaturePairs features;
        if (const auto base = stage_role_layer_(
                std::string(ui_composite::layer_role::kInitialFaciesDraft));
            base.has_value()) {
            features = layer_feature_pairs_(edit->layer(*base));
        }
        auto layer_id = create_role_layer_(
            "综合沉积相（草稿）", "polygon",
            std::string(ui_composite::layer_role::kIntegratedFacies), "", "",
            "", "", features);
        if (!layer_id.has_value()) return;
        state.artifact_maturity["integrated:" + *layer_id] = "draft";
        edit->set_active_layer(*layer_id);
        if (auto* doc = composite();
            doc != nullptr && doc->layer_manager != nullptr) {
            doc->layer_manager->select_layer(*layer_id);
        }
        register_integrated_interpretation_(*layer_id, "综合沉积相（草稿）",
                                            {}, "");
        status("已创建综合解释草稿（证据 "
               + std::to_string(state.compilation_input_set.size()) + " 项）");
    }

    // _register_integrated_interpretation parity（登记失败不阻断图层创建）.
    void register_integrated_interpretation_(
        const std::string& layer_id, const std::string& name,
        const std::vector<std::string>& class_names,
        const std::string& fusion_version_id,
        const Json& confidence_summary = Json::object(),
        const Json& conflicts = Json::object()) {
        const auto s = store();
        if (s == nullptr) return;
        Json& root = s->document().root();
        try {
            if (workflow_interpretation::find_by_layer(root, layer_id)
                    .has_value()) {
                return;  // 幂等：已有记录不重复创建
            }
            std::string input_set_id;
            if (auto input_set =
                    workflow_interpretation::active_input_set(root)) {
                input_set_id = input_set->id;
            }
            workflow_interpretation::create_integrated_interpretation(
                root, name, layer_id, input_set_id, fusion_version_id, "",
                class_names, confidence_summary, conflicts, "workstation");
        } catch (const std::exception&) {
            // logger.exception parity — visible in logs, never a block.
        }
    }

    void create_integrated_boundary_() {
        const auto s = store();
        if (s == nullptr) throw std::runtime_error("请先打开工程");
        auto& state = require_workspace_();
        auto* edit = edit_controller_();
        if (edit == nullptr) {
            throw std::runtime_error("图层控制面不可用");
        }
        if (stage_role_layer_(
                std::string(
                    ui_composite::layer_role::kIntegratedBoundary))
                .has_value()) {
            status("综合相带边界已存在（02 综合解释）");
            return;
        }
        FeaturePairs features;
        std::string source_id;
        const auto live_source =
            stage_role_layer_(
                std::string(
                    ui_composite::layer_role::kIntegratedFacies))
                .value_or(std::string());
        const auto source = !live_source.empty()
                                ? live_source
                                : stage_role_layer_(std::string(
                                      ui_composite::layer_role::
                                          kInitialFaciesDraft))
                                      .value_or(std::string());
        if (!source.empty()) {
            source_id = source;
            features = ui_composite::boundary_features_from_polygons(
                layer_feature_pairs_(edit->layer(source)), source);
        } else {
            // 无 live 编辑层时退回工程侧草稿（重开工程后的持久化几何）。
            const Json& root = s->document().root();
            const std::string roles[] = {
                std::string(
                    ui_composite::layer_role::kIntegratedFacies),
                std::string(
                    ui_composite::layer_role::kInitialFaciesDraft)};
            for (const std::string& role : roles) {
                for (const std::string& layer_id :
                     workspace::layers_with_role(state, role)) {
                    const Json descriptor =
                        ui_composite::integrated_boundary_action_helpers(
                            root, layer_id);
                    if (descriptor.is_null()) continue;
                    features = feature_pairs_from_json(
                        descriptor.contains("features")
                            ? descriptor["features"]
                            : Json());
                    if (!features.empty()) {
                        source_id = layer_id;
                        break;
                    }
                }
                if (!features.empty()) break;
            }
        }
        if (features.empty()) {
            status("没有可提取边界的草稿相面——先创建综合解释草稿（含相面几何）");
            return;
        }
        auto layer_id = create_role_layer_(
            "综合相带边界", "line",
            std::string(ui_composite::layer_role::kIntegratedBoundary), "",
            "", "", "", features);
        if (!layer_id.has_value()) return;
        state.artifact_maturity["integrated:" + *layer_id] = "draft";
        edit->set_active_layer(*layer_id);
        if (auto* doc = composite();
            doc != nullptr && doc->layer_manager != nullptr) {
            doc->layer_manager->select_layer(*layer_id);
        }
        status("已创建综合相带边界（" + std::to_string(features.size())
               + " 条，源自草稿 "
               + (source_id.empty() ? "（工程侧）" : source_id)
               + " 相面环）");
    }

    void run_fusion_() {
#if defined(PWB_WITH_CLOSURE_WORKFLOW)
        const auto s = store();
        if (s == nullptr) throw std::runtime_error("请先打开工程");
        auto& state = require_workspace_();
        auto& groups = require_groups_();
        Json& root = s->document().root();
        // 经单一适配器读证据集（结构化激活输入集优先）。
        auto input_set = workflow_interpretation::active_input_set(root);
        if (input_set.has_value() && !input_set->frozen) {
            status("请先冻结 Compilation Input Set 再运行融合");
            return;
        }
        Json ws_storage;
        const Json* ws = workspace_json_ptr_(ws_storage);
        auto evidence =
            workflow_interpretation::evidence_view(root, ws);
        if (evidence.empty()) {
            status("证据集为空——先选择证据版本（Compilation Input Set）");
            return;
        }
        bool has_factor = false;
        for (const auto& [label, selector] : evidence) {
            if (selector.rfind("factor:", 0) == 0) {
                has_factor = true;
                break;
            }
        }
        if (!has_factor) {
            status("证据集中没有单因素证据（factor 条目）——计算融合至少需要一个单因素网格");
            return;
        }
        auto* catalog = runtime_catalog();
        closure_workflow::IntegratedRunOutput out;
        try {
            auto seams = closure_workflow::make_production_grid_seams(
                catalog, live_grid_resolver_());
            out = closure_workflow::run_integrated_fusion(
                root, evidence, catalog, seams, std::nullopt,
                std::nullopt, std::nullopt, std::nullopt,
                /*register_output=*/catalog != nullptr);
        } catch (const std::exception& exc) {
            status(std::string("融合失败：") + exc.what());
            return;
        }
        const Json& summary = out.summary;
        // 标量 descriptor-only 登记（幂等：按 layer_id 已存在则跳过）。
        int registered = 0;
        std::string fusion_version_id = jstr(summary, "catalog_version_id");
        const Json* descriptors[] = {
            jfield(summary, "likelihood_descriptor"),
            jfield(summary, "confidence_descriptor"),
            jfield(summary, "variance_descriptor")};
        for (const Json* descriptor : descriptors) {
            if (descriptor == nullptr || descriptor->is_null()) continue;
            const std::string layer_id = jstr(*descriptor, "layer_id");
            if (layer_id.empty()
                || workspace::membership(state, layer_id) != nullptr) {
                continue;
            }
            const std::string pinned = [&]() {
                const std::string artifact =
                    jstr(*descriptor, "artifact_version_id");
                return !artifact.empty() ? artifact : fusion_version_id;
            }();
            groups.register_layer(layer_id,
                                  jstr(*descriptor, "role"), "", "",
                                  pinned);
            ++registered;
        }
        // 融合初稿（仅有分级多边形且无既有草稿时创建；绝不覆盖人工解释）。
        std::string draft_note;
        FeaturePairs features = feature_pairs_from_json(
            summary.contains("classification_features")
                ? summary["classification_features"]
                : Json());
        const Json* qc = jfield(summary, "qc");
        if (!features.empty()
            && !stage_role_layer_(std::string(
                  ui_composite::layer_role::kIntegratedFacies))
                     .has_value()) {
            auto created = create_role_layer_(
                "综合沉积相（融合初稿）", "polygon",
                std::string(ui_composite::layer_role::kIntegratedFacies),
                "", "", "", fusion_version_id, features);
            if (created.has_value()) {
                state.artifact_maturity["integrated:" + *created] = "draft";
                Json confidence;
                if (qc != nullptr && qc->is_object()) {
                    if (const Json* coverage =
                            jfield(*qc, "confidence_coverage");
                        coverage != nullptr && coverage->is_object()) {
                        confidence = *coverage;
                    }
                }
                Json conflicts = Json::object();
                if (qc != nullptr && qc->is_object()) {
                    for (const char* key :
                         workflow_interpretation::FUSION_CONFLICT_KEYS) {
                        if (const Json* value = jfield(*qc, key);
                            value != nullptr && !value->is_null()) {
                            conflicts[key] = *value;
                        }
                    }
                }
                std::vector<std::string> class_names;
                if (const Json* names = jfield(summary, "class_names");
                    names != nullptr && names->is_array()) {
                    for (const Json& name : *names) {
                        if (name.is_string()) {
                            class_names.push_back(
                                name.get<std::string>());
                        }
                    }
                }
                register_integrated_interpretation_(
                    *created, "综合沉积相（融合初稿）", class_names,
                    fusion_version_id, confidence, conflicts);
                record_revision_for_layer_(
                    *created, workflow_interpretation::TARGET_INTEGRATED_FACIES,
                    workflow_interpretation::BASE_FUSION, fusion_version_id,
                    {}, "融合初稿（算法播种，人工修编起点）");
                draft_note = "；已创建融合初稿（"
                             + std::to_string(features.size())
                             + " 个分级面，可编辑修编）";
            }
        } else if (!features.empty()) {
            draft_note = "；已有综合解释草稿，融合分级未覆盖（人工解释优先，见融合登记）";
        } else {
            draft_note = "；融合分级无多边形（阈值内无有效面，未建初稿）";
        }
        // 既有解释记录追踪最新融合版本（种子不变；latest 供产品谱系引用）。
        if (!fusion_version_id.empty()) {
            try {
                for (auto interpretation :
                     workflow_interpretation::interpretations_for_document(
                         root)) {
                    interpretation.latest_fusion_version_id =
                        fusion_version_id;
                    workflow_interpretation::upsert_interpretation(
                        root, interpretation);
                }
            } catch (const std::exception&) {
                // 追踪失败不阻断融合。
            }
        }
        std::string counts_text = "无";
        if (qc != nullptr && qc->is_object()) {
            if (const Json* counts = jfield(*qc, "class_counts");
                counts != nullptr && counts->is_object()
                && !counts->empty()) {
                counts_text.clear();
                for (auto it = counts->begin(); it != counts->end(); ++it) {
                    if (!counts_text.empty()) counts_text += "，";
                    counts_text +=
                        it.key() + " "
                        + (it.value().is_number()
                               ? std::to_string(
                                     it.value().get<long long>())
                               : it.value().dump());
                }
            }
        }
        std::string coverage_text = "无";
        if (qc != nullptr && qc->is_object()) {
            if (const Json* coverage = jfield(*qc, "confidence_coverage");
                coverage != nullptr && coverage->is_object()) {
                if (const Json* fraction =
                        jfield(*coverage, "finite_fraction");
                    fraction != nullptr && fraction->is_number()) {
                    // Python f"{fraction:.0%}" — nearest integer percent.
                    coverage_text =
                        std::to_string(std::lround(
                                           fraction->get<double>()
                                           * 100.0))
                        + "%";
                }
            }
        }
        const std::string reg_text =
            summary.value("registered", false)
                ? "已注册目录版本 "
                      + fusion_version_id.substr(
                            0, std::min<std::size_t>(
                                   fusion_version_id.size(), 12))
                      + "…"
                : "未注册目录（无目录服务，诚实降级——重开工程后可补注册）";
        status("融合完成："
               + std::to_string(summary.value("n_factors", 0)) + " 因子（"
               + reg_text + "）；分类 " + counts_text + "；置信度覆盖 "
               + coverage_text + "；标量登记 " + std::to_string(registered)
               + "（descriptor-only，画布标量发布待接入）" + draft_note);
#else
        throw std::runtime_error("融合服务未接入（编译工作流未启用）");
#endif
    }

#if defined(PWB_WITH_CLOSURE_WORKFLOW)
    closure_workflow::LiveGridResolver live_grid_resolver_() const {
        return [this](const Json& task)
                   -> std::optional<factor_fusion::FactorGrid> {
            const std::string task_id = jstr(task, "id");
            if (grids_ != nullptr) {
                if (auto entry = grids_->peek(task_id)) {
                    factor_fusion::FactorGrid grid;
                    grid.grid_x = entry->grid_x;
                    grid.grid_y = entry->grid_y;
                    grid.grid_z.reserve(entry->grid_z.size());
                    for (float cell : entry->grid_z) {
                        grid.grid_z.push_back(cell);
                    }
                    grid.width = static_cast<int>(grid.grid_x.size());
                    grid.height = static_cast<int>(grid.grid_y.size());
                    if (!entry->variance_grid.empty()) {
                        grid.variance_grid = entry->variance_grid;
                    }
                    grid.factor_name = jstr(task, "name");
                    grid.algorithm_id = jstr(task, "method");
                    return grid;
                }
            }
            // npz 工件原生不可读（诚实缺口）；编目版本 payload 可解码。
            const std::string version_id =
                jstr(task, "grid_artifact_version_id");
            if (!version_id.empty()) {
                if (auto* catalog = runtime_catalog()) {
                    return closure_workflow::load_grid_from_version(
                        catalog, version_id);
                }
            }
            return std::nullopt;
        };
    }
#endif

    void run_map_qa_() {
        const auto s = store();
        if (s == nullptr) {
            throw std::runtime_error("请先打开工程");
        }
        auto* state = workspace_state();
        auto* edit = edit_controller_();
        Json issues = Json::array();
        if (state != nullptr && edit != nullptr) {
            // ① 拓扑校验综合解释图层（验证器异常 → error issue，不跳过）。
            std::vector<std::string> targets =
                workspace::layers_with_role(
                    *state,
                    std::string(
                        ui_composite::layer_role::kIntegratedFacies));
            for (const std::string& layer_id : workspace::layers_with_role(
                     *state,
                     std::string(ui_composite::layer_role::
                                     kIntegratedBoundary))) {
                targets.push_back(layer_id);
            }
            for (const std::string& layer_id : targets) {
                auto* layer = edit->layer(layer_id);
                if (layer == nullptr) continue;
                std::vector<Json> found;
                try {
                    found = edit->topology().validate({layer});
                } catch (const std::exception&) {
                    Json issue = Json::object();
                    issue["kind"] = "error";
                    issue["message"] = "拓扑验证失败（验证器异常）："
                                       + layer->name();
                    issue["layer_id"] = layer_id;
                    issues.push_back(std::move(issue));
                    continue;
                }
                for (const Json& problem : found) {
                    Json issue = Json::object();
                    issue["kind"] = problem.contains("severity")
                                        ? problem["severity"]
                                        : Json("topology");
                    issue["message"] = jstr(problem, "message");
                    issue["layer_id"] = layer_id;
                    issues.push_back(std::move(issue));
                }
            }
        }
        // ② 过期输入汇总（同一依赖评估权威）。
        Json ws_storage;
        const Json* ws = workspace_json_ptr_(ws_storage);
        std::vector<workflow_interpretation::ArtifactFreshness> freshness;
        try {
            freshness = workflow_interpretation::
                evaluate_workspace_freshness(s->document().root(), ws,
                                             runtime_catalog());
        } catch (const std::exception&) {
            // 新鲜度评估失败不阻断 QA 本体。
        }
        for (const auto& artifact :
             workflow_interpretation::stale_entries(freshness)) {
            Json issue = Json::object();
            issue["kind"] = "stale";
            issue["message"] = artifact.artifact_key + "："
                               + artifact.status_label() + "（"
                               + artifact.detail + "）";
            issue["layer_id"] = "";
            issues.push_back(std::move(issue));
        }
        // ③ §14 制图规则集（薄委托；收集器失败转为 cartographic issue）。
        std::vector<std::string> carto_rules;
        try {
            workflow_runtime::CartographicQaInputs inputs;
            inputs.stale_summary =
                workflow_interpretation::stale_summary_json(freshness);
            inputs.catalog = runtime_catalog();
            Json found = workflow_runtime::cartographic_issues(
                s->document().root(), inputs,
                [](const Json& project,
                   const workflow_runtime::CartographicQaInputs& in) {
                    return cartography::collect_cartographic_qa_issues(
                        project, in);
                });
            std::set<std::string> rule_ids;
            if (found.is_array()) {
                for (const Json& issue : found) {
                    const std::string rule = jstr(issue, "rule");
                    rule_ids.insert(rule.empty() ? "cartographic" : rule);
                }
                for (const Json& issue : found) {
                    issues.push_back(issue);
                }
            }
            for (const std::string& rule : rule_ids) {
                carto_rules.push_back(rule);
            }
        } catch (const std::exception& exc) {
            Json issue = Json::object();
            issue["kind"] = "cartographic";
            issue["message"] =
                std::string("制图 QA 规则集评估失败：") + exc.what();
            issue["layer_id"] = "";
            issues.push_back(std::move(issue));
        }
        const std::string report_status =
            issues.empty() ? "passed" : "issues";
        project::QualityReport report;
        report.id = domain::make_id("qc_");
        report.linked_map_document_id = "";
        report.rules = {"topology", "staleness"};
        for (const std::string& rule : carto_rules) {
            report.rules.push_back(rule);
        }
        report.issues = issues;
        report.status = report_status;
        report.generated_at = domain::now_iso8601();
        Json& root = s->document().root();
        if (!root.contains("quality_reports")
            || !root["quality_reports"].is_array()) {
            root["quality_reports"] = Json::array();
        }
        root["quality_reports"].push_back(report.to_dict());
        controller_->core().on_qc_reports_updated();
        if (issues.empty()) {
            status("QA 通过：无几何/拓扑问题，无过期输入");
        } else {
            status("QA 发现 " + std::to_string(issues.size())
                   + " 个问题（见 05 QA/QC）");
        }
    }

    void commit_interpretation_() {
        const auto s = store();
        if (s == nullptr) {
            status("未打开工程");
            return;
        }
        auto* state = workspace_state();
        if (state == nullptr) {
            throw std::runtime_error("工作区状态不可用（图层控制面未接入本窗口）");
        }
        auto* edit = edit_controller_();
        std::vector<std::string> layer_ids = workspace::layers_with_role(
            *state,
            std::string(ui_composite::layer_role::kIntegratedFacies));
        if (layer_ids.empty()) {
            status("没有综合解释层——先创建综合草稿");
            return;
        }
        const std::string layer_id = layer_ids.front();
        Json& root = s->document().root();
        auto interpretation =
            workflow_interpretation::find_by_layer(root, layer_id);
        if (!interpretation.has_value()) {
            status("层 " + layer_id
                   + " 无综合解释记录（旧工程——重开或重建草稿）");
            return;
        }
        Json layer_json = Json();
        if (edit != nullptr && edit->layer(layer_id) != nullptr) {
            layer_json = layer_json_(edit->layer(layer_id));
        } else {
            const Json* layers = jfield(root, "user_vector_layers");
            if (layers != nullptr && layers->is_array()) {
                for (const Json& candidate : *layers) {
                    if (jstr(candidate, "id") == layer_id) {
                        layer_json = candidate;
                        break;
                    }
                }
            }
        }
        if (layer_json.is_null()) {
            status("解释层 " + layer_id + " 不可达");
            return;
        }
        auto* catalog = runtime_catalog();
        if (catalog == nullptr) {
            status("目录服务不可用——提交需要 catalog（不伪称已提交）");
            return;
        }
        Json ws_storage;
        const Json* ws = workspace_json_ptr_(ws_storage);
        std::vector<std::string> evidence_refs;
        {
            std::set<std::string> seen;
            for (const auto& [label, selector] :
                 workflow_interpretation::evidence_view(root, ws)) {
                if (seen.insert(selector).second) {
                    evidence_refs.push_back(selector);
                }
            }
        }
        std::sort(evidence_refs.begin(), evidence_refs.end());
        std::string version_id;
        try {
            version_id =
                workflow_interpretation::commit_integrated_interpretation(
                    root, *interpretation, layer_json, catalog,
                    "workstation", "", evidence_refs);
        } catch (const std::exception& exc) {
            status(std::string("综合解释提交被拒绝：") + exc.what());
            return;
        }
        const auto reloaded =
            workflow_interpretation::find_by_layer(root, layer_id);
        const std::size_t chain = reloaded.has_value()
                                      ? reloaded->revision_ids.size()
                                      : 0;
        status("综合解释已提交（版本 "
               + version_id.substr(
                     0, std::min<std::size_t>(version_id.size(), 12))
               + "…；修订链 " + std::to_string(chain) + " 条）");
    }

    // ------------------------------------------------------ stage save --

    void stage_save_() {
        const auto s = store();
        if (s == nullptr) throw std::runtime_error("请先打开工程");
        auto* edit = edit_controller_();
        int committed = 0;
        if (edit != nullptr) {
            committed = edit->flush_edit_sessions().first;
        }
        const int synced = sync_constraint_geometry_();
        const int recorded = record_interpretation_revisions_();
        persist_composite_layers_();
        sync_workspace_state_();
        std::string error;
        if (!closure_mapping::save_documents(window_, &error)) {
            throw std::runtime_error(error.empty() ? "保存失败" : error);
        }
        std::string message = "阶段成果已保存";
        if (committed > 0) {
            message += "（提交 " + std::to_string(committed)
                       + " 个编辑会话）";
        }
        if (synced > 0) {
            message += "；回填 " + std::to_string(synced)
                       + " 条约束几何（含内容指纹）";
        }
        if (recorded > 0) {
            message += "；记录 " + std::to_string(recorded)
                       + " 条解释修订（人工解释溯源）";
        }
        status(message);
        push_project_to_pages_();
    }

    // 约束几何回填（§11 P0-3）：数字化矢量 → ConstraintLine.coordinates。
    int sync_constraint_geometry_() {
        const auto s = store();
        if (s == nullptr) return 0;
        Json& root = s->document().root();
        int count = 0;
        std::set<std::string> seen;
        const Json* groups = jfield(root, "constraint_layers");
        if (groups == nullptr || !groups->is_array()) return 0;
        for (const Json& group : *groups) {
            const Json* lines = jfield(group, "lines");
            if (lines == nullptr || !lines->is_array()) continue;
            for (const Json& line : *lines) {
                const Json* properties = jfield(line, "properties");
                const std::string layer_id =
                    properties != nullptr && properties->is_object()
                        ? jstr(*properties, "layer_id")
                        : "";
                if (layer_id.empty() || seen.count(layer_id) != 0) {
                    continue;
                }
                seen.insert(layer_id);
                try {
                    const Json report =
                        ui_composite::sync_constraint_geometry(root,
                                                               layer_id);
                    if (report.is_object()
                        && report.value("ok", false)) {
                        count += report.value("lines_synced", 0);
                    }
                } catch (const std::exception&) {
                    // 失败不阻断保存——保存语义优先。
                }
            }
        }
        return count;
    }

    // 对有内容变化的解释面记录修订（证据归因 = 当前输入集）。
    int record_interpretation_revisions_() {
        const auto s = store();
        auto* state = workspace_state();
        auto* edit = edit_controller_();
        if (s == nullptr || state == nullptr || edit == nullptr) return 0;
        Json& root = s->document().root();
        std::vector<std::string> evidence_refs;
        {
            Json ws_storage;
            const Json* ws = workspace_json_ptr_(ws_storage);
            std::set<std::string> seen;
            for (const auto& [label, selector] :
                 workflow_interpretation::evidence_view(root, ws)) {
                if (seen.insert(selector).second) {
                    evidence_refs.push_back(selector);
                }
            }
        }
        std::sort(evidence_refs.begin(), evidence_refs.end());
        std::vector<std::pair<std::string, std::string>> targets;
        for (const std::string& layer_id : workspace::layers_with_role(
                 *state,
                 std::string(
                     ui_composite::layer_role::kInitialFaciesDraft))) {
            targets.emplace_back(layer_id,
                                 workflow_interpretation::
                                     TARGET_PHASE1_DRAFT);
        }
        for (const std::string& layer_id : workspace::layers_with_role(
                 *state,
                 std::string(
                     ui_composite::layer_role::kIntegratedFacies))) {
            targets.emplace_back(
                layer_id,
                workflow_interpretation::TARGET_INTEGRATED_FACIES);
        }
        for (const std::string& layer_id : workspace::layers_with_role(
                 *state,
                 std::string(
                     ui_composite::layer_role::kIntegratedBoundary))) {
            targets.emplace_back(
                layer_id,
                workflow_interpretation::TARGET_INTEGRATED_BOUNDARY);
        }
        int recorded = 0;
        for (const auto& [layer_id, target_kind] : targets) {
            if (record_revision_for_layer_(layer_id, target_kind, "manual",
                                           "", evidence_refs,
                                           "人工解释保存（stage_save 溯源）")) {
                ++recorded;
            }
        }
        return recorded;
    }

    // 单层修订记录（无变化 → false）。
    bool record_revision_for_layer_(
        const std::string& layer_id, const std::string& target_kind,
        const std::string& base_kind = "manual",
        const std::string& base_version_id = "",
        const std::vector<std::string>& evidence_refs = {},
        const std::string& note = "") {
        const auto s = store();
        auto* edit = edit_controller_();
        if (s == nullptr || edit == nullptr) return false;
        auto* layer = edit->layer(layer_id);
        if (layer == nullptr) return false;
        Json& root = s->document().root();
        try {
            std::string interpretation_id;
            if (auto interpretation =
                    workflow_interpretation::find_by_layer(root, layer_id)) {
                interpretation_id =
                    interpretation->interpretation_id;
            }
            auto revision =
                workflow_interpretation::record_interpretation_revision(
                    root, target_kind, layer_id, layer_json_(layer),
                    "workstation", "", interpretation_id, base_kind,
                    base_version_id, evidence_refs, note);
            return revision.has_value();
        } catch (const std::exception&) {
            return false;  // 修订失败不阻断保存路径
        }
    }

    // flush 后把组合编辑层的要素写回工程文档（user_vector_layers 按 id
    // upsert —— 约束回填/修订指纹在此之后读文档侧几何）。
    void persist_composite_layers_() {
        const auto s = store();
        auto* edit = edit_controller_();
        if (s == nullptr || edit == nullptr) return;
        Json ws = workspace_json_();
        const auto records = edit->sync_to_project(ws);
        if (records.empty()) return;
        Json& root = s->document().root();
        if (!root.contains("user_vector_layers")
            || !root["user_vector_layers"].is_array()) {
            root["user_vector_layers"] = Json::array();
        }
        Json& layers = root["user_vector_layers"];
        for (const Json& record : records) {
            const std::string id = jstr(record, "id");
            if (id.empty()) continue;
            bool replaced = false;
            for (Json& existing : layers) {
                if (existing.is_object()
                    && jstr(existing, "id") == id) {
                    existing = record;
                    replaced = true;
                    break;
                }
            }
            if (!replaced) layers.push_back(record);
        }
    }

    void assemble_map_product_() {
#if defined(PWB_WITH_CLOSURE_WORKFLOW)
        const auto s = store();
        if (s == nullptr) {
            throw std::runtime_error("请先打开工程");
        }
        auto* catalog = runtime_catalog();
        if (catalog == nullptr) {
            throw std::runtime_error("数据目录不可用（先打开工程文件）");
        }
        bool ok = false;
        const QString name = QInputDialog::getText(
            window_, QStringLiteral("组装图件产品"),
            QStringLiteral("产品名称："), QLineEdit::Normal, {}, &ok);
        if (!ok || name.trimmed().isEmpty()) return;
        const std::string product_name = name.trimmed().toStdString();

        Json& root = s->document().root();
        sync_workspace_state_();
        auto assembly = closure_workflow::assembly_from_workspace(
            root, product_name);
        if (assembly.factor_task_ids.empty()) {
            status("证据集中没有单因素任务——先选择证据（含 factor 版本）");
            return;
        }
        const Json manifest = closure_workflow::build_product_manifest(
            root, product_name, assembly.factor_task_ids);
        closure_workflow::AssembleDeps deps;
        deps.catalog = catalog;
        deps.payload_json = manifest.dump();
        const auto result = closure_workflow::assemble_map_product(
            root, assembly, deps);
        const auto saved = s->save_document();
        if (!saved.ok()) {
            throw std::runtime_error("工程保存失败：" + saved.message);
        }
        status("MapProduct 已生成（" + result.record_id + "；输出版本 "
               + result.output_version_id.substr(
                     0, std::min<std::size_t>(
                            result.output_version_id.size(), 12))
               + "…）");
        push_project_to_pages_();
#else
        throw std::runtime_error(
            "图件产品装配服务未接入（PWB_BUILD_CPP_CLOSE_02 未启用）");
#endif
    }

    // ----------------------------------------------------- factor shelf --

    // The active map document of the document bank (nullptr when none).
    const Json* active_map_document_() const {
        auto* bank = closure_mapping::document_bank(window_);
        if (bank == nullptr) return nullptr;
        const std::string active = bank->active_id();
        if (active.empty()) return nullptr;
        for (const Json& doc : bank->documents()) {
            if (jstr(doc, "id") == active) return &doc;
        }
        return nullptr;
    }

    // constraint_diagnostics_for parity (bounded port): the project's live
    // break/direction/boundary constraints → capability matrix verdict.
    // This dialog/agent path's interpolators honor NO geological
    // constraints — whatever the project carries is recorded as
    // requested-but-ignored on the task, never silently dropped.
    static std::optional<Json> constraint_diagnostics_for_(
        const Json& root, const std::string& method,
        const std::string& horizon) {
        const auto role_active = [&](const char* role,
                                     std::size_t min_points) {
            const Json* groups = jfield(root, "constraint_layers");
            if (groups == nullptr || !groups->is_array()) return false;
            for (const Json& group : *groups) {
                const std::string group_horizon =
                    jstr(group, "target_horizon");
                if (!horizon.empty() && !group_horizon.empty()
                    && group_horizon != horizon) {
                    continue;
                }
                const Json* lines = jfield(group, "lines");
                if (lines == nullptr || !lines->is_array()) continue;
                for (const Json& line : *lines) {
                    const Json* active = jfield(line, "active");
                    if (active != nullptr && active->is_boolean()
                        && !active->get<bool>()) {
                        continue;
                    }
                    if (jstr(line, "role") != role) continue;
                    const std::string line_horizon =
                        jstr(line, "target_horizon");
                    if (!horizon.empty() && !line_horizon.empty()
                        && line_horizon != horizon) {
                        continue;
                    }
                    const Json* coords = jfield(line, "coordinates");
                    if (coords != nullptr && coords->is_array()
                        && coords->size() >= min_points) {
                        return true;
                    }
                }
            }
            return false;
        };
        std::vector<std::string> requested;
        if (role_active("break", 2)) requested.push_back("barrier");
        if (role_active("direction", 2)) requested.push_back("direction");
        if (role_active("boundary", 3)) {
            requested.push_back("boundary_mask");
        }
        if (requested.empty()) return std::nullopt;
        return workflow_interpretation::evaluate_request(method, requested)
            .as_dict();
    }

    // GeologicalMappingService.create_factor_map C++ production chain
    // (§ native_factor_map): extract → interpolate → FactorMapTask record
    // → live grid registration → PaleoMapDocument compatibility record →
    // staleness anchors. The service runs on the dialog's worker thread —
    // it captures the project ROOT BY VALUE (document mutation stays on
    // the GUI thread in on_factor_map_created_) plus the thread-safe live
    // grid store; the thread-confined catalog seam is never touched.
    ui_seqviz::FactorMapServiceFn make_factor_map_service_() const {
#if defined(PWB_WITH_FACTOR_KERNEL)
        const auto s = store();
        if (s == nullptr) return nullptr;
        auto grids = grids_;
        const Json root = s->document().root();
        return [grids, root](const ui_seqviz::FactorMapParams& params)
                   -> ui_seqviz::FactorMapOutcome {
            // resolve_horizon: params → stratigraphy → "T1".
            std::string horizon = params.target_horizon;
            if (horizon.empty()) {
                if (const Json* stratigraphy = jfield(root, "stratigraphy");
                    stratigraphy != nullptr && stratigraphy->is_object()) {
                    horizon = jstr(*stratigraphy, "target_horizon");
                }
            }
            if (horizon.empty()) horizon = "T1";
            const std::string factor = params.factor_name;
            const std::string ramp =
                params.color_ramp.empty() ? "porosity" : params.color_ramp;
            const std::string crs = project_crs_of(root);

            // extract_well_factors: well tables → domain wells → existing
            // tasks' sample points → synthetic fallback (source_kind mock).
            std::vector<mapping::SamplePoint> samples;
            bool synthesized = false;
            const Json* tables = jfield(root, "well_tables");
            if (tables != nullptr && tables->is_array()) {
                for (const Json& table : *tables) {
                    const std::string table_horizon =
                        jstr(table, "target_horizon");
                    if (!table_horizon.empty()
                        && table_horizon != horizon) {
                        continue;
                    }
                    const Json points =
                        factor_production::sample_points_from_well_table(
                            table, /*include_flagged=*/false,
                            factor_production::value_key_for_factor_type(
                                factor));
                    for (const Json& point : points) {
                        if (!point.is_object()) continue;
                        const Json* x = jfield(point, "x");
                        const Json* y = jfield(point, "y");
                        const Json* value = jfield(point, "value");
                        if (x == nullptr || y == nullptr || value == nullptr
                            || !x->is_number() || !y->is_number()
                            || !value->is_number()) {
                            continue;
                        }
                        mapping::SamplePoint sample;
                        sample.x = x->get<double>();
                        sample.y = y->get<double>();
                        sample.value = value->get<double>();
                        sample.qc_flag = jstr(point, "qc_flag", "ok");
                        samples.push_back(sample);
                    }
                }
            }
            if (samples.empty()) {
                const Json* wells = jfield(root, "wells");
                if (wells != nullptr && wells->is_array()) {
                    for (const Json& well : *wells) {
                        const Json* x = jfield(well, "project_x");
                        const Json* y = jfield(well, "project_y");
                        if (x == nullptr || y == nullptr) {
                            x = jfield(well, "surface_x");
                            y = jfield(well, "surface_y");
                        }
                        if (x == nullptr || y == nullptr || !x->is_number()
                            || !y->is_number()) {
                            continue;
                        }
                        const double wx = x->get<double>();
                        const double wy = y->get<double>();
                        if (!std::isfinite(wx) || !std::isfinite(wy)) {
                            continue;
                        }
                        if (jstr(well, "coordinate_status") == "invalid") {
                            continue;
                        }
                        const Json* z = jfield(well, "surface_z");
                        if (z == nullptr || !z->is_number()) continue;
                        mapping::SamplePoint sample;
                        sample.x = wx;
                        sample.y = wy;
                        sample.value = z->get<double>();
                        sample.qc_flag = "ok";
                        samples.push_back(sample);
                    }
                }
            }
            if (samples.empty()) {
                const Json* tasks = jfield(root, "factor_map_tasks");
                if (tasks != nullptr && tasks->is_array()) {
                    for (const Json& task : *tasks) {
                        const std::string task_horizon =
                            jstr(task, "target_horizon");
                        if (!task_horizon.empty()
                            && task_horizon != horizon) {
                            continue;
                        }
                        if (jstr(task, "factor_type") != factor) continue;
                        const Json* parameters = jfield(task, "parameters");
                        const Json* points = parameters != nullptr
                                                 ? jfield(*parameters,
                                                          "sample_points")
                                                 : nullptr;
                        if (points == nullptr || !points->is_array()) {
                            continue;
                        }
                        for (const Json& point : *points) {
                            if (!point.is_object()) continue;
                            const Json* x = jfield(point, "x");
                            const Json* y = jfield(point, "y");
                            const Json* value = jfield(point, "value");
                            if (x == nullptr || y == nullptr
                                || value == nullptr || !x->is_number()
                                || !y->is_number() || !value->is_number()) {
                                continue;
                            }
                            mapping::SamplePoint sample;
                            sample.x = x->get<double>();
                            sample.y = y->get<double>();
                            sample.value = value->get<double>();
                            sample.qc_flag = "ok";
                            samples.push_back(sample);
                        }
                        if (!samples.empty()) break;
                    }
                }
            }
            if (samples.empty()) {
                for (const auto& point : ui_workers::synthetic_sample_points(
                         /*seed=*/42, factor, /*count=*/12)) {
                    mapping::SamplePoint sample;
                    const auto number = [&point](const char* key)
                        -> std::optional<double> {
                        const auto it = point.find(key);
                        if (it == point.end()) return std::nullopt;
                        if (const auto* v = std::any_cast<double>(&it->second)) {
                            return *v;
                        }
                        if (const auto* v = std::any_cast<int>(&it->second)) {
                            return static_cast<double>(*v);
                        }
                        return std::nullopt;
                    };
                    const auto x = number("x");
                    const auto y = number("y");
                    const auto value = number("value");
                    if (!x.has_value() || !y.has_value()
                        || !value.has_value()) {
                        continue;
                    }
                    sample.x = *x;
                    sample.y = *y;
                    sample.value = *value;
                    sample.qc_flag = "ok";
                    samples.push_back(sample);
                }
                synthesized = true;
            }

            // interpolate（对话框路径不吃约束——见上 diagnostics）。
            mapping::InterpolateOptions options;
            options.method = params.method;
            options.grid_n = params.grid_n;
            options.variogram_model = "spherical";
            options.crs = crs;
            const mapping::FactorGrid grid =
                mapping::interpolate_factor(samples, options);

            // FactorMapTask record (task side lands on the GUI thread).
            const std::string task_id = domain::make_id("task_");
            Json task = Json::object();
            task["id"] = task_id;
            task["name"] = horizon + " " + factor;
            task["target_horizon"] = horizon;
            task["factor_type"] = factor;
            task["method"] = params.method;
            Json parameters = Json::object();
            parameters["grid_n"] = params.grid_n;
            parameters["color_ramp"] = ramp;
            parameters["sample_count"] = samples.size();
            Json quality = Json::object();
            quality["grid"] =
                std::to_string(grid.grid_y.size()) + "×"
                + std::to_string(grid.grid_x.size());
            if (std::isfinite(grid.statistics.min)
                && std::isfinite(grid.statistics.max)) {
                quality["range"] = Json::array(
                    {grid.statistics.min, grid.statistics.max});
            }
            if (synthesized) {
                task["source_kind"] = "mock";
                quality["synthesized_fallback"] = true;
            } else {
                task["source_kind"] = "real";
            }
            if (const auto diagnostics = constraint_diagnostics_for_(
                    root, params.method, horizon);
                diagnostics.has_value()) {
                parameters["constraint_diagnostics"] = *diagnostics;
                if (const Json* unsupported =
                        jfield(*diagnostics, "unsupported_constraints");
                    unsupported != nullptr && unsupported->is_array()
                    && !unsupported->empty()) {
                    quality["constraints_ignored"] = *unsupported;
                }
            }
            task["parameters"] = std::move(parameters);
            task["quality_metrics"] = std::move(quality);
            task["status"] = "complete";

            // Staleness anchors (V9 P0-1): constraint pins without a
            // repository binding (Python calls with no catalog).
            {
                Json pins = workflow_runtime::constraint_pins_for_task(
                    task, root, nullptr);
                if (pins.is_array() && !pins.empty()) {
                    task["parameters"]["constraint_pins"] = pins;
                }
            }

            // grid_metadata descriptor (CONV-18 codec, metadata only).
            mapping::FactorGridEnvelope envelope;
            envelope.height =
                static_cast<int>(grid.grid_y.size());
            envelope.width = static_cast<int>(grid.grid_x.size());
            envelope.grid_x = grid.grid_x;
            envelope.grid_y = grid.grid_y;
            envelope.grid_z = grid.grid_z;
            envelope.variance_grid = grid.variance_grid;
            envelope.factor_name = factor;
            envelope.algorithm_id = grid.method;
            Json algorithm_parameters = Json::object();
            algorithm_parameters["grid_label"] =
                std::to_string(envelope.height) + "×"
                + std::to_string(envelope.width);
            algorithm_parameters["n_points"] = samples.size();
            algorithm_parameters["method"] = params.method;
            envelope.algorithm_parameters = std::move(algorithm_parameters);
            envelope.crs = crs.empty() ? Json(nullptr) : Json(crs);
            envelope.generator_version =
                ui_workers::kFactorInterpGeneratorVersion;
            envelope.statistics = grid.statistics;
            task["grid_metadata"] = mapping::to_descriptor(envelope);

            // Live grid registration under the task id (the same seam the
            // workflow interpolation paths use — thread-safe store).
            if (grids != nullptr) {
                factor_production::LiveGridEntry entry;
                entry.grid_x = grid.grid_x;
                entry.grid_y = grid.grid_y;
                entry.grid_z = grid.grid_z;
                entry.variance_grid = grid.variance_grid;
                entry.result_fingerprint = domain::make_id("fp");
                entry.metadata = task["grid_metadata"];
                grids->store(task_id, std::move(entry));
            }

            // PaleoMapDocument compatibility record: the vector features
            // are the interoperable payload (grid reachable via the task
            // link, never silently dropped — #1034).
            const std::string title = horizon + " " + factor + " 分布图";
            Json map_document = Json::object();
            map_document["id"] = domain::make_id("map_");
            map_document["name"] = title;
            map_document["linked_target_horizon"] = horizon;
            map_document["linked_factor_task_id"] = task_id;
            map_document["map_crs"] = crs;
            Json line_features = Json::array();
            Json well_overlays = Json::array();
            Json facies_polygons = Json::array();
            long long layer_count = 0;
            if (params.include_grid) ++layer_count;

            // grid → contouring Grid for the vector side products.
            mapping::Grid contour_grid;
            contour_grid.w = envelope.width;
            contour_grid.h = envelope.height;
            contour_grid.grid_x = grid.grid_x;
            contour_grid.grid_y = grid.grid_y;
            contour_grid.grid_z.reserve(grid.grid_z.size());
            for (float cell : grid.grid_z) {
                contour_grid.grid_z.push_back(static_cast<double>(cell));
            }
            if (params.include_contours
                && !contour_grid.grid_z.empty()) {
                const std::vector<double> levels =
                    mapping::quantile_contour_levels(contour_grid);
                for (double level : levels) {
                    for (const mapping::Polyline& line :
                         mapping::marching_squares_contours(contour_grid,
                                                            level)) {
                        if (line.size() < 2) continue;
                        Json coordinates = Json::array();
                        for (const mapping::Point& point : line) {
                            coordinates.push_back(
                                Json::array({point[0], point[1]}));
                        }
                        Json geometry = Json::object();
                        geometry["type"] = "LineString";
                        geometry["coordinates"] = std::move(coordinates);
                        Json feature = Json::object();
                        feature["id"] = domain::make_id("feat");
                        feature["role"] = "contour";
                        feature["geometry"] = std::move(geometry);
                        Json props = Json::object();
                        props["level"] = level;
                        props["factor"] = factor;
                        feature["properties"] = std::move(props);
                        line_features.push_back(std::move(feature));
                    }
                }
                if (!line_features.empty()) ++layer_count;
            }
            if (params.include_wells) {
                for (const mapping::SamplePoint& sample :
                     mapping::valid_points(samples)) {
                    Json geometry = Json::object();
                    geometry["type"] = "Point";
                    geometry["coordinates"] =
                        Json::array({sample.x, sample.y});
                    Json feature = Json::object();
                    feature["id"] = domain::make_id("feat");
                    feature["role"] = "well_point";
                    feature["geometry"] = std::move(geometry);
                    Json props = Json::object();
                    props["value"] = sample.value;
                    feature["properties"] = std::move(props);
                    well_overlays.push_back(std::move(feature));
                }
                if (!well_overlays.empty()) ++layer_count;
            }
            if (params.include_polygons && !contour_grid.grid_z.empty()) {
                // generate_facies_polygon_layer semantics: the grid's own
                // vmin/vmax default thresholds + 低/中/高 bands.
                const std::vector<double> thresholds =
                    mapping::default_class_thresholds(
                        grid.statistics.min, grid.statistics.max);
                const std::vector<std::string> names = {"低", "中", "高"};
                const std::vector<std::int16_t> class_grid =
                    mapping::classify_grid(contour_grid, thresholds,
                                           static_cast<int>(names.size()));
                for (std::size_t index = 0; index < names.size(); ++index) {
                    const auto [polygons, qc] = mapping::polygonize_class(
                        contour_grid, class_grid,
                        static_cast<int>(index));
                    (void)qc;
                    for (const mapping::Polygon& polygon : polygons) {
                        Json rings = Json::array();
                        auto ring_json =
                            [](const std::vector<mapping::Point>& ring) {
                                Json out = Json::array();
                                for (const mapping::Point& point : ring) {
                                    out.push_back(Json::array(
                                        {point[0], point[1]}));
                                }
                                return out;
                            };
                        Json coordinates = Json::array();
                        coordinates.push_back(
                            ring_json(polygon.exterior));
                        for (const auto& hole : polygon.holes) {
                            coordinates.push_back(ring_json(hole));
                        }
                        Json geometry = Json::object();
                        geometry["type"] = "Polygon";
                        geometry["coordinates"] = std::move(coordinates);
                        Json feature = Json::object();
                        feature["id"] = domain::make_id("feat");
                        feature["role"] = "facies";
                        feature["geometry"] = std::move(geometry);
                        Json props = Json::object();
                        props["facies"] = names[index];
                        props["factor"] = factor;
                        feature["properties"] = std::move(props);
                        facies_polygons.push_back(std::move(feature));
                    }
                }
                if (!facies_polygons.empty()) ++layer_count;
            }
            map_document["line_features"] = std::move(line_features);
            map_document["well_overlays"] = std::move(well_overlays);
            map_document["facies_polygons"] = std::move(facies_polygons);

            ui_seqviz::FactorMapOutcome outcome;
            outcome.map_document = std::any(map_document);
            outcome.task = std::any(task);
            outcome.map_title = title;
            outcome.layer_count = layer_count;
            return outcome;
        };
#else
        return nullptr;
#endif
    }

    // _on_create_factor_map_requested parity: modal dialog over the
    // production service; the created task + map document land on the GUI
    // thread (the project document never mutates from the worker).
    void open_factor_map_dialog_() {
        const auto s = store();
        if (s == nullptr) {
            QMessageBox::information(window_, QStringLiteral("地质单因素编图"),
                                     QStringLiteral("请先打开或绑定工程。"));
            return;
        }
        auto* dialog = new ui_seqviz::qt::CreateFactorMapDialog(window_);
        dialog->set_service(make_factor_map_service_());
        std::string target;
        if (const Json* stratigraphy =
                jfield(s->document().root(), "stratigraphy");
            stratigraphy != nullptr && stratigraphy->is_object()) {
            target = jstr(*stratigraphy, "target_horizon");
        }
        dialog->set_stratigraphy_target(
            QString::fromStdString(target));
        connect(dialog, &ui_seqviz::qt::CreateFactorMapDialog::map_created,
                this, [this](const ui_seqviz::FactorMapOutcome& outcome) {
                    on_factor_map_created_(outcome);
                });
        connect(dialog,
                &ui_seqviz::qt::CreateFactorMapDialog::info_requested, this,
                [this](const QString& title, const QString& message) {
                    QMessageBox::information(window_, title, message);
                });
        connect(dialog,
                &ui_seqviz::qt::CreateFactorMapDialog::error_requested, this,
                [this](const QString& title, const QString& message) {
                    QMessageBox::critical(window_, title, message);
                });
        dialog->setAttribute(Qt::WA_DeleteOnClose);
        dialog->setModal(true);
        dialog->show();
    }

    // _on_geological_factor_map_created parity: adopt the task + map
    // document into the project tree, refresh the mapping surfaces.
    void on_factor_map_created_(const ui_seqviz::FactorMapOutcome& outcome) {
        const auto s = store();
        if (s == nullptr) return;
        const auto* task = std::any_cast<Json>(&outcome.task);
        const auto* map_document =
            std::any_cast<Json>(&outcome.map_document);
        if (task == nullptr || map_document == nullptr) return;
        Json& root = s->document().root();
        if (!root.contains("factor_map_tasks")
            || !root["factor_map_tasks"].is_array()) {
            root["factor_map_tasks"] = Json::array();
        }
        root["factor_map_tasks"].push_back(*task);
        if (!root.contains("paleomap_documents")
            || !root["paleomap_documents"].is_array()) {
            root["paleomap_documents"] = Json::array();
        }
        root["paleomap_documents"].push_back(*map_document);
        controller_->core().on_factor_maps_updated();
        push_project_to_pages_();
        status("已生成地质图件：" + outcome.map_title);
    }

#if defined(PWB_WITH_CLOSURE_WORKFLOW)
    // _on_fault_interpretation_requested parity (P1-B): lift the active
    // map's break/fault polylines into a versioned fault interpretation —
    // map-plane coordinates stay the scientific authority, the lifecycle
    // mints the immutable DERIVED version + lineage.
    void fault_interpretation_requested_() {
        const auto s = store();
        if (s == nullptr || s->project_file().empty()) {
            QMessageBox::information(
                window_, QStringLiteral("断层解释"),
                QStringLiteral("请先打开并保存工程。"));
            return;
        }
        const Json* document = active_map_document_();
        if (document == nullptr) {
            QMessageBox::information(window_, QStringLiteral("断层解释"),
                                     QStringLiteral("当前没有活动图件。"));
            return;
        }
        // constraints_from_map_document: constraint-role line features.
        Json layers = Json::object();
        layers["name"] = jstr(*document, "name") + " 约束";
        layers["target_horizon"] = jstr(*document, "linked_target_horizon");
        Json lines = Json::array();
        if (const Json* features = jfield(*document, "line_features");
            features != nullptr && features->is_array()) {
            for (const Json& feature : *features) {
                if (!feature.is_object()) continue;
                const Json* props = jfield(feature, "properties");
                const Json* props_object =
                    props != nullptr && props->is_object() ? props : nullptr;
                std::string role = jstr(feature, "role");
                if (role.empty() && props_object != nullptr) {
                    role = jstr(*props_object, "role");
                    if (role.empty()) {
                        role = jstr(*props_object, "constraint_role");
                    }
                }
                if (role != "break" && role != "fault") continue;
                const Json* coords = jfield(feature, "coordinates");
                if (coords == nullptr) {
                    if (const Json* geometry = jfield(feature, "geometry");
                        geometry != nullptr && geometry->is_object()
                        && jstr(*geometry, "type") == "LineString") {
                        coords = jfield(*geometry, "coordinates");
                    }
                }
                if (coords == nullptr || !coords->is_array()
                    || coords->size() < 2) {
                    continue;
                }
                Json line = Json::object();
                line["id"] = jstr(feature, "id");
                line["name"] = jstr(feature, "name");
                if (line["name"].is_null() && props_object != nullptr) {
                    line["name"] = jstr(*props_object, "name");
                }
                line["role"] = role;
                line["coordinates"] = *coords;
                lines.push_back(std::move(line));
            }
        }
        layers["lines"] = std::move(lines);

        auto draft = workflow_interpretation::draft_from_constraint_layers(
            layers, /*name=*/"断层解释",
            /*crs=*/jstr(*document, "map_crs"));
        if (draft.payload.traces.empty()) {
            QMessageBox::information(
                window_, QStringLiteral("断层解释"),
                QStringLiteral("当前图件没有断线/断层多段线，无可保存的断层解释。"));
            return;
        }
        const std::filesystem::path project_file = s->project_file();
        const std::filesystem::path fault_dir =
            pwb::project::artifact_dir_for(project_file) / "faults";
        Json& root = s->document().root();
        try {
            const auto [ref, message] =
                workflow_interpretation::save_fault_draft(
                    draft, root, fault_dir, project_file.parent_path(),
                    runtime_catalog());
            if (!ref.has_value()) {
                QMessageBox::warning(
                    window_, QStringLiteral("断层解释"),
                    QStringLiteral("保存失败: %1")
                        .arg(QString::fromStdString(message)));
                return;
            }
        } catch (const std::exception& exc) {
            QMessageBox::warning(
                window_, QStringLiteral("断层解释"),
                QStringLiteral("保存失败: %1")
                    .arg(QString::fromStdString(exc.what())));
            return;
        }
        QMessageBox::information(
            window_, QStringLiteral("断层解释"),
            QStringLiteral("已保存断层解释版本（%1 条断层）")
                .arg(draft.payload.traces.size()));
    }
#endif  // PWB_WITH_CLOSURE_WORKFLOW

    void install_factor_shelf_() {
        auto* shelf = factor_shelf();
        if (shelf == nullptr) return;
        connect(shelf,
                &ui_pages_mapedit::MapFactorShelf::
                    contour_draft_requested,
                this, [this] {
                    // Route through the task panel's public signal — the
                    // page's private slot consumes it exactly like the
                    // in-page button press (no private-slot reach-around).
                    auto* page =
                        closure_mapping::preparation_page(window_);
                    if (page == nullptr) return;
                    if (auto* panel = page->task_panel();
                        panel != nullptr) {
                        panel->contour_draft_requested();
                    }
                });
        connect(shelf,
                &ui_pages_mapedit::MapFactorShelf::
                    map_product_requested,
                this, [this] {
                    try {
                        assemble_map_product_();
                    } catch (const std::exception& exc) {
                        status(exc.what());
                    }
                });
        connect(shelf,
                &ui_pages_mapedit::MapFactorShelf::
                    factor_overlay_requested,
                this, [this](const QString& overlay_id) {
                    // 因子叠加：叠加已完成单因素任务的六子层组（overlay_id
                    // 仅作诊断回显——子层组按任务整体构建）。
                    try {
                        overlay_factor_results_();
                    } catch (const std::exception& exc) {
                        status(std::string("因子叠加失败（")
                               + overlay_id.toStdString() + "）："
                               + exc.what());
                    }
                });
        connect(shelf,
                &ui_pages_mapedit::MapFactorShelf::
                    create_factor_map_requested,
                this, [this] { open_factor_map_dialog_(); });
#if defined(PWB_WITH_CLOSURE_WORKFLOW)
        connect(shelf,
                &ui_pages_mapedit::MapFactorShelf::
                    fault_interpretation_requested,
                this, [this] { fault_interpretation_requested_(); });
#else
        connect(shelf,
                &ui_pages_mapedit::MapFactorShelf::
                    fault_interpretation_requested,
                this, [this] {
                    status("断层解释流程未接入（编译工作流未启用）");
                });
#endif
    }

    QMainWindow* window_ = nullptr;
    AppShell* shell_ = nullptr;
    AppContext* context_ = nullptr;
    ui_controllers::qt::WorkflowController* controller_ = nullptr;

#if defined(PWB_WITH_CATALOG_CLOSURE)
    // Per-project deep catalog (CatalogServiceApi/CatalogPortApi owner —
    // the runtime bag is rebuilt on every notify).
    std::optional<closure_catalog::InstalledCatalogClosure>
        catalog_closure_;
#endif
#if defined(PWB_WITH_FACTOR_KERNEL)
    std::shared_ptr<factor_production::LiveFactorGridStore> grids_;
    // Recompute-time exec-context scratch (interpolate_fn builds the
    // PrepareExecContext against these members — the references must
    // outlive the batch call).
    Json ctx_coordinate_ = Json::object();
    Json ctx_stratigraphy_ = Json::object();
    std::vector<std::any> ctx_constraints_;
    std::optional<std::string> ctx_crs_;
#endif
    // Pages hold non-owning pointers into these slices — rebuild in place,
    // never rebind mid-call.
    ui_wellseis::ProjectSlice wellseis_slice_;
    ui_seqviz::StratigraphyProjectSlice stratigraphy_slice_;
    ui_workers::CorrelationProjectSlice correlation_slice_;
    ui_seqviz::VizPageProjectSlice viz_slice_;
};

WorkflowBinding* binding_for(QMainWindow* window) {
    if (window == nullptr) return nullptr;
    const QVariant stored = window->property("pwb_workflow_binding");
    return dynamic_cast<WorkflowBinding*>(
        stored.value<QObject*>());
}

}  // namespace

bool install(QMainWindow* window, AppShell* shell, AppContext* context,
             JobCenter* jobs) {
    if (window == nullptr || shell == nullptr || jobs == nullptr) {
        return false;
    }
    if (binding_for(window) != nullptr) return true;
    auto* binding = new WorkflowBinding(window, shell, context, jobs);
    window->setProperty(
        "pwb_workflow_binding",
        QVariant::fromValue(static_cast<QObject*>(binding)));
    return true;
}

void notify_project_changed(QMainWindow* window) {
    if (auto* binding = binding_for(window); binding != nullptr) {
        binding->notify_project_changed();
    }
}

}  // namespace pwb::app::workflow_wiring
