// UI-15 core smoke — Qt-free semantics: extent math, snapshot
// signatures/dedup keys, layer-tree order/drop resolution, properties
// payload + Classes validation, symbology normalization/apply, export
// spec/cleanup, QGIS snapshot encoding (full/delta/prune/stale-delta),
// and the backend factory/selection contract.

#include <cmath>
#include <fstream>
#include <memory>
#include <stdexcept>
#include <string>

#include "ui_canvas_test.hpp"

#include <layer_model.hpp>

#include <pwb/ui_canvas/export_core.hpp>
#include <pwb/ui_canvas/layer_properties_core.hpp>
#include <pwb/ui_canvas/layer_tree_core.hpp>
#include <pwb/ui_canvas/map_render_backend.hpp>
#include <pwb/ui_canvas/snapshot_encoder.hpp>
#include <pwb/ui_canvas/symbology_core.hpp>

using namespace pwb::ui_canvas;
using pwb::layer_model::LayerRegistry;
using pwb::layer_model::LayerType;
using pwb::layer_model::MapLayer;

namespace {

bool near(double a, double b, double tol = 1e-9) {
    return std::fabs(a - b) <= tol;
}

MapLayer* add(LayerRegistry& registry, const std::string& id,
              LayerType type = LayerType::Vector) {
    return registry.add_layer(
        std::make_unique<MapLayer>(id, id + "-name", type));
}

// Synchronous fake backend — exercises the MapRenderBackend base contract.
class FakeBackend final : public MapRenderBackend {
public:
    std::string backend_name() const override { return "fake"; }
    bool is_available() const override { return available_; }

    RenderFrame render_sync() override {
        // The Python fallback bumps the generation inside its render path
        // (request_render returns frame.generation) — same here.
        RenderFrame out;
        out.generation = next_generation();
        out.width = output_size().first;
        out.height = output_size().second;
        out.stride = out.width * 4;
        out.rgba.assign(
            static_cast<std::size_t>(out.stride) * out.height, '\x7F');
        return out;
    }
    void shutdown() override {
        ++shutdown_calls;
        MapRenderBackend::shutdown();
    }

    int shutdown_calls = 0;
    bool available_ = true;
};

// Captureless factories — BackendFactory is a raw function pointer.
struct FactoryCounters {
    int plain_calls = 0;
    int unusable_qgis_calls = 0;
    int usable_qgis_calls = 0;
};

FactoryCounters& factory_counters() {
    static FactoryCounters counters;
    return counters;
}

std::shared_ptr<MapRenderBackend> plain_factory() {
    ++factory_counters().plain_calls;
    return std::make_shared<FakeBackend>();
}

std::shared_ptr<MapRenderBackend> unusable_qgis_factory() {
    ++factory_counters().unusable_qgis_calls;
    auto backend = std::make_shared<FakeBackend>();
    backend->available_ = false;
    return backend;
}

std::shared_ptr<MapRenderBackend> usable_qgis_factory() {
    ++factory_counters().usable_qgis_calls;
    return std::make_shared<FakeBackend>();
}

}  // namespace

PWB_TEST(sanitize_extent_swaps_and_pads) {
    Extent e = sanitize_extent({10.0, 5.0, 0.0, 5.0});
    CHECK(near(e[0], 0.0));
    CHECK(near(e[2], 10.0));
    // Degenerate y pads by 1% of the x span around the center (0.05 each).
    CHECK(near(e[1], 4.95));
    CHECK(near(e[3], 5.05));

    bool threw = false;
    try {
        sanitize_extent({0.0, 0.0, std::nan(""), 1.0});
    } catch (const std::invalid_argument&) {
        threw = true;
    }
    CHECK(threw);
}

