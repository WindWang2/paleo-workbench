// UI-09 — Qt-free core smoke: the semantic cores reproduce the Python
// page behaviors (task keys/active task, status tokens, resource filters,
// cursor gates, output-nature labels, correlation rows/mutations,
// diagnostic redaction, failed-run replay, well-table formatting,
// well-map model/CRS warnings, joint-state round-trip, export options).

#include <cmath>
#include <optional>
#include <string>
#include <vector>

#include <pwb/ui_wellseis/correlation.hpp>
#include <pwb/ui_wellseis/cursor_gates.hpp>
#include <pwb/ui_wellseis/export_options.hpp>
#include <pwb/ui_wellseis/joint_state.hpp>
#include <pwb/ui_wellseis/output_labels.hpp>
#include <pwb/ui_wellseis/page_state.hpp>
#include <pwb/ui_wellseis/redact.hpp>
#include <pwb/ui_wellseis/resource_sources.hpp>
#include <pwb/ui_wellseis/run_diagnostic.hpp>
#include <pwb/ui_wellseis/seismic_attributes.hpp>
#include <pwb/ui_wellseis/task_state.hpp>
#include <pwb/ui_wellseis/well_detail.hpp>
#include <pwb/ui_wellseis/well_map.hpp>
#include <pwb/ui_wellseis/well_table_format.hpp>
#include <pwb/well_science/depth_unit.hpp>

#include "ui_wellseis_test.hpp"

using namespace pwb::ui_wellseis;
using pwb::domain::Json;

namespace {

PredictionTaskSlice task(const std::string& id, const std::string& name,
                         const std::string& status) {
    PredictionTaskSlice t;
    t.id = id;
    t.name = name;
    t.status = status;
    return t;
}

}  // namespace

PWB_TEST(task_keys_and_active_task) {
    const auto named = task("t-1", "任务甲", "running");
    CHECK_EQ(task_key(named), "id:t-1");
    const auto unnamed_id = task("", "任务乙", "");
    CHECK_EQ(task_key(unnamed_id), "name:任务乙");

    const std::vector<PredictionTaskSlice> tasks = {
        task("a", "第一", "done"), task("b", "第二", "running")};
    // prediction_helpers.active_prediction_task: last element.
    CHECK(active_prediction_task(tasks) == &tasks.back());
    CHECK(active_prediction_task(std::vector<PredictionTaskSlice>{}) ==
          nullptr);

    CHECK_EQ(index_of_task_id(tasks, "a").value_or(-9), 0);
    CHECK_EQ(index_of_task_id(tasks, "b").value_or(-9), 1);
    CHECK(!index_of_task_id(tasks, "zzz").has_value());
    CHECK(!index_of_task_id(tasks, "").has_value());
    CHECK_EQ(index_of_task_named(tasks, "第二").value_or(-9), 1);

    // Explicit selection wins; invalid falls back to the active row.
    CHECK_EQ(task_panel_active_row(tasks, 0), 0);
    CHECK_EQ(task_panel_active_row(tasks, std::nullopt), 1);
    CHECK_EQ(task_panel_active_row(tasks, 99), 1);
}

PWB_TEST(task_status_tokens) {
    CHECK_EQ(task_status_token("running").label, "运行中");
    CHECK_EQ(task_status_token("complete").label, "完成");
    CHECK_EQ(task_status_token("warning").label, "降级完成");
    CHECK_EQ(task_status_token("FAILED").label, "失败");
    CHECK_EQ(task_status_token("  pending ").label, "排队中");
    // Unknown statuses keep raw text, muted — never coerced.
    CHECK_EQ(task_status_token("mystery").label, "mystery");
    CHECK_EQ(task_status_token("mystery").tone, "muted");
    CHECK_EQ(task_status_token("").label, "待开始");

    CHECK_EQ(badge_tone_of("ok"), "success");
    CHECK_EQ(badge_tone_of("warn"), "warning");
    CHECK_EQ(badge_tone_of("locked"), "neutral");
    CHECK_EQ(badge_tone_of("other"), "neutral");

    CHECK_EQ(task_row_text(task("x", "", "done")), "未命名预测任务 · 完成");
    CHECK_EQ(task_row_text(task("x", "任务丙", "running")),
             "任务丙 · 运行中");
}

