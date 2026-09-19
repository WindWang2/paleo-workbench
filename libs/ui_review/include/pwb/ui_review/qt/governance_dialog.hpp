#pragma once

// UI-11 — governance_dialog.py Qt shell: free-text fields
// (source/region/creator) + controlled-vocabulary combos
// (discipline/confidence/review_status). The dialog only collects a
// patch; normalization/validation reuse
// ``pwb::catalog::normalize_governance_value`` — the write itself stays
// in DataCatalogService.update_asset_metadata (host-side).

#include <QDialog>

#include "pwb/domain/errors.hpp"
#include "pwb/domain/json.hpp"

class QComboBox;
class QLabel;
class QLineEdit;

namespace pwb::ui_review::qt {

class GovernanceMetadataDialog : public QDialog {
    Q_OBJECT
public:
    GovernanceMetadataDialog(QWidget* parent = nullptr,
                             const QString& asset_name = QString(),
                             const domain::Json& current = domain::Json());

    // patch() — validated governance patch (key → normalized string).
    // Returns the error Result on an invalid value (Python raises
    // ValueError and the dialog shows it; the caller never accepts).
    domain::Result<domain::Json> patch() const;

    // Python attribute surface for tests.
    QLineEdit* source_edit() const { return source_edit_; }
    QLineEdit* region_edit() const { return region_edit_; }
    QLineEdit* creator_edit() const { return creator_edit_; }
    QComboBox* discipline_combo() const { return discipline_combo_; }
    QComboBox* confidence_combo() const { return confidence_combo_; }
    QComboBox* review_combo() const { return review_combo_; }
    QLabel* error_label() const { return error_label_; }

private:
    void on_save();
    QComboBox* vocab_combo(const std::string& key,
                           const std::string& current);

    QLineEdit* source_edit_ = nullptr;
    QLineEdit* region_edit_ = nullptr;
    QLineEdit* creator_edit_ = nullptr;
    QComboBox* discipline_combo_ = nullptr;
    QComboBox* confidence_combo_ = nullptr;
    QComboBox* review_combo_ = nullptr;
    QLabel* error_label_ = nullptr;
};

}  // namespace pwb::ui_review::qt
