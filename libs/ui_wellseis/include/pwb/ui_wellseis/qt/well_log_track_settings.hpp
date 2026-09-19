#pragma once

// UI-09 — CurveTrackSettingsDialog Qt shell
// (well_log_track_settings.py). Thin dialog over the existing
// pwb::viz::WellLogTrackLayout model — visibility checkboxes, drag-onto
// merge (max 3/group), unmerge, restore-default. No layout semantics are
// re-derived here; every mutation goes through the model's
// with_visible/merge/unmerge/default_track_layout.

#include <string>
#include <vector>

#include <QDialog>
#include <QTreeWidget>

#include <pwb/viz/well_log_track_layout.hpp>

class QLabel;
class QPushButton;
class QTreeWidgetItem;

namespace pwb::ui_wellseis::qt {

// _CurveLayoutTree parity — an internal drop reads "merge source onto
// target"; emits merge_requested(source_key, target_key).
class CurveLayoutTree : public QTreeWidget {
    Q_OBJECT
public:
    explicit CurveLayoutTree(QWidget* parent = nullptr);
    static constexpr int CurveKeyRole = Qt::UserRole + 7;

signals:
    void merge_requested(const QString& source_key,
                         const QString& target_key);

protected:
    void dropEvent(QDropEvent* event) override;
};

class CurveTrackSettingsDialog : public QDialog {
    Q_OBJECT
public:
    // `mnemonics` are the curve names in document order — the layout's
    // curve_keys are "curve:{index}:{name}" (curve_key_for parity).
    CurveTrackSettingsDialog(
        const std::vector<std::string>& mnemonics,
        pwb::viz::WellLogTrackLayout layout, QWidget* parent = nullptr);

    [[nodiscard]] const pwb::viz::WellLogTrackLayout& layout() const;
    [[nodiscard]] QString status_text() const;

    // Public ops (Python method parity — also used by tests).
    bool merge_curve(const std::string& curve_key,
                     const std::string& onto_key);
    bool unmerge_curve(const std::string& curve_key);

private:
    void rebuild_tree();
    QTreeWidgetItem* make_curve_item(const std::string& key);

    std::vector<std::string> mnemonics_;
    std::vector<std::string> curve_keys_;  // parallel to mnemonics_
    pwb::viz::WellLogTrackLayout layout_;
    CurveLayoutTree* tree_ = nullptr;
    QLabel* status_label_ = nullptr;
    QPushButton* unmerge_btn_ = nullptr;
    QPushButton* reset_btn_ = nullptr;
    bool rebuilding_ = false;
};

}  // namespace pwb::ui_wellseis::qt