PWB_TEST(resource_filters_and_labels) {
    ResourceSlice segy{"r1", "三维工区", "/data/a.segy", "seismic", "segy"};
    ResourceSlice sgy_path{"r2", "二维", "/data/b.SGY", "seismic", ""};
    ResourceSlice non_segy{"r3", "其他", "/data/c.segy", "seismic_other",
                           "segy"};
    ResourceSlice las{"r4", "井A", "/data/a.las", "well_log", "las"};

    CHECK(is_segy_resource(segy));
    CHECK(is_segy_resource(sgy_path));
    CHECK(!is_segy_resource(non_segy));
    CHECK(!is_segy_resource(las));
    CHECK(is_well_log_resource(las));
    CHECK(!is_well_log_resource(segy));

    // "{name} · {FORMAT}"; unnamed fallback; format-less stays bare.
    CHECK_EQ(resource_combo_label(segy, "未命名"), "三维工区 · SEGY");
    CHECK_EQ(resource_combo_label(sgy_path, "未命名"), "二维");
    ResourceSlice unnamed{"r5", "", "/x.sgy", "seismic", "sgy"};
    CHECK_EQ(resource_combo_label(unnamed, "未命名"), "未命名 · SGY");

    const auto entries = source_combo_entries({segy, las}, "未命名", "空");
    CHECK_EQ(entries.size(), 2);
    CHECK_EQ(entries[0].resource_id, "r1");
    const auto empty_entries =
        source_combo_entries({}, "未命名", "（无可用数据源）");
    CHECK_EQ(empty_entries.size(), 1);
    CHECK_EQ(empty_entries[0].label, "（无可用数据源）");
    CHECK_EQ(empty_entries[0].resource_id, "");

    CHECK_EQ(resolved_source_index({segy, las}, "r4"), 1);
    CHECK_EQ(resolved_source_index({segy, las}, "gone"), -1);
    CHECK_EQ(resolved_source_index({segy, las}, ""), -1);

    const SourceSignature sig = source_signature(entries);
    CHECK_EQ(sig.size(), 2);
    CHECK_EQ(sig[0].first, "三维工区 · SEGY");
    CHECK_EQ(sig[0].second, "r1");

    const std::vector<ResourceSlice> resources = {segy, las};
    CHECK(find_resource(resources, "r4") == &resources[1]);
    CHECK(find_resource(resources, "zzz") == nullptr);
    CHECK(find_resource(resources, "") == nullptr);

    // task.input_refs[key][0] -> the bound resource.
    std::map<std::string, std::vector<std::string>> refs = {
        {"well_log_resource_ids", {"r4"}}};
    CHECK(primary_resource(refs, "well_log_resource_ids", resources) ==
          &resources[1]);
    CHECK(primary_resource(refs, "seismic_resource_ids", resources) ==
          nullptr);
}

PWB_TEST(seismic_cursor_gate) {
    double now = 100.0;  // seconds (the gate multiplies by 1000)
    SeismicCursorGate gate(30.0, 1.0, [&now] { return now; });

    CHECK(gate.should_publish(10.0));  // first event always publishes
    now += 0.010;                      // +10 ms < 30 ms
    CHECK(!gate.should_publish(10.5)); // small move throttled
    CHECK(gate.should_publish(12.0));  // jump > il_jump publishes anyway
    now += 0.010;
    CHECK(!gate.should_publish(12.4));
    now += 0.025;                      // +35 ms since last publish
    CHECK(gate.should_publish(12.5));
}

PWB_TEST(depth_cursor_gate) {
    double now = 50.0;
    DepthCursorGate gate([&now] { return now; });

    const auto first = gate.offer(1234.5);
    CHECK(first.publish_now);
    CHECK(!first.hold);

    now += 0.050;  // +50 ms < 120 ms
    const auto held = gate.offer(1235.0);
    CHECK(!held.publish_now);
    CHECK(held.hold);
    CHECK(held.flush_in_ms > 0.0 && held.flush_in_ms <= 120.0);
    CHECK(gate.has_pending());

    const auto flushed = gate.flush_pending();
    CHECK(flushed.has_value());
    CHECK_EQ(flushed.value(), 1235.0);
    CHECK(!gate.has_pending());

    // Gate re-arms from the flush timestamp.
    now += 0.130;
    const auto after = gate.offer(1240.0);
    CHECK(after.publish_now);
    CHECK(gate.flush_pending() == std::nullopt);
}

