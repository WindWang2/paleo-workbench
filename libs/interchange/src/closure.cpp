// Implementation of closure.hpp — the line-10 composition layer. The
// sniffing vocabulary covers exactly the formats the native side can truly
// serve or verify (paleo-package containers, FLAC3D/Abaqus text); anything
// else reports honestly as undetermined/unsupported.
#include <pwb/interchange/closure.hpp>

#include <algorithm>
#include <fstream>

#include <pwb/interchange/unicode.hpp>
#include <pwb/interchange/zip_archive.hpp>

namespace pwb::interchange::closure {

namespace {

// Bridges the closure registration sink into the batch service's export
// registration port (single choke point parity with the Python executor).
class BatchRegistrationAdapter final : public IExportRegistration {
public:
    explicit BatchRegistrationAdapter(IRegistrationSink& sink) : sink_(sink) {}
    std::string register_export(const ExportPlan& plan,
                                const std::filesystem::path& output,
                                const ExportVerification& verification) override {
        return sink_.register_export(plan, output, verification);
    }

private:
    IRegistrationSink& sink_;
};

constexpr std::size_t kSniffPrefixBytes = 8192;  // registry.SNIFF_PREFIX_BYTES

double printable_ratio(const std::string_view bytes) {
    if (bytes.empty()) return 0.0;
    std::size_t printable = 0;
    for (const unsigned char c : bytes) {
        if (c == '\t' || c == '\n' || c == '\r' || (c >= 0x20 && c < 0x7f) ||
            c >= 0x80) {
            ++printable;
        }
    }
    return static_cast<double>(printable) / static_cast<double>(bytes.size());
}

std::string first_line(std::string_view text) {
    const auto newline = text.find('\n');
    if (newline != std::string_view::npos) text = text.substr(0, newline);
    while (!text.empty() && (text.back() == '\r' || text.back() == ' ')) {
        text.remove_suffix(1);
    }
    return std::string(text);
}

// Native-recognizable content sniffing (registry.sniff_format's slice this
// side can actually judge): zip family via entry names, then the text rules
// for Abaqus (high) and FLAC3D (medium, extension-qualified).
SniffResult sniff_native(const std::filesystem::path& path) {
    SniffResult result;
    std::error_code ec;
    if (!std::filesystem::is_regular_file(path, ec)) return result;

    std::ifstream stream(path, std::ios::binary);
    if (!stream) return result;
    std::string prefix(kSniffPrefixBytes, '\0');
    stream.read(prefix.data(), static_cast<std::streamsize>(prefix.size()));
    prefix.resize(static_cast<std::size_t>(stream.gcount()));

    const std::string extension = path_suffix_lower(path);

    if (prefix.size() >= 4 && prefix[0] == 'P' && prefix[1] == 'K' &&
        (prefix[2] == 3 || prefix[2] == 5 || prefix[2] == 7)) {
        try {
            ZipReader archive(path);
            for (const auto& entry : archive.infolist()) {
                if (entry.name == "manifest.json") {
                    try {
                        const std::string manifest_text =
                            archive.read_entry_bytes(entry);
                        const Json manifest =
                            Json::parse(manifest_text, nullptr, false);
                        if (!manifest.is_discarded() &&
                            manifest.value("kind", "") == "paleo-package") {
                            result.format_id = "paleo-package";
                            result.confidence = "high";
                            result.evidence = "zip 条目 manifest.json (kind=paleo-package)";
                            result.extension = extension;
                            return result;
                        }
                    } catch (const std::exception&) {
                        // Unreadable manifest: keep scanning.
                    }
                }
            }
        } catch (const std::exception&) {
            // Not a readable zip after all.
        }
        result.format_id = "zip";
        result.confidence = "low";
        result.evidence = "PK zip 头";
        result.extension = extension;
        return result;
    }

    if (printable_ratio(prefix) >= 0.9) {
        const std::string line = first_line(prefix);
        if (line.rfind("*HEADING", 0) == 0 || line.rfind("*NODE", 0) == 0) {
            result.format_id = "abaqus_inp";
            result.confidence = "high";
            result.evidence = "首行 " + line;
            result.extension = extension;
            return result;
        }
        if (line.rfind("G ", 0) == 0 && extension == "f3grid") {
            result.format_id = "flac3d_f3grid";
            result.confidence = "medium";
            result.evidence = "首行网格点记录";
            result.extension = extension;
            return result;
        }
    }
    return result;
}

// The preflight registry over the native model adapters (flac3d/abaqus —
// both import-unavailable by declared capability, exactly like Python).
Registry build_preflight_registry(const NativeInterchangeService& service) {
    Registry registry;
    for (const auto& adapter : service.capability_matrix()) {
        // capability_matrix rows carry the ids in insertion order.
        const std::string format_id = adapter.value("format_id", "");
        const ModelAdapter* resolved = service.adapter(format_id);
        if (resolved == nullptr) continue;
        AdapterSpec spec;
        spec.format_id = resolved->format_id;
        spec.display_name = resolved->display_name;
        spec.extensions = resolved->extensions;
        spec.import_data = resolved->capability().import_data;
        spec.notes = resolved->capability().notes;
        spec.inspect = [&service, format_id](const std::string& path) {
            return service.inspect(format_id, std::filesystem::path(path));
        };
        registry.register_adapter(std::move(spec));
    }
    return registry;
}

}  // namespace

// --- InterchangeClosure ------------------------------------------------------

InterchangeClosure::InterchangeClosure(InterchangeClosureConfig config,
                                       IRegistrationSink* registration)
    : config_(std::move(config)),
      registration_(registration),
      batch_registration_(registration != nullptr
                              ? std::make_unique<BatchRegistrationAdapter>(
                                    *registration)
                              : nullptr),
      batch_(std::make_unique<BatchConversionService>(
          service_, 2, batch_registration_.get())),
      plugin_loader_(plugin_registry_) {}

InterchangeClosure::~InterchangeClosure() = default;

PreflightReport InterchangeClosure::detect(const std::filesystem::path& path) const {
    Registry registry = build_preflight_registry(service_);
    ImportPreflightService preflight(std::move(registry), &sniff_native);
    try {
        return preflight.inspect(path);
    } catch (const std::exception& exc) {
        PreflightReport report;
        report.path = path.string();
        PreflightIssue issue;
        issue.severity = "error";
        issue.code = "inspect-failed";
        issue.message = exc.what();
        report.issues.push_back(std::move(issue));
        return report;
    }
}

Json InterchangeClosure::ImportOutcome::to_json() const {
    Json out = Json::object();
    out["ok"] = ok;
    out["kind"] = kind;
    out["materialized"] = materialized.string();
    out["verify"] = verify_report.to_dict();
    out["registration_id"] = registration_id;
    out["warnings"] = warnings;
    return out;
}

InterchangeClosure::ImportOutcome InterchangeClosure::import_path(
    const std::filesystem::path& path, const std::filesystem::path& dest_dir,
    const CancelToken& cancel) {
    ImportOutcome outcome;
    std::error_code ec;
    if (!std::filesystem::exists(path, ec)) {
        outcome.kind = "missing";
        outcome.warnings.push_back("路径不存在: " + path.string());
        return outcome;
    }

    // Packages are the one real import the native side performs today;
    // everything else honestly reports unsupported.
    bool looks_like_package = false;
    if (std::filesystem::is_directory(path, ec)) {
        looks_like_package =
            std::filesystem::exists(path / "manifest.json", ec);
    } else {
        const SniffResult sniff = sniff_native(path);
        looks_like_package = sniff.format_id == "paleo-package";
    }
    if (looks_like_package) {
        outcome.kind = "package";
        try {
            auto [materialized, report] = open_package(path, dest_dir, true);
            outcome.materialized = materialized;
            outcome.verify_report = std::move(report);
            outcome.ok = outcome.verify_report.ok();
            for (const auto& issue : outcome.verify_report.issues) {
                if (issue.severity != "error") {
                    outcome.warnings.push_back(issue.code + ": " + issue.message);
                }
            }
            if (outcome.ok && registration_ != nullptr) {
                ImportPlan plan;
                plan.format_id = "paleo-package";
                plan.source_path = path.string();
                plan.action = "managed_copy";
                plan.asset_name = materialized.filename().string();
                outcome.registration_id =
                    registration_->register_import(plan, materialized);
            }
            cancel.checkpoint();
            return outcome;
        } catch (const CancelledError&) {
            throw;
        } catch (const std::exception& exc) {
            // Unsafe/undecipherable container: fail closed with the reason.
            outcome.ok = false;
            outcome.warnings.push_back(exc.what());
            return outcome;
        }
    }

    // Not a package: run the preflight decision tree and report honestly.
    const PreflightReport report = detect(path);
    outcome.kind = "unsupported";
    for (const auto& issue : report.issues) {
        outcome.warnings.push_back(issue.severity + "/" + issue.code + ": " +
                                   issue.message);
    }
    outcome.warnings.push_back("recommendation: " + report.recommendation);
    if (!report.adapter_id.has_value() || report.recommendation == "unavailable") {
        outcome.warnings.push_back(
            "当前原生版本未提供该格式的导入适配（仅导出/交付路径可用）");
    }
    return outcome;
}

Json InterchangeClosure::ExportOutcome::to_json() const {
    Json out = Json::object();
    out["ok"] = ok;
    out["output"] = output.string();
    out["verification"] = verification.summary();
    out["registration_id"] = registration_id;
    out["plan"] = plan_json;
    out["warnings"] = warnings;
    return out;
}

InterchangeClosure::ExportOutcome InterchangeClosure::export_as(
    const std::filesystem::path& source, const std::string& format_id,
    const std::filesystem::path& target, Json options, const CancelToken& cancel) {
    ExportOutcome outcome;
    ExportPlan plan = service_.plan_export(format_id, source, target,
                                           std::move(options));
    outcome.plan_json = plan.to_dict();
    outcome.output = service_.export_data(plan, cancel);
    outcome.verification = service_.verify_output(outcome.output, plan);
    outcome.ok = outcome.verification.ok();
    if (outcome.ok && registration_ != nullptr) {
        plan.target_path = outcome.output.string();
        try {
            outcome.registration_id =
                registration_->register_export(plan, outcome.output,
                                               outcome.verification);
        } catch (const std::exception& exc) {
            // 登记失败追加 warning 不改结果。
            outcome.warnings.push_back(std::string("输出登记失败: ") + exc.what());
        }
    }
    return outcome;
}

DeliveryResult InterchangeClosure::build_delivery(
    const std::string& profile_id, const std::filesystem::path& output_dir,
    ILinkableCatalog* catalog, const CancelToken& cancel) const {
    return build_delivery_profile(get_profile(profile_id), output_dir, catalog,
                                  cancel);
}

DeliveryResult InterchangeClosure::build_delivery_profile(
    const DeliveryProfile& profile, const std::filesystem::path& output_dir,
    ILinkableCatalog* catalog, const CancelToken& cancel) const {
    DeliveryService service(config_.project_path, catalog,
                            config_.application_version);
    return service.build(profile, output_dir, cancel);
}

BatchConversionService& InterchangeClosure::batch() { return *batch_; }

providers::PluginLoader& InterchangeClosure::plugin_loader() {
    return plugin_loader_;
}

std::vector<providers::PluginInfo> InterchangeClosure::load_available_plugins() {
    std::vector<providers::PluginInfo> loaded;
    std::error_code ec;
    for (const auto& search_path : config_.plugin_search_paths) {
        if (!std::filesystem::is_directory(search_path, ec)) continue;
        std::vector<std::filesystem::path> candidates;
        for (auto it = std::filesystem::directory_iterator(search_path, ec);
             it != std::filesystem::directory_iterator(); it.increment(ec)) {
            if (ec) break;
            if (!it->is_regular_file(ec)) continue;
            const std::string name = it->path().filename().string();
            if (name.find(".so") == std::string::npos) continue;
            candidates.push_back(it->path());
        }
        std::sort(candidates.begin(), candidates.end());
        for (const auto& candidate : candidates) {
            try {
                loaded.push_back(plugin_loader_.load(candidate));
            } catch (const providers::PluginError& exc) {
                providers::log_event("warning",
                                     "插件加载失败 " + candidate.string() + ": " +
                                         exc.what());
            }
        }
    }
    return loaded;
}

Json closure_interchange_capability_report(const InterchangeClosure& closure) {
    Json out = Json::object();
    out["interchange"] = closure.interchange().capability_matrix();
    Json formats = Json::array();
    for (const auto& adapter : closure.interchange().capability_matrix()) {
        formats.push_back(adapter.value("format_id", ""));
    }
    out["formats"] = std::move(formats);
    Json package_runtime = Json::object();
    package_runtime["verify"] = true;
    package_runtime["build"] = true;
    package_runtime["container_zip"] = true;
    out["package_runtime"] = std::move(package_runtime);
    Json profiles = Json::array();
    for (const auto& profile : builtin_profiles()) {
        profiles.push_back(profile.profile_id);
    }
    out["delivery_profiles"] = std::move(profiles);
    Json plugins = Json::array();
    for (const auto& plugin : closure.plugin_loader().loaded()) {
        plugins.push_back(plugin.to_json());
    }
    out["plugins"] = std::move(plugins);
    return out;
}

std::unique_ptr<InterchangeClosure> closure_interchange_install(
    InterchangeClosureConfig config, IRegistrationSink* registration) {
    return std::make_unique<InterchangeClosure>(std::move(config), registration);
}

}  // namespace pwb::interchange::closure
