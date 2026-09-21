// import_service + scanner oracle replay — resources/import_service.py and
// resources/scanner.py parity over a deterministic fixture tree.

#include <cstdio>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>

#include <pwb/domain/json.hpp>
#include <pwb/ui_data_core/facies_groups.hpp>
#include <pwb/ui_data_core/import_service.hpp>
#include <pwb/ui_data_core/scanner.hpp>

using pwb::domain::Json;
using namespace pwb::ui_data_core;
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

void write_bytes(const fs::path& path, const std::string& bytes) {
    fs::create_directories(path.parent_path());
    std::ofstream out(path, std::ios::binary | std::ios::trunc);
    out << bytes;
}

std::string hex_decode(const std::string& hex) {
    std::string out;
    for (std::size_t i = 0; i + 1 < hex.size(); i += 2)
        out.push_back(
            static_cast<char>(std::stoi(hex.substr(i, 2), nullptr, 16)));
    return out;
}

// Normalize an item: path → tree-relative when absolute.
Json item_json(const ResourceItem& r, const fs::path& tree) {
    Json j = Json::object();
    std::string path = r.path;
    if (fs::path(path).is_absolute()) {
        std::error_code ec;
        const auto rel = fs::relative(path, tree, ec);
        path = ec ? fs::path(path).filename().string()
                  : rel.generic_string();
    }
    j["path"] = path;
    j["name"] = r.name;
    j["type"] = r.type;
    j["format"] = r.format;
    j["status"] = r.status;
    j["source"] = r.source;
    j["external"] = r.external;
    j["checksum"] = r.checksum.has_value() ? Json(*r.checksum) : Json(nullptr);
    j["artifact_role"] = r.artifact_role.has_value() ? Json(*r.artifact_role)
                                                     : Json(nullptr);
    j["tags"] = r.tags;
    j["parsed_summary"] = r.parsed_summary;
    // facies_product_group_id digests the absolute parent dir at runtime —
    // re-key over the frozen (fixture-relative) parent for portability.
    if (j["parsed_summary"].is_object() &&
        j["parsed_summary"].contains("facies_product_group_id")) {
        if (const auto key = facies_group_key(r);
            key.has_value() && key->rfind("path:", 0) == 0) {
            const std::string stem = key->substr(key->rfind(':') + 1);
            const std::string parent =
                fs::path(path).parent_path().generic_string();
            j["parsed_summary"]["facies_product_group_id"] =
                facies_group_id(
                    "path:" + (parent.empty() ? "." : parent) + ":" + stem);
        }
    }
    return j;
}

Json report_json(const ImportReport& rep, const fs::path& tree) {
    Json j = Json::object();
    Json added = Json::array();
    for (const auto& r : rep.added) added.push_back(item_json(r, tree));
    j["added"] = added;
    auto names = [&](const std::vector<fs::path>& ps) {
        Json out = Json::array();
        for (const auto& p : ps) {
            std::error_code ec;
            const auto rel = fs::relative(p, tree, ec);
            out.push_back(ec ? p.filename().string()
                             : rel.generic_string());
        }
        return out;
    };
    j["skipped_path"] = names(rep.skipped_path);
    j["skipped_checksum"] = names(rep.skipped_checksum);
    j["skipped_filter"] = names(rep.skipped_filter);
    Json warnings = Json::array();
    for (const auto& w : rep.warnings) {
        // "<path>: <msg>" → relative path inside the tree.
        const auto pos = w.find(": ");
        if (pos != std::string::npos) {
            const fs::path head(w.substr(0, pos));
            std::error_code ec;
            const auto rel = fs::relative(head, tree, ec);
            warnings.push_back(
                (ec ? head.filename().string() : rel.generic_string()) +
                ": " + w.substr(pos + 2));
        } else {
            warnings.push_back(w);
        }
    }
    j["warnings"] = warnings;
    j["added_count"] = rep.added_count();
    j["skipped_count"] = rep.skipped_count();
    Json by_type = Json::object();
    for (const auto& [k, v] : rep.by_type()) by_type[k] = v;
    j["by_type"] = by_type;
    j["facies_product_count"] = rep.facies_product_count();
    j["summary_text"] = rep.summary_text();
    return j;
}

}  // namespace