PWB_TEST(depth_unit_gate_reasons) {
    using pwb::well_science::DepthUnitInfo;
    DepthUnitInfo meters;
    meters.unit = "m";
    meters.declared = true;
    meters.raw = "M";
    CHECK(!depth_cursor_unavailable_reason(meters).has_value());

    DepthUnitInfo feet;
    feet.unit = "ft";
    feet.declared = true;
    feet.raw = "FT";
    CHECK_EQ(depth_cursor_unavailable_reason(feet).value_or(""),
             "depth-unit:ft");

    DepthUnitInfo weird;
    weird.declared = true;
    weird.raw = "FURLONGS";
    CHECK_EQ(depth_cursor_unavailable_reason(weird).value_or(""),
             "depth-unit:FURLONGS");

    DepthUnitInfo undeclared;
    CHECK_EQ(depth_cursor_unavailable_reason(undeclared).value_or(""),
             "depth-unit:unknown");
}

PWB_TEST(output_nature_labels) {
    CHECK_EQ(seismic_output_nature(Json::object()), "启发式 · 固定");
    CHECK_EQ(seismic_output_nature(Json{{"is_mock", true}}), "Mock · 固定");
    CHECK_EQ(seismic_output_nature(
                 Json{{"final_scientific_prediction", true},
                      {"is_replaceable", true}}),
             "科学预测 · 可替换");
    CHECK_EQ(seismic_output_nature(Json{{"demo", true}, {"is_mock", true}}),
             "Demo · Mock · 固定");
    CHECK_EQ(seismic_output_nature(Json{{"source", "synthetic/demo"}}),
             "Demo · 启发式 · 固定");

    // Online well-log model types outrank every other flag.
    CHECK_EQ(well_log_output_nature(
                 Json{{"model_type", "geoviz_online"}}),
             "线上测井预测 · 固定");
    CHECK_EQ(well_log_output_nature(
                 Json{{"model_type", "inference_api_online"},
                      {"is_mock", true},
                      {"demo", true},
                      {"is_replaceable", true}}),
             "Demo · 线上测井预测 · 可替换");
    CHECK_EQ(well_log_output_nature(Json::object()), "启发式 · 固定");

    CHECK_EQ(prediction_source_label(Json{{"model_type", "geoviz_online"}},
                                     false),
             "认证线上推理服务");
    CHECK_EQ(prediction_source_label(Json{{"demo", true}}, true),
             "合成演示数据");
    CHECK_EQ(prediction_source_label(Json::object(), true), "绑定 LAS");
    CHECK_EQ(prediction_source_label(Json::object(), false), "合成曲线");

    CHECK_EQ(attribute_label_or_default(""), "振幅");
    CHECK_EQ(attribute_label_or_default("相似性"), "相似性");
    CHECK_EQ(predicted_region_count(
                 Json{{"predicted_regions", Json::array({1, 2, 3})}}),
             3);
    CHECK_EQ(predicted_region_count(Json::object()), 0);

    const auto dist = class_distribution_of(
        Json{{"remote_summary",
              Json{{"classCounts",
                    Json{{"甲", 5}, {"乙", 3}, {"丙", 2}}}}}});
    CHECK_EQ(dist.text, "甲 50.0%、乙 30.0%");
    CHECK(class_distribution_of(Json::object()).text.empty());

    const auto rows = evidence_rows(
        Json::array({Json{{"name", "GR"}, {"weight", 0.4}},
                     Json{{"weight", 0.1}}}));
    CHECK_EQ(rows.size(), 2);
    CHECK_EQ(rows[0], "GR: 40%");
    CHECK_EQ(rows[1], "未命名证据: 10%");
}

