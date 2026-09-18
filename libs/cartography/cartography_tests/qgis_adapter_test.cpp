// CONV-27 — QGIS bridge payload adapter + payload model oracle test.
#include <pwb/cartography/qgis_adapter.hpp>

#include "check.hpp"

#include <cmath>
#include <string>

using namespace pwb::cartography;
using cartography_test::check;
using cartography_test::check_json_eq;
using Json = pwb::domain::Json;

namespace {

const Json& fixture() {
    static const Json value =
        cartography_test::load_fixture(PWB_QGIS_STYLE_FIXTURE);
    return value;
}

const Json& flatten_fixture() {
    static const Json value =
        cartography_test::load_fixture(PWB_FLATTEN_QGIS_FIXTURE);
    return value;
}

void run_scalar_payload() {
    // The payload the C++ bridge build_scalar_renderer_xml consumes must
    // match encode_scalar_renderer_xml's assembly (field order + values).
    ScalarStyleSpec spec;
    spec.ramp_name = "porosity";
    spec.mode = "classified";
    spec.classification = "equal_interval";
    spec.n_classes = 4;
    spec.unit_label = "%";
    spec.colorbar_title = "孔隙度";
    ScalarRendererStats stats;
    stats.values = {1.0, 2.0, std::nan(""), 3.0, 4.0, 5.0, 6.0, 7.0, 8.0,
                    std::numeric_limits<double>::infinity()};
    stats.min = 1.0;
    stats.max = 8.0;
    const Json payload = scalar_renderer_payload(spec, stats, "EPSG:4326");
    check(payload["ramp_name"] == "porosity", "payload ramp_name");
    check(payload["mode"] == "classified", "payload mode");
    check(payload["items"].is_array() && payload["items"].size() == 5,
          "payload classified item count");
    check(payload["min"] == Json(1.0) && payload["max"] == Json(8.0),
          "payload min/max");
    check(payload["crs"] == "EPSG:4326", "payload crs");
    check(payload["labels"].size() == 5, "payload labels count");
    // Field order pinned (ordered_json).
    std::string keys;
    for (auto it = payload.begin(); it != payload.end(); ++it) {
        if (!keys.empty()) keys += ",";
        keys += it.key();
    }
    check(keys == "ramp_name,mode,items,min,max,opacity,nodata_transparent,"
                  "unit_label,colorbar_title,crs,labels",
          "payload key order: " + keys);
    // Degenerate span widens max by exactly 1.
    ScalarRendererStats degenerate;
    degenerate.values = {5.0, 5.0};
    const Json wide = scalar_renderer_payload(ScalarStyleSpec{}, degenerate, "");
    check(wide["min"] == Json(5.0) && wide["max"] == Json(6.0),
          "payload degenerate span");
}

void run_legacy_renderer_style() {
    VectorStyle style;
    style.fill = "#101010";
    style.stroke = "#eeeeee";
    style.stroke_width = 2.0;
    style.renderer = "graduated";
    style.field = "confidence";
    style.ranges = {{0.0, 0.5, "#c9b8d8", "低"}, {0.5, 1.01, "#7fbf9e", "高"}};
    TextStyle labels;
    labels.field = "name";
    labels.size = 9.0;
    style.labels = labels;
    const Json spec = legacy_renderer_style(style);
    check(spec["renderer_kind"] == "graduated", "spec renderer_kind alias");
    check(spec["classification_field"] == "confidence",
          "spec classification_field alias");
    check(spec["ranges"].is_array() && spec["ranges"].size() == 2,
          "spec ranges carried");
    check(spec["labels"]["field"] == "name", "spec labels carried");
}

void run_symbol_renderer_spec() {
    const Json categorized = symbol_renderer_spec("fault_v2");
    check(categorized["renderer_kind"] == "categorized",
          "symbol spec fault kind");
    check(categorized["classification_field"] == "fault_type",
          "symbol spec fault field");
    // The bridge's categorized path consumes classification_field +
    // categories triples (A7): the fallback palette rides verbatim.
    check(categorized["categories"].size() == 5,
          "symbol spec fault categories");
    check(categorized["categories"][0]["value"] == "normal",
          "symbol spec fault category value");
    check(categorized["categories"][1]["color"] == "#a93226",
          "symbol spec fault category color");
    check(categorized["legacy_style"]["categories"].size() == 5,
          "symbol spec fault fallback categories");
    const Json single = symbol_renderer_spec("shoreline_v2");
    check(single["renderer_kind"] == "single", "symbol spec shoreline kind");
    check(single["legacy_style"]["stroke"] == "#1f78b4",
          "symbol spec shoreline fallback");
}

void run_flatten() {
    const Json& want = flatten_fixture();
    // legacy_only / promoted / label_units / explicit_buffer_kept / no_labels.
    VectorStyle legacy;
    legacy.labels = TextStyle{};  // then rebuild the Python base labels
    legacy.labels->field = "name";
    legacy.labels->size = 9.0;
    legacy.labels->halo_color = "#f8f9fa";
    legacy.labels->halo_width = 1.0;
    VectorStyle legacy_style;
    legacy_style.fill = "#6c8ebf";
    legacy_style.stroke = "#26364d";
    legacy_style.labels = legacy.labels;
    check_json_eq(flatten_qgis_style(legacy_style.to_dict()),
                  want["legacy_only"], "flatten legacy_only");

    // The Python frozen case starts from a partial dict: fill + stroke +
    // the FULL TextStyle dump + qgis_style. Mirror it exactly.
    Json promoted = Json::object();
    promoted["fill"] = "#6c8ebf";
    promoted["stroke"] = "#26364d";
    promoted["labels"] = legacy.labels->to_dict();
    promoted["qgis_style"] = Json::parse(
        R"({"schema_version": 1,
            "renderer_xml": "<renderer-v2 type=\"categorizedSymbol\"/>",
            "labeling_xml": "  ",
            "name": "n", "tags": [], "revision": 3})");
    check_json_eq(flatten_qgis_style(promoted), want["promoted"],
                  "flatten promoted");

