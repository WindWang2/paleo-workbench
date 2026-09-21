// CONV-36 — frozen-oracle replay for export_service + data_asset_registry.
// Fixture: tools/oracle/generate_export_oracle.py (real Python outputs).

#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <map>
#include <optional>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/interchange/exporters.hpp>

#include "../../interchange/src/xlsx_io.hpp"
#include <pwb/project/document.hpp>
#include <pwb/ui_data_core/data_asset_registry.hpp>
#include <pwb/ui_data_core/export_service.hpp>

namespace fs = std::filesystem;
using pwb::domain::Json;
using namespace pwb::ui_data_core;

namespace {

int failures = 0;

void check(bool ok, const std::string& name, const std::string& detail = "") {
    if (!ok) {
        ++failures;
        std::cout << "FAIL " << name;
        if (!detail.empty()) std::cout << "  " << detail;
        std::cout << "\n";
    }
}

Json read_json(const fs::path& path) {
    std::ifstream in(path);
    return Json::parse(in);
}

void write_text(const fs::path& path, const std::string& text) {
    fs::create_directories(path.parent_path());
    std::ofstream out(path, std::ios::binary | std::ios::trunc);
    out << text;
}

std::string file_bytes(const fs::path& path) {
    std::ifstream in(path, std::ios::binary);
    return {std::istreambuf_iterator<char>(in),
            std::istreambuf_iterator<char>()};
}

std::string hex_encode(const std::string& bytes) {
    static const char* kHex = "0123456789abcdef";
    std::string out;
    out.reserve(bytes.size() * 2);
    for (unsigned char b : bytes) {
        out.push_back(kHex[b >> 4]);
        out.push_back(kHex[b & 0xF]);
    }
    return out;
}

// Fixture paths are relative to the case root; the generator anchored
// absolute paths as "<root>/...".
fs::path resolve_frozen(const std::string& frozen, const fs::path& root) {
    std::string s = frozen;
    if (s.rfind("<root>/", 0) == 0) s = s.substr(6);
    if (s == "<root>") return root;
    return root / s;
}

// Normalize a runtime path/message back to the frozen form.
std::string freeze_path(const std::string& p, const fs::path& root) {
    fs::path pp(p);
    if (pp.is_absolute()) {
        std::error_code ec;
        const auto rel = fs::relative(fs::weakly_canonical(pp, ec),
                                      fs::weakly_canonical(root), ec);
        if (!ec) return rel.generic_string();
        return pp.filename().generic_string();
    }
    return p;
}

std::string freeze_message(const std::string& m, const fs::path& root) {
    std::string out = m;
    const std::string abs = fs::weakly_canonical(root).generic_string();
    std::size_t pos = 0;
    while ((pos = out.find(abs, pos)) != std::string::npos) {
        out.replace(pos, abs.size(), "<root>");
        pos += 6;
    }
    return out;
}

Json freeze_artifact(const std::optional<ExportArtifact>& a,
                     const fs::path& root) {
    if (!a.has_value()) return Json(nullptr);
    Json j = Json::object();
    j["id"] = "artifact_<id>";
    j["linked_id"] = a->linked_id;
    j["format"] = a->format;
    j["output_path"] = freeze_path(a->output_path, root);
    j["options"] = a->options;
    j["included_map_elements"] = a->included_map_elements;
    j["generated_at"] = "<ts>";
    j["source_task_ids"] = a->source_task_ids;
    j["catalog_version_id"] = a->catalog_version_id.has_value()
                                  ? Json(*a->catalog_version_id)
                                  : Json(nullptr);
    return j;
}

// export_artifacts section of a ProjectDocument → normalized list.
Json doc_artifacts(pwb::project::ProjectDocument& doc, const fs::path& root) {
    Json out = Json::array();
    const Json* sec = doc.find_section("export_artifacts");
    if (sec == nullptr || !sec->is_array()) return out;
    for (const auto& row : *sec) {
        Json j = row;
        if (j.contains("id")) j["id"] = "artifact_<id>";
        if (j.contains("generated_at")) j["generated_at"] = "<ts>";
        if (j.contains("output_path") && j["output_path"].is_string()) {
            j["output_path"] =
                freeze_path(j["output_path"].get<std::string>(), root);
        }
        out.push_back(std::move(j));
    }
    return out;
}

Json freeze_result(const ExportJobResult& r, const fs::path& root) {
    Json j = Json::object();
    j["success"] = r.success;
    j["output_path"] = freeze_path(r.output_path, root);
    j["format"] = r.format;
    j["artifact"] = freeze_artifact(r.artifact, root);
    j["message"] = freeze_message(r.message, root);
    j["warnings"] = r.warnings;
    return j;
}

// The fixture's project_artifacts rows come from pydantic model_dump —
// export_service rows include every artifact field; compare after
// normalization (the doc row is a superset of the dumped dict).
Json normalized_doc_row(Json row, const fs::path& root) {
    if (row.contains("id") && row["id"].is_string() &&
        row["id"].get<std::string>().rfind("artifact_", 0) == 0) {
        row["id"] = "artifact_<id>";
    }
    if (row.contains("generated_at")) row["generated_at"] = "<ts>";
    if (row.contains("output_path") && row["output_path"].is_string()) {
        row["output_path"] =
            freeze_path(row["output_path"].get<std::string>(), root);
    }
    return row;
}

// Frozen expected artifact dicts use pydantic field order/subset; compare
// key-by-key so generated_at/id stay normalized.
bool artifacts_match(const Json& actual_rows, const Json& expected,
                     const fs::path& root, std::string* diff) {
    if (actual_rows.size() != expected.size()) {
        *diff = "count " + std::to_string(actual_rows.size()) + " vs " +
                std::to_string(expected.size());
        return false;
    }
    for (std::size_t i = 0; i < expected.size(); ++i) {
        Json a = normalized_doc_row(actual_rows[i], root);
        for (const auto& [k, v] : expected[i].items()) {
            if (!a.contains(k) || a[k] != v) {
                *diff = "row " + std::to_string(i) + " key " + k +
                        ": actual=" +
                        (a.contains(k) ? a[k].dump() : "<missing>") +
                        " expected=" + v.dump();
                return false;
            }
        }
    }
    return true;
}

ResourceItem make_asset(const Json& spec) {
    ResourceItem r;
    r.id = spec.value("id", "");
    r.name = spec.value("name", "");
    r.path = spec.value("path", "");
    r.type = spec.value("type", "");
    r.format = spec.value("format", "");
    return r;
}

}  // namespace