PWB_TEST(correlation_rows_and_mutations) {
    CorrelationDraftSlice draft;
    draft.tops = {{"t1", "井A", "T3", 1000.5, "MD", "MANUAL", "0.9"},
                  {"t2", "井B", "T3", 1010.0, "MD", "DTW_ASSISTED", ""}};
    CHECK(correlation_add_manual_link(draft, "l1", "t1", "t2", true,
                                      "笔记"));
    CHECK(!correlation_add_manual_link(draft, "l2", "t1", "t1", false, ""));
    CHECK(!correlation_add_manual_link(draft, "l3", "t1", "ghost", false,
                                       ""));
    CHECK(!correlation_add_manual_link(draft, "", "t1", "t2", false, ""));

    CHECK_EQ(correlation_method_label("MANUAL"), "手工");
    CHECK_EQ(correlation_method_label("DTW_ASSISTED"), "DTW 辅助");
    CHECK_EQ(correlation_method_label("CURVE_SHAPE_ASSISTED"),
             "曲线形态辅助");
    CHECK_EQ(correlation_method_label("IMPORTED"), "导入");
    CHECK_EQ(correlation_method_label("OTHER"), "OTHER");
    CHECK_EQ(kCorrelationStatuses.size(), 3);

    const auto links = correlation_link_rows(draft);
    CHECK_EQ(links.size(), 1);
    CHECK_EQ(links[0].pair_text, "井A → 井B");
    CHECK_EQ(links[0].marker, "T3");
    CHECK_EQ(links[0].method_label, "手工");
    CHECK_EQ(links[0].adjacent_text, "是");

    const auto tops = correlation_top_rows(draft);
    CHECK_EQ(tops.size(), 2);
    CHECK_EQ(tops[0].well_name, "井A");
    CHECK_EQ(tops[0].depth_text, "1000.50 MD");
    CHECK_EQ(tops[0].method_label, "手工");
    CHECK_EQ(tops[1].confidence_text, "—");

    const auto choices = correlation_top_choices(draft);
    CHECK_EQ(choices.size(), 2);
    CHECK_EQ(choices[0].label, "井A · T3 (1000.5) #0");
    CHECK_EQ(choices[0].top_id, "t1");

    CHECK(correlation_edit_link(draft, "l1", "IMPORTED", "改注"));
    CHECK_EQ(draft.links[0].method, "IMPORTED");
    CHECK_EQ(draft.links[0].notes, "改注");
    CHECK(!correlation_edit_link(draft, "nope", "MANUAL", ""));

    CHECK(correlation_edit_top(draft, "t2", "MANUAL", "0.5", "tentative",
                               "顶注解"));
    CHECK_EQ(draft.tops[1].status, "tentative");
    CHECK(!correlation_edit_top(draft, "nope", "MANUAL", "", "active", ""));

    CHECK(correlation_remove_link(draft, "l1"));
    CHECK_EQ(draft.links.size(), 0);
    CHECK(!correlation_remove_link(draft, "l1"));
}

PWB_TEST(diagnostic_redaction) {
    CHECK_EQ(redact_diagnostic_text("authorization: Bearer abc123 done"),
             "authorization: Bearer <REDACTED> done");
    CHECK_EQ(redact_diagnostic_text("token=sekrit api_key:xyz"),
             "token=<REDACTED> api_key:<REDACTED>");
    const std::string long_text(4000, 'x');
    CHECK_EQ(redact_diagnostic_text(long_text).size(), kDiagnosticCharCap);

    CHECK_EQ(redact_endpoint("https://user:pw@host:8443/v1/predict?q=1#f"),
             "https://host:8443/v1/predict");
    CHECK_EQ(redact_endpoint("https://host/path"), "https://host/path");
    CHECK_EQ(redact_endpoint("not a url token=abc"),
             "not a url token=<REDACTED>");
    CHECK_EQ(redact_endpoint(""), "");
    CHECK_EQ(redact_endpoint("https://host:badport/p"), "<无效地址>");
}