PWB_TEST(fit_extent_to_aspect_letterboxes) {
    // Extent 10x10 in a 2:1 canvas widens x to a 20-unit span.
    Extent fit = fit_extent_to_aspect({0.0, 0.0, 10.0, 10.0}, 200, 100);
    CHECK(near(fit[0], -5.0));
    CHECK(near(fit[2], 15.0));
    CHECK(near(fit[1], 0.0));
    CHECK(near(fit[3], 10.0));
    // Degenerate canvas clamps to 1px → extent stays centered.
    Extent same = fit_extent_to_aspect({1.0, 2.0, 3.0, 4.0}, 0, 0);
    CHECK(near(same[0], 1.0));
    CHECK(near(same[2], 3.0));
}

PWB_TEST(letterboxed_extent_passthrough_when_close) {
    const Extent e{0.0, 0.0, 16.0, 9.0};
    // Matching aspect (within 1e-3) → unchanged.
    Extent out = letterboxed_extent(e, 1600, 900);
    CHECK(near(out[0], e[0]));
    CHECK(near(out[2], e[2]));
    // Taller target expands the y axis around the center.
    Extent tall = letterboxed_extent(e, 100, 100);
    CHECK(tall[1] < e[1]);
    CHECK(tall[3] > e[3]);
    CHECK(near(tall[0], e[0]));
    // Degenerate target → unchanged.
    Extent deg = letterboxed_extent(e, 0, 0);
    CHECK(near(deg[0], e[0]));
}

PWB_TEST(default_export_height_clamps_and_falls_back) {
    CHECK_EQ(default_export_height({0.0, 0.0, 2.0, 1.0}, 800), 400);
    // width=0 → round(0 * aspect) = 0 → clamps to 64 (Python parity —
    // the clamp is applied to whatever the formula produces).
    CHECK_EQ(default_export_height({0.0, 0.0, 1.0, 1.0}, 0), 64);
    // Degenerate/zero span → Python falls back to 1600.
    CHECK_EQ(default_export_height({0.0, 0.0, 0.0, 5.0}, 800), 1600);
    // Extremes clamp to [64, 16000].
    CHECK_EQ(default_export_height({0.0, 0.0, 1.0, 1000000.0}, 800),
             16000);
    CHECK_EQ(default_export_height({0.0, 0.0, 1000000.0, 1.0}, 800), 64);
}

PWB_TEST(map_coordinate_conversion_roundtrips) {
    Extent view = sanitize_extent({0.0, 0.0, 100.0, 50.0});
    auto px = map_to_screen(view, 200, 100, {50.0, 25.0});
    CHECK(px.has_value());
    // Canvas is 2:1, view is 2:1 → center maps to center.
    CHECK(near(px->first, 100.0, 1.0));
    CHECK(near(px->second, 50.0, 1.0));
    auto world = screen_to_map(view, 200, 100, {100.0, 50.0});
    CHECK(near(world.first, 50.0, 1e-6));
    CHECK(near(world.second, 25.0, 1e-6));
    // Degenerate fitted span → nullopt (Python None parity).
    CHECK(!map_to_screen({0.0, 0.0, 0.0, 0.0}, 200, 100, {0.0, 0.0})
               .has_value());
    CHECK(fitted_map_units_per_pixel(view, 0, 0) <= 0.0 ||
          std::isfinite(fitted_map_units_per_pixel(view, 0, 0)));
}

PWB_TEST(snapshot_signature_dedup_key) {
    MapRenderSnapshot snapshot;
    snapshot.project_crs = "EPSG:4326";
    MapLayerSnapshot layer;
    layer.id = "l1";
    layer.data_revision = 7;
    layer.style_revision = 3;
    layer.visible = true;
    layer.opacity = 0.5;
    layer.source_version_id = "v2";
    snapshot.layers.push_back(layer);

    const std::string sig_a = snapshot_signature(snapshot);
    CHECK(sig_a.find("l1") != std::string::npos);
    CHECK(sig_a.find("EPSG:4326") != std::string::npos);
    // Same snapshot → identical signature (unified-canvas dedup input).
    CHECK_EQ(snapshot_signature(snapshot), sig_a);
    snapshot.layers[0].style_revision = 4;
    CHECK(snapshot_signature(snapshot) != sig_a);
}

