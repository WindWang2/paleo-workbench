// ingest.parsers — the C++ ingest parse cores vs the frozen Python oracle
// (libs/ingest/oracle/fixtures/ingest_oracle.json, generated from the REAL
// implementations by libs/ingest/oracle/generate_ingest_oracles.py).
//
// Every group compares a projected JSON view of the C++ result against the
// frozen projection using the domain kernel's semantic diff (same comparator
// convention as the data-suite oracles).

#include <sys/stat.h>
#include <atomic>
#if !defined(_WIN32)
#include <unistd.h>
#endif

#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <charconv>
#include <filesystem>
#include <set>
#include <fstream>
#include <map>
#include <optional>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/ingest/classifier.hpp>
#include <pwb/ingest/preview/document_parsers.hpp>
#include <pwb/ingest/preview/models.hpp>
#include <pwb/ingest/preview/office.hpp>
#include <pwb/ingest/preview/registry.hpp>
#include <pwb/ingest/preview/spreadsheetml.hpp>
#include <pwb/ingest/preview/text_parsers.hpp>
#include <pwb/ingest/preview/well_log_xml_preview.hpp>
#include <pwb/ingest/project_path.hpp>
#include <pwb/ingest/py_compat.hpp>
#include <pwb/ingest/well_parsers.hpp>
#include <pwb/ingest/classifier.hpp>
#include <pwb/ingest/well_xml.hpp>
#include "pwb/ingest/xml_scanner.hpp"

using pwb::domain::Json;
using namespace pwb::ingest;
using namespace pwb::ingest::preview;

