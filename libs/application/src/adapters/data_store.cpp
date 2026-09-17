#include <pwb/application/adapters/data_store.hpp>

#include <algorithm>
#include <utility>

namespace pwb::application {

PwbDataStore::Impl::Impl(pwb::project::ProjectManager m,
                         pwb::catalog::CatalogRepository r,
                         pwb::project::ProjectDocument d)
    : manager(std::move(m)),
      repository(std::move(r)),
      document(std::move(d)),
      coordinator(manager, repository,
                  pwb::data::DataFacade::journal_dir_for(manager.path())) {}

std::shared_ptr<PwbDataStore> PwbDataStore::open(
    const std::filesystem::path& project_file, std::string* error) {
    pwb::project::ProjectManager manager(project_file);
    auto loaded = manager.load();
    if (!loaded.is_ok()) {
        if (error != nullptr) {
            *error = "project load refused: " + loaded.error().message;
        }
        return nullptr;
    }
    if (loaded.value().document.read_only()) {
        if (error != nullptr) {
            *error = "project is read-only (future schema) — writable "
                     "store refused";
        }
        return nullptr;
    }
    pwb::catalog::CatalogRepository repository(
        pwb::project::catalog_sqlite_for(project_file));
    auto writable = repository.open_read_write();
    if (!writable.is_ok()) {
        if (error != nullptr) {
            *error = "catalog open read-write refused: "
                + writable.error().message;
        }
        return nullptr;
    }
    auto snapshot = pwb::data::DataFacade(project_file).open_snapshot();
    if (!snapshot.is_ok()) {
        if (error != nullptr) {
            *error = "snapshot failed: " + snapshot.error().message;
        }
        return nullptr;
    }
    auto impl = std::make_unique<Impl>(
        std::move(manager), std::move(repository),
        std::move(loaded.value().document));
    return std::shared_ptr<PwbDataStore>(new PwbDataStore(
        std::move(impl), std::move(snapshot).value()));
}

PwbDataStore::PwbDataStore(std::unique_ptr<Impl> impl,
                           pwb::data::ProjectSnapshotV1 initial)
    : impl_(std::move(impl)), snapshot_cache_(std::move(initial)) {}

ProjectSnapshotV1 PwbDataStore::open(const std::string& project_uri) {
    // Read-side projection of B's snapshot: diagnostics pass through, ids
    // stay domain strings.
    ProjectSnapshotV1 view;
    view.project_id = std::filesystem::path(project_uri).stem().string();
    view.schema_version =
        std::to_string(snapshot_cache_.schema_version);
    for (const auto& diagnostic : snapshot_cache_.diagnostics) {
        view.diagnostics.push_back(diagnostic.message.empty()
                                       ? diagnostic.code
                                       : diagnostic.message);
    }
    if (snapshot_cache_.read_only) {
        view.diagnostics.push_back("project.read_only");
    }
    return view;
}

std::vector<LayerBindingV1> PwbDataStore::load_bindings() {
    std::vector<LayerBindingV1> bindings;
    bindings.reserve(snapshot_cache_.layer_bindings.size());
    for (const pwb::workspace::LayerBinding& binding :
         snapshot_cache_.layer_bindings) {
        LayerBindingV1 mapped;
        mapped.layer_id = binding.layer_id;
        mapped.asset_id = binding.source_asset_id;    // "" = UNKNOWN (honest)
        mapped.version_id = binding.source_version_id;
        // B's binding vocabulary is the honest carrier for A's kind slot.
        mapped.kind = binding.binding_kind.empty() ? "unbound"
                                                   : binding.binding_kind;
        bindings.push_back(std::move(mapped));
    }
    return bindings;
}

const pwb::workspace::LayerBinding* PwbDataStore::binding_for(
    const std::string& layer_id) const {
    const auto it = std::find_if(
        snapshot_cache_.layer_bindings.begin(),
        snapshot_cache_.layer_bindings.end(),
        [&layer_id](const pwb::workspace::LayerBinding& binding) {
            return binding.layer_id == layer_id;
        });
    return it == snapshot_cache_.layer_bindings.end() ? nullptr : &*it;
}

CommitReceiptV1 PwbDataStore::commit(const CommitRequestV1& request) {
    CommitReceiptV1 receipt;
    receipt.ok = false;

    // Target asset: explicit request target first (host authority), then
    // the B binding of the staged layer (the join key). First-time layer
    // commits have no binding yet — when the project carries exactly ONE
    // non-trashed asset, that asset is the deterministic target (fresh
    // bootstrap projects); with more than one asset an explicit target or
    // binding is required (never guess among candidates).
    std::string asset_id = request.asset_id;
    if (asset_id.empty()) {
        const pwb::workspace::LayerBinding* binding =
            binding_for(request.staged.source_layer_id);
        if (binding != nullptr) asset_id = binding->source_asset_id;
    }
    if (asset_id.empty()) {
        const pwb::catalog::DataAsset* single = nullptr;
        int live_assets = 0;
        for (const auto& asset : snapshot_cache_.catalog_assets) {
            if (asset.trashed) continue;
            single = &asset;
            ++live_assets;
        }
        if (live_assets == 1) asset_id = single->id.str();
    }
    if (asset_id.empty()) {
        receipt.error = "no asset target for layer '"
            + request.staged.source_layer_id + "' (no explicit asset, no "
              "catalog binding, and the asset choice is ambiguous)";
        return receipt;
    }
    // Optimistic lock: explicit base, else the asset's current head version.
    std::string base_version = request.base_version;
    if (base_version.empty()) {
        for (const auto& asset : snapshot_cache_.catalog_assets) {
            if (asset.id.str() == asset_id && asset.current_version_id
                && !asset.current_version_id->empty()) {
                base_version = asset.current_version_id->str();
                break;
            }
        }
    }
    if (base_version.empty()) {
        receipt.error = "base version unknown for asset '" + asset_id + "'";
        return receipt;
    }

    pwb::data::CommitRequestV1 b_request;
    b_request.operation_id = pwb::domain::OperationId(request.operation_id);
    b_request.asset_id = pwb::domain::AssetId(asset_id);
    b_request.base_version_id = pwb::domain::VersionId(base_version);
    b_request.stage = pwb::domain::DataStage::Derived;
    b_request.staged.source_path = request.staged.geojson_path;
    b_request.staged.sha256 = request.staged.sha256;
    b_request.staged.format = "GeoJSON";
    b_request.rebind_layer =
        pwb::domain::LayerId(request.staged.source_layer_id);
    b_request.version_name = "platform edit "
        + request.staged.source_layer_id;

    auto result = impl_->coordinator.commit(b_request, impl_->document);
    if (!result.is_ok()) {
        receipt.error = "B commit failed: " + result.error().message;
        return receipt;
    }
    const pwb::data::CommitReceiptV1& b_receipt = result.value();
    if (b_receipt.status == pwb::data::CommitStatus::Committed ||
        b_receipt.status == pwb::data::CommitStatus::Duplicate) {
        receipt.ok = true;
        receipt.new_version = b_receipt.new_version_id.str();
        receipt.duplicate = b_receipt.status
            == pwb::data::CommitStatus::Duplicate;
    } else {
        receipt.error = "B commit status="
            + std::string(pwb::data::to_string(b_receipt.status));
        return receipt;
    }

    // Refresh the cached snapshot so subsequent load_bindings reflect the
    // new version (close/reopen semantics without a second session).
    auto refreshed = snapshot();
    if (refreshed.is_ok()) snapshot_cache_ = std::move(refreshed).value();
    return receipt;
}

}  // namespace pwb::application