    Json label_units = Json::parse(
        R"({"labels": {"size": 12.0, "halo_width": 2.0, "halo_color": "#101010"},
            "qgis_style": {"renderer_xml": "<renderer-v2/>"}})");
    check_json_eq(flatten_qgis_style(label_units), want["label_units"],
                  "flatten label_units");

    Json explicit_buffer = Json::parse(
        R"({"labels": {"size": 10.0, "buffer": 0.5, "buffer_color": "#ffffff",
                       "halo_width": 3.0}})");
    check_json_eq(flatten_qgis_style(explicit_buffer),
                  want["explicit_buffer_kept"], "flatten explicit_buffer");

    check_json_eq(flatten_qgis_style(Json::parse(R"({"fill": "#000000"})")),
                  want["no_labels"], "flatten no_labels");

    try {
        flatten_qgis_style(Json("not-a-dict"));
        check(false, "flatten non_mapping (no exception)");
    } catch (const std::invalid_argument&) {
        check(true, "flatten non_mapping raised");
    }
}

void run_payload_model() {
    const Json& want = fixture();
    QgisStylePayload payload;
    payload.renderer_xml = "<renderer-v2 type=\"singleSymbol\"/>";
    payload.name = "fault style";
    payload.tags = {"fault", "v2"};
    check_json_eq(payload.to_dict(), want["valid"], "qgis payload valid");
    check(payload.bumped().revision == 2, "qgis payload bumped");
    check_json_eq(payload.bumped().to_dict(), want["bumped"],
                  "qgis payload bumped doc");
    check_json_eq(QgisStylePayload::from_dict(payload.to_dict())->to_dict(),
                  want["roundtrip"], "qgis payload roundtrip");
    check(!QgisStylePayload::from_dict(Json()).has_value(),
          "qgis payload from null");
    check(!QgisStylePayload::from_dict(Json::object()).has_value(),
          "qgis payload from empty");
    // Blank renderer_xml payloads are invalid -> None (Python from_dict).
    check(!QgisStylePayload::from_dict(Json::parse(R"({"renderer_xml": "   "})"))
               .has_value(),
          "qgis payload blank -> None");
    // Foreign schema versions raise (Python __post_init__ ValueError).
    try {
        QgisStylePayload::from_dict(Json::parse(
            R"({"renderer_xml": "<r/>", "schema_version": 2})"));
        check(false, "qgis payload bad schema (no exception)");
    } catch (const std::invalid_argument& exc) {
        check(std::string(exc.what()) ==
                  "unsupported qgis_style schema version 2",
              "qgis payload bad schema message");
    }
    // revision clamps at 1 (Python: max(1, int(revision or 1))).
    const auto clamped = QgisStylePayload::from_dict(Json::parse(
        R"({"renderer_xml": "<r/>", "revision": 0})"));
    check(clamped.has_value() && clamped->revision == 1,
          "qgis payload revision clamp");
    try {
        QgisStylePayload blank;
        blank.renderer_xml = "   ";
        blank.validate();
        check(false, "qgis payload blank (no exception)");
    } catch (const std::invalid_argument& exc) {
        check(std::string(exc.what()) ==
              want["blank_renderer"]["message"].get<std::string>(),
              "qgis payload blank message");
    }
    check_json_eq(
        QgisStylePayload::from_dict(Json::parse(R"({"renderer_xml": "<renderer-v2/>"})"))
            ->to_dict(),
        want["minimal"], "qgis payload minimal");
}

}  // namespace

int main() {
    run_scalar_payload();
    run_legacy_renderer_style();
    run_symbol_renderer_spec();
    run_flatten();
    run_payload_model();
    return cartography_test::g_failures;
}