namespace {

int g_cases = 0;
int g_failures = 0;
std::string g_tmp;  // this run's sandbox; expected values carry <TMP> markers

std::string replace_all(std::string s, const std::string& from,
                        const std::string& to);

// Integers parsed through JSON text so the comparator sees the same
// number_unsigned kind the fixture parse produces.
inline Json jint(long long v) { return Json::parse(std::to_string(v)); }

void fail(const std::string& what) {
    std::fprintf(stderr, "FAIL %s\n", what.c_str());
    ++g_failures;
}

void check(bool ok, const std::string& what) {
    if (!ok) fail(what);
}

void check_diff(const Json& expected_in, const Json& actual, const std::string& what) {
    ++g_cases;
    Json expected = expected_in;
    if (!g_tmp.empty() && expected.is_string() &&
        expected.get_ref<const std::string&>().find("<TMP>") != std::string::npos) {
        expected = replace_all(expected.get_ref<const std::string&>(), "<TMP>", g_tmp);
    } else if (expected.is_object() || expected.is_array()) {
        std::string dump = expected.dump();
        if (dump.find("<TMP>") != std::string::npos) {
            expected = Json::parse(replace_all(dump, "<TMP>", g_tmp));
        }
    }
    auto diff = pwb::domain::json_semantic_diff(expected, actual);
    if (!diff.equal) {
        fail(what + " @ " + diff.path + ": " + diff.reason +
             "\n  expected: " + expected.dump() + "\n  actual:   " + actual.dump());
    }
}

Json load_fixture() {
    std::ifstream in(PWB_INGEST_FIXTURE);
    if (!in) {
        std::fprintf(stderr, "cannot open oracle fixture %s\n", PWB_INGEST_FIXTURE);
        std::exit(2);
    }
    return Json::parse(in);
}

std::string b64_decode(const std::string& in) {
    static const std::string alphabet =
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    std::string out;
    int val = 0, valb = -8;
    for (unsigned char c : in) {
        if (c == '=') break;
        size_t pos = alphabet.find(static_cast<char>(c));
        if (pos == std::string::npos) continue;
        val = (val << 6) + static_cast<int>(pos);
        valb += 6;
        if (valb >= 0) {
            out.push_back(static_cast<char>((val >> valb) & 0xFF));
            valb -= 8;
        }
    }
    return out;
}

std::string b64_encode(const std::string& in) {
    static const std::string alphabet =
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    std::string out;
    int val = 0, valb = -6;
    for (unsigned char c : in) {
        val = (val << 8) + c;
        valb += 8;
        while (valb >= 0) {
            out.push_back(alphabet[(val >> valb) & 0x3F]);
            valb -= 6;
        }
    }
    if (valb > -6) out.push_back(alphabet[((val << 8) >> (valb + 8)) & 0x3F]);
    while (out.size() % 4) out.push_back('=');
    return out;
}

std::string make_tmp_dir() {
#if defined(_WIN32)
    // mkdtemp is POSIX-only — same contract (unique, created directory)
    // through the std::filesystem temp root + a monotonic unique suffix.
    static std::atomic<unsigned long long> counter{0};
    for (int attempt = 0; attempt < 64; ++attempt) {
        const auto dir = std::filesystem::temp_directory_path() /
                         ("ingest_oracle_" + std::to_string(counter++));
        std::error_code ec;
        if (std::filesystem::create_directory(dir, ec) && !ec) {
            return dir.string();
        }
    }
    std::perror("make_tmp_dir");
    std::exit(2);
#else
    std::string tmpl = "/tmp/ingest_oracle_XXXXXX";
    std::vector<char> buf(tmpl.begin(), tmpl.end());
    buf.push_back('\0');
    if (!mkdtemp(buf.data())) {
        std::perror("mkdtemp");
        std::exit(2);
    }
    return std::string(buf.data());
#endif
}

void write_file(const std::string& path, std::string_view bytes) {
    std::ofstream out(path, std::ios::binary | std::ios::trunc);
    out.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
}

// Canonical settings JSON: int/bool/string/float buckets per JSON type.
PreviewSettings settings_from_case(const Json& values, std::string* error) {
    std::vector<std::pair<std::string, long long>> ints;
    std::vector<std::pair<std::string, bool>> bools;
    std::vector<std::pair<std::string, std::string>> strings;
    std::vector<std::pair<std::string, double>> floats;
    for (auto it = values.begin(); it != values.end(); ++it) {
        const Json& v = it.value();
        if (v.is_boolean()) bools.emplace_back(it.key(), v.get<bool>());
        else if (v.is_string()) strings.emplace_back(it.key(), v.get<std::string>());
        else if (v.is_number_integer()) ints.emplace_back(it.key(), v.get<long long>());
        else if (v.is_number_float()) floats.emplace_back(it.key(), v.get<double>());
    }
    return PreviewSettings::from_mapping(ints, bools, strings, error, floats);
}

std::string replace_all(std::string s, const std::string& from,
                        const std::string& to) {
    size_t pos = 0;
    while ((pos = s.find(from, pos)) != std::string::npos) {
        s.replace(pos, from.size(), to);
        pos += to.size();
    }
    return s;
}

Json replace_json_tmp(Json j, const std::string& tmp) {
    return Json::parse(replace_all(j.dump(), "<TMP>", tmp));
}

// Python repr() of a float: shortest round-trip digits, integral values get
// a trailing ".0", inf/nan spell out.
std::string repr_double(double v) {
    if (std::isnan(v)) return "nan";
    if (std::isinf(v)) return v > 0 ? "inf" : "-inf";
    char buf[64];
    auto res = std::to_chars(buf, buf + sizeof(buf), v);
    std::string s(buf, res.ptr);
    if (s.find('.') == std::string::npos && s.find('e') == std::string::npos &&
        s.find('n') == std::string::npos) {
        s += ".0";
    }
    return s;
}

// ---- result projection (mirrors the generator's project_result) ----

Json revision_json(const Revision& rev) {
    if (!rev.present) return Json(nullptr);
    Json stat_item = Json::array();
    stat_item.push_back("stat");
    stat_item.push_back(rev.has_stat ? jint(rev.stat_size) : Json(nullptr));
    if (rev.text_parts.empty()) {
        // bare (size, mtime) stat tuple -> [["stat", size]]
        Json out = Json::array();
        out.push_back(stat_item);
        return out;
    }
    Json out = Json::array();
    for (const auto& part : rev.text_parts) {
        out.push_back(part.empty() ? Json(nullptr) : Json(part));
    }
    // Python's token carries the raw stat tuple: null when unreadable
    out.push_back(rev.has_stat ? Json(stat_item) : Json(nullptr));
    return out;
}

Json project_result(const PreviewResult& r, bool include_bytes) {
    Json j;
    j["mode"] = r.mode;
    j["title"] = r.title;
    j["path"] = r.path;
    j["format"] = r.format;
    j["status"] = r.status;
    j["type_label"] = r.type_label;
    j["message"] = r.message;
    j["warning"] = r.warning;
    j["text"] = r.text;
    j["truncated"] = r.truncated;
    j["rich_html"] = r.rich_html;
    j["media_path"] = r.media_path;
    j["table_headers"] = r.table_headers;
    j["table_rows"] = r.table_rows;
    Json summary = Json::array();
    for (const auto& [k, v] : r.summary_rows) {
        Json pair = Json::array();
        pair.push_back(k);
        pair.push_back(v);
        summary.push_back(pair);
    }
    j["summary_rows"] = summary;
    j["sheets"] = r.sheets;
    j["data_headers"] = r.data_headers;
    j["data_rows"] = r.data_rows;
    j["json_truncated"] = r.json_truncated;
    j["json_ok"] = r.json_ok;
    j["estimated_bytes"] = jint(r.estimated_bytes);
    j["visualization_available"] = r.visualization_available;
    if (include_bytes) {
        j["image_bytes_b64"] = b64_encode(r.image_bytes);
    } else {
        j["image_bytes_b64"] = nullptr;
    }
    j["revision"] = revision_json(r.revision);
    return j;
}

}  // namespace

