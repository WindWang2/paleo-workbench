// UI-15 — modal container for the shared preview-settings editor
// (ui/preview_settings_dialog.py parity). Wraps the existing
// pwb::ui_pages_preview::PreviewSettingsPanel: Apply accepts the dialog,
// Reset stays inside the panel, settings_applied forwards through.
#pragma once

#include <QDialog>

#include <pwb/ui_pages_preview/preview_settings.hpp>

namespace pwb::ui_pages_preview {
class PreviewSettingsPanel;
class PreviewSettingsStore;
}

namespace pwb::ui_canvas {

class PreviewSettingsDialog : public QDialog {
    Q_OBJECT

public:
    // `store` is injected into the panel (tests pass a temp-file store);
    // null constructs the panel's default platform store. Not owned.
    explicit PreviewSettingsDialog(
        QWidget* parent = nullptr,
        pwb::ui_pages_preview::PreviewSettingsStore* store = nullptr);

    pwb::ui_pages_preview::PreviewSettingsPanel* panel() const {
        return panel_;
    }

    void set_settings(
        const pwb::ui_pages_preview::PreviewSettings& settings);
    void set_preview_mode(const QString& mode);

signals:
    void settings_applied(
        const pwb::ui_pages_preview::PreviewSettings& settings);

private:
    pwb::ui_pages_preview::PreviewSettingsPanel* panel_ = nullptr;  // child
};

}  // namespace pwb::ui_canvas
