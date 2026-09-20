// pwb::interchange::closure — the product-closure composition of the
// interchange half (line 10): 导入探测 → 配置校验 → native 执行 → 输出登记 →
// 可移植包导入导出, composed over the kernels this line owns
// (NativeInterchangeService, ImportPreflightService, PackageBuilder/
// verifier, DeliveryService, BatchConversionService) plus the provider
// plugin runtime (pwb::providers::PluginLoader) for line 11's typed
// invocation.
//
// The composition is a LIBRARY surface on purpose: line 12 owns the
// MainWindow/AppShell composition root, so consumers (01 registration, 09
// export governance) bind their catalog-backed implementations through two
// narrow ports instead of this line reaching into app files:
//   * IRegistrationSink — asset/output registration (line 01);
//   * ILinkableCatalog / CatalogSource — catalog read (+ relink write).
// Everything degrades honestly: a format the native side cannot serve
// reports recommendation=unavailable / status=unavailable — never a stub
// success, never a Python fallback.
#pragma once

#include <pwb/domain/json.hpp>
#include <pwb/interchange/batch.hpp>
#include <pwb/interchange/dependency_audit.hpp>
#include <pwb/interchange/delivery.hpp>
#include <pwb/interchange/preflight.hpp>
#include <pwb/interchange/service.hpp>
#include <pwb/providers/plugin_loader.hpp>

#include <filesystem>
#include <memory>
#include <string>
#include <vector>

namespace pwb::interchange::closure {

using Json = pwb::domain::Json;

// Asset/output registration port (line 01 provides the catalog-backed
// implementation; tests provide fakes). Every registered import/export
// returns a stable id the caller can reference.
class IRegistrationSink {
public:
    virtual ~IRegistrationSink() = default;
    // An imported (materialized/verified) source entering the workspace.
    virtual std::string register_import(const ImportPlan& plan,
                                        const std::filesystem::path& materialized_path) = 0;
    // A verified (or honestly unverified) export output.
    virtual std::string register_export(const ExportPlan& plan,
                                        const std::filesystem::path& output,
                                        const ExportVerification& verification) = 0;
};

struct InterchangeClosureConfig {
    std::filesystem::path workspace_root;   // containment root for outputs
    std::filesystem::path project_path;     // current project document (packages)
    std::string application_version;        // frozen from the product version
    std::vector<std::filesystem::path> plugin_search_paths;  // deployment-decided
    std::string default_delivery_profile = "internal-archive";
};

// One composed interchange runtime. Not thread-safe as a whole (the
// underlying kernels are); hosts serialize the top-level operations.
class InterchangeClosure {
public:
    InterchangeClosure(InterchangeClosureConfig config,
                       IRegistrationSink* registration = nullptr);
    // Out-of-line: unique_ptr members over types complete only in the .cpp.
    ~InterchangeClosure();
    InterchangeClosure(const InterchangeClosure&) = delete;
    InterchangeClosure& operator=(const InterchangeClosure&) = delete;

    // --- 导入探测 + 配置校验（只读，从不落盘） -----------------------------
    // Content sniffing (paleo-package / FLAC3D / Abaqus vocabulary the
    // native side knows) + the preflight decision tree.
    PreflightReport detect(const std::filesystem::path& path) const;

    // --- 导入闭环 ---------------------------------------------------------
    // Packages (.paleopkg.zip / package directory): materialize + verify +
    // register. Structured result; never throws for an unopenable package —
    // the verify report says exactly why it is not openable.
    struct ImportOutcome {
        bool ok = false;
        std::string kind;  // "package" | "unsupported" | "missing"
        std::filesystem::path materialized;
        PackageVerifyReport verify_report;
        std::string registration_id;
        std::vector<std::string> warnings;
        Json to_json() const;
    };
    ImportOutcome import_path(const std::filesystem::path& path,
                              const std::filesystem::path& dest_dir,
                              const CancelToken& cancel = null_cancel());

    // --- 导出闭环（01/09 消费的调用链） ------------------------------------
    struct ExportOutcome {
        bool ok = false;
        std::filesystem::path output;
        ExportVerification verification;
        std::string registration_id;
        Json plan_json = Json::object();
        std::vector<std::string> warnings;
        Json to_json() const;
    };
    // plan → native execute → verify → register. Throws FormatNotSupported
    // / PreflightFailed with the adapter's own message on misuse.
    ExportOutcome export_as(const std::filesystem::path& source,
                            const std::string& format_id,
                            const std::filesystem::path& target,
                            Json options = Json::object(),
                            const CancelToken& cancel = null_cancel());

    // --- 可移植包交付（09 审核治理消费） -----------------------------------
    DeliveryResult build_delivery(const std::string& profile_id,
                                  const std::filesystem::path& output_dir,
                                  ILinkableCatalog* catalog = nullptr,
                                  const CancelToken& cancel = null_cancel()) const;
    // Same flow with an explicit profile object (custom profiles).
    DeliveryResult build_delivery_profile(const DeliveryProfile& profile,
                                          const std::filesystem::path& output_dir,
                                          ILinkableCatalog* catalog = nullptr,
                                          const CancelToken& cancel = null_cancel()) const;

    // --- 批量转换 ----------------------------------------------------------
    BatchConversionService& batch();

    // --- 插件运行时（11 线 typed invocation 消费） -------------------------
    providers::PluginLoader& plugin_loader();
    const providers::PluginLoader& plugin_loader() const { return plugin_loader_; }
    // Discover-and-load every loadable module under the configured search
    // paths; per-path failures are collected, never fatal. Returns the
    // loaded plugin infos (in load order).
    std::vector<providers::PluginInfo> load_available_plugins();

    const NativeInterchangeService& interchange() const { return service_; }
    const InterchangeClosureConfig& config() const { return config_; }

private:
    InterchangeClosureConfig config_;
    IRegistrationSink* registration_;
    NativeInterchangeService service_;
    std::unique_ptr<IExportRegistration> batch_registration_;  // sink → batch port
    std::unique_ptr<BatchConversionService> batch_;
    providers::ProviderRegistry plugin_registry_;
    providers::PluginLoader plugin_loader_;
};

// Capability report for 04/09/12: model-adapter matrix + package runtime
// support + loaded plugin provider descriptors (typed invocation surface).
Json closure_interchange_capability_report(const InterchangeClosure& closure);

// Composition entry point 12 assembles at boot (library-level installer; the
// app wiring itself stays in line 12's files).
std::unique_ptr<InterchangeClosure> closure_interchange_install(
    InterchangeClosureConfig config, IRegistrationSink* registration = nullptr);

}  // namespace pwb::interchange::closure
