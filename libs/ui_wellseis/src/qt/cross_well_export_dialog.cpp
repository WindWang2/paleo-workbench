#include <pwb/ui_wellseis/qt/cross_well_export_dialog.hpp>

#include <QComboBox>
#include <QDialogButtonBox>
#include <QFormLayout>
#include <QSpinBox>
#include <QVBoxLayout>

namespace pwb::ui_wellseis::qt {

namespace {

QString qs(const std::string& text) {
    return QString::fromUtf8(text.data(), static_cast<int>(text.size()));
}

}  // namespace

CrossWellExportDialog::CrossWellExportDialog(QWidget* parent)
    : QDialog(parent) {
    setWindowTitle(QStringLiteral("导出连井剖面"));
    auto* layout = new QVBoxLayout(this);
    auto* form = new QFormLayout();

    fmt_combo_ = new QComboBox(this);
    fmt_combo_->addItem(QStringLiteral("SVG 矢量图"), QStringLiteral("svg"));
    fmt_combo_->addItem(QStringLiteral("PNG 位图"), QStringLiteral("png"));
    fmt_combo_->addItem(QStringLiteral("PDF 文档"), QStringLiteral("pdf"));
    connect(fmt_combo_, &QComboBox::currentIndexChanged, this,
            [this] { update_enabled(); });
    form->addRow(QStringLiteral("格式"), fmt_combo_);

    dpi_combo_ = new QComboBox(this);
    for (const int dpi : {96, 150, 300}) {
        dpi_combo_->addItem(QString::number(dpi), dpi);
    }
    dpi_combo_->setCurrentIndex(1);  // 150
    form->addRow(QStringLiteral("DPI"), dpi_combo_);

    width_spin_ = new QSpinBox(this);
    width_spin_->setRange(0, 20000);
    width_spin_->setSingleStep(100);
    width_spin_->setSpecialValueText(QStringLiteral("自然宽度"));
    width_spin_->setSuffix(QStringLiteral(" px"));
    width_spin_->setValue(0);
    form->addRow(QStringLiteral("宽度"), width_spin_);

    page_size_combo_ = new QComboBox(this);
    page_size_combo_->addItem(QStringLiteral("内容尺寸"), QVariant{});
    page_size_combo_->addItem(QStringLiteral("A4"), QStringLiteral("A4"));
    page_size_combo_->addItem(QStringLiteral("Letter"),
                              QStringLiteral("LETTER"));
    connect(page_size_combo_, &QComboBox::currentIndexChanged, this,
            [this] { update_enabled(); });
    form->addRow(QStringLiteral("纸张"), page_size_combo_);

    layout->addLayout(form);
    auto* buttons = new QDialogButtonBox(
        QDialogButtonBox::Ok | QDialogButtonBox::Cancel, this);
    connect(buttons, &QDialogButtonBox::accepted, this, &QDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, this, &QDialog::reject);
    layout->addWidget(buttons);

    update_enabled();
}

CrossWellExportOptions CrossWellExportDialog::raw_options() const {
    CrossWellExportOptions options;
    options.fmt = fmt_combo_->currentData().toString().toStdString();
    options.dpi = dpi_combo_->currentData().toInt();
    options.width_px = width_spin_->value();
    const QVariant page = page_size_combo_->currentData();
    if (page.isValid() && !page.toString().isEmpty()) {
        options.page_size = page.toString().toStdString();
    }
    return options;
}

ResolvedExportOptions CrossWellExportDialog::options() const {
    return resolve_export_options(raw_options());
}

void CrossWellExportDialog::set_options(
    const CrossWellExportOptions& options) {
    const int fmt_index = fmt_combo_->findData(qs(options.fmt));
    if (fmt_index >= 0) {
        fmt_combo_->setCurrentIndex(fmt_index);
    }
    const int dpi_index = dpi_combo_->findData(options.dpi);
    if (dpi_index >= 0) {
        dpi_combo_->setCurrentIndex(dpi_index);
    }
    width_spin_->setValue(options.width_px);
    if (options.page_size.has_value()) {
        const int page_index =
            page_size_combo_->findData(qs(*options.page_size));
        if (page_index >= 0) {
            page_size_combo_->setCurrentIndex(page_index);
        }
    } else {
        page_size_combo_->setCurrentIndex(0);
    }
    update_enabled();
}

void CrossWellExportDialog::update_enabled() {
    const CrossWellExportEnabled enabled = export_enabled(raw_options());
    dpi_combo_->setEnabled(enabled.dpi);
    page_size_combo_->setEnabled(enabled.page_size);
    width_spin_->setEnabled(enabled.width);
}

}  // namespace pwb::ui_wellseis::qt
