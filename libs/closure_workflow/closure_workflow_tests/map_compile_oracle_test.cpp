// Frozen-oracle replay for map_compile.cpp vs
// paleo_workbench/pipeline/compile_map{,_production}.py.
//
// Cases (tools/oracle/generate_map_compile_oracle.py): deterministic
// demo-draft geometry (incl. Python % on negative seeds), idempotent
// demo-doc replacement, well-overlay fallbacks, the production
// fail-closed gate matrix (verbatim error classes/messages), model-trust
// resolution, _versions_for_domain_tasks input lineage (latest complete
// run, trashed outputs excluded), and lineage-first registration with
// the RUNNING → complete / → failed bookkeeping.
//
// The recording catalog mirrors the generator's double: sequential
// "run_000001" ids shared across register calls, sha256 over the payload
// bytes, seeded run/version state for input resolution.

#include <pwb/closure_workflow/map_compile.hpp>
#include <pwb/domain/json.hpp>
#include <pwb/domain/sha256.hpp>
#include <pwb/workflow_runtime/catalog_seam.hpp>

#include <cctype>
#include <cstdio>
#include <fstream>
#include <iostream>
#include <map>
#include <optional>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

using pwb::domain::Json;
using pwb::closure_workflow::ModelVersionTrust;
using pwb::closure_workflow::ProductionMapCompileOptions;
using pwb::closure_workflow::ProductionMapError;
using pwb::workflow_runtime::AssetRecord;
using pwb::workflow_runtime::RegisteredAssetVersion;
using pwb::workflow_runtime::RunRecord;
using pwb::workflow_runtime::VersionRecord;

int failures = 0;
int checks = 0;

Json read_fixture(const char* path) {
    std::ifstream in(path);
    if (!in) throw std::runtime_error(std::string("cannot open: ") + path);
    Json data;
    in >> data;
    return data;
}

void canonicalize_ints(Json& node) {
    if (node.is_number_integer() && !node.is_number_float()) {
        node = Json(static_cast<std::uint64_t>(node.get<std::int64_t>()));
        return;
    }
    if (node.is_object()) {
        for (auto it = node.begin(); it != node.end(); ++it) {
            canonicalize_ints(*it);
        }
    } else if (node.is_array()) {
        for (auto it = node.begin(); it != node.end(); ++it) {
            canonicalize_ints(*it);
        }
    }
}

// The failed-run `error` parameter records "ClassName: message" on both
// sides — Python class names (RuntimeError/KeyError) vs the C++ mapping
// (std::exception) differ, so compare the message tail. The prefix gate
// accepts identifier chars + "::" qualifiers; a message containing
// ": " with a non-identifier head (e.g. the Chinese prefixes) is left
// intact.
std::string error_tail(std::string text) {
    const std::size_t sep = text.find(": ");
    if (sep != std::string::npos && sep > 0) {
        bool looks_like_class =
            std::isalpha(static_cast<unsigned char>(text[0])) ||
            text[0] == '_';
        for (std::size_t i = 1; i < sep && looks_like_class; ++i) {
            const char c = text[i];
            if (!std::isalnum(static_cast<unsigned char>(c)) &&
                c != '_' && c != '.' && c != ':') {
                looks_like_class = false;
            }
        }
        if (looks_like_class) text = text.substr(sep + 2);
    }
    return text;
}

void normalize_catalog(Json& out) {
    if (!out.is_object()) return;
    const auto cat = out.find("catalog");
    if (cat == out.end() || !cat->is_object()) return;
    Json* runs = nullptr;
    const auto it = cat->find("runs");
    if (it != cat->end() && it->is_array()) runs = &*it;
    if (runs == nullptr) return;
    for (Json& run : *runs) {
        const auto ep = run.find("extra_parameters");
        if (ep == run.end() || !ep->is_object()) continue;
        const auto err = ep->find("error");
        if (err != ep->end() && err->is_string()) {
            *err = error_tail(err->get<std::string>());
        }
    }
}

void check(const std::string& id, bool ok, const std::string& detail = "") {
    ++checks;
    if (!ok) {
        ++failures;
        std::printf("FAIL %s%s%s\n", id.c_str(), detail.empty() ? "" : ": ",
                    detail.c_str());
    }
}

