// Governance metadata updates on assets (conv-31b; service.py
// update_asset_metadata 3205-3247 — R7 recon contract, frozen in
// 31b-findings).
//
// Normalization is the delivered policies.hpp governance face
// (normalize_governance_patch — Chinese error texts frozen there).
// The apply loop: None/"" values DELETE the key (a missing key is not a
// change); only differing values count as changed; a no-op patch does
// NOT save and does not touch updated_at; a real change stamps
// updated_at (UTC isoformat) and saves with dirty assets={asset.id};
// failure → metadata + updated_at snapshot rollback. Version-level
// metadata is deliberately immutable (ADR 0056) — no counterpart here.
//
// CONV-31b: implemented in Wave2-A7 (src/asset_metadata.cpp).
#pragma once

#include "pwb/catalog/apply_changes.hpp"  // SaveHook
#include "pwb/catalog/models.hpp"
#include "pwb/domain/errors.hpp"

#include <optional>

namespace pwb::catalog {

// GovernanceError maps to DataError{InvalidArgument, <byte-identical
// Chinese message>}. Returns a pointer into *document.
domain::Result<DataAsset*> update_asset_metadata(
    CatalogDocument& document, const SaveHook& save,
    const domain::AssetId& asset_id, const domain::Json& patch,
    const std::optional<std::string>& now_iso = std::nullopt);

}  // namespace pwb::catalog