PWB_TEST(failed_run_replay_and_log) {
    RunSlice failed_old;
    failed_old.id = "run-1";
    failed_old.status = "failed";
    failed_old.created_at = "2025-01-01T00:00:00";
    failed_old.parameters =
        Json{{"workflow", "geoviz_online_well_log_facies"},
             {"well_log_resource_ids", Json::array({"res-9"})},
             {"model_version", "v2"},
             {"online_endpoint", "https://u:p@svc:9000/api?token=q"},
             {"error", "authorization: Bearer leak"}};

    RunSlice failed_new = failed_old;
    failed_new.id = "run-2";
    failed_new.created_at = "2025-02-01T00:00:00";

    RunSlice other_workflow = failed_old;
    other_workflow.id = "run-3";
    other_workflow.created_at = "2025-03-01T00:00:00";
    other_workflow.parameters["workflow"] = "local_stub";

    RunSlice other_resource = failed_old;
    other_resource.id = "run-4";
    other_resource.created_at = "2025-04-01T00:00:00";
    other_resource.parameters["well_log_resource_ids"] =
        Json::array({"res-1"});

    const std::vector<RunSlice> runs = {failed_old, failed_new,
                                        other_workflow, other_resource};
    const RunSlice* latest = latest_failed_online_run(runs, "res-9");
    CHECK(latest == &runs[1]);
    CHECK(latest_failed_online_run(runs, "res-1") == &runs[3]);
    CHECK(latest_failed_online_run(runs, "missing") == nullptr);
    CHECK(latest_failed_online_run(runs, "") == nullptr);

    CHECK_EQ(run_error_text(failed_old), "authorization: Bearer leak");
    RunSlice no_error = failed_old;
    no_error.parameters.erase("error");
    CHECK_EQ(run_error_text(no_error), "未知错误");

    ResourceSlice resource{"res-9", "井Z", "/z.las", "well_log", "las"};
    const std::string log =
        run_diagnostic_log(latest, "失败", "token=abc 调用失败", &resource);
    CHECK(log.find("线上测井预测运行日志") != std::string::npos);
    CHECK(log.find("状态: 失败") != std::string::npos);
    CHECK(log.find("运行 ID: run-2") != std::string::npos);
    CHECK(log.find("井数据: 井Z (res-9)") != std::string::npos);
    CHECK(log.find("模型版本: v2") != std::string::npos);
    // Endpoint redacted to scheme://host:port/path (no userinfo/query).
    CHECK(log.find("服务地址: https://svc:9000/api") != std::string::npos);
    CHECK(log.find("token=q") == std::string::npos);
    // Error line scrubbed.
    CHECK(log.find("token=<REDACTED> 调用失败") != std::string::npos);

    const std::string no_run_log =
        run_diagnostic_log(nullptr, "推断中", "", nullptr);
    CHECK(no_run_log.find("运行 ID: 未创建") != std::string::npos);
    CHECK(no_run_log.find("井数据: 未解析") != std::string::npos);
}

PWB_TEST(well_table_formatting) {
    CHECK_EQ(well_table_fmt(12.345678), "12.3457");
    // Python "%.4g" rounds half-to-even: 1234.5 -> "1234" (not "1235").
    CHECK_EQ(well_table_fmt(1234.5), "1234");
    CHECK_EQ(well_table_fmt(0.0005), "0.0005");
    CHECK_EQ(well_table_fmt(std::nullopt), "");
    CHECK_EQ(well_table_fmt(std::nullopt, "n/a"), "n/a");
    CHECK_EQ(well_table_fmt(1500.0), "1500");
    CHECK_EQ(well_table_fmt(-0.0001), "-0.0001");

    CHECK_EQ(normalized_qc_flag(""), "ok");
    CHECK_EQ(normalized_qc_flag("outlier"), "outlier");
    CHECK_EQ(qc_foreground_token("ok").value_or(""), "SUCCESS");
    CHECK_EQ(qc_foreground_token("invalid_ratio").value_or(""), "ERROR_RED");
    CHECK(!qc_foreground_token("weird").has_value());

    WellTableSlice table;
    table.name = "井参数表";
    table.target_horizon = "T3";
    table.rows = {{.well_id = "w1", .name = "井A", .qc_flag = "ok"},
                  {.well_id = "w2", .name = "井B", .qc_flag = "outlier"},
                  {.well_id = "w3", .name = "井C", .qc_flag = "outlier"},
                  {.well_id = "w4", .name = "井D", .qc_flag = ""}};
    CHECK_EQ(well_table_title(table), "井参数表 · T3");
    CHECK_EQ(well_table_summary(table), "4 行 · ok:2 · outlier:2");

    const WellTableRowSlice& row = table.rows[0];
    CHECK_EQ(well_table_cell(row, "name"), "井A");
    CHECK_EQ(well_table_cell(row, "qc_flag"), "ok");
    CHECK_EQ(well_table_cell(row, "x"), "");
    CHECK_EQ(kWellTableColumns.size(), 11);
    CHECK_EQ(kWellTableColumns[0].title, "井名");
}

