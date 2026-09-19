#pragma once

// 01-line closure — the production INSTALLER: binds the concrete adapter
// into the ui_controllers::CatalogRuntimeApi function bag that the
// (Qt-free) ProjectControllerCore consumes, and exposes the 04/09 handles.
//
// Composition-root note (line-12 contract): this file ships with its own
// CMake guard block (`PWB_BUILD_CATALOG_CLOSURE`, declared HERE, hoistable
// by 12 into cmake/PwbFeatures.cmake later without an API change). The Qt
// shell constructs one InstalledCatalogClosure per open project and hands
// runtime() to the ProjectControllerCore constructor — no process globals.

#include "closure_catalog_service.hpp"

#include <pwb/ui_controllers/catalog_api.hpp>

#include <memory>

namespace pwb::app::closure_catalog {

// A bulk-registration batch (CatalogPort adapter.batch_save() context).
// The C++ core has no deferred-save window yet (the deep-core batch is a
// body-driven API), so the chunk commits per registration and finish()
// performs one final reconcile flush — semantics preserved (all-or-nothing
// per registration), the deferral optimization is an honest divergence
// recorded in the 01 ledger findings.
class InstalledRegistrationBatch final : public ui_controllers::RegistrationBatch {
public:
    explicit InstalledRegistrationBatch(CatalogClosureAdapter* adapter)
        : adapter_(adapter) {}
    bool finish() override;

private:
    CatalogClosureAdapter* adapter_;
};

// One open project's catalog closure. Non-copyable; close() is idempotent.
// Lifetime: the closure must outlive every runtime bag made from it, and
// make_runtime() must be called on its FINAL home (the bag lambdas capture
// `this` — moving the closure afterwards invalidates them). One closure per
// open project held by the composition root is the intended shape (Python's
// process-global get_catalog() parity).
class InstalledCatalogClosure {
public:
    // Opens the adapter eagerly and runs the open-time maintenance pass the
    // controller would otherwise schedule: recover → sweep → ghost repair →
    // run-ports migration (each honest; errors do NOT block the install —
    // the controller's own maintenance thread re-runs them).
    static domain::Result<InstalledCatalogClosure> install(
        const fs::path& project_path, CatalogProjectIdentity identity);

    InstalledCatalogClosure() = default;
    InstalledCatalogClosure(InstalledCatalogClosure&& other) noexcept;
    InstalledCatalogClosure& operator=(InstalledCatalogClosure&& other) noexcept;
    InstalledCatalogClosure(const InstalledCatalogClosure&) = delete;
    InstalledCatalogClosure& operator=(const InstalledCatalogClosure&) = delete;
    ~InstalledCatalogClosure();  // close() + swallow

    bool active() const { return adapter_ != nullptr; }
    CatalogClosureAdapter* adapter() const { return adapter_.get(); }
    ui_controllers::CatalogServiceApi* service() const { return adapter_.get(); }
    ui_controllers::CatalogPortApi* port() const { return adapter_.get(); }
    ui_review::ICatalogApi* review_api() const;
    CatalogChangeFeed* change_feed() const;
    const CatalogRecoveryReport* recovery_report() const;

    // The runtime function bag for ProjectControllerCore. Bound here:
    //   open_catalog / reset_catalog / get_catalog_service / get_catalog /
    //   enter_batch / register_resource_input / clear_session_caches(no-op)
    // Deliberately UNSET (honest "unavailable" degrade, documented seam
    // semantics — NOT silent fakes):
    //   shutdown_lifecycle / resume_lifecycle  (05/03 seismic lifecycle)
    ui_controllers::CatalogRuntimeApi make_runtime();

private:
    std::unique_ptr<CatalogClosureAdapter> adapter_;
};

}  // namespace pwb::app::closure_catalog
