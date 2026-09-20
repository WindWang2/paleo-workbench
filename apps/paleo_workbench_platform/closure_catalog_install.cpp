// 01-line closure — installer implementation. See closure_catalog_install.hpp.
#include "closure_catalog_install.hpp"

namespace pwb::app::closure_catalog {

namespace {

using ui_controllers::CatalogRuntimeApi;

// catalog.lifecycle.register_resource_input parity: a legacy resource row
// becomes a catalog input version (managed → immutable RAW snapshot;
// external → unmanaged RAW link). Returns nullopt when no backend is
// active or the file is missing — the honest degrade the controllers
// already handle.
std::optional<catalog::DataVersionRef> register_resource_input_(
    CatalogClosureAdapter& adapter, const domain::Json& resource_row) {
    if (!resource_row.is_object()) return std::nullopt;
    const std::string path_raw =
        resource_row.value("path", std::string());
    if (path_raw.empty()) return std::nullopt;
    fs::path path(path_raw);
    if (path.is_relative()) {
        path = adapter.project_path().parent_path() / path;
    }
    std::error_code ec;
    if (!fs::is_regular_file(path, ec)) return std::nullopt;

    const std::string name = resource_row.value("name", path.filename().string());
    const std::string type = resource_row.value("type", std::string());
    const std::string format = resource_row.value("format", std::string());
    const bool external = resource_row.value("external", false);
    const std::optional<std::string> legacy_id =
        resource_row.contains("id") && resource_row["id"].is_string()
            ? std::optional<std::string>(resource_row["id"].get<std::string>())
            : std::nullopt;

    domain::Json metadata = domain::Json::object();
    if (resource_row.contains("parsed_summary") &&
        resource_row["parsed_summary"].is_object()) {
        metadata["parsed_summary"] = resource_row["parsed_summary"];
    }
    if (resource_row.contains("tags") && resource_row["tags"].is_array()) {
        metadata["tags"] = resource_row["tags"];
    }

    domain::Result<catalog::DataVersion> registered =
        external
            ? adapter.link_external(path, name,
                                    type.empty() ? std::nullopt
                                                 : std::optional<std::string>(type),
                                    format.empty() ? std::nullopt
                                                   : std::optional<std::string>(format),
                                    metadata, legacy_id)
            : adapter.import_raw(path, name,
                                 type.empty() ? std::nullopt
                                              : std::optional<std::string>(type),
                                 format.empty() ? std::nullopt
                                                : std::optional<std::string>(format),
                                 metadata, legacy_id);
    if (!registered.is_ok()) return std::nullopt;
    const catalog::DataVersion& version = registered.value();
    catalog::DataVersionRef ref;
    ref.version_id = version.id.str();
    ref.asset_id = version.asset_id.str();
    ref.name = name;
    ref.stage = version.stage;
    ref.path = version.path;
    ref.checksum = version.sha256;
    ref.external = !version.managed;
    if (version.run_id.has_value()) {
        ref.producing_run_id = version.run_id->str();
    }
    ref.created_at = version.created_at;
    ref.format_field = version.format;
    ref.legacy_resource_id = legacy_id;
    ref.trashed = version.trashed;
    ref.version_number = version.version_number;
    if (const catalog::DataAsset* asset =
            adapter.get_asset(version.asset_id.str());
        asset != nullptr) {
        ref.kind = asset->type;
    }
    return ref;
}

}  // namespace

bool InstalledRegistrationBatch::finish() {
    if (adapter_ == nullptr) return false;
    try {
        // One final reconcile flush; per-registration saves already landed.
        return adapter_->document_revision() >= 0;
    } catch (...) {
        return false;
    }
}

domain::Result<InstalledCatalogClosure> InstalledCatalogClosure::install(
    const fs::path& project_path, CatalogProjectIdentity identity) {
    auto opened = CatalogClosureAdapter::open(project_path, std::move(identity));
    if (!opened.is_ok()) return opened.error();
    InstalledCatalogClosure closure;
    closure.adapter_ = std::move(opened.value());

    // Open-time maintenance pass (controller parity): recover first, then
    // the conservative sweep; ghost repair and run-port migration are
    // idempotent and non-fatal here (the controller thread re-runs them).
    try {
        closure.adapter_->recover_working_copies();
        closure.adapter_->sweep_temp_on_open();
        closure.adapter_->repair_ghost_runs();
        closure.adapter_->migrate_run_ports();
        closure.adapter_->ensure_index_ready();
    } catch (...) {
        // Maintenance must never block a project open (Python parity).
    }
    return closure;
}

InstalledCatalogClosure::InstalledCatalogClosure(
    InstalledCatalogClosure&& other) noexcept
    : adapter_(std::move(other.adapter_)) {}

InstalledCatalogClosure& InstalledCatalogClosure::operator=(
    InstalledCatalogClosure&& other) noexcept {
    if (this != &other) {
        if (adapter_) {
            try {
                adapter_->close();
            } catch (...) {
            }
        }
        adapter_ = std::move(other.adapter_);
    }
    return *this;
}

InstalledCatalogClosure::~InstalledCatalogClosure() {
    if (adapter_) {
        try {
            adapter_->close();
        } catch (...) {
        }
    }
}

ui_review::ICatalogApi* InstalledCatalogClosure::review_api() const {
    return adapter_ != nullptr ? &adapter_->review_api() : nullptr;
}

CatalogChangeFeed* InstalledCatalogClosure::change_feed() const {
    return adapter_ != nullptr ? &adapter_->change_feed() : nullptr;
}

const CatalogRecoveryReport* InstalledCatalogClosure::recovery_report()
    const {
    return adapter_ != nullptr ? &adapter_->last_recovery_report() : nullptr;
}

CatalogRuntimeApi InstalledCatalogClosure::make_runtime() {
    CatalogRuntimeApi runtime;
    // ALL lambdas capture `this` (never the adapter pointer): a session
    // switch replaces adapter_, and the bag must always resolve the LIVE
    // adapter at call time.

    runtime.open_catalog =
        [this](const fs::path& target) -> ui_controllers::CatalogServiceApi* {
        // Session-switch entry (工程切换): the controller closed the previous
        // service before calling; an active same-path adapter is reused
        // (idempotent), everything else reopens. Open failure THROWS — the
        // controller's open_catalog_ catch is the user-facing error channel
        // (Python DataCatalogService.open raise parity).
        if (adapter_ && !adapter_->is_closed() &&
            adapter_->project_path() == target) {
            return adapter_.get();
        }
        CatalogProjectIdentity identity;
        identity.project_path = target;
        identity.project_name = target.stem().string();
        auto reopened = CatalogClosureAdapter::open(target, identity);
        if (!reopened.is_ok()) {
            throw domain::DataException(reopened.error());
        }
        adapter_ = std::move(reopened.value());
        return adapter_.get();
    };
    runtime.get_catalog_service =
        [this]() -> ui_controllers::CatalogServiceApi* {
        // A closed adapter is not a service (Python get_catalog_service is
        // None after reset): the controllers' degrade paths key on null.
        if (!adapter_ || adapter_->is_closed()) return nullptr;
        return adapter_.get();
    };
    runtime.get_catalog = [this]() -> ui_controllers::CatalogPortApi* {
        if (!adapter_ || adapter_->is_closed()) return nullptr;
        return adapter_.get();
    };
    runtime.reset_catalog = [this]() {
        if (adapter_) {
            try {
                adapter_->close();
            } catch (...) {
            }
        }
    };
    runtime.enter_batch =
        [this]() -> std::unique_ptr<ui_controllers::RegistrationBatch> {
        return std::make_unique<InstalledRegistrationBatch>(adapter_.get());
    };
    runtime.register_resource_input =
        [this](const domain::Json& resource_row)
        -> std::optional<catalog::DataVersionRef> {
        if (!adapter_) return std::nullopt;
        return register_resource_input_(*adapter_, resource_row);
    };
    // clear_session_caches: the session caches it clears in Python
    // (factor_grid_artifacts/freshness/plan_cache) belong to 03/04 modules;
    // a no-op here is the honest contract until those modules register
    // their own teardown into this bag.
    runtime.clear_session_caches = []() {};

    // BEGIN PWB-V14-DATA-LINEAGE: manual-edit provenance seams (the bag
    // entries existed but were unset). The bag's flat signatures carry
    // note/extra only; entity context comes through the adapter method by
    // direct callers. Errors surface as exceptions per the adapter's
    // raise_ contract — the controllers' existing catch is the degrade
    // path (run_id-less continuation, commit never blocked).
    runtime.register_manual_edit_run =
        [this](ui_controllers::CatalogServiceApi* service,
               const std::vector<std::string>& source_version_ids,
               const std::optional<std::string>& note,
               const domain::Json& extra_parameters)
        -> std::optional<catalog::DataRun> {
        if (!adapter_ || adapter_->is_closed()) return std::nullopt;
        (void)service;  // the LIVE adapter is the service (bag contract)
        return adapter_->register_manual_edit_run(
            source_version_ids, "", "", "", "",
            note.value_or(""), false, extra_parameters);
    };
    runtime.complete_manual_edit_run =
        [this](ui_controllers::CatalogServiceApi* service,
               const std::string& run_id,
               const std::vector<std::string>& committed_version_ids) {
        if (!adapter_ || adapter_->is_closed()) return;
        (void)service;
        adapter_->complete_manual_edit_run(run_id, committed_version_ids,
                                           "", 0);
    };
    // END PWB-V14-DATA-LINEAGE

    // shutdown_lifecycle / resume_lifecycle: unset — 05/03 own the seismic
    // lifecycle; an unset std::function is the documented "unavailable".
    return runtime;
}

}  // namespace pwb::app::closure_catalog
