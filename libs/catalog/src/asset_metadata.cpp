// Governance metadata updates on assets (conv-31b; service.py
// update_asset_metadata 3205-3247 — R7 recon contract, frozen in
// 31b-findings).
//
// The normalization pipeline is the delivered policies.hpp face
// (normalize_governance_patch); its GovernanceError maps to
// DataError{InvalidArgument, <byte-identical Chinese message>} here
// (findings B-12). Apply-loop semantics: None/"" values DELETE the key
// (stored = None if value in (None, "")), a missing key reads back as
// null so null-vs-missing is NOT a change, only differing values count as
// changed, iteration follows the patch's key order (ordered_json). A
// no-op patch returns WITHOUT saving and without touching updated_at; a
// real change stamps updated_at (Python _now_iso shape — injectable via
// now_iso for oracles) and saves dirty assets={asset.id}; a save failure
// restores the metadata + updated_at snapshots. Version-level metadata is
// deliberately immutable (ADR 0056) — no counterpart exists.
#include "pwb/catalog/asset_metadata.hpp"

#include "pwb/catalog/policies.hpp"
#include "pwb/catalog/refs.hpp"

#include <utility>

namespace pwb::catalog {

namespace {

using pwb::domain::DataError;
using pwb::domain::ErrorCode;

// Null hook → Ok (TagStore::save_or_rollback precedent).
DataError run_save(const SaveHook& save, const DirtySet& dirty) {
    return save ? save(dirty) : DataError(ErrorCode::Ok, "");
}

// Python `value in (None, "")` — exactly null and the empty string clear
// a key; 0 / false / [] / {} do not.
bool clears_key(const domain::Json& value) {
    return value.is_null() ||
           (value.is_string() && value.get<std::string>().empty());
}

}  // namespace

domain::Result<DataAsset*> update_asset_metadata(
    CatalogDocument& document, const SaveHook& save,
    const domain::AssetId& asset_id, const domain::Json& patch,
    const std::optional<std::string>& now_iso) {
    DataAsset* asset = document.find_asset_mut(asset_id);
    if (asset == nullptr) {
        return DataError(ErrorCode::NotFound,
                         "Unknown asset: " + asset_id.str());
    }
    domain::Result<domain::Json> normalized =
        normalize_governance_patch(patch);
    if (!normalized.is_ok()) {
        return normalized.error();
    }
    const domain::Json before_metadata = asset->metadata;
    const std::string before_updated = asset->updated_at;
    // DTO invariant: metadata is an object (defensive — a non-object from
    // a hand-built document is normalized here, unreachable via the
    // loaders).
    if (!asset->metadata.is_object()) {
        asset->metadata = domain::Json::object();
    }
    bool changed = false;
    for (auto it = normalized.value().begin();
         it != normalized.value().end(); ++it) {
        const domain::Json& value = *it;
        const domain::Json stored =
            clears_key(value) ? domain::Json(nullptr) : value;
        // asset.metadata.get(key) — a MISSING key reads back as null
        // (Python .get default), so "absent" vs "explicit null" is not a
        // change and a null-valued key is never popped by a null patch.
        domain::Json current = domain::Json(nullptr);
        if (asset->metadata.contains(it.key())) {
            current = asset->metadata[it.key()];
        }
        if (!(current == stored)) {  // deep, key-order-independent (R7 ⑤-6)
            if (stored.is_null()) {
                asset->metadata.erase(it.key());  // pop(key, None)
            } else {
                asset->metadata[it.key()] = stored;
            }
            changed = true;
        }
    }
    if (!changed) {
        return asset;  // no save, updated_at untouched
    }
    asset->updated_at = now_iso.has_value() ? *now_iso : utc_now_iso();
    DirtySet dirty;
    dirty.mark_asset(asset->id.str());
    const DataError error = run_save(save, dirty);
    if (error.code != ErrorCode::Ok) {
        asset->metadata = before_metadata;
        asset->updated_at = before_updated;
        return error;
    }
    return asset;
}

}  // namespace pwb::catalog
