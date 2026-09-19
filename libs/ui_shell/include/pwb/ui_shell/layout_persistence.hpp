#pragma once

// Port of paleo_workbench/ui/layout_persistence.py (UI-01).
// QSettings-backed persistence for panel float/dock layouts, keyed
// "page:panel" so entries stay namespaced per page. Entries are only
// written when a float/dock actually happens — offscreen CI stays inert
// unless a caller asks.

#include <QRect>
#include <QSettings>

#include <optional>
#include <string>
#include <vector>

namespace pwb::ui_shell {

// Unified QSettings identity (B2): historically the shell used
// "WorkstationV3", panel-floating "paleo-workbench", theme "Workstation" —
// unified to (PaleoWorkbench, Workstation); legacy data migrates once.
inline constexpr const char* kSettingsOrg = "PaleoWorkbench";
inline constexpr const char* kSettingsApp = "Workstation";

// Layout-state version: unrecognised (newer or missing) versions are
// discarded and the default layout applies.
inline constexpr int kLayoutStateVersion = 5;

// Migrate legacy-identity layout data into (PaleoWorkbench, Workstation).
// Idempotent pure function over the default QSettings stores: never
// overwrites an existing new key; deletes legacy keys after a successful
// copy. Returns true when anything was migrated.
bool migrate_legacy_layout_settings();

struct PanelLayoutRecord {
    bool floating = false;
    std::optional<QRect> geometry;
    std::optional<std::vector<int>> docked_sizes;
    bool visible = true;

    // True when the store holds nothing worth restoring.
    bool is_empty() const {
        return !floating && !docked_sizes.has_value() && visible;
    }
};

class LayoutPersistence {
public:
    static constexpr const char* organization() { return kSettingsOrg; }
    static constexpr const char* application() { return kSettingsApp; }
    static constexpr const char* group() { return "panel_layout"; }

    // `settings == nullptr` binds the workbench org/application store
    // lazily on first use (running the one-shot legacy migration first);
    // tests inject a temp-file QSettings.
    explicit LayoutPersistence(QSettings* settings = nullptr);

    // --- write ---
    void save_float(const std::string& key, const QRect& geometry);
    void save_dock(const std::string& key, const std::vector<int>& sizes);
    // Written at float time so a crash mid-float still leaves the
    // pre-float dock slot recoverable (floating stays true).
    void save_docked_sizes(const std::string& key,
                           const std::vector<int>& sizes);
    void save_visibility(const std::string& key, bool visible);
    void clear(const std::string& key);

    // --- read ---
    PanelLayoutRecord load(const std::string& key) const;

private:
    QSettings& bind();
    const QSettings& bind() const;
    static QString group_for(const std::string& key);
    static QString encode_sizes(const std::vector<int>& sizes);
    static std::optional<QRect> parse_geometry(const QString& raw);
    static std::optional<std::vector<int>> parse_sizes(const QString& raw);

    QSettings* settings_ = nullptr;
    mutable std::unique_ptr<QSettings> owned_;
};

}  // namespace pwb::ui_shell
