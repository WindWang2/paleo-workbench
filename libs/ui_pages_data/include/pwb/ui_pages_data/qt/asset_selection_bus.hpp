// CLOSURE-PREVIEW (task 04) — the single real asset-selection state.
//
// One bus per window carries the data page's asset rows and the current
// selection, so every entry point (AppShell hub page, mounts driving
// selection programmatically, future panels) reads and writes the SAME
// state instead of keeping a private DataAssetTable copy. The bus is the
// source of truth; DataWorkspace::bind_selection_bus mirrors it into the
// table widget (with a re-entrancy guard, data_asset_table.hpp keeps its
// widget-local selection for its own view logic).
//
// Deletion semantics (update_assets parity): set_assets() drops rows that
// are gone; a current selection whose (kind, id) is no longer present is
// CLEARED — the reader shows the honest empty state, never a stale asset.
// Project identity travels with the rows: a new project id clears the
// selection even when a row with the same id reappears.
#pragma once

#include <QObject>
#include <QString>

#include <optional>
#include <string>
#include <vector>

#include <pwb/ui_pages_data/asset_view.hpp>

namespace pwb::ui_pages_data::qt {

class AssetSelectionBus : public QObject {
    Q_OBJECT
public:
    explicit AssetSelectionBus(QObject* parent = nullptr);

    // The current real selection (nullopt = nothing selected).
    const std::optional<AssetRow>& current_asset() const {
        return current_;
    }
    // The rows the bus currently holds (canonical order).
    const std::vector<AssetRow>& assets() const { return assets_; }
    // Project identity the rows belong to (informational; a CHANGE of id
    // clears any current selection on set_assets).
    const QString& project_id() const { return project_id_; }

    // Row identity: (kind, id) — the DataAssetTable reuse key.
    static bool same_asset(const AssetRow& a, const AssetRow& b);
    static bool same_asset(const AssetRow& a,
                           const std::optional<AssetRow>& b);

public Q_SLOTS:
    // Replace the row set (catalog refresh / project switch). Clears the
    // current selection when it disappears or the project changed.
    void set_assets(std::vector<AssetRow> rows, const QString& project_id);
    // Publish a selection (nullopt clears). Ignored when the asset is not
    // among the current rows — selection must reference a real row.
    void set_current_asset(const std::optional<AssetRow>& asset);
    // Clear everything (project closed).
    void clear();

Q_SIGNALS:
    void assets_changed(const std::vector<AssetRow>& rows,
                        const QString& project_id);
    void current_asset_changed(const std::optional<AssetRow>& asset);

private:
    std::vector<AssetRow> assets_;
    std::optional<AssetRow> current_;
    QString project_id_;
};

}  // namespace pwb::ui_pages_data::qt