void check_json(const std::string& id, Json got, Json expect) {
    canonicalize_ints(got);
    canonicalize_ints(expect);
    normalize_catalog(got);
    normalize_catalog(expect);
    const bool ok = pwb::domain::json_semantically_equal(got, expect);
    std::string detail;
    if (!ok) {
        const auto diff =
            pwb::domain::json_semantic_diff(got, expect);
        detail = diff.path + " (" + diff.reason + ") got=" +
                 got.dump().substr(0, 400) + " expect=" +
                 expect.dump().substr(0, 400);
        if (diff.path.find("sha256") != std::string::npos) {
            const Json& gv = got.at("catalog").at("versions").back();
            const Json& ev = expect.at("catalog").at("versions").back();
            const std::string gs = gv.value("payload_text", "");
            const std::string es = ev.value("payload_text", "");
            std::size_t k = 0;
            while (k < gs.size() && k < es.size() && gs[k] == es[k]) ++k;
            detail += " | first-byte-diff@" + std::to_string(k) +
                      " got…" + gs.substr(k, 80) + "… expect…" +
                      es.substr(k, 80) + "…";
        }
    }
    check(id, ok, detail);
}

// ---------------------------------------------------------------- catalog --

std::string pad6(int n) {
    char buf[16];
    std::snprintf(buf, sizeof buf, "%06d", n);
    return buf;
}

class FakeCatalog : public pwb::workflow_runtime::CatalogRepository {
public:
    explicit FakeCatalog(const Json& seed) {
        const Json seed_runs = seed.value("runs", Json::array());
        for (const Json& r : seed_runs) {
            RunRecord record;
            record.run_id = r.value("id", std::string());
            if (r.contains("domain_task_id") && !r.at("domain_task_id").is_null()) {
                record.domain_task_id =
                    r.at("domain_task_id").get<std::string>();
            }
            record.status = r.value("status", std::string("complete"));
            for (const Json& v : r.value("output_version_ids", Json::array())) {
                record.output_version_ids.push_back(v.get<std::string>());
            }
            for (const Json& v : r.value("input_version_ids", Json::array())) {
                record.input_version_ids.push_back(v.get<std::string>());
            }
            run_records_.push_back(record);
        }
        for (const Json& v : seed.value("versions", Json::array())) {
            VersionRecord record;
            record.version_id = v.value("id", std::string());
            record.trashed = v.value("trashed", false);
            version_records_[record.version_id] = record;
            frozen_seed_versions_.push_back(
                Json::object({{"id", record.version_id},
                              {"trashed", record.trashed}}));
        }
        model_versions_ = seed.value("model_versions", Json::object());
        fail_output_ = seed.value("fail_output", false);
    }

    bool fail_output_ = false;
    int seq = 0;
    Json registered_runs_ = Json::array();
    Json assets_ = Json::array();
    Json versions_ = Json::array();
    Json model_versions_ = Json::object();

    // -- reads (seed state only — the Python double's list_runs returns
    //    the seeds; registrations land in the freeze below) -------------
    std::vector<AssetRecord> list_assets() override { return {}; }
    std::optional<AssetRecord> resolve_asset(
        const std::string&) override {
        return std::nullopt;
    }
    std::vector<VersionRecord> list_versions(
        const std::string&) override {
        return {};
    }
    std::vector<RunRecord> list_runs() override { return run_records_; }
    std::optional<RunRecord> resolve_run(
        const std::string&) override {
        return std::nullopt;
    }
    std::optional<VersionRecord> resolve_version(
        const std::string& version_id) override {
        const auto it = version_records_.find(version_id);
        if (it == version_records_.end()) return std::nullopt;
        return it->second;
    }

    // -- writes -------------------------------------------------------------
    std::string register_run(
        const std::string& operation,
        const std::vector<std::string>& input_version_ids,
        const Json& parameters,
        const std::optional<std::string>& generator,
        const std::string& status,
        const std::optional<std::string>& = std::nullopt,
        const std::optional<std::string>& = std::nullopt,
        const std::optional<std::string>& = std::nullopt) override {
        ++seq;
        Json run = Json::object();
        run["id"] = "run_" + pad6(seq);
        run["operation"] = operation;
        run["input_version_ids"] = input_version_ids;
        run["parameters"] = parameters;
        run["generator"] =
            generator.has_value() ? Json(*generator) : Json(nullptr);
        run["status"] = status;
        registered_runs_.push_back(std::move(run));
        return registered_runs_.back()["id"].get<std::string>();
    }