PWB_TEST(snapshot_source_version_ids_unique_ordered) {
    MapRenderSnapshot snapshot;
    MapLayerSnapshot a;
    a.source_version_id = "x";
    MapLayerSnapshot b;
    b.source_version_id = "x";  // duplicate collapses
    MapLayerSnapshot c;
    c.source_version_id = "y";
    MapLayerSnapshot d;         // empty skipped
    snapshot.layers = {a, b, c, d};
    const auto ids = snapshot_source_version_ids(snapshot);
    CHECK_EQ(static_cast<long long>(ids.size()), 2);
    CHECK_EQ(ids[0], std::string("x"));
    CHECK_EQ(ids[1], std::string("y"));
}

PWB_TEST(backend_base_validates_and_sync_renders) {
    FakeBackend backend;
    CHECK_EQ(backend.backend_name(), std::string("fake"));
    CHECK(backend.snapshot().layers.empty());

    bool threw = false;
    try {
        backend.set_extent({0.0, 0.0, 0.0, 1.0});  // zero width
    } catch (const std::invalid_argument&) {
        threw = true;
    }
    CHECK(threw);
    threw = false;
    try {
        backend.set_output_size(0, 10);
    } catch (const std::invalid_argument&) {
        threw = true;
    }
    CHECK(threw);
    threw = false;
    try {
        backend.set_dpi(-1.0);
    } catch (const std::invalid_argument&) {
        threw = true;
    }
    CHECK(threw);

    backend.set_extent({0.0, 0.0, 10.0, 10.0});
    backend.set_output_size(8, 8);
    backend.set_dpi(96.0);
    const std::uint64_t gen = backend.request_render();
    CHECK_EQ(static_cast<long long>(gen), 1);
    auto frame = backend.take_completed_frame();
    CHECK(frame.has_value());
    CHECK_EQ(static_cast<long long>(frame->width), 8);
    CHECK_EQ(static_cast<long long>(frame->height), 8);
    // Second poll → nothing left to deliver.
    CHECK(!backend.take_completed_frame().has_value());
    backend.cancel_render();  // no-op by contract
    CHECK(!backend.render_active());
    RenderFrame sync = backend.render_sync();
    CHECK_EQ(static_cast<long long>(sync.width), 8);
    CHECK_EQ(static_cast<long long>(sync.rgba.size()),
             8 * 8 * 4);
    backend.shutdown();
    CHECK_EQ(static_cast<long long>(backend.shutdown_calls), 1);
}

PWB_TEST(backend_factory_selection_and_native_guard) {
    register_backend_factory(&plain_factory, /*is_qgis=*/false);
    register_backend_factory(&unusable_qgis_factory, /*is_qgis=*/true);

    auto selected = create_map_render_backend();
    CHECK(selected != nullptr);
    CHECK_EQ(factory_counters().plain_calls, 1);
    // Non-QGIS selection never consults QGIS factories.
    CHECK_EQ(factory_counters().unusable_qgis_calls, 0);

    // prefer_qgis=false skips the QGIS-marked factories entirely.
    create_map_render_backend(/*prefer_qgis=*/false);
    CHECK_EQ(factory_counters().unusable_qgis_calls, 0);

    // Native-only selection rejects the unusable candidate and falls
    // through to the usable one (initialize() failure → next factory).
    register_backend_factory(&usable_qgis_factory, /*is_qgis=*/true);
    auto native = create_native_map_render_backend();
    CHECK(native != nullptr);
    CHECK_EQ(factory_counters().unusable_qgis_calls, 1);
    CHECK_EQ(factory_counters().usable_qgis_calls, 1);
    CHECK(native->initialized());
}

