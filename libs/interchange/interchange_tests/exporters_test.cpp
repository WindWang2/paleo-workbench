// exporters oracle replay — resources/exporters.py parity.
//
// Fixture files are rebuilt from the frozen `work_files` / `xlsx_input` /
// `png_input_hex` payloads, each converter runs, and outputs compare
// cell-wise (xlsx via our own reader) or byte-wise (text/png).
//
// Error cases compare the ExportError class plus the deterministic prefix
// (the "XXX 失败:" vocabulary); library-specific tails (lasio / PIL / json
// messages) differ by design and are not frozen semantics.

#include <cstdio>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>

#include <pwb/domain/json.hpp>
#include <pwb/interchange/exporters.hpp>
#include <pwb/seismic_io/segy_layout.hpp>

#include "../src/xlsx_io.hpp"

namespace ix = pwb::interchange;
using pwb::domain::Json;
namespace fs = std::filesystem;

namespace {

int failures = 0;
int checks = 0;

void fail(const std::string& where, const Json& actual, const Json& want) {
    ++failures;
    std::cout << "FAIL " << where << "\n  actual   " << actual.dump()
              << "\n  expected " << want.dump() << "\n";
}

void check(bool ok, const std::string& where) {
    ++checks;
    if (!ok) {
        ++failures;
        std::cout << "FAIL " << where << "\n";
    }
}

// Numeric-tolerant JSON equality (1520 == 1520.0 across int/double storage).
bool json_eq(const Json& a, const Json& b) {
    if (a.is_number() && b.is_number())
        return a.get<double>() == b.get<double>();
    if (a.is_array() && b.is_array() && a.size() == b.size()) {
        for (std::size_t i = 0; i < a.size(); ++i)
            if (!json_eq(a[i], b[i])) return false;
        return true;
    }
    if (a.is_object() && b.is_object() && a.size() == b.size()) {
        for (auto it = a.begin(); it != a.end(); ++it) {
            if (!b.contains(it.key()) || !json_eq(it.value(), b[it.key()]))
                return false;
        }
        return true;
    }
    return a == b;
}

std::string read_text(const fs::path& path) {
    std::ifstream in(path, std::ios::binary);
    std::ostringstream ss;
    ss << in.rdbuf();
    return ss.str();
}

void write_text(const fs::path& path, const std::string& text) {
    std::ofstream out(path, std::ios::binary | std::ios::trunc);
    out << text;
}

void write_hex(const fs::path& path, const std::string& hex) {
    std::ofstream out(path, std::ios::binary | std::ios::trunc);
    for (std::size_t i = 0; i + 1 < hex.size(); i += 2) {
        out.put(static_cast<char>(
            std::stoi(hex.substr(i, 2), nullptr, 16)));
    }
}

std::string message_prefix(const std::string& message) {
    const auto pos = message.find(": ");
    return pos == std::string::npos ? message
                                    : message.substr(0, pos + 2);
}

}  // namespace