namespace {

void test_constants(const Json& fixture) {
    const Json& c = fixture.at("constants");
    std::string what = "constants";
    check(static_cast<int>(in_text_formats("txt")) +
              static_cast<int>(in_text_formats("dat")) +
              static_cast<int>(in_text_formats("xml")) ==
              3, what);
    check(!in_text_formats("csv"), what);
    check(in_table_formats("tsv") && !in_table_formats("json"), what);
    check(in_excel_formats("xls") && !in_excel_formats("png"), what);
    check(in_image_formats("jpeg") && in_image_formats("tiff"), what);
    check(in_pdf_formats("pdf"), what);
    check(in_las_formats("las") && !in_las_formats("txt"), what);
    check(in_segy_formats("sgy") && in_segy_formats("segy"), what);
    check(in_markdown_formats("md") && in_markdown_formats("html"), what);
    check(in_html_formats("htm"), what);
    check(in_json_formats("geojson"), what);
    check(in_geotiff_formats("tif") && in_geotiff_formats("tiff"), what);
    check(in_audio_formats("ogg"), what);
    check(in_video_formats("mkv"), what);
    check(kMaxTextPreviewBytes == c.at("max_text_preview_bytes").get<int>(), what);
    check(kMaxTableRows == c.at("max_table_rows").get<int>(), what);
    check(kMaxTableColumns == c.at("max_table_columns").get<int>(), what);
    check(kMaxJsonParseBytes == c.at("max_json_parse_bytes").get<long long>(), what);
    check(kMaxArchiveNames == c.at("max_archive_names").get<int>(), what);
    check(static_cast<long long>(kMaxEmbeddedImageBytes) ==
              c.at("max_embedded_image_bytes").get<long long>(), what);
    check(static_cast<long long>(kMaxCentralDirectoryBytes) ==
              c.at("max_central_directory_bytes").get<long long>(), what);
    check(kMaxCentralEntries == c.at("max_central_entries").get<int>(), what);
    check(static_cast<long long>(kMaxCentralNameBytes) ==
              c.at("max_central_name_bytes").get<long long>(), what);
    check(kJsonArrayCollapseThreshold ==
              c.at("json_array_collapse_threshold").get<int>(), what);
    check(well_location_max_records() ==
              static_cast<size_t>(
                  c.at("max_records_well_location").get<long long>()),
          what);
    check(well_log_xml_max_elements() ==
              static_cast<size_t>(
                  c.at("max_elements_well_log_xml").get<long long>()),
          what);
    ++g_cases;

    // full frozen format-set reconciliation (every member must be claimed)
    auto check_set = [&](const char* fixture_key, bool (*claims)(std::string_view)) {
        for (const auto& ext : c.at(fixture_key)) {
            check(claims(ext.get<std::string>()),
                  std::string("constants/set:") + fixture_key + "/" +
                      ext.get<std::string>());
        }
    };
    check_set("text_formats", in_text_formats);
    check_set("table_formats", in_table_formats);
    check_set("excel_formats", in_excel_formats);
    check_set("image_formats", in_image_formats);
    check_set("pdf_formats", in_pdf_formats);
    check_set("las_formats", in_las_formats);
    check_set("segy_formats", in_segy_formats);
    check_set("markdown_formats", in_markdown_formats);
    check_set("html_formats", in_html_formats);
    check_set("json_formats", in_json_formats);
    check_set("geotiff_formats", in_geotiff_formats);
    check_set("audio_formats", in_audio_formats);
    check_set("video_formats", in_video_formats);
    ++g_cases;

    // io_registry tables
    for (auto it = c.at("type_labels").begin(); it != c.at("type_labels").end();
         ++it) {
        auto found = type_labels().find(it.key());
        check(found != type_labels().end() &&
                  found->second == it.value().get<std::string>(),
              std::string("constants/type_labels/") + it.key());
    }
    for (auto it = c.at("role_by_type").begin(); it != c.at("role_by_type").end();
         ++it) {
        auto found = role_by_type().find(it.key());
        check(found != role_by_type().end() &&
                  found->second == it.value().get<std::string>(),
              std::string("constants/role_by_type/") + it.key());
    }
    for (const auto& ext : c.at("preferred_import_extensions")) {
        check(is_preferred_import_extension(ext.get<std::string>()),
              std::string("constants/preferred/") + ext.get<std::string>());
    }
    ++g_cases;

    // well-log SpreadsheetML recognition table
    {
        std::vector<std::string> frozen;
        for (const auto& n : c.at("spreadsheet_names_well_log")) {
            frozen.push_back(n.get<std::string>());
        }
        std::set<std::string> frozen_set(frozen.begin(), frozen.end());
        std::set<std::string> actual_set(well_log_spreadsheet_names().begin(),
                                         well_log_spreadsheet_names().end());
        check(frozen_set == actual_set,
              "constants/spreadsheet_names_well_log");
        ++g_cases;
    }
}

void test_well_tops(const Json& fixture) {
    for (const auto& case_json : fixture.at("well_tops")) {
        auto tops = parse_well_tops_text(case_json.at("text").get<std::string>());
        Json rows = Json::array();
        for (const auto& t : tops) {
            Json row;
            row["well_name"] = t.well_name;
            row["top_name"] = t.top_name;
            row["md"] = repr_double(t.md);
            row["tvd"] = t.tvd ? Json(repr_double(*t.tvd)) : Json(nullptr);
            rows.push_back(row);
        }
        Json actual;
        actual["records"] = rows;
        Json expected;
        expected["records"] = case_json.at("expected");
        check_diff(expected, actual,
                   "well_tops/" + case_json.at("name").get<std::string>());
    }
}

void test_well_location_xml(const Json& fixture) {
    for (const auto& case_json : fixture.at("well_location_xml")) {
        auto result = extract_well_locations_xml_bytes(
            case_json.at("xml").get<std::string>());
        Json records = Json::array();
        for (const auto& r : result.records) {
            Json row;
            row["name"] = r.name;
            row["x"] = repr_double(r.x);
            row["y"] = repr_double(r.y);
            row["z"] = r.z ? Json(repr_double(*r.z)) : Json(nullptr);
            row["uwi"] = r.uwi;
            row["source_crs"] = r.source_crs;
            records.push_back(row);
        }
        Json actual;
        actual["records"] = records;
        actual["warnings"] = result.warnings;
        actual["is_well_location"] = is_well_location_xml_bytes(
            case_json.at("xml").get<std::string>());
        Json expected;
        expected["records"] = case_json.at("expected").at("records");
        expected["warnings"] = case_json.at("expected").at("warnings");
        expected["is_well_location"] =
            case_json.at("expected").at("is_well_location");
        check_diff(expected, actual,
                   "well_location_xml/" + case_json.at("name").get<std::string>());
    }
}

void test_well_log_xml(const Json& fixture) {
    for (const auto& case_json : fixture.at("well_log_xml")) {
        bool got = is_well_log_xml_bytes(case_json.at("xml").get<std::string>());
        bool want = case_json.at("expected").get<bool>();
        check(got == want, "well_log_xml/" + case_json.at("name").get<std::string>() +
                               " got " + (got ? "true" : "false"));
        ++g_cases;
    }
}

void test_classifier(const Json& fixture) {
    for (const auto& case_json : fixture.at("classify_path")) {
        auto got = classify_path(case_json.at("path").get<std::string>());
        Json actual = Json::array({got.type, got.format, got.status});
        check_diff(case_json.at("expected"), actual,
                   "classify_path/" + case_json.at("name").get<std::string>());
    }
    for (const auto& case_json : fixture.at("classify_import")) {
        auto got = classify_import_path(case_json.at("filename").get<std::string>(),
                                        case_json.at("content").get<std::string>());
        Json actual = Json::array({got.type, got.format, got.status});
        check_diff(case_json.at("expected"), actual,
                   "classify_import/" + case_json.at("name").get<std::string>());
    }
}

void test_project_paths(const Json& fixture) {
    // reconstruct the generator's sandbox layout under g_tmp; expected
    // values carry <TMP> and check_diff substitutes this run's sandbox.
    std::string tmp = g_tmp;
    write_file(tmp + "/demo.paleo.json", "{}");
    std::filesystem::create_directories(tmp + "/demo.paleo.json.artifacts/data");
    write_file(tmp + "/demo.paleo.json.artifacts/data/a.las", "~V\n");
    std::filesystem::create_directories(tmp + "/outside");
    write_file(tmp + "/outside/secret.txt", "x");

    for (const auto& case_json : fixture.at("project_paths")) {
        std::string name = case_json.at("name").get<std::string>();
        std::string op = case_json.at("op").get<std::string>();
        std::string path = replace_all(case_json.at("path").get<std::string>(),
                                       "<TMP>", tmp);
        std::string project = replace_all(
            case_json.at("project").get<std::string>(), "<TMP>", tmp);
        const Json& expected = case_json.at("expected");
        if (op == "relativize") {
            auto got = relativize_path(path, project);
            Json actual = Json::array({got.path, got.external});
            check_diff(expected, actual, "project_paths/" + name);
        } else if (op == "resolve") {
            try {
                std::string got = resolve_project_path(path, project);
                Json actual = Json::array({Json(got), Json(nullptr)});
                check_diff(expected, actual, "project_paths/" + name);
            } catch (const ProjectPathError&) {
                Json actual = Json::array({Json(nullptr), Json("ProjectPathError")});
                check_diff(expected, actual, "project_paths/" + name);
            }
        } else if (op == "is_within") {
            bool got = is_within_directory(path, project);
            Json actual = Json::array({Json(got), Json(nullptr)});
            check_diff(expected, actual, "project_paths/" + name);
        } else if (op == "stat") {
            auto got = safe_file_stat(path);
            Json actual = Json::array(
                {got ? jint(got->size) : Json(nullptr), Json(nullptr)});
            check_diff(expected, actual, "project_paths/" + name);
        }
    }
}

void test_previews(const Json& fixture) {
    std::string tmp = g_tmp;
    const Json& groups = fixture.at("previews");
    for (auto group_it = groups.begin(); group_it != groups.end(); ++group_it) {
        const std::string& group = group_it.key();
        for (const auto& case_json : group_it.value()) {
            std::string name = case_json.at("name").get<std::string>();
            std::string raw = b64_decode(case_json.at("bytes_b64").get<std::string>());
            std::string path = tmp + "/" + case_json.at("filename").get<std::string>();
            write_file(path, raw);
            ResourceRef res;
            res.id = "res-oracle";
            res.name = case_json.at("filename").get<std::string>();
            res.path = path;
            res.type = case_json.at("type").get<std::string>();
            res.format = case_json.at("format").get<std::string>();
            res.status = case_json.at("status").get<std::string>();
            // safe_stat-shaped revision for every direct table_parsers /
            // document_parsers preview call
            res.revision.present = true;
            res.revision.has_stat = true;
            res.revision.stat_size = static_cast<long long>(raw.size());
            if (group == "json") {
                res.revision.text_parts = {"resource", "res-oracle", path,
                                           res.type, res.format, res.status, ""};
            }
            std::string settings_error;
            PreviewSettings settings =
                settings_from_case(case_json.at("settings"), &settings_error);
            PreviewResult r;
            if (group == "text") {
                r = text_preview(res, raw, settings);
            } else if (group == "dat") {
                r = dat_preview(res, raw, settings);
            } else if (group == "csv") {
                r = table_preview(res, raw,
                                  res.format == "tsv" ? '\t' : ',', settings);
            } else if (group == "markdown") {
                r = markdown_rich_preview(res, raw, settings);
            } else if (group == "json") {
                r = json_preview(res, raw, settings);
                if (r.mode == "message") {
                    // parse_error_preview switches to the bare safe_stat
                    res.revision.text_parts.clear();
                    res.revision.has_stat = true;
                    res.revision.stat_size = static_cast<long long>(raw.size());
                    r.revision = res.revision;
                }
            } else {
                continue;
            }
            check_diff(case_json.at("expected"), project_result(r, false),
                       "previews." + group + "/" + name);
        }
    }
}

void test_spreadsheetml(const Json& fixture) {
    std::string tmp = g_tmp;
    for (const auto& case_json : fixture.at("spreadsheetml")) {
        std::string name = case_json.at("name").get<std::string>();
        std::string raw = b64_decode(case_json.at("bytes_b64").get<std::string>());
        std::string path = tmp + "/case.xml";
        write_file(path, raw);
        ResourceRef res;
        res.id = "res-oracle";
        res.name = "case.xml";
        res.path = path;
        res.type = "spreadsheet";
        res.format = "xml";
        res.status = "indexed";
        res.revision.present = true;
        res.revision.has_stat = true;
        res.revision.stat_size = static_cast<long long>(raw.size());
        const Json& limits = case_json.at("limits");
        auto result = spreadsheetml_preview(res, raw,
                                            limits.at("max_text_bytes").get<long long>(),
                                            limits.at("max_rows").get<int>(),
                                            limits.at("max_columns").get<int>());
        Json actual = result ? Json(project_result(*result, false)) : Json(nullptr);
        const Json& expected = case_json.at("expected");
        check_diff(expected.is_null() ? Json(nullptr) : expected, actual,
                   "spreadsheetml/" + name);
    }
}

void test_xml_well_log(const Json& fixture) {
    std::string tmp = g_tmp;
    for (const auto& case_json : fixture.at("xml_well_log")) {
        std::string name = case_json.at("name").get<std::string>();
        std::string raw = b64_decode(case_json.at("bytes_b64").get<std::string>());
        std::string path = tmp + "/case.xml";
        write_file(path, raw);
        ResourceRef res;
        res.id = "res-oracle";
        res.name = "case.xml";
        res.path = path;
        res.type = "well_log";
        res.format = "xml";
        res.status = "indexed";
        res.revision.present = true;
        res.revision.has_stat = true;
        res.revision.stat_size = static_cast<long long>(raw.size());
        PreviewSettings settings = PreviewSettings::defaults();
        settings.table_max_rows = case_json.at("table_max_rows").get<int>();
        auto result = xml_well_log_preview(res, raw, settings);
        Json actual = result ? Json(project_result(*result, false)) : Json(nullptr);
        const Json& expected = case_json.at("expected");
        check_diff(expected.is_null() ? Json(nullptr) : expected, actual,
                   "xml_well_log/" + name);
    }
}

void test_image_validators(const Json& fixture) {
    for (const auto& case_json : fixture.at("image_validators")) {
        std::string name = case_json.at("name").get<std::string>();
        std::string raw = b64_decode(case_json.at("bytes_b64").get<std::string>());
        const std::string& kind = case_json.at("kind").get<std::string>();
        std::optional<size_t> end;
        size_t start = raw.find(kind == "png" ? "\x89PNG\r\n\x1a\n" : "\xff\xd8");
        if (start != std::string::npos) {
            end = kind == "png" ? validated_png_range(raw, start)
                                : validated_jpeg_range(raw, start);
        }
        Json actual;
        if (end) {
            Json range = Json::array();
            range.push_back(start);
            range.push_back(*end);
            actual["expected_range"] = range;
            actual["expected_bytes"] = b64_encode(raw.substr(start, *end - start));
        } else {
            actual["expected_range"] = nullptr;
            actual["expected_bytes"] = nullptr;
        }
        Json expected;
        expected["expected_range"] = case_json.at("expected_range");
        expected["expected_bytes"] = case_json.at("expected_bytes");
        check_diff(expected, actual, "image_validators/" + name);
    }
}

void test_office(const Json& fixture) {
    std::string tmp = g_tmp;
    const Json& groups = fixture.at("office");
    for (auto group_it = groups.begin(); group_it != groups.end(); ++group_it) {
        const std::string& group = group_it.key();
        for (const auto& case_json : group_it.value()) {
            std::string name = case_json.at("name").get<std::string>();
            std::string raw = b64_decode(case_json.at("bytes_b64").get<std::string>());
            std::string fmt = case_json.value("fmt", group);
            std::string filename = "case." + fmt;
            std::string path = tmp + "/" + filename;
            write_file(path, raw);
            ResourceRef res;
            res.id = "res-oracle";
            res.name = filename;
            res.path = path;
            res.type = "archive";
            res.format = fmt;
            res.status = "indexed";
            res.revision.present = true;
            res.revision.has_stat = true;
            res.revision.stat_size = static_cast<long long>(raw.size());
            PreviewResult r;
            if (fmt == "zip") {
                int max_rows =
                    case_json.value("max_rows", kMaxArchiveNames);
                r = zip_preview(res, raw, max_rows);
            } else if (fmt == "pptx") {
                res.type = "document";
                r = pptx_preview(res, raw);
            } else if (fmt == "wlp") {
                res.type = "well_reference";
                r = wlp_preview(res);
            } else if (fmt == "dfb") {
                res.type = "reference_map";
                std::vector<std::pair<std::string, std::string>> siblings;
                for (auto it = case_json.at("extra_files").begin();
                     it != case_json.at("extra_files").end(); ++it) {
                    write_file(tmp + "/" + it.key(),
                               b64_decode(it.value().get<std::string>()));
                    siblings.emplace_back(it.key(),
                                          b64_decode(it.value().get<std::string>()));
                }
                r = dfb_preview(res, raw, siblings);
            }
            check_diff(case_json.at("expected"), project_result(r, true),
                       "office." + group + "/" + name);
        }
    }
}

void test_registry(const Json& fixture) {
    std::string tmp = g_tmp;
    for (const auto& case_json : fixture.at("registry")) {
        std::string name = case_json.at("name").get<std::string>();
        std::string path;
        std::string raw;
        if (!case_json.at("bytes_b64").is_null()) {
            raw = b64_decode(case_json.at("bytes_b64").get<std::string>());
            path = tmp + "/" + case_json.at("filename").get<std::string>();
            write_file(path, raw);
        }
        ResourceRef res;
        res.id = "res-oracle";
        res.name = case_json.at("filename").get<std::string>();
        res.type = case_json.at("type").get<std::string>();
        res.format = case_json.at("format").get<std::string>();
        res.status = case_json.at("status").get<std::string>();
        if (case_json.at("checksum").is_string()) {
            res.checksum = case_json.at("checksum").get<std::string>();
        }
        if (res.path.empty()) {
            res.path = tmp + "/" + case_json.at("filename").get<std::string>();
        }
        std::optional<std::string> project_root;
        std::vector<std::pair<std::string, std::string>> siblings;
        if (case_json.at("project_root").get<bool>()) {
            std::string pr = tmp + "/projroot";
            std::filesystem::create_directories(pr);
            project_root = pr;
            for (auto it = case_json.at("project_files").begin();
                 it != case_json.at("project_files").end(); ++it) {
                std::string dest = pr + "/" + it.key();
                std::filesystem::create_directories(
                    std::filesystem::path(dest).parent_path());
                write_file(dest, b64_decode(it.value().get<std::string>()));
            }
        }
        if (!case_json.at("resource_path").is_null()) {
            res.path = case_json.at("resource_path").get<std::string>();
        }
        PreviewResult r = build_preview(res, PreviewSettings::defaults(),
                                        project_root, siblings);
        Json actual = project_result(r, true);
        Json expected = case_json.at("expected");
        // machine paths: substitute our tmp for the generator's <TMP> marker
        std::string expected_str = replace_all(expected.dump(), "<TMP>", tmp);
        Json expected_local = Json::parse(expected_str);
        check_diff(expected_local, actual, "registry/" + name);
    }
}

void test_artifact_and_revision(const Json& fixture) {
    std::string tmp = g_tmp;
    std::string out_path = tmp + "/map.png";  // must not exist (oracle ran before any map.png)
    Json artifact = project_result(
        artifact_preview(out_path, "png", "map_1"), true);
    check_diff(fixture.at("artifact_preview"), artifact, "artifact_preview");

    ResourceRef res;
    res.id = "res-fixed";
    res.name = "f.txt";
    res.path = tmp + "/f.txt";
    res.type = "document";
    res.format = "txt";
    res.status = "indexed";
    res.checksum = "ck";
    Revision rev = resource_revision_token(res, true, 12, 100);
    Json actual = revision_json(rev);
    Json expected = Json::array();
    const Json& head = fixture.at("revision_token").at("expected_head");
    for (const auto& part : head) expected.push_back(part);
    Json stat = Json::array();
    stat.push_back("stat");
    stat.push_back(jint(fixture.at("revision_token").at("stat").at(0).get<long long>()));
    expected.push_back(stat);
    check_diff(expected, actual, "revision_token");
}

void test_preview_settings(const Json& fixture) {
    const Json& group = fixture.at("preview_settings");
    PreviewSettings defaults = PreviewSettings::defaults();
    check(defaults.fingerprint() ==
              group.at("defaults_fingerprint").get<std::string>(),
          "preview_settings/defaults_fingerprint");
    ++g_cases;
    // defaults_mapping values
    const Json& mapping = group.at("defaults_mapping");
    std::map<std::string, std::string> actual_defaults;
    actual_defaults["auto_fit_columns"] = defaults.auto_fit_columns ? "true" : "false";
    actual_defaults["density"] = defaults.density;
    actual_defaults["font_size"] = std::to_string(defaults.font_size);
    actual_defaults["geotiff_thumbnail_px"] = std::to_string(defaults.geotiff_thumbnail_px);
    actual_defaults["geoviz_max_curves"] = std::to_string(defaults.geoviz_max_curves);
    actual_defaults["geoviz_max_depth_samples"] = std::to_string(defaults.geoviz_max_depth_samples);
    actual_defaults["geoviz_max_points"] = std::to_string(defaults.geoviz_max_points);
    actual_defaults["geoviz_max_slice_axis"] = std::to_string(defaults.geoviz_max_slice_axis);
    actual_defaults["geoviz_surface_grid_size"] = std::to_string(defaults.geoviz_surface_grid_size);
    actual_defaults["json_array_collapse_threshold"] = std::to_string(defaults.json_array_collapse_threshold);
    actual_defaults["json_expand_depth"] = std::to_string(defaults.json_expand_depth);
    actual_defaults["json_limit_mib"] = std::to_string(defaults.json_limit_mib);
    actual_defaults["media_autoplay"] = defaults.media_autoplay ? "true" : "false";
    actual_defaults["media_volume"] = std::to_string(defaults.media_volume);
    actual_defaults["pdf_fit_mode"] = defaults.pdf_fit_mode;
    actual_defaults["pdf_zoom_percent"] = std::to_string(defaults.pdf_zoom_percent);
    actual_defaults["show_geo_metadata"] = defaults.show_geo_metadata ? "true" : "false";
    actual_defaults["show_metadata"] = defaults.show_metadata ? "true" : "false";
    actual_defaults["smooth_images"] = defaults.smooth_images ? "true" : "false";
    actual_defaults["table_max_columns"] = std::to_string(defaults.table_max_columns);
    actual_defaults["table_max_rows"] = std::to_string(defaults.table_max_rows);
    actual_defaults["text_limit_kib"] = std::to_string(defaults.text_limit_kib);
    actual_defaults["theme_mode"] = defaults.theme_mode;
    actual_defaults["wrap_text"] = defaults.wrap_text ? "true" : "false";
    for (auto it = mapping.begin(); it != mapping.end(); ++it) {
        const Json& v = it.value();
        std::string actual_value;
        if (v.is_boolean()) actual_value = v.get<bool>() ? "true" : "false";
        else if (v.is_string()) actual_value = v.get<std::string>();
        else if (v.is_number_integer()) actual_value = std::to_string(v.get<long long>());
        check(actual_defaults[it.key()] == actual_value,
              "preview_settings/defaults_mapping/" + it.key());
        ++g_cases;
    }
    for (const auto& case_json : group.at("cases")) {
        std::string error;
        PreviewSettings s = settings_from_case(case_json.at("values"), &error);
        Json actual;
        actual["expect_error"] = error.empty() ? Json(nullptr) : Json(error);
        if (error.empty()) {
            actual["fingerprint"] = s.fingerprint();
        } else {
            actual["fingerprint"] = nullptr;
        }
        Json expected;
        expected["expect_error"] = case_json.at("expect_error");
        expected["fingerprint"] = case_json.at("fingerprint");
        check_diff(expected, actual,
                   "preview_settings/case:" + case_json.at("values").dump());
        if (case_json.contains("from_mapping_font_size")) {
            check(s.font_size ==
                      case_json.at("from_mapping_font_size").get<int>(),
                  "preview_settings/from_mapping_font_size");
            check(s.table_max_rows ==
                      case_json.at("from_mapping_table_max_rows").get<int>(),
                  "preview_settings/from_mapping_table_max_rows");
        }
    }
}

void test_shlex(const Json& fixture) {
    for (const auto& case_json : fixture.at("shlex")) {
        auto tokens = shlex_split(case_json.at("input").get<std::string>());
        Json actual;
        if (tokens) {
            actual["expected"] = *tokens;
            actual["error"] = nullptr;
        } else {
            actual["expected"] = nullptr;
            actual["error"] = "ValueError";
        }
        Json expected;
        expected["expected"] = case_json.at("expected").is_null()
                                   ? Json(nullptr)
                                   : case_json.at("expected");
        expected["error"] = case_json.at("error").is_null()
                                ? Json(nullptr)
                                : Json("ValueError");
        check_diff(expected, actual,
                   "shlex/" + case_json.at("input").get<std::string>());
    }
}

void test_markdown_direct(const Json& fixture) {
    for (const auto& case_json : fixture.at("markdown_direct")) {
        std::string got =
            markdown_to_html(case_json.at("input").get<std::string>());
        check_diff(case_json.at("expected"), Json(got),
                   "markdown_direct/" + case_json.at("input").get<std::string>());
    }
}

void test_format_size(const Json& fixture) {
    for (const auto& pair : fixture.at("format_size")) {
        const Json& input = pair.at(0);
        std::string got = input.is_null() ? format_size(-1)
                                          : format_size(input.get<long long>());
        check_diff(pair.at(1), Json(got), "format_size");
    }
}

// #1386 — Unicode whitespace parity for the float/strip primitives. The
// well_tops oracle cases cover py_split; these pin the same predicate where
// the separators are embedded INSIDE the token (float() strips them, Python
// accepts NBSP/ideographic space padding).
void test_py_compat_unicode_space() {
    ++g_cases;
    const auto padded = py_parse_float("\xC2\xA0\xC2\xA0" "300.0" "\xE3\x80\x80");
    check(padded.has_value() && *padded == 300.0,
          "py_parse_float must strip NBSP + U+3000 like Python float()");
    ++g_cases;
    check(py_strip("\xE3\x80\x80" "abc" "\xC2\xA0") == "abc",
          "py_strip U+3000/NBSP edges");
    ++g_cases;
    // Full str.isspace() membership: NEL (U+0085) and FS/GS/RS/US
    // (0x1C-0x1F) are Python whitespace too.
    check(py_strip("\xC2\x85" "abc" "\x1C\x1F") == "abc",
          "py_strip NEL + FS/US edges (str.isspace members)");
    ++g_cases;
    const auto nel = py_parse_float("\xC2\x85" "7.5" "\x1E");
    check(nel.has_value() && *nel == 7.5,
          "py_parse_float must strip NEL + RS like Python float()");
}


void iter_walk_survives_deep_nesting() {
    // CP5: hostile deeply-nested XML used to recurse in the descendant
    // walk AND destruct the tree recursively — both overflow the stack.
    // The walk is iterative now and the parser fails closed beyond 4096
    // levels (the tree destructor is bounded with it).
    const char* open = "<a>";
    const char* close_tag = "</a>";
    auto make = [](int depth) {
        std::string xml;
        xml.reserve(static_cast<std::size_t>(depth) * 8);
        for (int i = 0; i < depth; ++i) xml += "<a>";
        for (int i = 0; i < depth; ++i) xml += "</a>";
        return xml;
    };

    // Within the cap: parse + full iterative walk.
    {
        const std::string xml = make(3000);
        pwb::ingest::XmlScanner scanner(/*forbid_entities=*/true);
        scanner.feed(xml);
        scanner.mark_end();
        pwb::ingest::XmlScanner::Event event;
        pwb::ingest::XmlScanner::Attributes attrs;
        const XmlNode* ended = nullptr;
        const XmlNode* last_end = nullptr;
        while (scanner.next(event, attrs, ended)) {
            if (event == pwb::ingest::XmlScanner::Event::End) last_end = ended;
        }
        check(last_end != nullptr, "deep (in-cap) document parsed");
        std::unique_ptr<XmlNode> root = scanner.take_root();
        check(root != nullptr, "root taken");
        std::vector<const XmlNode*> all;
        root->iter(all);
        check(static_cast<int>(all.size()) == 3000,
              "iterative walk visits every node");
    }

    // Beyond the cap: fail closed, never a stack overflow.
    {
        const std::string xml = make(2000000);
        pwb::ingest::XmlScanner scanner(/*forbid_entities=*/true);
        scanner.feed(xml);
        scanner.mark_end();
        pwb::ingest::XmlScanner::Event event;
        pwb::ingest::XmlScanner::Attributes attrs;
        const XmlNode* ended = nullptr;
        bool stopped = false;
        while (scanner.next(event, attrs, ended)) {
        }
        stopped = scanner.failed();
        check(stopped, "2M-deep hostile nesting fails closed (depth cap)");
    }
}

}  // namespace