PWB_TEST(display_children_reverses_registry_order) {
    LayerRegistry registry;
    add(registry, "a");
    add(registry, "b");
    add(registry, "g", LayerType::Group);
    add(registry, "c");
    registry.set_parent("c", "g");

    const auto roots = display_children(registry, "");
    // Root children = a, b, g → displayed reversed (topmost first).
    CHECK_EQ(static_cast<long long>(roots.size()), 3);
    CHECK_EQ(roots[0]->id(), std::string("g"));
    CHECK_EQ(roots[1]->id(), std::string("b"));
    CHECK_EQ(roots[2]->id(), std::string("a"));

    const auto grouped = display_children(registry, "g");
    CHECK_EQ(static_cast<long long>(grouped.size()), 1);
    CHECK_EQ(grouped[0]->id(), std::string("c"));
}

PWB_TEST(resolve_drop_matches_python_index_semantics) {
    LayerRegistry registry;
    add(registry, "a");
    add(registry, "b");
    add(registry, "g", LayerType::Group);
    add(registry, "c");
    registry.set_parent("c", "g");

    // Drop onto a non-group layer resolves to that layer's parent.
    auto on_b = resolve_drop(registry, "a", "b", 0);
    CHECK(on_b.has_value());
    CHECK(on_b->parent_id.has_value());
    CHECK_EQ(*on_b->parent_id, std::string(""));

    // row < 0 appends past the sibling list → absolute index 0.
    auto append = resolve_drop(registry, "a", "g", -1);
    CHECK(append.has_value());
    CHECK_EQ(*append->parent_id, std::string("g"));
    CHECK_EQ(static_cast<long long>(append->absolute_index), 0);

    // Row above the first sibling maps to that sibling's registry index.
    auto top = resolve_drop(registry, "a", "g", 0);
    CHECK(top.has_value());
    CHECK_EQ(*top->parent_id, std::string("g"));
    CHECK_EQ(static_cast<long long>(top->absolute_index),
             static_cast<long long>(registry.index_of("c")));

    // Missing dragged id rejects the drop (nullopt).
    CHECK(!resolve_drop(registry, "zzz", "g", 0).has_value());
}

PWB_TEST(properties_payload_scalar_qgis_legacy) {
    // Scalar path → {name, crs, opacity, scalar_style}; blank name falls
    // back to the layer id.
    PropertiesForm scalar;
    scalar.layer_id = "s1";
    scalar.is_scalar = true;
    scalar.name = "   ";
    scalar.crs = "EPSG:4326";
    scalar.opacity = 0.75;
    Json sp = build_properties_payload(scalar);
    CHECK_EQ(sp.at("name").get<std::string>(), std::string("s1"));
    CHECK(near(sp.at("opacity").get<double>(), 0.75));
    CHECK_EQ(sp.at("scalar_style").at("color_ramp").get<std::string>(),
             std::string("default"));
    CHECK(near(sp.at("scalar_style").at("gamma").get<double>(), 1.0));

    // QGIS path carries the pending native payload + the layer's existing
    // labels config (#929 carry-through).
    PropertiesForm qgis;
    qgis.layer_id = "v1";
    qgis.qgis_symbology = true;
    qgis.name = "Roads";
    qgis.pending_qgis_style = Json{{"renderer_xml", "<r/>"},
                                   {"revision", 4}};
    qgis.existing_style =
        Json{{"labels", Json{{"field", "name"}, {"size", 9.0}}}};
    Json qp = build_properties_payload(qgis);
    CHECK_EQ(qp.at("name").get<std::string>(), std::string("Roads"));
    CHECK_EQ(qp.at("qgis_style").at("renderer_xml").get<std::string>(),
             std::string("<r/>"));
    CHECK_EQ(qp.at("labels").at("field").get<std::string>(),
             std::string("name"));

    // Legacy path → style{fill..renderer, field, labels, categories?}.
    PropertiesForm legacy;
    legacy.layer_id = "l1";
    legacy.name = "Zones";
    legacy.fill = "#FF0000";
    legacy.renderer = "categorized";
    legacy.classification_field = "epoch";
    legacy.classes_text = "{\"a\": \"#fff\"}";
    legacy.label_field = "name";
    legacy.label_size = 11.0;
    Json lp = build_properties_payload(legacy);
    CHECK_EQ(lp.at("style").at("renderer").get<std::string>(),
             std::string("categorized"));
    CHECK(lp.at("style").contains("categories"));
    CHECK_EQ(lp.at("style").at("labels").at("field").get<std::string>(),
             std::string("name"));

    // Invalid classes JSON leaves renderer classes out entirely (host
    // applies the valid style change instead of corrupting state).
    legacy.classes_text = "{not json";
    Json bad = build_properties_payload(legacy);
    CHECK(!bad.at("style").contains("categories"));
}