PWB_TEST(well_map_model_and_crs) {
    CHECK_EQ(coordinate_status_flag("untransformed"), " ⚠坐标未转换");
    CHECK_EQ(coordinate_status_flag("invalid"), " ⚠坐标无效");
    CHECK_EQ(coordinate_status_flag("missing"), " ⚠无坐标");
    CHECK_EQ(coordinate_status_flag("ok"), "");

    CHECK(crs_equivalent("EPSG:4528", " epsg:4528 "));
    CHECK(!crs_equivalent("EPSG:4528", "EPSG:4326"));
    CHECK(!crs_equivalent("", "EPSG:4326"));

    // 3-corner survey extent completes the parallelogram.
    const auto corners = complete_survey_corners(
        {{0, 0}, {10, 0}, {10, 5}});
    CHECK_EQ(corners.size(), 4);
    CHECK_EQ(corners[3].first, 0.0);
    CHECK_EQ(corners[3].second, 5.0);

    std::vector<WellSlice> wells = {
        {.id = "w1",
         .name = "井A",
         .surface_x = 1.0,
         .surface_y = 2.0,
         .project_x = 100.0,
         .project_y = 200.0,
         .coordinate_status = "ok"},
        {.id = "w2",
         .name = "井B",
         .surface_x = 5.0,
         .surface_y = 6.0,
         .coordinate_status = "untransformed"},
        {.id = "w3",
         .name = "",
         .coordinate_status = "missing"},
        {.id = "w4",
         .name = "参考井",
         .project_x = 1.0,
         .project_y = 1.0,
         .coordinate_status = "ok",
         .spatial_scope = "reference"},
    };
    const WellMapModel model = build_well_map_model(wells);
    CHECK_EQ(model.rows.size(), 3);  // reference well excluded
    CHECK_EQ(model.rows[2].display_name, "(未命名井)");
    CHECK_EQ(model.rows[1].flag, " ⚠坐标未转换");
    // OK block first (project coords), then flagged (surface fallback).
    CHECK_EQ(model.ok_count, 1);
    CHECK_EQ(model.scatter.size(), 2);
    CHECK_EQ(model.scatter[0].first, 100.0);
    CHECK_EQ(model.scatter[1].first, 5.0);
    CHECK_EQ(model.ordered_list_rows[0], 0);
    CHECK_EQ(model.ordered_list_rows[1], 1);
    CHECK_EQ(model.row_to_array.at(1), 1);

    ProjectSlice project;
    project.project_crs = "EPSG:4528";
    project.workarea_boundary = {{0, 0}, {1, 0}, {1, 1}};
    project.workarea_boundary_crs = "EPSG:4326";  // mismatch -> warn, skip
    project.seismic_surveys = {
        {.id = "s1",
         .name = "三维",
         .crs = "EPSG:4528",
         .extent = {{0, 0}, {10, 0}, {10, 5}}},
        {.id = "s2",
         .name = "二维",
         .crs = "EPSG:9999",
         .extent = {{0, 0}, {1, 0}, {1, 1}, {0, 1}}},
    };
    const auto warnings = crs_warnings(project);
    CHECK_EQ(warnings.size(), 2);
    CHECK(crs_warning_banner(project).find("⚠ ") == 0);
    CHECK_EQ(project_crs_label(project), "工程 CRS: EPSG:4528");
    // Mismatched boundary produces no ring.
    CHECK(boundary_ring(project).empty());
    // Only the CRS-matching survey yields a ring (3 corners -> 4 + close).
    const auto rings = survey_extent_rings(project);
    CHECK_EQ(rings.size(), 1);
    CHECK_EQ(rings[0].size(), 5);

    // Matching boundary closes itself.
    project.workarea_boundary_crs = "EPSG:4528";
    const auto boundary = boundary_ring(project);
    CHECK_EQ(boundary.size(), 4);
    CHECK(boundary.front() == boundary.back());
}