    RegisteredAssetVersion register_result_asset(
        const std::string& name, const std::string& type,
        const std::string& format, const Json& asset_metadata,
        const std::string& payload_json, const std::string& stage,
        const std::string& run_id, const Json& version_metadata) override {
        if (fail_output_) {
            throw std::runtime_error("catalog write refused");
        }
        ++seq;
        Json asset = Json::object();
        asset["id"] = "asset_" + pad6(seq);
        asset["name"] = name;
        asset["type"] = type;
        asset["format"] = format;
        asset["asset_metadata"] = asset_metadata;
        assets_.push_back(std::move(asset));
        Json version = Json::object();
        version["id"] = "ver_" + pad6(seq);
        version["asset_id"] = assets_.back()["id"];
        version["name"] = name;
        version["stage"] = stage;
        version["run_id"] = run_id;
        version["sha256"] = pwb::domain::Sha256::of_bytes(payload_json);
        version["version_metadata"] = version_metadata;
        version["payload_text"] = payload_json;
        version["payload"] = Json::parse(payload_json);
        versions_.push_back(std::move(version));
        return {assets_.back()["id"].get<std::string>(),
                versions_.back()["id"].get<std::string>()};
    }

    std::string register_version(const std::string&,
                                 const std::string&, const std::string&,
                                 const std::vector<std::string>&,
                                 const std::string&,
                                 const Json&) override {
        throw std::runtime_error("register_version not used");
    }

    void update_run_status(const std::string& run_id,
                           const std::string& status) override {
        update_run_status(run_id, status, Json(nullptr));
    }
    void update_run_status(const std::string& run_id,
                           const std::string& status,
                           const Json& extra_parameters) override {
        for (Json& run : registered_runs_) {
            if (run.at("id").get<std::string>() == run_id) {
                run["status"] = status;
                if (!extra_parameters.is_null()) {
                    run["extra_parameters"] = extra_parameters;
                }
                return;
            }
        }
        throw std::runtime_error("unknown run " + run_id);
    }

    void attach_run_output(const std::string&,
                           const std::string&) override {}
    void set_current_version(const std::string&,
                             const std::string&) override {}
    std::optional<std::string> verify_integrity(
        const std::string&) override {
        return std::nullopt;
    }

    // The frozen catalog view: seeds first (normalised dict shape —
    // the Python double emits all five keys), then registrations.
    Json freeze() const {
        Json catalog = Json::object();
        Json runs = Json::array();
        for (const RunRecord& r : run_records_) {
            Json entry = Json::object();
            entry["id"] = r.run_id;
            entry["domain_task_id"] =
                r.domain_task_id.has_value() ? Json(*r.domain_task_id)
                                             : Json(nullptr);
            entry["status"] = r.status;
            entry["output_version_ids"] = r.output_version_ids;
            entry["input_version_ids"] = r.input_version_ids;
            runs.push_back(std::move(entry));
        }
        for (const Json& r : registered_runs_) runs.push_back(r);
        catalog["runs"] = std::move(runs);
        catalog["assets"] = assets_;
        Json versions = Json::array();
        for (const Json& v : frozen_seed_versions_) versions.push_back(v);
        for (const Json& v : versions_) versions.push_back(v);
        catalog["versions"] = std::move(versions);
        return catalog;
    }

private:
    std::vector<RunRecord> run_records_;
    std::map<std::string, VersionRecord> version_records_;
    Json frozen_seed_versions_ = Json::array();
};

// ------------------------------------------------------------- replay ------

// Owned storage for the payload pointer inside ProductionMapCompileOptions.
Json owned_payload_;

// Deterministic doc ids matching the generator's patched _id (the counter
// is process-global there, so the test keeps one counter across all cases
// replayed in fixture order).
struct FrozenIds {
    int next = 0;
    std::string operator()(std::string_view prefix) {
        ++next;
        char buf[32];
        std::snprintf(buf, sizeof buf, "_fix%04d", next);
        return std::string(prefix) + buf;
    }
};

std::optional<std::string> opt_str(const Json& obj, const char* key) {
    const auto it = obj.find(key);
    if (it == obj.end() || it->is_null()) return std::nullopt;
    return it->get<std::string>();
}

