// UI-15 — modal preview-settings container
// (ui/preview_settings_dialog.py parity).

#include <pwb/ui_canvas/qt/preview_settings_dialog.hpp>

#include <QPushButton>
#include <QVBoxLayout>

#include <pwb/ui_pages_preview/qt/preview_settings_panel.hpp>

namespace pwb::ui_canvas {

PreviewSettingsDialog::PreviewSettingsDialog(
    QWidget* parent, pwb::ui_pages_preview::PreviewSettingsStore* store)
    : QDialog(parent) {
    setObjectName(QStringLiteral("PreviewSettingsDialog"));
    setWindowTitle(QStringLiteral("预览设置"));
    setModal(true);
    setMinimumWidth(520);

    auto* layout = new QVBoxLayout(this);
    // tokens.SPACE_4 = 20 (legacy「较松区块距」).
    layout->setContentsMargins(20, 20, 20, 20);
    panel_ = new pwb::ui_pages_preview::PreviewSettingsPanel(this, store);
    layout->addWidget(panel_);

    connect(panel_,
            &pwb::ui_pages_preview::PreviewSettingsPanel::settings_applied,
            this, &PreviewSettingsDialog::settings_applied);
    // Apply accepts; Reset only mutates settings (panel-internal).
    connect(panel_->apply_button(), &QPushButton::clicked, this,
            &PreviewSettingsDialog::accept);
}

void PreviewSettingsDialog::set_settings(
    const pwb::ui_pages_preview::PreviewSettings& settings) {
    panel_->set_settings(settings);
}

void PreviewSettingsDialog::set_preview_mode(const QString& mode) {
    panel_->set_preview_mode(mode);
}

}  // namespace pwb::ui_canvas