PWB_TEST(classes_json_error_inline_validation) {
    PropertiesForm form;
    // Scalar / QGIS paths are gated out (Python returns "" early).
    form.is_scalar = true;
    form.classes_text = "{bad";
    CHECK(!classes_json_error(form).has_value());

    form.is_scalar = false;
    form.classes_text = "   ";
    CHECK(!classes_json_error(form).has_value());
    form.classes_text = "{not json";
    const std::optional<std::string> err = classes_json_error(form);
    CHECK(err.has_value());
    CHECK(err->find("Invalid Classes JSON") != std::string::npos);
    form.classes_text = "[{\"label\":\"x\"}]";
    CHECK(!classes_json_error(form).has_value());
}

PWB_TEST(normalize_dialog_style_downgrades_empty_renderers) {
    // categorized/graduated with no fields AND no field → "single" so the
    // native dialog never opens an empty mirror (#937-2).
    Json style = {{"renderer", "categorized"}};
    Json out = normalize_dialog_style(style, /*fields=*/{});
    CHECK_EQ(out.at("renderer").get<std::string>(), std::string("single"));

    // A usable classification field keeps the renderer.
    Json with_field = {{"renderer", "graduated"}, {"field", "epoch"}};
    Json kept = normalize_dialog_style(with_field, {});
    CHECK_EQ(kept.at("renderer").get<std::string>(),
             std::string("graduated"));

    // Available attribute fields also keep it.
    Json kept2 = normalize_dialog_style(style, {"epoch"});
    CHECK_EQ(kept2.at("renderer").get<std::string>(),
             std::string("categorized"));
}

PWB_TEST(geometry_type_for_features) {
    Json features = Json::array({
        Json{{"geometry",
              Json{{"type", "Point"},
                   {"coordinates", Json::array({0, 0})}}}},
    });
    CHECK_EQ(geometry_type_for_features(features), std::string("Point"));
    CHECK_EQ(geometry_type_for_features(Json::array()),
             std::string("Polygon"));
}

PWB_TEST(renderer_request_defaults_and_seed) {
    Json features = Json::array({
        Json{{"geometry", Json{{"type", "Point"},
                               {"coordinates", Json::array({0, 0})}}},
             {"properties", Json{{"kind", "a"}, {"other", "b"}}}},
    });
    Json style = {{"field", "kind"}};
    SymbologyRequest request = build_renderer_request(
        "Layer One", features, "EPSG:4326", {"kind"}, style, std::nullopt,
        std::nullopt);
    CHECK_EQ(request.title, std::string("Layer One"));
    CHECK_EQ(request.geometry_type, std::string("Point"));
    CHECK_EQ(request.fill, std::string("#6c8ebf"));   // legacy default
    CHECK_EQ(request.stroke, std::string("#26364d"));
    // Unstyled request + field → seed_values from the first feature's
    // properties (#937-2 alternative).
    CHECK(!request.seed_values.empty());

    // An authoritative payload wins over legacy migration and suppresses
    // seeding.
    pwb::cartography::QgisStylePayload payload;
    payload.renderer_xml = "<auth-renderer/>";
    payload.labeling_xml = "<labels/>";
    payload.revision = 3;
    SymbologyRequest authed = build_renderer_request(
        "Layer One", features, "EPSG:4326", {"kind"}, style, payload,
        std::optional<std::string>("<legacy/>"));
    CHECK_EQ(authed.renderer_xml, std::string("<auth-renderer/>"));
    CHECK_EQ(authed.labeling_xml, std::string("<labels/>"));
    CHECK(authed.seed_values.empty());
}

