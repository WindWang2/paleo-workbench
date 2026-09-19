#pragma once

// UI-10 — Qt Widgets dialog shells:
//   * lithology_crossplot_dialog.py → LithologyCrossplotDialog (PwbDialog)
//   * curve_operation_dialog.py     → CurveOperationDialog (QDialog)
//
// The lithology report HTML comes from lithology_state (palette injected
// from the theme layer); the curve-op parameter editors are built from
// curve_ops_state ParamRowDesc descriptors and the diagnostics go through
// the injected CurveReadFn seam.

#include <QDialog>
#include <QFormLayout>
#include <QMap>
#include <QString>

#include <map>
#include <pwb/ui_seqviz/curve_ops_state.hpp>
#include <pwb/ui_seqviz/lithology_state.hpp>
#include <pwb/ui_widgets/dialog.hpp>
#include <vector>

class QComboBox;
class QDialogButtonBox;
class QDoubleSpinBox;
class QLineEdit;
class QTextBrowser;

namespace pwb::ui_seqviz::qt {

// ---------------------------------------------------------------------------
// lithology_crossplot_dialog.py — PwbDialog with the HTML cluster report.
// ---------------------------------------------------------------------------
class LithologyCrossplotDialog : public ui_widgets::PwbDialog {
    Q_OBJECT
public:
    // palette: injected theme colors (LIGHT palette frozen defaults when
    // omitted — host should pass live theme values).
    explicit LithologyCrossplotDialog(
        const LithologyAnalysisSlice& analysis_result,
        const LithologyPalette& palette = {},
        QWidget* parent = nullptr);

    QTextBrowser* browser() const { return browser_; }

private:
    QTextBrowser* browser_ = nullptr;
};

// ---------------------------------------------------------------------------
// curve_operation_dialog.py — parameter toolbox for one catalog version.
// ---------------------------------------------------------------------------
class CurveOperationDialog : public QDialog {
    Q_OBJECT
public:
    explicit CurveOperationDialog(std::string version_id,
                                  QWidget* parent = nullptr);

    // DataCatalogService.get_version + resolve_path + lasio seam —
    // required before run_diagnostics().
    void set_curve_reader(CurveReadFn read_fn);
    // apply_curve_operation seam — invoked on accept via
    // apply_and_collect(); the host wires it to the catalog service.
    using ApplyFn = std::function<
        domain::Json(const std::string& version_id, const std::string& op,
                     const std::string& curve, const domain::Json& params)>;
    void set_apply_fn(ApplyFn apply_fn);

    std::string operation() const;
    std::string curve() const;
    domain::Json collect_parameters() const;
    const std::string& version_id() const { return version_id_; }

    // The frozen result_summary surface ("" until set by the host).
    std::string result_summary;
    // The apply result when apply_and_collect succeeded (output_version_id
    // + the success body the host can surface). empty when not applied.
    std::string output_version_id;

    // _run_diagnostics — emits diagnostics_requested (never blocks on
    // QMessageBox); returns the outcome for tests.
    DiagnosticsOutcome run_diagnostics();
    // run_curve_operation_dialog's post-accept apply: calls the injected
    // apply_fn with the collected params; emits info/warning seams.
    bool apply_and_collect();

    QComboBox* operation_combo() const { return operation_combo_; }
    QLineEdit* curve_edit() const { return curve_edit_; }

signals:
    // QMessageBox.information / .warning seams.
    void info_requested(const QString& title, const QString& body);
    void warning_requested(const QString& title, const QString& body);

private:
    void rebuild_parameter_rows();
    QWidget* make_editor(const ParamRowDesc& desc);
    ParamValue editor_value(const QString& name, QWidget* editor) const;

    std::string version_id_;
    CurveReadFn read_fn_;
    ApplyFn apply_fn_;
    QComboBox* operation_combo_ = nullptr;
    QLineEdit* curve_edit_ = nullptr;
    QWidget* param_host_ = nullptr;
    QFormLayout* param_form_ = nullptr;
    // name -> (kind, editor) — editor lookup for collect_parameters.
    std::vector<std::pair<ParamRowDesc, QWidget*>> rows_;
};

}  // namespace pwb::ui_seqviz::qt