int main() {
#ifndef PWB_EXPORTERS_ORACLE
    std::cout << "PWB_EXPORTERS_ORACLE not defined\n";
    return 2;
#endif
    std::ifstream in(PWB_EXPORTERS_ORACLE);
    if (!in) {
        std::cout << "cannot open " << PWB_EXPORTERS_ORACLE << "\n";
        return 2;
    }
    const Json oracle = Json::parse(in);
    const fs::path work =
        fs::temp_directory_path() / "pwb_exporters_oracle";
    fs::remove_all(work);
    fs::create_directories(work);

    // ---- registry ---------------------------------------------------------
    for (const auto& row : oracle["registry"]) {
        if (row.contains("format")) {
            std::vector<std::string> got;
            for (const auto& [label, fn] :
                 ix::get_available_formats(
                     row["format"].get<std::string>())) {
                got.push_back(label);
            }
            const Json want = row["labels"];
            if (!json_eq(Json(got), want))
                fail("registry " + row["format"].get<std::string>(),
                     Json(got), want);
            ++checks;
        } else {
            const std::string got =
                ix::extension_for_label(row["ext_for"].get<std::string>());
            const Json want = row["ext"];
            if (!json_eq(Json(got), want))
                fail("ext " + row["ext_for"].get<std::string>(), Json(got),
                     want);
            ++checks;
        }
    }

    // ---- fixture materialization -------------------------------------------
    for (const auto& [name, content] : oracle["work_files"].items()) {
        write_text(work / name, content.get<std::string>());
    }
    // Recreate the pandas-produced xlsx input from its frozen grid.
    {
        const Json& grid = oracle["xlsx_input"]["xlsx_grid"];
        std::vector<std::string> cols;
        for (const auto& c : grid[0]) cols.push_back(c.get<std::string>());
        std::vector<std::vector<Json>> rows;
        for (std::size_t r = 1; r < grid.size(); ++r) {
            rows.emplace_back(grid[r].begin(), grid[r].end());
        }
        ix::xlsx::write_xlsx(work / "in.xlsx", cols, rows);
    }
    write_hex(work / "img.png", oracle["png_input_hex"].get<std::string>());

    // ---- converters ---------------------------------------------------------
    ix::set_image_png_provider(
        [](const fs::path& src, const fs::path& dst) -> bool {
            // Orchestration stub: only decodes real PNG bytes (the PIL
            // counterpart); other inputs fail like PIL would.
            const auto head = read_text(src);
            if (head.size() < 8 || head.substr(0, 8) != "\x89PNG\r\n\x1a\n")
                return false;
            write_text(dst, head);
            return true;
        });

    for (const auto& row : oracle["cases"]) {
        const std::string id = row["id"].get<std::string>();
        const std::string& fn_name = id.substr(0, id.find('.'));
        const fs::path src = work / row["src"].get<std::string>();
        const fs::path out = work / row["out_name"].get<std::string>();
        ix::ConvertFn fn;
        if (fn_name == "las_to_csv") fn = ix::las_to_csv;
        else if (fn_name == "las_to_xlsx") fn = ix::las_to_xlsx;
        else if (fn_name == "las_to_json_summary") fn = ix::las_to_json_summary;
        else if (fn_name == "table_to_json") fn = ix::table_to_json;
        else if (fn_name == "table_to_xlsx") fn = ix::table_to_xlsx;
        else if (fn_name == "image_to_png") fn = ix::image_to_png;
        else if (fn_name == "text_to_txt") fn = ix::text_to_txt;
        else if (fn_name == "geojson_normalize") fn = ix::geojson_normalize;
        else {
            std::cout << "unknown converter " << fn_name << "\n";
            ++failures;
            continue;
        }

        ++checks;
        try {
            fn(src, out);
        } catch (const ix::ExportError& exc) {
            if (!row.contains("error")) {
                fail(id + " threw", Json(exc.what()), Json("ok"));
                continue;
            }
            check(row["error"]["class"] == "ExportError", id + " class");
            const std::string want =
                row["error"]["message"].get<std::string>();
            const std::string got = exc.what();
            if (got != want &&
                got.compare(0, message_prefix(want).size(),
                            message_prefix(want)) != 0) {
                fail(id + " message", Json(got), Json(want));
            }
            continue;
        }
        if (row.contains("error")) {
            fail(id + " expected error", Json("ok"), row["error"]["class"]);
            continue;
        }
        const Json& frozen = row["file"];
        if (frozen.contains("xlsx_grid")) {
            const auto table = ix::xlsx::read_xlsx(out);
            Json got_grid = Json::array();
            Json head = Json::array();
            for (const auto& c : table.columns) head.push_back(c);
            got_grid.push_back(head);
            for (const auto& r : table.rows) got_grid.push_back(r);
            if (!json_eq(got_grid, frozen["xlsx_grid"]))
                fail(id + " grid", got_grid, frozen["xlsx_grid"]);
            if (table.sheet_name != frozen["xlsx_sheet"].get<std::string>())
                fail(id + " sheet", Json(table.sheet_name),
                     frozen["xlsx_sheet"]);
        } else if (frozen.contains("png_hex")) {
            // Provider-copy semantics: output equals the input bytes.
            check(read_text(out) == read_text(src), id + " png copy");
        } else {
            const std::string got = read_text(out);
            std::string want = frozen["text"].get<std::string>();
            // `source` fields embed the Python-side tmp path — normalize to
            // the basename before comparing.
            if (id.find("las_to_json_summary") == 0) {
                Json gj = Json::parse(got), wj = Json::parse(want);
                gj["source"] = fs::path(gj["source"].get<std::string>())
                                   .filename()
                                   .string();
                wj["source"] = fs::path(wj["source"].get<std::string>())
                                   .filename()
                                   .string();
                if (!json_eq(gj, wj)) fail(id, gj, wj);
            } else if (got != want) {
                fail(id, Json(got), Json(want));
            }
        }
    }

    // ---- seismic payload: real SEGY inspect → summary keys -----------------
    // The geoviz SeismicLoader is not importable for oracle generation; the
    // frozen stub documents the key set/order. Here the converter runs on the
    // real tiny.sgy and the payload is validated against inspect_segy's own
    // descriptor (the only semantic the converter adds is the field mapping).
    {
#ifdef PWB_TINY_SEGY
        const fs::path segy = PWB_TINY_SEGY;
#else
        const fs::path segy =
            fs::path(PWB_EXPORTERS_ORACLE).parent_path() /
            "../../../../tests/fixtures/realdata/tiny.sgy";
#endif
        const fs::path out = work / "segy.json";
        ++checks;
        if (fs::exists(segy)) {
            try {
                ix::seismic_to_summary_json(segy, out);
                const Json payload = Json::parse(read_text(out));
                const Json want_keys =
                    oracle["seismic_stub_payload"];
                for (auto it = want_keys.begin(); it != want_keys.end();
                     ++it) {
                    if (!payload.contains(it.key())) {
                        fail("segy key", Json(it.key()), payload);
                        break;
                    }
                }
                std::string error;
                const auto layout =
                    pwb::seismic_io::inspect_segy(segy, &error);
                if (!layout.has_value()) {
                    fail("segy inspect", Json("ok"), Json(error));
                } else {
                    const auto& d = layout->descriptor;
                    Json mapped = Json::object();
                    mapped["n_inlines"] = d.ni;
                    mapped["n_crosslines"] = d.nc;
                    mapped["n_samples"] = d.ns;
                    mapped["dt_ms"] = d.sample_step;
                    mapped["t0_ms"] = d.sample_start;
                    mapped["iline_start"] = d.iline_start;
                    mapped["iline_step"] = d.iline_step;
                    mapped["xline_start"] = d.xline_start;
                    mapped["xline_step"] = d.xline_step;
                    for (auto it = mapped.begin(); it != mapped.end(); ++it) {
                        if (!json_eq(payload[it.key()], it.value())) {
                            fail("segy " + it.key(), payload[it.key()],
                                 it.value());
                            break;
                        }
                    }
                }
            } catch (const std::exception& exc) {
                fail("segy convert", Json("ok"), Json(exc.what()));
            }
        }
    }

    std::cout << "exporters: " << checks << " checks, " << failures
              << " failure(s)\n";
    fs::remove_all(work);
    return failures ? 1 : 0;
}