PWB_TEST(apply_dialog_result_preserves_labels_and_bumps) {
    pwb::cartography::QgisStylePayload payload;
    payload.renderer_xml = "<old/>";
    payload.labeling_xml = "<existing-labels/>";
    payload.revision = 2;

    // Empty dialog labeling → existing labeling_xml carried through
    // (#937-3 / #929 label preservation).
    Json applied = apply_dialog_result(payload, "<new-renderer/>", "", 0.8);
    const Json& style = applied.at("qgis_style");
    CHECK_EQ(style.at("renderer_xml").get<std::string>(),
             std::string("<new-renderer/>"));
    CHECK_EQ(style.at("labeling_xml").get<std::string>(),
             std::string("<existing-labels/>"));
    CHECK_EQ(style.at("revision").get<long long>(), 3);
    CHECK(near(applied.at("opacity").get<double>(), 0.8));

    // No prior payload → fresh payload at revision 1; dialog labeling wins.
    Json fresh = apply_dialog_result(std::nullopt, "<r/>", "<lab/>", 1.0);
    CHECK_EQ(fresh.at("qgis_style").at("revision").get<long long>(), 1);
    CHECK_EQ(fresh.at("qgis_style").at("labeling_xml").get<std::string>(),
             std::string("<lab/>"));

    // Blank renderer → SymbologyBridgeError (Python raise parity).
    bool threw = false;
    try {
        apply_dialog_result(payload, "   ", "", 1.0);
    } catch (const SymbologyBridgeError&) {
        threw = true;
    }
    CHECK(threw);
}

PWB_TEST(apply_symbol_result_validates) {
    pwb::cartography::QgisStylePayload payload;
    payload.renderer_xml = "<old/>";
    payload.labeling_xml = "<keep/>";
    payload.revision = 5;
    Json out = apply_symbol_result(payload, "<sym-renderer/>", "");
    CHECK_EQ(out.at("qgis_style").at("renderer_xml").get<std::string>(),
             std::string("<sym-renderer/>"));
    CHECK_EQ(out.at("qgis_style").at("labeling_xml").get<std::string>(),
             std::string("<keep/>"));
    CHECK_EQ(out.at("qgis_style").at("revision").get<long long>(), 6);
    bool threw = false;
    try {
        apply_symbol_result(payload, "", "");
    } catch (const SymbologyBridgeError&) {
        threw = true;
    }
    CHECK(threw);
}

PWB_TEST(export_spec_derives_height_and_validates) {
    Extent view{0.0, 0.0, 2.0, 1.0};
    MapExportSpec spec = make_export_spec(MapRenderSnapshot{}, view,
                                          "/tmp/out.png", 800, std::nullopt,
                                          300.0, Json::object(), false);
    CHECK_EQ(static_cast<long long>(spec.height), 400);
    CHECK_EQ(spec.path, std::string("/tmp/out.png"));

    bool threw = false;
    try {
        make_export_spec(MapRenderSnapshot{}, view, "/tmp/x.png", 0,
                         std::nullopt, 300.0, Json::object(), false);
    } catch (const std::invalid_argument&) {
        threw = true;
    }
    CHECK(threw);
    threw = false;
    try {
        make_export_spec(MapRenderSnapshot{}, view, "/tmp/x.png", 800, 0,
                         300.0, Json::object(), false);
    } catch (const std::invalid_argument&) {
        threw = true;
    }
    CHECK(threw);
}

