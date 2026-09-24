#include "factor_method_dialogs.hpp"

#include <QDialogButtonBox>
#include <QDoubleSpinBox>
#include <QFormLayout>
#include <QLabel>
#include <QListWidget>
#include <QSpinBox>
#include <QVBoxLayout>

namespace pwb::app {

using factor_config::MethodOption;
using factor_config::RunParams;

FactorMethodDialog::FactorMethodDialog(const QString& current, QWidget* parent)
    : QDialog(parent) {
    setWindowTitle(QStringLiteral("插值方法"));
    setObjectName(QStringLiteral("FactorMethodDialog"));
    auto* layout = new QVBoxLayout(this);
    list_ = new QListWidget(this);
    list_->setObjectName(QStringLiteral("FactorMethodList"));
    for (const MethodOption& option : factor_config::available_methods()) {
        auto* item = new QListWidgetItem(
            QString::fromStdString(option.label), list_);
        item->setData(Qt::UserRole,
                      QString::fromStdString(option.backend));
        if (!current.isEmpty() && option.label == current.toStdString()) {
            list_->setCurrentItem(item);
        }
    }
    if (list_->currentItem() == nullptr && list_->count() > 0) {
        list_->setCurrentRow(0);
    }
    layout->addWidget(list_);
    description_ = new QLabel(this);
    description_->setWordWrap(true);
    description_->setObjectName(QStringLiteral("FactorMethodDescription"));
    layout->addWidget(description_);
    auto* buttons = new QDialogButtonBox(
        QDialogButtonBox::Ok | QDialogButtonBox::Cancel, this);
    connect(buttons, &QDialogButtonBox::accepted, this, &QDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, this, &QDialog::reject);
    layout->addWidget(buttons);

    const auto show_description = [this](QListWidgetItem* item) {
        if (item == nullptr) {
            description_->clear();
            return;
        }
        const std::string label = item->text().toStdString();
        for (const MethodOption& option :
             factor_config::available_methods()) {
            if (option.label == label) {
                description_->setText(
                    QString::fromStdString(option.description));
                return;
            }
        }
    };
    connect(list_, &QListWidget::currentItemChanged, this, show_description);
    show_description(list_->currentItem());
}

QString FactorMethodDialog::selected_method() const {
    QListWidgetItem* item = list_->currentItem();
    return item != nullptr ? item->text() : QString();
}

FactorParamsDialog::FactorParamsDialog(const RunParams& current,
                                       const QString& method_label,
                                       QWidget* parent)
    : QDialog(parent),
      backend_(QString::fromStdString(
          factor_config::backend_of_label(method_label.toStdString()))) {
    setWindowTitle(QStringLiteral("插值参数 — %1").arg(method_label));
    setObjectName(QStringLiteral("FactorParamsDialog"));
    auto* layout = new QVBoxLayout(this);
    auto* form = new QFormLayout;

    grid_n_ = new QSpinBox(this);
    grid_n_->setObjectName(QStringLiteral("FactorParamsGridN"));
    grid_n_->setRange(20, 200);
    grid_n_->setValue(current.grid_n);
    grid_n_->setSuffix(QStringLiteral(" 格"));
    form->addRow(QStringLiteral("网格分辨率"), grid_n_);

    power_ = new QDoubleSpinBox(this);
    power_->setObjectName(QStringLiteral("FactorParamsPower"));
    power_->setRange(0.5, 8.0);
    power_->setSingleStep(0.1);
    power_->setDecimals(1);
    power_->setValue(current.power);
    form->addRow(QStringLiteral("IDW 幂参数"), power_);

    seed_ = new QSpinBox(this);
    seed_->setObjectName(QStringLiteral("FactorParamsSeed"));
    seed_->setRange(0, 2147483647);
    seed_->setValue(current.seed);
    form->addRow(QStringLiteral("随机种子"), seed_);

    hint_ = new QLabel(this);
    hint_->setWordWrap(true);
    form->addRow(QString(), hint_);

    layout->addLayout(form);
    auto* buttons = new QDialogButtonBox(
        QDialogButtonBox::Ok | QDialogButtonBox::Cancel, this);
    connect(buttons, &QDialogButtonBox::accepted, this, [this] {
        const std::string problem = factor_config::validate_params(
            params(), backend_.toStdString());
        if (!problem.empty()) {
            hint_->setText(QString::fromStdString(problem));
            return;
        }
        accept();
    });
    connect(buttons, &QDialogButtonBox::rejected, this, &QDialog::reject);
    layout->addWidget(buttons);

    sync_fields_for_backend(backend_);
}

void FactorParamsDialog::sync_fields_for_backend(const QString& backend) {
    const bool uses_power = backend == QStringLiteral("idw")
                            || backend == QStringLiteral("constrained_idw");
    // Non-applicable fields stay visible but inert (greyed) — the schema
    // is one form; what the selected backend actually consumes is legible
    // at a glance and validate_params re-guards on OK.
    power_->setEnabled(uses_power);
    power_->setToolTip(uses_power
                           ? QStringLiteral("反距离幂参数")
                           : QStringLiteral("该方法不消费幂参数"));
    if (backend == QStringLiteral("kriging")) {
        hint_->setText(
            QStringLiteral("克里金变差函数由引擎按样本自动拟合"
                           "（kriging_diagnostics 记录 nugget/sill/range）——"
                           "换参会改变指纹并触发重算"));
    } else if (backend == QStringLiteral("cubic")
               || backend == QStringLiteral("directional")) {
        hint_->setText(QStringLiteral("该方法不消费幂参数与变差函数"));
    } else {
        hint_->setText(QString());
    }
}

RunParams FactorParamsDialog::params() const {
    RunParams out;
    out.grid_n = grid_n_->value();
    out.power = power_->value();
    out.seed = seed_->value();
    return out;
}

}  // namespace pwb::app
