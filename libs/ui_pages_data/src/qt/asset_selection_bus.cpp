// CLOSURE-PREVIEW (task 04) — see qt/asset_selection_bus.hpp.
#include <pwb/ui_pages_data/qt/asset_selection_bus.hpp>

#include <algorithm>

namespace pwb::ui_pages_data::qt {

AssetSelectionBus::AssetSelectionBus(QObject* parent) : QObject(parent) {}

bool AssetSelectionBus::same_asset(const AssetRow& a, const AssetRow& b) {
    return a.kind == b.kind && a.view.id == b.view.id;
}

bool AssetSelectionBus::same_asset(const AssetRow& a,
                                   const std::optional<AssetRow>& b) {
    return b.has_value() && same_asset(a, *b);
}

void AssetSelectionBus::set_assets(std::vector<AssetRow> rows,
                                   const QString& project_id) {
    const bool project_changed = project_id_ != project_id;
    assets_ = std::move(rows);
    project_id_ = project_id;
    // Deletion/switch semantics: the selection must reference a row that
    // still exists in the SAME project — otherwise it is stale and is
    // cleared (the reader falls back to the honest empty state).
    if (current_.has_value() &&
        (project_changed ||
         std::none_of(assets_.begin(), assets_.end(),
                      [this](const AssetRow& row) {
                          return same_asset(row, current_);
                      }))) {
        current_.reset();
        Q_EMIT current_asset_changed(current_);
    }
    Q_EMIT assets_changed(assets_, project_id_);
}

void AssetSelectionBus::set_current_asset(
    const std::optional<AssetRow>& asset) {
    if (asset.has_value()) {
        const bool known =
            std::any_of(assets_.begin(), assets_.end(),
                        [&](const AssetRow& row) {
                            return same_asset(row, asset);
                        });
        if (!known) {
            return;  // selection must reference a real row — never phantom
        }
    }
    const bool unchanged = asset.has_value() == current_.has_value() &&
                           (!asset.has_value() ||
                            same_asset(*current_, *asset));
    if (unchanged) {
        return;
    }
    current_ = asset;
    Q_EMIT current_asset_changed(current_);
}

void AssetSelectionBus::clear() {
    assets_.clear();
    project_id_.clear();
    if (current_.has_value()) {
        current_.reset();
        Q_EMIT current_asset_changed(current_);
    }
    Q_EMIT assets_changed(assets_, project_id_);
}

}  // namespace pwb::ui_pages_data::qt
