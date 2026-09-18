// CompositionLayoutService — implementation (CONV-29).

#include <pwb/qgis/composition_layout_service.hpp>

#include <stdexcept>
#include <system_error>
#include <utility>

#include <QString>

#include <qgscoordinatereferencesystem.h>
#include <qgsmaplayer.h>
#include <qgsproject.h>

#include "layout_spec_exec.hpp"

#include <pwb/layout_export/layout_export.hpp>
#include <pwb/mapping_document/composition.hpp>
#include <pwb/qgis/map_session.hpp>

namespace pwb::qgis {

namespace {

using pwb::domain::Json;

Json failure_report(const std::string& failure) {
    Json out = Json::object();
    out["ok"] = false;
    out["failure"] = failure;
    return out;
}

std::string join(const std::vector<std::string>& parts,
                 const std::string& sep) {
    std::string out;
    for (std::size_t i = 0; i < parts.size(); ++i) {
        if (i != 0) out += sep;
        out += parts[i];
    }
    return out;
}

pwb::layout_export::ExportRequest to_kernel_request(
    const CompositionExportRequest& request, const std::string& project_crs) {
    pwb::layout_export::ExportRequest kernel;
    kernel.format = request.format;
    kernel.dpi = request.dpi;
    kernel.geo_pdf = request.geo_pdf;
    kernel.force_vector = request.force_vector;
    kernel.has_map_extent = request.has_extent;
    for (int i = 0; i < 4; ++i) kernel.map_extent[i] = request.extent[i];
    kernel.crs = request.crs.empty() ? project_crs : request.crs;
    kernel.mirror_layers = request.mirror_layers;
    return kernel;
}

}  // namespace

CompositionLayoutService::CompositionLayoutService(MapSession& session)
    : session_(session) {}

pwb::layout_spec_exec::ExecContext CompositionLayoutService::exec_context()
    const {
    pwb::layout_spec_exec::ExecContext context;
    context.project = session_.project();
    context.order_top_first = [this] { return session_.layerIdsTopFirst(); };
    context.resolve_layer = [this](const std::string& key) -> QgsMapLayer* {
        if (QgsMapLayer* layer = session_.layerById(key)) return layer;
        QgsProject* project = session_.project();
        if (project == nullptr) return nullptr;
        if (QgsMapLayer* by_id =
                project->mapLayer(QString::fromStdString(key))) {
            return by_id;
        }
        const QList<QgsMapLayer*> by_name =
            project->mapLayersByName(QString::fromStdString(key));
        return by_name.isEmpty() ? nullptr : by_name.first();
    };
    return context;
}

Json CompositionLayoutService::validate_layout(
    const std::string& composition_json,
    const CompositionExportRequest& request) {
    Json out = Json::object();
    pwb::mapping_document::Composition doc;
    try {
        doc = pwb::mapping_document::parse_composition(
            Json::parse(composition_json));
    } catch (const std::exception& ex) {
        return failure_report(std::string("composition parse failed: ")
                              + ex.what());
    }

    std::string project_crs;
    if (session_.project() != nullptr) {
        project_crs = session_.project()->crs().authid().toStdString();
    }
    const pwb::layout_export::ExportRequest kernel_request =
        to_kernel_request(request, project_crs);

    out["page_mm"] = Json::array({doc.width_mm, doc.height_mm});
    const std::vector<std::string> hybrid = pwb::layout_export::hybrid_element_types(
        doc, kernel_request.mirror_layers);
    Json hybrid_json = Json::array();
    for (const std::string& value : hybrid) hybrid_json.push_back(value);
    out["hybrid_items"] = hybrid_json;

    std::vector<std::string> warnings;
    try {
        pwb::layout_export::BuildSpecInput input;
        input.map_extent = kernel_request.map_extent;
        input.crs = kernel_request.crs;
        input.mirror_layers = kernel_request.mirror_layers;
        const Json spec =
            pwb::layout_export::build_layout_spec(doc, input, &warnings);
        Json items = Json::array();
        if (spec.is_object() && spec.contains("items")
            && spec["items"].is_array()) {
            items = spec["items"];
        }
        out["items"] = items.size();
        out["spec"] = spec;
        out["ok"] = hybrid.empty();
        if (!hybrid.empty()) {
            out["failure"] =
                "composition has elements with no native layout counterpart ("
                + join(hybrid, ", ")
                + "); the native chain is fail-closed (no composer fallback)";
        }
    } catch (const std::invalid_argument& ex) {
        warnings.push_back(ex.what());
        out["spec"] = nullptr;
        out["items"] = 0;
        out["ok"] = false;
        out["failure"] = ex.what();
    }
    Json warnings_json = Json::array();
    for (const std::string& w : warnings) warnings_json.push_back(w);
    out["warnings"] = warnings_json;
    return out;
}

Json CompositionLayoutService::export_layout(
    const std::string& composition_json,
    const std::filesystem::path& output_path,
    const CompositionExportRequest& request) {
    pwb::mapping_document::Composition doc;
    try {
        doc = pwb::mapping_document::parse_composition(
            Json::parse(composition_json));
    } catch (const std::exception& ex) {
        return failure_report(std::string("composition parse failed: ")
                              + ex.what());
    }
    std::string project_crs;
    if (session_.project() != nullptr) {
        project_crs = session_.project()->crs().authid().toStdString();
    }
    pwb::layout_export::ExportRequest kernel_request =
        to_kernel_request(request, project_crs);
    pwb::layout_spec_exec::ExecContext context = exec_context();

    pwb::layout_export::LayoutExecutor executor =
        [&context](const std::string& spec_json, const std::string& path,
                   const std::string& format,
                   double dpi) -> Json {
            return Json::parse(pwb::layout_spec_exec::execute_layout_spec(
                context, spec_json, path, format, dpi));
        };

    try {
        const pwb::layout_export::LayoutExportReport report =
            pwb::layout_export::export_composition_reported(
                doc, output_path, kernel_request, &executor);
        return report.to_dict();
    } catch (const std::invalid_argument& ex) {
        // Budget breaches (caller errors) surface as failure reports, not
        // exceptions, so the UI can render them.
        return failure_report(ex.what());
    }
}

Json CompositionLayoutService::preview(
    const std::string& composition_json,
    const std::filesystem::path& preview_dir,
    const CompositionExportRequest& request) {
    CompositionExportRequest preview_request = request;
    preview_request.format = "png";
    preview_request.dpi = 96.0;
    preview_request.geo_pdf = false;
    preview_request.force_vector = false;
    std::error_code ec;
    std::filesystem::create_directories(preview_dir, ec);
    return export_layout(composition_json, preview_dir / "pwb_preview.png",
                         preview_request);
}

Json CompositionLayoutService::export_map_body(
    const std::filesystem::path& output_path, const MapBodyRequest& request) {
    std::string project_crs;
    if (session_.project() != nullptr) {
        project_crs = session_.project()->crs().authid().toStdString();
    }
    if (!request.has_extent) {
        return failure_report("map body export requires an extent");
    }
    if (request.width_mm <= 0.0 || request.height_mm <= 0.0) {
        return failure_report("map body width_mm/height_mm must be positive");
    }
    const std::string crs =
        request.crs.empty() ? project_crs : request.crs;

    // Canvas-equivalent page: a single map item without furniture.
    Json spec = Json::object();
    Json page = Json::object();
    page["width_mm"] = request.width_mm;
    page["height_mm"] = request.height_mm;
    page["background"] = request.transparent ? std::string("#00000000")
                                             : std::string("#ffffff");
    spec["page"] = page;
    Json item = Json::object();
    item["type"] = "map";
    item["key"] = "map";
    item["x"] = 0.0;
    item["y"] = 0.0;
    item["w"] = request.width_mm;
    item["h"] = request.height_mm;
    item["crs"] = crs;
    Json extent = Json::array();
    for (int i = 0; i < 4; ++i) extent.push_back(request.extent[i]);
    item["extent"] = extent;
    item["frame"] = false;  // map body: no neatline frame
    spec["items"] = Json::array({item});
    if (request.force_vector) spec["force_vector"] = true;

    try {
        const pwb::layout_spec_exec::ExecContext context = exec_context();
        const std::string report = pwb::layout_spec_exec::execute_layout_spec(
            context, spec.dump(), output_path.string(), request.format,
            request.dpi);
        Json payload = Json::parse(report);
        payload["map_body"] = true;
        return payload;
    } catch (const std::exception& ex) {
        Json out = failure_report(ex.what());
        out["map_body"] = true;
        return out;
    }
}

Json CompositionLayoutService::parity_report(
    const std::string& canvas_state_json,
    const std::string& composition_json,
    const CompositionExportRequest& request) {
    Json canvas_state;
    try {
        canvas_state = Json::parse(canvas_state_json);
    } catch (const std::exception& ex) {
        return failure_report(std::string("canvas state parse failed: ")
                              + ex.what());
    }
    pwb::mapping_document::Composition doc;
    try {
        doc = pwb::mapping_document::parse_composition(
            Json::parse(composition_json));
    } catch (const std::exception& ex) {
        return failure_report(std::string("composition parse failed: ")
                              + ex.what());
    }
    std::string project_crs;
    if (session_.project() != nullptr) {
        project_crs = session_.project()->crs().authid().toStdString();
    }
    const pwb::layout_export::ExportRequest kernel_request =
        to_kernel_request(request, project_crs);

    Json spec;
    std::vector<std::string> warnings;
    try {
        pwb::layout_export::BuildSpecInput input;
        input.map_extent = kernel_request.map_extent;
        input.crs = kernel_request.crs;
        input.mirror_layers = kernel_request.mirror_layers;
        spec = pwb::layout_export::build_layout_spec(doc, input, &warnings);
    } catch (const std::invalid_argument& ex) {
        return failure_report(ex.what());
    }

    const Json export_state = build_export_state(request, &spec);
    const pwb::layout_export::ParityReport parity =
        pwb::layout_export::screen_export_parity(canvas_state, export_state);
    Json out = parity.to_dict();
    out["export_state"] = export_state;
    out["warnings"] = warnings;
    return out;
}

Json CompositionLayoutService::build_export_state(
    const CompositionExportRequest& request, const Json* spec) const {
    Json state = Json::object();
    // Export extent/CRS: the request, else the session-derived screen
    // equivalent (never silently re-read from a live canvas here).
    if (request.has_extent) {
        state["extent"] = Json::array({request.extent[0], request.extent[1],
                                       request.extent[2], request.extent[3]});
    } else {
        state["extent"] = nullptr;
    }
    std::string project_crs;
    if (session_.project() != nullptr) {
        project_crs = session_.project()->crs().authid().toStdString();
    }
    state["crs"] = request.crs.empty() ? project_crs : request.crs;
    state["layers"] = Json::parse(session_.canvas_state_json())["layers"];

    // Furniture declared by the composition (grid → spec map item,
    // legend → spec legend item): reported so the parity comparer can
    // flag "the export adds/drops furniture relative to the screen".
    bool has_grid = false;
    double grid_ix = 0.0;
    double grid_iy = 0.0;
    bool has_legend = false;
    if (spec != nullptr && spec->is_object() && spec->contains("items")
        && (*spec)["items"].is_array()) {
        for (const Json& item : (*spec)["items"]) {
            if (!item.is_object()) continue;
            const std::string type = item.value("type", "");
            if (type == "map" && item.contains("grid")
                && item["grid"].is_object()) {
                has_grid = true;
                grid_ix = item["grid"].value("interval_x", 0.0);
                grid_iy = item["grid"].value("interval_y", 0.0);
            }
            if (type == "legend") has_legend = true;
        }
    }
    if (has_grid) {
        Json grid = Json::object();
        grid["enabled"] = true;
        grid["interval_x"] = grid_ix;
        grid["interval_y"] = grid_iy;
        state["grid"] = grid;
    } else {
        state["grid"] = false;
    }
    state["legend"] = has_legend;
    return state;
}

}  // namespace pwb::qgis