int main() {
#ifndef PWB_IMPORT_ORACLE
    std::cout << "PWB_IMPORT_ORACLE not defined\n";
    return 2;
#endif
    std::ifstream in(PWB_IMPORT_ORACLE);
    if (!in) {
        std::cout << "cannot open " << PWB_IMPORT_ORACLE << "\n";
        return 2;
    }
    const Json oracle = Json::parse(in);

    const fs::path work = fs::temp_directory_path() / "pwb_import_oracle";
    fs::remove_all(work);
    const fs::path tree = work / "tree";
    const fs::path proj = work / "proj" / "project.pwb";
    const fs::path tree2 = proj.parent_path() / "data";

    // Materialize both trees (tree + proj/data mirror) with fixed mtimes.
    const std::set<std::string> binary_names(
        oracle["binary_names"].begin(), oracle["binary_names"].end());
    for (const auto& [rel, content] : oracle["files"].items()) {
        const std::string bytes = binary_names.count(rel)
                                      ? hex_decode(content.get<std::string>())
                                      : content.get<std::string>();
        write_bytes(tree / rel, bytes);
        write_bytes(tree2 / rel, bytes);
    }
    // Fixed mtime for deterministic isoformat probes.
    const auto target_sys = std::chrono::system_clock::from_time_t(
        oracle["mtime"].get<std::time_t>());
    const auto mtime = fs::file_time_type::clock::now() +
                       std::chrono::duration_cast<
                           fs::file_time_type::duration>(
                           target_sys - std::chrono::system_clock::now());
    for (const auto* root : {&tree, &tree2}) {
        for (const auto& entry : fs::recursive_directory_iterator(*root)) {
            fs::last_write_time(entry.path(), mtime);
        }
    }

    for (const auto& c : oracle["cases"]) {
        const std::string id = c["id"].get<std::string>();
        const std::string kind = c["kind"].get<std::string>();
        const int workers = c.value("workers", 1);
        const fs::path* proj_ptr =
            c.contains("project_path") ? &proj : nullptr;
        const fs::path& base =
            c.contains("project_path") ? tree2 : tree;

        ++checks;
        if (kind == "scan") {
            const bool skip = id == "scan.skip_checksum";
            const auto items = scan_resources(
                base, nullptr, skip ? 100 : -1, workers);
            Json got = Json::array();
            for (const auto& r : items) got.push_back(item_json(r, base));
            if (!json_eq(got, c["items"])) fail(id, got, c["items"]);
            continue;
        }

        std::vector<ResourceItem> existing;
        if (id == "folder.dedup_existing") {
            // First pass over the same tree seeds the existing set.
            const auto first =
                import_folder(base, {}, proj_ptr, {.workers = workers});
            existing = first.added;
        }

        ImportReport rep;
        if (kind == "folder") {
            rep = import_folder(
                base, existing, proj_ptr,
                {.workers = workers,
                 .preferred_only = c.value("preferred_only", false)});
        } else {
            std::vector<fs::path> paths;
            for (const auto& p : c["paths"]) {
                paths.push_back(base / p.get<std::string>());
            }
            rep = import_files(
                paths, existing, proj_ptr,
                {.workers = workers,
                 .preferred_only = c.value("preferred_only", false)});
        }
        const Json got = report_json(rep, base);
        if (!json_eq(got, c["report"])) fail(id, got, c["report"]);
    }

    std::cout << "import_oracle: " << checks << " checks, " << failures
              << " failure(s)\n";
    fs::remove_all(work);
    return failures ? 1 : 0;
}
