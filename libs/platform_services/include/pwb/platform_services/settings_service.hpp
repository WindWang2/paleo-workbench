#pragma once

// SettingsService — native QSettings persistence for the platform shell,
// porting the Python platform layer:
//   * ui/layout_persistence.py migrate_legacy_layout_settings() — one-time,
//     idempotent migration of the historical identities
//     (PaleoWorkbench, WorkstationV3) and (PaleoWorkbench, paleo-workbench)
//     into the unified (PaleoWorkbench, Workstation) store;
//   * ui/workstation/shell.py layout save/restore — version-fenced
//     QMainWindow saveState/restoreState + window geometry (same keys and
//     fence value LAYOUT_STATE_VERSION = 5);
//   * ui/command_registry.py recent commands (key ui/recent_commands, cap 8,
//     string-list coercion) and the native recent-projects MRU.
//
// Every function takes the QSettings backend explicitly — no hidden global
// store — so tests bind temporary ini files and production binds
// (PaleoWorkbench, Workstation).

#include <QStringList>
#include <QList>
#include <QRect>
#include <QSettings>
#include <QMainWindow>

namespace pwb::platform_services {

// clamp_geometry_to_screens core (panel_float_controller.py 1:1): screens
// are the available geometries, primary the primary screen's available
// rect. Offscreen entirely -> primary +24px margin, size bounded; partial
// overlap -> position clamped so >=60px stays visible; size preserved.
QRect clamp_to_desktop(const QRect& geometry, const QList<QRect>& screens,
                       const QRect& primary);


// Storage identity (ui/layout_persistence.py SETTINGS_ORG / SETTINGS_APP).
QString settings_organization();  // "PaleoWorkbench"
QString settings_application();   // "Workstation"

// Version fence: unknown (older/missing/newer) layout states are discarded
// and the default layout is used (B2 fence semantics, shell.py).
inline constexpr int kLayoutStateVersion = 5;

// Keys under the unified identity.
struct LayoutKeys {
    static const QString window_state;        // layout/window_state
    static const QString window_geometry;     // layout/window_geometry
    static const QString state_version;       // layout/state_version
    static const QString inspector_hidden;    // layout/inspector_user_hidden
    static const QString panel_group;         // panel_layout
    static const QString recent_commands;     // ui/recent_commands
    static const QString recent_projects;     // projects/recent
};

// ---- legacy migration (layout_persistence.py:32-80) --------------------

// Moves WorkstationV3's layout/windowState.v4 + inspector flag (writing the
// current state version) and the paleo-workbench panel_layout group into
// `target`, then deletes the legacy keys. Idempotent: existing target keys
// are not overwritten; returns whether anything migrated.
bool migrate_legacy_layout_settings(QSettings& target);

// Convenience: binds (settings_organization(), settings_application()) and
// runs the migration; safe to call at every startup (idempotent inside).
void migrate_legacy_settings();

// ---- window layout (shell.py _save_layout / _restore_layout) -----------

// Saves dock state + geometry behind the version fence. Skips silently when
// the window is not visible (a hidden window's default geometry must not
// pollute the persisted layout) unless force=true.
void save_window_layout(QSettings& settings, QMainWindow& window,
                        bool force = false);

// Restores dock state + geometry when (and only when) the stored state
// version matches kLayoutStateVersion; otherwise leaves the default layout.
void restore_window_layout(QSettings& settings, QMainWindow& window);

// ---- recent lists ------------------------------------------------------

inline constexpr int kRecentCommandsMax = 8;
inline constexpr int kRecentProjectsMax = 10;

// Most-recent-first; stores string lists under LayoutKeys::recent_commands.
// Push semantics mirror command_registry.py: dedupe move-to-front, cap.
QStringList load_recent_commands(QSettings& settings);
void push_recent_command(QSettings& settings, const QString& command_id);

// Native recent-projects MRU (the Python app had none — new surface,
// same push/cap semantics, directories-or-project-files as given).
QStringList load_recent_projects(QSettings& settings);
void push_recent_project(QSettings& settings, const QString& path);
void clear_recent_projects(QSettings& settings);

}  // namespace pwb::platform_services