PWB_TEST(page_state_helpers) {
    CHECK_EQ(engine_unavailable_text("井曲线引擎", "no sdk"),
             "井曲线引擎不可用: no sdk");
    CHECK_EQ(engine_unavailable_text("井曲线引擎", ""),
             "井曲线引擎不可用: unknown");

    CHECK_EQ(well_log_backend_label(kWellLogBackendEngine), "WellLogEngine");
    CHECK_EQ(well_log_backend_label("legacy"), "Legacy (QPainter)");

    CHECK(well_log_engine_env_enabled(""));
    CHECK(well_log_engine_env_enabled("1"));
    CHECK(!well_log_engine_env_enabled("0"));
    CHECK(!well_log_engine_env_enabled("Legacy"));
    CHECK(!well_log_engine_env_enabled("OFF"));

    CHECK(!well_log_export_block_reason(kWellLogBackendEngine, "PNG")
               .has_value());
    CHECK(well_log_export_block_reason(kWellLogBackendEngine, "SVG")
              .has_value());
    CHECK(!well_log_export_block_reason("legacy", "SVG").has_value());

    CHECK(seismic_controls_enabled(true));
    CHECK(!seismic_controls_enabled(false));

    const auto counts = well_map_counts(
        {{.id = "a", .spatial_scope = "workarea"},
         {.id = "b", .spatial_scope = "reference"},
         {.id = "c", .spatial_scope = ""}});
    CHECK_EQ(counts.workarea, 2);
    CHECK_EQ(counts.reference, 1);
    CHECK_EQ(well_map_counts_text(counts), "2 口测区井 · 1 口参考井");
    CHECK_EQ(well_map_counts_text({.workarea = 3, .reference = 0}),
             "3 口井");
    CHECK_EQ(well_map_counts_text({}), "");
}

PWB_TEST(joint_state_round_trip) {
    JointAnalysisSlice state;
    state.tree_checks = {{"wells", true}, {"horizons", false}};
    state.well_visibility = {{"w1", false}};
    state.seismic_color_scale = "mono";
    state.gr_color_scale = "plasma";
    state.well_width_px = 99;   // clamped to [2,10] on read
    state.orthogonal_inline_index = 7;
    state.orthogonal_inline_number = 151.0;
    state.time_slices = {{100.0, true}, {200.0, false}};
    state.active_time_slice_ms = 100.0;
    state.time_slice_opacity = 5;  // clamped to [10,100] on read
    state.vertical_domain = "Depth";
    state.active_fence_wells = {"w1", "w2"};

    const Json payload = joint_state_to_json(state);
    const JointAnalysisSlice back = joint_state_from_json(payload);
    CHECK_EQ(back.tree_checks.size(), 2);
    CHECK(back.tree_checks.at("wells"));
    CHECK_EQ(back.well_visibility.at("w1"), false);
    CHECK_EQ(back.seismic_color_scale, "mono");
    CHECK_EQ(back.well_width_px, kJointWellWidthMax);
    CHECK_EQ(back.orthogonal_inline_index.value_or(-1), 7);
    CHECK_EQ(back.orthogonal_inline_number.value_or(-1), 151.0);
    CHECK_EQ(back.time_slices.size(), 2);
    CHECK_EQ(back.active_time_slice_ms.value_or(-1), 100.0);
    CHECK_EQ(back.time_slice_opacity, kJointOpacityMin);
    CHECK_EQ(back.vertical_domain, "Depth");
    CHECK_EQ(back.active_fence_wells.size(), 2);

    // Empty payload -> defaults (never throws).
    const JointAnalysisSlice defaults = joint_state_from_json(Json::object());
    CHECK_EQ(defaults.seismic_color_scale, "blue-white-red");
    CHECK_EQ(defaults.gr_color_scale, "viridis");
    CHECK_EQ(defaults.well_width_px, 5);
    CHECK_EQ(defaults.time_slice_opacity, 80);
    CHECK_EQ(defaults.vertical_domain, "Time");
}

