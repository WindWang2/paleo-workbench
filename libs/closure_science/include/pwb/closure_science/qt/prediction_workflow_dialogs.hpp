// pwb::closure_science::qt — production dialogs for the ws1 prediction
// workflow commands (predict.select_well / predict.model_params /
// predict.params). Data in = run_spec_service candidates/schema (real
// catalog rows + kernel-anchored parameter schema); data out = stable ids
// / a validated params object — the dialogs never touch the catalog or
// the spec directly, the controller owns that single truth.
#pragma once

#include <pwb/closure_science/run_spec_service.hpp>
#include <pwb/domain/json.hpp>
#include <pwb/prediction/run_spec.hpp>

#include <QDialog>
#include <QString>

#include <map>
#include <string>
#include <utility>
#include <vector>

class QLabel;
class QListWidget;
class QPushButton;

namespace pwb::closure_science::qt {

// predict.select_well: multi-select over the project's well_log resources.
// Rows carry stable resource ids; wells without a usable catalog version
// stay visible but unselectable with their exact reason.
class WellSelectionDialog : public QDialog {
    Q_OBJECT
public:
    WellSelectionDialog(
        const std::vector<WellCandidate>& wells,
        const std::vector<std::string>& initially_selected,
        QWidget* parent = nullptr);

    [[nodiscard]] std::vector<std::string> selected_resource_ids() const;

private:
    // Cached on accept (cell widgets die with the dialog).
    std::vector<std::string> selected_;
};

// predict.model_params: one registered model version + its real package
// facts (identity/checksum/expected inputs/vocabulary/runtime/executor).
// Selecting requires an executable provider and a validated package
// (*summaries carries the pre-inspected package facts keyed by
// model_version_id; a missing entry = "not a package" and shows as such).
class ModelSelectionDialog : public QDialog {
    Q_OBJECT
public:
    ModelSelectionDialog(
        const std::vector<ModelCandidate>& models,
        const std::map<std::string, ModelPackageSummary>& summaries,
        const std::string& initially_selected, QWidget* parent = nullptr);

    [[nodiscard]] std::string selected_model_version_id() const;
    // Whether the CURRENT selection can be confirmed (executable provider
    // + validated package) — the OK button state, probeable offscreen.
    [[nodiscard]] bool selection_confirmable() const;

private:
    void show_details_for(const std::string& model_version_id);

    std::vector<ModelCandidate> models_;
    std::map<std::string, ModelPackageSummary> summaries_;
    std::string selected_;
    QLabel* detail_label_ = nullptr;
    QListWidget* list_ = nullptr;
    QPushButton* ok_ = nullptr;
};

// predict.params: schema-driven parameter editor (ranges/defaults/units
// from prediction_param_schema()). Invalid values cannot leave the dialog;
// "恢复默认" resets to the kernel defaults.
class PredictionParamsDialog : public QDialog {
    Q_OBJECT
public:
    PredictionParamsDialog(const domain::Json& current_params,
                           QWidget* parent = nullptr);

    [[nodiscard]] domain::Json params() const;
    [[nodiscard]] bool params_changed() const { return params_changed_; }

private:
    void reset_to_defaults();
    void revalidate();

    domain::Json initial_ = domain::Json::object();
    domain::Json current_ = domain::Json::object();
    bool params_changed_ = false;
    QLabel* error_label_ = nullptr;
    QPushButton* ok_ = nullptr;
    // schema key -> editor widget
    std::vector<std::pair<std::string, QWidget*> > editors_;
};

}  // namespace pwb::closure_science::qt
