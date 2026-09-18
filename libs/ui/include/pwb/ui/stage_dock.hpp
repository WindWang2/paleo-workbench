#pragma once

// CONV-27 — StageDock: the C++ port of the workstation's stage context
// surface (mapping_stage_panel.py's contract, adapted to the platform's
// stage dock): a stage switcher, the stage description, and the readiness
// checklist. The central map NEVER switches with the stage — only this
// dock's content does (V5 §35). The dock only emits requests; workflow
// execution stays in the host (MainWindow wiring), the dock itself never
// touches QGIS or the catalog.

#include <string>

#include <QDockWidget>
#include <QString>
#include <QStringList>

#include <pwb/tool_policy/stages.hpp>
#include <pwb/ui/stage_readiness.hpp>

class QLabel;
class QListWidget;
class QPushButton;
class QStackedWidget;

namespace pwb::ui {

class StageDock : public QDockWidget {
    Q_OBJECT
public:
    explicit StageDock(QWidget* parent = nullptr);

    // Reflects the authoritative session stage (host drives; buttons show
    // the checked state, the description and checklist pages follow).
    void set_current_stage(pwb::tool_policy::MappingStage stage);
    pwb::tool_policy::MappingStage current_stage() const {
        return current_stage_;
    }

    // Displays the readiness report for the given stage page (kernel
    // output; sorted error-first like the Python panel).
    void set_readiness(pwb::tool_policy::MappingStage stage,
                       const StageReadiness& readiness);

    // Test/automation readback: one row per visible readiness item
    // ("glyph|check_id|title" joined), in display order.
    QStringList readiness_rows() const;

signals:
    // Emitted when the user requests a stage change. The host decides
    // (authoritative session stage lives in ProjectSession).
    void stage_change_requested(const QString& stage_value);

private:
    void build_stage_page(pwb::tool_policy::MappingStage stage);
    void on_stage_button_clicked(pwb::tool_policy::MappingStage stage);

    pwb::tool_policy::MappingStage current_stage_ =
        pwb::tool_policy::MappingStage::FaciesCalibration;
    QStackedWidget* pages_ = nullptr;
    // Parallel to kStageOrder: the switcher buttons (checked = current).
    QPushButton* stage_buttons_[3] = {nullptr, nullptr, nullptr};
    QLabel* stage_descriptions_[3] = {nullptr, nullptr, nullptr};
    QListWidget* readiness_lists_[3] = {nullptr, nullptr, nullptr};
    QLabel* status_labels_[3] = {nullptr, nullptr, nullptr};
};

}  // namespace pwb::ui