PWB_TEST(export_options) {
    CrossWellExportOptions svg;
    svg.fmt = "svg";
    svg.width_px = 800;
    auto enabled = export_enabled(svg);
    CHECK(!enabled.dpi);
    CHECK(enabled.width);
    CHECK(!enabled.page_size);
    auto resolved = resolve_export_options(svg);
    CHECK_EQ(resolved.fmt, "svg");
    CHECK_EQ(resolved.width_px.value_or(-1), 800);
    CHECK(!resolved.page_size.has_value());

    CrossWellExportOptions pdf;
    pdf.fmt = "pdf";
    pdf.page_size = "A4";
    pdf.width_px = 900;  // ignored when a page size is chosen
    enabled = export_enabled(pdf);
    CHECK(enabled.dpi);
    CHECK(enabled.page_size);
    CHECK(!enabled.width);
    resolved = resolve_export_options(pdf);
    CHECK_EQ(resolved.page_size.value_or(""), "A4");
    CHECK(!resolved.width_px.has_value());

    CrossWellExportOptions pdf_free = pdf;
    pdf_free.page_size = std::nullopt;
    enabled = export_enabled(pdf_free);
    CHECK(enabled.width);  // content size keeps width editable
    resolved = resolve_export_options(pdf_free);
    CHECK_EQ(resolved.width_px.value_or(-1), 900);

    CrossWellExportOptions png;
    png.fmt = "png";
    enabled = export_enabled(png);
    CHECK(enabled.dpi);
    CHECK(!enabled.page_size);
    CHECK(enabled.width);
}

PWB_TEST(seismic_attribute_vocabulary) {
    CHECK(!seismic_attribute_groups().empty());
    CHECK(!all_seismic_attributes().empty());
    CHECK(is_known_seismic_attribute(
        all_seismic_attributes().front()));
    CHECK(!is_known_seismic_attribute("__not_an_attribute__"));
    CHECK(!seismic_attribute_panel_groups().empty());
    CHECK(!computable_kernel_labels().empty());
    // (kernel_key, display_label) pairs; kernel_for_label maps back.
    const auto& [kernel, text] = computable_kernel_labels().front();
    CHECK_EQ(kernel_for_label(text), kernel);
    CHECK_EQ(kernel_for_label("__nope__"), "");
    CHECK(seismic_display_modes().size() >= 2);
    // The 振幅 leaf is the user-reachable "clear attribute view" entry
    // (closure_seismic maps the pseudo-kernel to clear_attribute_view):
    // it must live in the FIRST panel group with its own kernel id.
    CHECK_EQ(kernel_for_label("振幅"), "amplitude");
    bool amplitude_leaf = false;
    for (const SeismicAttributeGroup& group :
         seismic_attribute_panel_groups()) {
        for (const std::string& leaf : group.attributes) {
            amplitude_leaf = amplitude_leaf || leaf == "振幅";
        }
    }
    CHECK(amplitude_leaf);
}

PWB_TEST(well_detail_rows) {
    WellDataViewSlice view;
    view.well_name = "井A";
    view.uwi = "UWI-1";
    view.role_slots = {
        {.role = "log",
         .members = {{.name = "GR", .is_primary = true,
                      .version_count = 2,
                      .current_version_id = "abcdefghijklmnop"},
                     {.name = "DEN", .version_count = 1}}},
        {.role = "tops", .unresolved = true},
    };
    view.stale_items = {{.stage = "interp", .version_id = "v123456789012345"},
                        {.stage = "import", .version_id = "v2", .pinned = true}};
    view.uncommitted_edits = {{.state = "draft", .source_version_id = "sv1"}};
    view.missing_source_asset_ids = {"asset-9"};

    CHECK_EQ(well_detail_title(view), "井A");
    CHECK(!well_detail_subtitle(view).empty());

    const auto rows = well_role_rows(view);
    CHECK_EQ(rows.size(), 2);
    CHECK_EQ(rows[0].primary_mark, "✓");
    CHECK_EQ(rows[0].member_names.find("GR") != std::string::npos, true);
    CHECK_EQ(rows[0].current_version_text, "abcdefghijklmn…");
    CHECK_EQ(rows[0].version_count_sum, 3);

    const auto empty = well_empty_roles(view);
    CHECK_EQ(empty.size(), 1);
    CHECK_EQ(empty[0], "tops");

    const auto stale = well_stale_lines(view, true);
    CHECK_EQ(stale.size(), 2);
    CHECK(stale[0].find("v12345678901…") != std::string::npos ||
          stale[0].find("v1234567890123…") != std::string::npos);
    const auto edits = well_edit_lines(view);
    CHECK_EQ(edits.size(), 1);
    const auto missing = well_missing_lines(view);
    // Python parity: member-less slots (incl. unresolved) emit 角色缺失
    // lines before the missing-source lines.
    CHECK_EQ(missing.size(), 2);
    CHECK(missing[0].find("角色缺失") != std::string::npos);
    CHECK(missing[1].find("asset-9") != std::string::npos);
}

int main() { return pwb_test::run_all(); }
