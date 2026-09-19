#pragma once

// Port of paleo_workbench/ui/pages/preview_settings.py PreviewSettingsStore
// (UI-07): persists preview-only preferences in a QSettings group without
// touching ProjectDocument. The Python store uses identity
// (PaleoWorkbench, paleo-workbench); the C++ side uses the platform's
// unified (settings_organization(), settings_application()) =
// (PaleoWorkbench, Workstation) — the group key "preview/settings" is
// unchanged. Previously persisted data interop is an integration-slice
// decision (see ui-07 findings).

#include <QSettings>
#include <QString>
#include <memory>

#include <pwb/ui_pages_preview/preview_settings.hpp>

namespace pwb::ui_pages_preview {

class PreviewSettingsStore {
public:
    // GROUP = "preview/settings".
    static const QString& group_key();

    // `qsettings` may be injected (tests pass a temp-file store); when null
    // the store owns a QSettings(settings_organization(),
    // settings_application()).
    explicit PreviewSettingsStore(QSettings* qsettings = nullptr);

    // Field-wise read with typed defaults; malformed payloads fall back to
    // PreviewSettings::defaults() (Python's try/except around
    // from_mapping).
    PreviewSettings load() const;

    void save(const PreviewSettings& settings);

    // Removes the whole group and returns defaults.
    PreviewSettings reset();

    QSettings* store() const { return settings_; }

private:
    QSettings* settings_ = nullptr;   // not owned when injected
    std::unique_ptr<QSettings> owned_;
};

}  // namespace pwb::ui_pages_preview