PWB_TEST(discard_partial_export_file_best_effort) {
    const std::string path = "/tmp/ui_canvas_partial_test.png";
    {
        std::ofstream out(path);
        out << "partial";
    }
    discard_partial_export_file(path);  // removes without throwing
    std::ifstream check(path);
    CHECK(!check.good());
    // Missing file → still no throw.
    discard_partial_export_file("/tmp/ui_canvas_missing_file.xyz");
}

PWB_TEST(wkt_from_geometry_converts_and_rejects) {
    CHECK_EQ(wkt_from_geometry(
                 Json{{"type", "Point"},
                      {"coordinates", Json::array({1.5, -2})}}),
             std::string("POINT (1.5 -2)"));
    CHECK_EQ(
        wkt_from_geometry(Json{{"type", "LineString"},
                               {"coordinates",
                                Json::array({Json::array({0, 0}),
                                             Json::array({1, 1})})}}),
        std::string("LINESTRING (0 0, 1 1)"));
    CHECK_EQ(
        wkt_from_geometry(Json{{"type", "Polygon"},
                               {"coordinates",
                                Json::array({Json::array(
                                    {Json::array({0, 0}),
                                     Json::array({4, 0}),
                                     Json::array({4, 4}),
                                     Json::array({0, 0})})})}}),
        std::string("POLYGON ((0 0, 4 0, 4 4, 0 0))"));
    // Malformed → "" (feature skipped upstream).
    CHECK(wkt_from_geometry(Json::object()).empty());
    CHECK(wkt_from_geometry(Json{{"type", "Point"},
                                 {"coordinates", Json::array({1})}})
              .empty());
}

PWB_TEST(encode_qgis_snapshot_raster_and_vector) {
    MapRenderSnapshot snapshot;
    snapshot.project_crs = "EPSG:3857";

    MapLayerSnapshot raster;
    raster.id = "r1";
    raster.layer_type = "raster_source";
    raster.source_path = "/data/dem.tif";
    raster.data_revision = 2;
    snapshot.layers.push_back(raster);

    MapLayerSnapshot empty_source;
    empty_source.id = "r2";
    empty_source.layer_type = "raster_source";  // no source_path → skipped
    snapshot.layers.push_back(empty_source);

    MapLayerSnapshot vector;
    vector.id = "v1";
    vector.layer_type = "vector";
    vector.data_revision = 1;
    vector.style_revision = 5;
    vector.visible = true;
    vector.opacity = 0.9;
    vector.scale_range = std::make_pair(500.0, 25000.0);
    vector.features = Json::array({
        Json{{"id", "f1"},
             {"geometry", Json{{"type", "Point"},
                               {"coordinates", Json::array({3, 4})}}},
             {"properties", Json{{"name", "alpha"}}}},
        Json{{"id", "f2"},
             {"geometry", Json{{"type", "Point"},
                               {"coordinates", Json::array({5, 6})}}},
             {"properties", Json::object()}},
    });
    snapshot.layers.push_back(vector);

    SnapshotEncoderState state;
    Json layers = encode_qgis_snapshot(snapshot, state);
    CHECK_EQ(static_cast<long long>(layers.size()), 2);

    const Json& raster_entry_json = layers.at(0);
    CHECK_EQ(raster_entry_json.at("kind").get<std::string>(),
             std::string("raster"));
    CHECK_EQ(raster_entry_json.at("source_path").get<std::string>(),
             std::string("/data/dem.tif"));

    const Json& vector_entry = layers.at(1);
    CHECK_EQ(vector_entry.at("crs").get<std::string>(),
             std::string("EPSG:3857"));
    CHECK_EQ(static_cast<long long>(vector_entry.at("features").size()),
             2);
    const Json& f1 = vector_entry.at("features").at(0);
    CHECK_EQ(f1.at("wkt").get<std::string>(), std::string("POINT (3 4)"));
    CHECK_EQ(f1.at("attributes").at("__pwb_id").get<std::string>(),
             std::string("f1"));
    CHECK_EQ(f1.at("attributes").at("name").get<std::string>(),
             std::string("alpha"));
    CHECK(near(vector_entry.at("scale_range").at(0).get<double>(),
               500.0));
    CHECK(!vector_entry.contains("delta"));

    // Second encode, same revision → feature-payload cache hit.
    state.shipped_revisions["v1"] = 1;
    Json again = encode_qgis_snapshot(snapshot, state);
    CHECK_EQ(static_cast<long long>(again.at(1).at("features").size()),
             2);
    CHECK_EQ(static_cast<long long>(state.feature_encoding_cache_hits),
             1);
}

