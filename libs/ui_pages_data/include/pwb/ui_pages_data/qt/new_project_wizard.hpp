// UI-06 — new_project_wizard.py :: NewProjectWizardDialog Qt shell.
//
// Two-step QStackedWidget wizard. Validation/summary/report formatting is
// in wizard_model.hpp (oracle-covered); the analysis engine + well-map
// panel are injected seams.
#pragma once

#include <QDialog>

#include <functional>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>

class QCheckBox;
class QLabel;
class QLineEdit;
class QProgressBar;
class QPushButton;
class QStackedWidget;
class QTableWidget;
class QTextBrowser;
class QVBoxLayout;
class QWidget;

namespace pwb::ui_pages_data::qt {

// Analysis result seam (_AnalyzeWorker's result: document + report).
// The document is the host's — the dialog only forwards its opaque handle.
struct WizardAnalysisResult {
    pwb::domain::Json report = pwb::domain::Json::object();
    int imported_fallback = 0;
    void* document = nullptr;  // host-owned; passed to the map refresh fn
};

// Async analysis seam: the host runs the engine off-thread and invokes
// exactly one callback (on the UI thread).
using WizardAnalyzeFn = std::function<void(
    const std::string& data_dir, const std::string& project_name,
    std::function<void(const WizardAnalysisResult&)> on_finished,
    std::function<void(const QString&)> on_failed)>;

class NewProjectWizardDialog : public QDialog {
    Q_OBJECT
public:
    explicit NewProjectWizardDialog(QWidget* parent = nullptr);

    void set_analyze_fn(WizardAnalyzeFn fn) { analyze_fn_ = std::move(fn); }
    // Well-map seam: called with the document handle on success; may be
    // null (panel hidden entirely when absent — Python keeps the widget
    // hidden until first success).
    void set_well_map_widget(
        QWidget* panel,
        std::function<void(void* document)> refresh_fn);
    // Job seam: returns true while a prior analysis still runs
    // (reject/back shutdown parity).
    void set_job_running_fn(std::function<bool()> fn) {
        job_running_fn_ = std::move(fn);
    }
    void set_job_shutdown_fn(std::function<void()> fn) {
        job_shutdown_fn_ = std::move(fn);
    }

    void* result_document() const { return result_document_; }
    std::string project_name() const;
    std::string data_dir() const;
    std::string intermediate_dir() const;
    std::string analysis_state() const { return analysis_state_; }

    void reject() override;

protected:
    void closeEvent(QCloseEvent* event) override;

private:
    void browse_data_dir();
    void browse_intermediate_dir();
    void on_same_dir_toggled(bool checked);
    void show_error(const QString& msg);
    void clear_error();
    bool validate_step1();
    void on_next_clicked();
    void on_back_clicked();
    void update_buttons();
    void reset_step2();
    void start_analysis();
    void on_analysis_finished(const WizardAnalysisResult& result);
    void on_analysis_failed(const QString& msg);
    void shutdown_job();
    bool data_dir_exists(const std::string& path) const;
    bool intermediate_exists(const std::string& path) const;
    bool target_exists() const;

    QStackedWidget* stack_;
    QWidget* page1_ = nullptr;
    QVBoxLayout* step2_layout_ = nullptr;
    QLineEdit* name_edit_;
    QLineEdit* data_dir_edit_;
    QPushButton* data_browse_btn_;
    QCheckBox* same_dir_check_;
    QWidget* intermediate_row_;
    QLabel* intermediate_label_;
    QLineEdit* intermediate_edit_;
    QLabel* error_label_;
    QProgressBar* progress_;
    QLabel* status_label_;
    QLabel* summary_label_;
    QTableWidget* inventory_table_;
    QTextBrowser* issues_browser_;
    QLabel* step2_error_;
    QPushButton* cancel_btn_;
    QPushButton* back_btn_;
    QPushButton* next_btn_;
    QPushButton* finish_btn_;
    QWidget* well_map_panel_ = nullptr;
    std::function<void(void*)> map_refresh_fn_;

    WizardAnalyzeFn analyze_fn_;
    std::function<bool()> job_running_fn_;
    std::function<void()> job_shutdown_fn_;
    void* result_document_ = nullptr;
    std::string analysis_state_ = "idle";
};

}  // namespace pwb::ui_pages_data::qt