template <typename F>
void run_group(const char* name, F&& fn) {
    try {
        fn();
    } catch (const std::exception& e) {
        fail(std::string(name) + " threw: " + e.what());
    }
}


int main() {
    run_group("iter_walk_survives_deep_nesting", iter_walk_survives_deep_nesting);
    g_tmp = make_tmp_dir();
    Json fixture = load_fixture();
    run_group("test_constants", [&] { test_constants(fixture); });
    run_group("test_well_tops", [&] { test_well_tops(fixture); });
    run_group("test_well_location_xml", [&] { test_well_location_xml(fixture); });
    run_group("test_well_log_xml", [&] { test_well_log_xml(fixture); });
    run_group("test_classifier", [&] { test_classifier(fixture); });
    run_group("test_project_paths", [&] { test_project_paths(fixture); });
    run_group("test_previews", [&] { test_previews(fixture); });
    run_group("test_spreadsheetml", [&] { test_spreadsheetml(fixture); });
    run_group("test_xml_well_log", [&] { test_xml_well_log(fixture); });
    run_group("test_image_validators", [&] { test_image_validators(fixture); });
    run_group("test_office", [&] { test_office(fixture); });
    run_group("test_artifact_and_revision", [&] { test_artifact_and_revision(fixture); });
    run_group("test_registry", [&] { test_registry(fixture); });
    run_group("test_preview_settings", [&] { test_preview_settings(fixture); });
    run_group("test_shlex", [&] { test_shlex(fixture); });
    run_group("test_markdown_direct", [&] { test_markdown_direct(fixture); });
    run_group("test_format_size", [&] { test_format_size(fixture); });
    run_group("test_py_compat_unicode_space",
              [] { test_py_compat_unicode_space(); });

    std::printf("ingest.parsers: %d comparisons, %d failures\n", g_cases,
                g_failures);
    return g_failures == 0 ? 0 : 1;
}