PWB_TEST(encode_qgis_snapshot_delta_and_prune) {
    MapRenderSnapshot snapshot;
    snapshot.project_crs = "EPSG:4326";
    MapLayerSnapshot vector;
    vector.id = "v1";
    vector.layer_type = "vector";
    vector.data_revision = 1;
    vector.features = Json::array({
        Json{{"id", "f1"},
             {"geometry", Json{{"type", "Point"},
                               {"coordinates", Json::array({0, 0})}}},
             {"properties", Json{{"v", 1}}}},
        Json{{"id", "f2"},
             {"geometry", Json{{"type", "Point"},
                               {"coordinates", Json::array({1, 1})}}},
             {"properties", Json{{"v", 2}}}},
    });
    snapshot.layers.push_back(vector);

    SnapshotEncoderState state;
    encode_qgis_snapshot(snapshot, state);          // full ship rev 1
    state.shipped_revisions["v1"] = 1;              // mirror holds rev 1

    // Rev 2: f1 unchanged (entry reuse), f2 changed, nothing removed →
    // changed(1)+removed(0) < total(2) → delta ship (#932).
    vector.data_revision = 2;
    vector.features.at(1)["properties"]["v"] = 22;
    snapshot.layers.at(0) = vector;
    Json layers = encode_qgis_snapshot(snapshot, state);
    const Json& entry = layers.at(0);
    CHECK(entry.contains("delta"));
    CHECK_EQ(static_cast<long long>(entry.at("features").size()), 0);
    CHECK_EQ(static_cast<long long>(
                 entry.at("delta").at("changed_features").size()),
             1);
    CHECK_EQ(entry.at("delta").at("base_revision").get<std::uint64_t>(),
             static_cast<std::uint64_t>(1));
    CHECK_EQ(static_cast<long long>(state.feature_delta_ships), 1);
    CHECK_EQ(static_cast<long long>(state.feature_payload_reuse_hits), 1);

    // Prune: remove v1 from the snapshot → all per-layer encoder state goes.
    snapshot.layers.clear();
    prune_encoder_state(state, snapshot);
    CHECK(state.feature_payloads.empty());
    CHECK(state.feature_entries.empty());
    CHECK(state.shipped_revisions.empty());
}

PWB_TEST(scalar_grid_without_mirror_throws) {
    MapRenderSnapshot snapshot;
    MapLayerSnapshot scalar;
    scalar.id = "s1";
    scalar.layer_type = "scalar_grid";  // no source_path → honest throw
    snapshot.layers.push_back(scalar);
    SnapshotEncoderState state;
    bool threw = false;
    try {
        encode_qgis_snapshot(snapshot, state);
    } catch (const std::runtime_error&) {
        threw = true;
    }
    CHECK(threw);
}

PWB_TEST(is_stale_delta_error_matches_message) {
    try {
        throw std::runtime_error("Stale mirror for feature delta: v9");
    } catch (const std::exception& exc) {
        CHECK(is_stale_delta_error(exc));
    }
    try {
        throw std::runtime_error("some other failure");
    } catch (const std::exception& exc) {
        CHECK(!is_stale_delta_error(exc));
    }
}

int main() {
    return pwb_test::run_all();
}
