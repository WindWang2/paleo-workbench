// UI-06 — NewProjectWizardDialog shell (see qt/new_project_wizard.hpp).
#include <pwb/ui_pages_data/qt/new_project_wizard.hpp>

#include <QCheckBox>
#include <QCloseEvent>
#include <QFileDialog>
#include <QFileInfo>
#include <QFormLayout>
#include <QHBoxLayout>
#include <QHeaderView>
#include <QLabel>
#include <QLineEdit>
#include <QProgressBar>
#include <QPushButton>
#include <QStackedWidget>
#include <QTableWidget>
#include <QTextBrowser>
#include <QVBoxLayout>

#include <pwb/ui_pages_data/wizard_model.hpp>
#include <pwb/ui_shell/style_registry.hpp>

namespace pwb::ui_pages_data::qt {

namespace {

QString pal(const char* key) {
    const auto p = ui_shell::style_palette();
    const auto it = p.find(key);
    return it != p.end() ? QString::fromStdString(it->second) : QString();
}

QString trim(const QString& s) { return s.trimmed(); }

}  // namespace

NewProjectWizardDialog::NewProjectWizardDialog(QWidget* parent)
    : QDialog(parent) {
    setObjectName(QStringLiteral("NewProjectWizard"));
    setWindowTitle(QStringLiteral("新建工程"));
    setMinimumWidth(640);
    resize(860, 640);

    auto* root = new QVBoxLayout(this);
    root->setContentsMargins(16, 16, 16, 16);
    root->setSpacing(8);

    stack_ = new QStackedWidget(this);
    root->addWidget(stack_, 1);

    // ---- Page 0: 设置 ----
    auto* page0 = new QWidget(this);
    auto* page0_layout = new QVBoxLayout(page0);
    page0_layout->setContentsMargins(0, 0, 0, 0);
    page0_layout->setSpacing(8);
    auto* form = new QFormLayout();
    form->setSpacing(8);
    form->setLabelAlignment(Qt::AlignmentFlag::AlignRight);

    name_edit_ = new QLineEdit(page0);
    name_edit_->setObjectName(QStringLiteral("WizardNameEdit"));
    name_edit_->setPlaceholderText(QStringLiteral("请输入工程名称"));
    form->addRow(QStringLiteral("工程名称："), name_edit_);

    auto* data_row = new QWidget(page0);
    auto* data_row_layout = new QHBoxLayout(data_row);
    data_row_layout->setContentsMargins(0, 0, 0, 0);
    data_row_layout->setSpacing(8);
    data_dir_edit_ = new QLineEdit(data_row);
    data_dir_edit_->setReadOnly(true);
    data_dir_edit_->setPlaceholderText(
        QStringLiteral("请选择原始数据文件夹"));
    data_browse_btn_ = new QPushButton(QStringLiteral("浏览…"), data_row);
    data_browse_btn_->setObjectName(QStringLiteral("SecondaryButton"));
    connect(data_browse_btn_, &QPushButton::clicked, this,
            &NewProjectWizardDialog::browse_data_dir);
    data_row_layout->addWidget(data_dir_edit_, 1);
    data_row_layout->addWidget(data_browse_btn_);
    form->addRow(QStringLiteral("原始数据文件夹："), data_row);

    same_dir_check_ =
        new QCheckBox(QStringLiteral("中间文件与原始数据同目录"), page0);
    same_dir_check_->setChecked(true);
    connect(same_dir_check_, &QCheckBox::toggled, this,
            &NewProjectWizardDialog::on_same_dir_toggled);
    form->addRow(QString(), same_dir_check_);

    intermediate_row_ = new QWidget(page0);
    auto* inter_layout = new QHBoxLayout(intermediate_row_);
    inter_layout->setContentsMargins(0, 0, 0, 0);
    inter_layout->setSpacing(8);
    intermediate_edit_ = new QLineEdit(intermediate_row_);
    intermediate_edit_->setReadOnly(true);
    intermediate_edit_->setPlaceholderText(
        QStringLiteral("请选择中间文件目录"));
    auto* inter_browse =
        new QPushButton(QStringLiteral("浏览…"), intermediate_row_);
    inter_browse->setObjectName(QStringLiteral("SecondaryButton"));
    connect(inter_browse, &QPushButton::clicked, this,
            &NewProjectWizardDialog::browse_intermediate_dir);
    inter_layout->addWidget(intermediate_edit_, 1);
    inter_layout->addWidget(inter_browse);
    intermediate_label_ =
        new QLabel(QStringLiteral("中间文件目录："), page0);
    form->addRow(intermediate_label_, intermediate_row_);
    intermediate_label_->setVisible(false);
    intermediate_row_->setVisible(false);

    page0_layout->addLayout(form);
    error_label_ = new QLabel(QString(), page0);
    error_label_->setObjectName(QStringLiteral("WizardErrorLabel"));
    error_label_->setWordWrap(true);
    ui_shell::style_bind(error_label_, [] {
        return QStringLiteral("color: %1;").arg(pal("ERROR_RED"));
    });
    error_label_->hide();
    page0_layout->addWidget(error_label_);
    page0_layout->addStretch(1);
    stack_->addWidget(page0);

    // ---- Page 1: 分析与预览 ----
    auto* page1 = new QWidget(this);
    auto* step2 = new QVBoxLayout(page1);
    step2->setContentsMargins(0, 0, 0, 0);
    step2->setSpacing(8);
    step2_layout_ = step2;
    page1_ = page1;

    progress_ = new QProgressBar(page1);
    progress_->setRange(0, 0);
    progress_->hide();
    step2->addWidget(progress_);

    status_label_ = new QLabel(QString(), page1);
    status_label_->setWordWrap(true);
    ui_shell::style_bind(status_label_, [] {
        return QStringLiteral("color: %1;").arg(pal("TEXT_SECONDARY"));
    });
    status_label_->hide();
    step2->addWidget(status_label_);

    summary_label_ = new QLabel(QString(), page1);
    summary_label_->setWordWrap(true);
    ui_shell::style_bind(summary_label_, [] {
        return QStringLiteral("color: %1;").arg(pal("TEXT_PRIMARY"));
    });
    summary_label_->hide();
    step2->addWidget(summary_label_);

    inventory_table_ = new QTableWidget(0, 2, page1);
    inventory_table_->setObjectName(
        QStringLiteral("WizardInventoryTable"));
    inventory_table_->setHorizontalHeaderLabels(
        {QStringLiteral("数据类型"), QStringLiteral("数量")});
    inventory_table_->horizontalHeader()->setSectionResizeMode(
        0, QHeaderView::ResizeMode::Stretch);
    inventory_table_->horizontalHeader()->setSectionResizeMode(
        1, QHeaderView::ResizeMode::ResizeToContents);
    inventory_table_->verticalHeader()->setVisible(false);
    inventory_table_->setEditTriggers(
        QTableWidget::EditTrigger::NoEditTriggers);
    inventory_table_->setAlternatingRowColors(true);
    inventory_table_->setSizePolicy(QSizePolicy::Policy::Expanding,
                                    QSizePolicy::Policy::Maximum);
    inventory_table_->hide();
    step2->addWidget(inventory_table_);

    issues_browser_ = new QTextBrowser(page1);
    issues_browser_->setReadOnly(true);
    issues_browser_->setMaximumHeight(120);
    issues_browser_->hide();
    step2->addWidget(issues_browser_);

    step2_error_ = new QLabel(QString(), page1);
    step2_error_->setObjectName(QStringLiteral("WizardStep2ErrorLabel"));
    step2_error_->setWordWrap(true);
    ui_shell::style_bind(step2_error_, [] {
        return QStringLiteral("color: %1;").arg(pal("ERROR_RED"));
    });
    step2_error_->hide();
    step2->addWidget(step2_error_);
    stack_->addWidget(page1);

    // ---- Buttons ----
    auto* btn_row = new QHBoxLayout();
    btn_row->setSpacing(8);
    cancel_btn_ = new QPushButton(QStringLiteral("取消"), this);
    cancel_btn_->setObjectName(QStringLiteral("SecondaryButton"));
    connect(cancel_btn_, &QPushButton::clicked, this,
            &NewProjectWizardDialog::reject);
    btn_row->addWidget(cancel_btn_);
    btn_row->addStretch(1);
    back_btn_ = new QPushButton(QStringLiteral("上一步"), this);
    back_btn_->setObjectName(QStringLiteral("SecondaryButton"));
    connect(back_btn_, &QPushButton::clicked, this,
            &NewProjectWizardDialog::on_back_clicked);
    back_btn_->setEnabled(false);
    btn_row->addWidget(back_btn_);
    next_btn_ = new QPushButton(QStringLiteral("下一步"), this);
    next_btn_->setObjectName(QStringLiteral("PrimaryButton"));
    connect(next_btn_, &QPushButton::clicked, this,
            &NewProjectWizardDialog::on_next_clicked);
    btn_row->addWidget(next_btn_);
    finish_btn_ = new QPushButton(QStringLiteral("完成"), this);
    finish_btn_->setObjectName(QStringLiteral("PrimaryButton"));
    finish_btn_->setEnabled(false);
    connect(finish_btn_, &QPushButton::clicked, this,
            &NewProjectWizardDialog::accept);
    btn_row->addWidget(finish_btn_);
    root->addLayout(btn_row);

    stack_->setCurrentIndex(0);
    update_buttons();
}

void NewProjectWizardDialog::set_well_map_widget(
    QWidget* panel, std::function<void(void*)> refresh_fn) {
    well_map_panel_ = panel;
    map_refresh_fn_ = std::move(refresh_fn);
    if (well_map_panel_ != nullptr && page1_ != nullptr) {
        step2_layout_->addWidget(well_map_panel_, 1);
        well_map_panel_->hide();
    }
}

std::string NewProjectWizardDialog::project_name() const {
    return trim(name_edit_->text()).toStdString();
}

std::string NewProjectWizardDialog::data_dir() const {
    return trim(data_dir_edit_->text()).toStdString();
}

std::string NewProjectWizardDialog::intermediate_dir() const {
    if (same_dir_check_->isChecked()) return data_dir();
    return trim(intermediate_edit_->text()).toStdString();
}

void NewProjectWizardDialog::browse_data_dir() {
    const QString start = trim(data_dir_edit_->text());
    const QString dir = QFileDialog::getExistingDirectory(
        this, QStringLiteral("选择数据文件夹"), start);
    if (dir.isEmpty()) return;
    data_dir_edit_->setText(dir);
    if (trim(name_edit_->text()).isEmpty()) {
        name_edit_->setText(QFileInfo(dir).fileName());
    }
    clear_error();
}

void NewProjectWizardDialog::browse_intermediate_dir() {
    QString start = trim(intermediate_edit_->text());
    if (start.isEmpty()) start = trim(data_dir_edit_->text());
    const QString dir = QFileDialog::getExistingDirectory(
        this, QStringLiteral("选择中间文件目录"), start);
    if (dir.isEmpty()) return;
    intermediate_edit_->setText(dir);
    clear_error();
}

void NewProjectWizardDialog::on_same_dir_toggled(bool checked) {
    intermediate_label_->setVisible(!checked);
    intermediate_row_->setVisible(!checked);
    clear_error();
}

void NewProjectWizardDialog::show_error(const QString& msg) {
    error_label_->setText(msg);
    error_label_->show();
}

void NewProjectWizardDialog::clear_error() {
    error_label_->hide();
    error_label_->clear();
}

bool NewProjectWizardDialog::data_dir_exists(
    const std::string& path) const {
    const QFileInfo info(QString::fromStdString(path));
    return info.exists() && info.isDir();
}

bool NewProjectWizardDialog::intermediate_exists(
    const std::string& path) const {
    const QFileInfo info(QString::fromStdString(path));
    return info.exists() && info.isDir();
}

bool NewProjectWizardDialog::target_exists() const {
    const std::string dir = intermediate_dir();
    if (dir.empty()) return false;
    const QFileInfo info(QString::fromStdString(
        dir + "/" + project_name() + ".paleo.json"));
    return info.exists();
}

bool NewProjectWizardDialog::validate_step1() {
    ui_pages_data::WizardStep1Input in;
    in.name = project_name();
    in.data_dir_text = data_dir();
    in.data_dir_exists =
        !in.data_dir_text.empty() && data_dir_exists(in.data_dir_text);
    in.same_dir = same_dir_check_->isChecked();
    in.intermediate_text = trim(intermediate_edit_->text()).toStdString();
    in.intermediate_exists =
        !in.intermediate_text.empty() &&
        intermediate_exists(in.intermediate_text);
    in.target_exists = target_exists();
    const std::string error = ui_pages_data::validate_step1(in);
    if (!error.empty()) {
        show_error(QString::fromStdString(error));
        return false;
    }
    return true;
}

void NewProjectWizardDialog::on_next_clicked() {
    if (!validate_step1()) return;
    clear_error();
    stack_->setCurrentIndex(1);
    update_buttons();
    start_analysis();
}

void NewProjectWizardDialog::on_back_clicked() {
    shutdown_job();
    stack_->setCurrentIndex(0);
    reset_step2();
    update_buttons();
    clear_error();
}

void NewProjectWizardDialog::update_buttons() {
    if (stack_->currentIndex() == 0) {
        back_btn_->setEnabled(false);
        next_btn_->setEnabled(true);
        next_btn_->setVisible(true);
        finish_btn_->setEnabled(false);
    } else {
        back_btn_->setEnabled(true);
        next_btn_->setEnabled(false);
        next_btn_->setVisible(false);
        finish_btn_->setEnabled(analysis_state_ == "success");
    }
}

void NewProjectWizardDialog::reset_step2() {
    analysis_state_ = "idle";
    progress_->hide();
    status_label_->hide();
    status_label_->clear();
    summary_label_->hide();
    summary_label_->clear();
    inventory_table_->clearContents();
    inventory_table_->setRowCount(0);
    inventory_table_->hide();
    issues_browser_->clear();
    issues_browser_->hide();
    step2_error_->hide();
    step2_error_->clear();
    if (well_map_panel_ != nullptr) well_map_panel_->hide();
    result_document_ = nullptr;
}

void NewProjectWizardDialog::start_analysis() {
    analysis_state_ = "running";
    result_document_ = nullptr;
    progress_->setRange(0, 0);
    progress_->show();
    status_label_->setText(QStringLiteral("正在分析数据文件夹…"));
    status_label_->show();
    summary_label_->hide();
    inventory_table_->hide();
    issues_browser_->hide();
    step2_error_->hide();
    if (well_map_panel_ != nullptr) well_map_panel_->hide();
    update_buttons();
    shutdown_job();
    if (!analyze_fn_) {
        on_analysis_failed(QStringLiteral("no analysis engine"));
        return;
    }
    const std::string dir = data_dir();
    const std::string name = project_name();
    analyze_fn_(
        dir, name,
        [this](const WizardAnalysisResult& r) { on_analysis_finished(r); },
        [this](const QString& msg) { on_analysis_failed(msg); });
}

void NewProjectWizardDialog::on_analysis_finished(
    const WizardAnalysisResult& result) {
    analysis_state_ = "success";
    result_document_ = result.document;
    progress_->hide();
    status_label_->hide();
    const auto view = ui_pages_data::format_wizard_report(
        result.report, result.imported_fallback);
    summary_label_->setText(QString::fromStdString(view.summary));
    summary_label_->show();
    inventory_table_->setRowCount(
        static_cast<int>(view.inventory.size()));
    for (int row = 0; row < static_cast<int>(view.inventory.size());
         ++row) {
        const auto i = static_cast<std::size_t>(row);
        inventory_table_->setItem(
            row, 0,
            new QTableWidgetItem(
                QString::fromStdString(view.inventory[i].first)));
        // str(v) parity — bools render "True"/"False", null "None".
        inventory_table_->setItem(
            row, 1,
            new QTableWidgetItem(
                QString::fromStdString(view.inventory_text[i])));
    }
    inventory_table_->resizeRowsToContents();
    const int header_h = inventory_table_->horizontalHeader()->height();
    int rows_h = 0;
    for (int r = 0; r < inventory_table_->rowCount(); ++r) {
        rows_h += inventory_table_->rowHeight(r);
    }
    const int frame = 2 * inventory_table_->frameWidth();
    inventory_table_->setMaximumHeight(
        std::min(header_h + rows_h + frame + 4, 260));
    inventory_table_->show();
    if (view.issues_visible) {
        QString text;
        for (const auto& line : view.issue_lines) {
            if (!text.isEmpty()) text += '\n';
            text += QString::fromStdString(line);
        }
        issues_browser_->setText(text);
        issues_browser_->show();
    } else {
        issues_browser_->hide();
    }
    if (well_map_panel_ != nullptr) {
        if (map_refresh_fn_) map_refresh_fn_(result.document);
        well_map_panel_->show();
    }
    update_buttons();
}

void NewProjectWizardDialog::on_analysis_failed(const QString& msg) {
    analysis_state_ = "failed";
    progress_->hide();
    status_label_->hide();
    step2_error_->setText(QStringLiteral("分析失败: %1").arg(msg));
    step2_error_->show();
    finish_btn_->setEnabled(false);
    back_btn_->setEnabled(true);
}

void NewProjectWizardDialog::shutdown_job() {
    if (job_running_fn_ && job_running_fn_() && job_shutdown_fn_) {
        job_shutdown_fn_();
    }
}

void NewProjectWizardDialog::reject() {
    shutdown_job();
    QDialog::reject();
}

void NewProjectWizardDialog::closeEvent(QCloseEvent* event) {
    shutdown_job();
    QDialog::closeEvent(event);
}

}  // namespace pwb::ui_pages_data::qt