int main() {
    const char* fixture = PWB_EXPORT_ORACLE;
    const Json oracle = read_json(fixture);

    const fs::path root =
        fs::temp_directory_path() / "pwb_export_oracle_test";
    std::error_code ec;
    fs::remove_all(root, ec);
    const fs::path tree = root / "tree";
    fs::create_directories(tree);

    // Fixture files (must exist before the case sequence runs — the scan
    // case snapshots the tree including earlier export outputs).
    write_text(tree / "table.csv", "a,b\n1,2\n3,4\n");
    write_text(tree / "notes.txt", "line1\nline2\n");
    write_text(tree / "bad.las", "not a las\n");
    write_text(tree / "map.geojson",
               "{\"type\":\"FeatureCollection\",\"features\":[]}");
    write_text(tree / "x.xyz", "unknown\n");

    const fs::path proj_dir = root / "proj";
    fs::create_directories(proj_dir);
    const fs::path project_path = proj_dir / "project.pwb";
    write_text(project_path, "{}");

    for (const auto& c : oracle["cases"]) {
        const std::string id = c["id"].get<std::string>();

        if (id == "labels") {
            for (const auto& [fmt, expected] : c["labels"].items()) {
                Json got = Json::array();
                for (const auto& l : list_asset_export_labels(fmt))
                    got.push_back(l);
                check(got == expected, id + "." + fmt,
                      got.dump() + " vs " + expected.dump());
            }
            for (const auto& [lbl, expected] : c["ranks"].items()) {
                check(view_format_rank(lbl) == expected.get<int>(),
                      id + ".rank." + lbl,
                      std::to_string(view_format_rank(lbl)) + " vs " +
                          expected.dump());
            }
            continue;
        }

        if (id.rfind("asset.", 0) == 0) {
            // Per-case asset table mirroring the generator.
            ResourceItem asset;
            asset.id = "res_src01";
            if (id == "asset.csv_to_json" || id == "asset.csv_to_xlsx" ||
                id == "asset.unsupported_label" ||
                id == "asset.registered") {
                asset.name = "table.csv";
                asset.path = (tree / "table.csv").generic_string();
                asset.type = "tabular";
                asset.format = "csv";
            } else if (id == "asset.missing_source") {
                asset.name = "missing.csv";
                asset.path = (tree / "missing.csv").generic_string();
                asset.type = "tabular";
                asset.format = "csv";
            } else if (id == "asset.las_error") {
                asset.name = "bad.las";
                asset.path = (tree / "bad.las").generic_string();
                asset.type = "well_log";
                asset.format = "las";
            }
            const std::map<std::string, std::string> out_names = {
                {"asset.csv_to_json", "out_table.json"},
                {"asset.csv_to_xlsx", "out_table.xlsx"},
                {"asset.unsupported_label", "out.pdf"},
                {"asset.missing_source", "out_missing.json"},
                {"asset.las_error", "out_bad.csv"},
                {"asset.registered", "out_reg.json"},
            };
            const std::map<std::string, std::string> labels = {
                {"asset.csv_to_json", "JSON"},
                {"asset.csv_to_xlsx", "XLSX"},
                {"asset.unsupported_label", "PDF"},
                {"asset.missing_source", "JSON"},
                {"asset.las_error", "CSV"},
                {"asset.registered", "JSON"},
            };
            const fs::path out = tree / out_names.at(id);
            ExportJobResult r;
            std::optional<pwb::project::ProjectDocument> doc;
            if (id == "asset.registered") {
                doc = pwb::project::ProjectDocument::create_new("demo", "R1");
                r = export_asset_to_path(asset, labels.at(id), out, &*doc,
                                         &project_path);
            } else {
                r = export_asset_to_path(asset, labels.at(id), out);
            }
            const Json got = freeze_result(r, root);
            check(got == c["result"], id + ".result",
                  got.dump() + "\n  vs " + c["result"].dump());
            if (c.contains("output_text")) {
                check(fs::exists(out) &&
                          file_bytes(out) ==
                              c["output_text"].get<std::string>(),
                      id + ".output_text");
            } else if (c.contains("output_xlsx")) {
                // Semantic parity: read the produced workbook back through
                // our own OOXML reader and compare the grid.
                const auto table =
                    pwb::interchange::xlsx::read_xlsx(out);
                Json grid = Json::array();
                Json head = Json::array();
                for (const auto& col : table.columns) head.push_back(col);
                grid.push_back(head);
                for (const auto& row : table.rows) grid.push_back(row);
                check(grid == c["output_xlsx"]["grid"], id + ".xlsx_grid",
                      grid.dump() + " vs " +
                          c["output_xlsx"]["grid"].dump());
                check(table.sheet_name ==
                          c["output_xlsx"]["sheet"].get<std::string>(),
                      id + ".xlsx_sheet");
            }
            if (id == "asset.registered") {
                std::string diff;
                check(artifacts_match(doc_artifacts(*doc, root),
                                      c["project_artifacts"], root, &diff),
                      id + ".project_artifacts", diff);
            }
            continue;
        }

        if (id == "inventory") {
            auto doc = pwb::project::ProjectDocument::create_new("inv", "Z");
            // Seed the PRE-state snapshot; the export itself appends the
            // inventory artifact.
            const Json& pj = c["seed_project"];
            doc.root()["resources"] = Json::array();
            for (const auto& res : pj["resources"]) {
                Json row = res;
                if (row["path"].is_string()) {
                    row["path"] =
                        resolve_frozen(row["path"].get<std::string>(), root)
                            .generic_string();
                }
                doc.root()["resources"].push_back(std::move(row));
            }
            doc.root()["export_artifacts"] = pj["export_artifacts"];
            const fs::path out = tree / "inv.json";
            const ExportJobResult r = export_project_inventory(
                doc, out, &project_path);
            check(freeze_result(r, root) == c["result"], id + ".result",
                  freeze_result(r, root).dump() + "\n  vs " +
                      c["result"].dump());
            // Written payload: parse + normalize resource paths, compare
            // semantically (whitespace parity is incidental).
            Json written = Json::parse(file_bytes(out));
            for (auto& row : written["resources"]) {
                row["path"] =
                    freeze_path(row["path"].get<std::string>(), root);
            }
            check(written == c["output_json"], id + ".output_json",
                  written.dump() + "\n  vs " + c["output_json"].dump());
            std::string diff;
            check(artifacts_match(doc_artifacts(doc, root),
                                  c["project_artifacts"], root, &diff),
                  id + ".project_artifacts", diff);
            continue;
        }

        if (id == "register_view") {
            auto doc = pwb::project::ProjectDocument::create_new("viz", "");
            const auto art = register_exported_view(
                "generic", tree / "view.png", "PNG", &doc, &project_path,
                "viz_view", true, {"task_a", "task_b"});
            check(freeze_artifact(art, root) == c["artifact"],
                  id + ".artifact",
                  freeze_artifact(art, root).dump() + " vs " +
                      c["artifact"].dump());
            std::string diff;
            check(artifacts_match(doc_artifacts(doc, root),
                                  c["project_artifacts"], root, &diff),
                  id + ".project_artifacts", diff);
            // register=False → nullopt
            check(!register_exported_view("generic", tree / "v.png", "PNG",
                                          &doc, &project_path, "viz_view",
                                          false)
                       .has_value(),
                  id + ".register_false");
            continue;
        }

        if (id == "default_export_dir") {
            check(default_export_dir(nullptr).filename().generic_string() ==
                      c["no_project"].get<std::string>(),
                  id + ".no_project");
            const fs::path got = default_export_dir(&project_path);
            check(freeze_path(got.generic_string(), root) ==
                      c["with_project"].get<std::string>(),
                  id + ".with_project",
                  freeze_path(got.generic_string(), root) + " vs " +
                      c["with_project"].dump());
            continue;
        }

        if (id == "registry") {
            DataAssetRegistry reg;
            FormatSpec spec;
            spec.format_id = "xyzdata";
            spec.extensions = {"xyz"};
            spec.resource_type = "custom_type";
            spec.status = "indexed_custom";
            spec.exporter = [](const ResourceItem&, std::string_view,
                               const fs::path& out) {
                write_text(out, "spec-export");
                return true;
            };
            reg.register_format(std::move(spec));

            for (const auto& [name, expected] : c["classify"].items()) {
                const auto [t, f, s] = reg.classify_path(tree / name);
                const Json got = Json::array({t, f, s});
                check(got == expected, id + ".classify." + name,
                      got.dump() + " vs " + expected.dump());
            }

            const auto scanned = reg.scan_directory(tree);
            Json names = Json::array(), types = Json::array();
            for (const auto& r : scanned) {
                names.push_back(r.name);
                types.push_back(r.type);
            }
            check(static_cast<int>(scanned.size()) ==
                      c["scan_count"].get<int>(),
                  id + ".scan_count");
            check(names == c["scan_names"], id + ".scan_names",
                  names.dump() + " vs " + c["scan_names"].dump());
            check(types == c["scan_types"], id + ".scan_types",
                  types.dump() + " vs " + c["scan_types"].dump());

            ResourceItem xyz;
            xyz.name = "x.xyz";
            xyz.path = (tree / "x.xyz").generic_string();
            xyz.type = "custom_type";
            xyz.format = "xyz";
            const fs::path spec_out = tree / "spec_out.bin";
            check(reg.export_asset(xyz, "xyzdata", spec_out) ==
                      c["spec_export_ok"].get<bool>(),
                  id + ".spec_export_ok");
            check(file_bytes(spec_out) ==
                      c["spec_export_text"].get<std::string>(),
                  id + ".spec_export_text");

            ResourceItem csv;
            csv.name = "table.csv";
            csv.path = (tree / "table.csv").generic_string();
            csv.type = "tabular";
            csv.format = "csv";
            const fs::path conv_out = tree / "conv_out.json";
            check(reg.export_asset(csv, "json", conv_out) ==
                      c["conv_export_ok"].get<bool>(),
                  id + ".conv_export_ok");
            check(file_bytes(conv_out) ==
                      c["conv_export_text"].get<std::string>(),
                  id + ".conv_export_text");

            try {
                reg.export_asset(xyz, "pdf", tree / "never.pdf");
                check(false, id + ".missing_exporter", "no throw");
            } catch (const pwb::interchange::ExportError& e) {
                check(std::string("ExportError: ") + e.what() ==
                          c["missing_exporter"].get<std::string>(),
                      id + ".missing_exporter", e.what());
            }
            continue;
        }

        check(false, "unknown case " + id);
    }

    std::cout << "export_oracle: " << oracle["cases"].size()
              << " checks, " << failures << " failure(s)\n";
    return failures == 0 ? 0 : 1;
}
