#pragma once

// UI-09 — CrossWellExportDialog Qt shell (cross_well_export_dialog.py).
// All enablement/option semantics live in export_options.hpp; this dialog
// only binds widgets to that core.

#include <QDialog>

#include <pwb/ui_wellseis/export_options.hpp>

class QComboBox;
class QSpinBox;
class QLabel;

namespace pwb::ui_wellseis::qt {

class CrossWellExportDialog : public QDialog {
    Q_OBJECT
public:
    explicit CrossWellExportDialog(QWidget* parent = nullptr);

    // options() parity — resolved via resolve_export_options().
    [[nodiscard]] ResolvedExportOptions options() const;
    [[nodiscard]] CrossWellExportOptions raw_options() const;
    void set_options(const CrossWellExportOptions& options);

private:
    void update_enabled();

    QComboBox* fmt_combo_;
    QComboBox* dpi_combo_;
    QSpinBox* width_spin_;
    QComboBox* page_size_combo_;
};

}  // namespace pwb::ui_wellseis::qt