void replay_case(const Json& c, FrozenIds& ids) {
    const std::string name = c.at("name").get<std::string>();
    Json root = c.value("project", Json::object());
    const Json opts = c.value("options", Json::object());
    const Json expect = c.at("expect");

    const bool is_production = name.rfind("production.", 0) == 0;
    Json got = Json::object();
    std::string error_class;
    std::string error_message;

    std::unique_ptr<FakeCatalog> catalog;
    ProductionMapCompileOptions popts;
    if (is_production) {
        popts.target_horizon = opt_str(opts, "target_horizon");
        popts.prediction_task_id = opt_str(opts, "prediction_task_id");
        Json payload = opts.value("prediction_payload", Json(nullptr));
        if (!payload.is_null()) {
            owned_payload_ = std::move(payload);
            popts.prediction_payload = &owned_payload_;
        }
        popts.map_crs = opt_str(opts, "map_crs");
        popts.prediction_version_id =
            opt_str(opts, "prediction_version_id");
        popts.allow_demo_task = opts.value("allow_demo_task", false);
        if (c.contains("catalog_seed") && !c.at("catalog_seed").is_null()) {
            catalog = std::make_unique<FakeCatalog>(c.at("catalog_seed"));
            popts.catalog = catalog.get();
            const bool has_verifier =
                c.at("catalog_seed").value("has_verifier", true);
            if (has_verifier) {
                popts.model_version_resolver =
                    [&catalog](const std::string& id)
                    -> std::optional<ModelVersionTrust> {
                    const auto it = catalog->model_versions_.find(id);
                    if (it == catalog->model_versions_.end()) {
                        // KeyError parity: str(KeyError('x')) == "'x'".
                        throw std::runtime_error("'" + id + "'");
                    }
                    ModelVersionTrust trust;
                    trust.status =
                        it->value("status", std::string());
                    trust.demo_only = it->value("demo_only", false);
                    return trust;
                };
            }
        }
        popts.make_id = [&ids](std::string_view prefix) {
            return ids(prefix);
        };
    }

    try {
        Json doc;
        if (is_production) {
            doc = pwb::closure_workflow::compile_map_production(root, popts);
        } else {
            doc = pwb::closure_workflow::compile_map_draft(
                root, opt_str(opts, "target_horizon"),
                opt_str(opts, "prediction_task_id"),
                opts.value("seed", 0),
                [&ids](std::string_view prefix) { return ids(prefix); });
        }
        got["doc"] = doc;
        got["documents"] = root.value("paleomap_documents", Json::array());
        const Json* runs =
            root.contains("compilation_runs") &&
                    root["compilation_runs"].is_array() &&
                    !root["compilation_runs"].empty()
                ? &root["compilation_runs"].back()
                : nullptr;
        got["active_id"] =
            runs != nullptr && runs->contains("active_paleomap_document_id")
                ? (*runs)["active_paleomap_document_id"]
                : Json(nullptr);
        if (is_production) {
            got["catalog"] =
                catalog ? catalog->freeze() : Json(nullptr);
        }
    } catch (const ProductionMapError& exc) {
        error_class = "ProductionMapError";
        error_message = exc.what();
    } catch (const std::out_of_range& exc) {
        // KeyError analogue — the uncaught feat["geometry"] path.
        error_class = "KeyError";
        error_message = exc.what();
    } catch (const std::exception& exc) {
        error_class = "Exception";
        error_message = exc.what();
    }

    if (!error_class.empty()) {
        Json err = Json::object();
        err["class"] = error_class;
        err["message"] = error_message;
        got = Json::object();
        got["error"] = std::move(err);
        if (is_production) {
            got["catalog"] =
                catalog ? catalog->freeze() : Json(nullptr);
        }
    }

    check_json(name, got, expect);
}

}  // namespace

int main(int argc, char** argv) {
    if (argc < 2) {
        std::fprintf(stderr, "usage: %s <map_compile_oracle.json>\n",
                     argv[0]);
        return 2;
    }
    const Json fixture = read_fixture(argv[1]);
    FrozenIds ids;
    for (const Json& c : fixture.at("cases")) {
        try {
            replay_case(c, ids);
        } catch (const std::exception& exc) {
            check(c.value("name", std::string("?")) + ".harness", false,
                  exc.what());
        }
    }
    std::printf("map_compile_oracle: %d checks, %d failure(s)\n", checks,
                failures);
    return failures == 0 ? 0 : 1;
}
