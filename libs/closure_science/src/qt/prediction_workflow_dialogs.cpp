#include <pwb/closure_science/qt/prediction_workflow_dialogs.hpp>

#include <pwb/prediction/run_spec.hpp>

#include <QCheckBox>
#include <QDialogButtonBox>
#include <QHBoxLayout>
#include <QHeaderView>
#include <QLabel>
#include <QListWidget>
#include <QPushButton>
#include <QSpinBox>
#include <QTableWidget>
#include <QTableWidgetItem>
#include <QTextStream>
#include <QVBoxLayout>

#include <algorithm>
#include <set>

namespace pwb::closure_science::qt {

namespace {

QString qs(const std::string& text) {
    return QString::fromStdString(text);
}

QString availability_text(const WellCandidate& well) {
    if (well.availability == "ok") {
        if (!well.missing_required_curves.empty()) {
            QString joined;
            for (const auto& curve : well.missing_required_curves) {
                if (!joined.isEmpty()) joined += QStringLiteral(", ");
                joined += qs(curve);
            }
            return QStringLiteral("缺模型必需曲线: %1").arg(joined);
        }
        return QStringLiteral("可用");
    }
    if (well.availability == "trashed_asset") {
        return QStringLiteral("资产已在回收站");
    }
    if (well.availability == "no_current_version") {
        return QStringLiteral("无当前版本（版本被取代/删除）");
    }
    return QStringLiteral("未纳管（需先导入并纳管）");
}

}  // namespace

// ---------------------------------------------------------------------------
// WellSelectionDialog
// ---------------------------------------------------------------------------

WellSelectionDialog::WellSelectionDialog(
    const std::vector<WellCandidate>& wells,
    const std::vector<std::string>& initially_selected, QWidget* parent)
    : QDialog(parent) {
    setWindowTitle(QStringLiteral("选择井数据"));
    setModal(true);
    auto* layout = new QVBoxLayout(this);
    auto* table = new QTableWidget(this);
    table->setColumnCount(4);
    table->setHorizontalHeaderLabels({QStringLiteral("参与"),
                                      QStringLiteral("井"),
                                      QStringLiteral("当前版本"),
                                      QStringLiteral("状态")});
    table->horizontalHeader()->setStretchLastSection(true);
    table->verticalHeader()->hide();
    table->setRowCount(static_cast<int>(wells.size()));
    const std::set<std::string> selected(initially_selected.begin(),
                                         initially_selected.end());
    for (int row = 0; row < static_cast<int>(wells.size()); ++row) {
        const WellCandidate& well = wells[static_cast<std::size_t>(row)];
        const bool usable =
            well.availability == "ok" && well.version_id.empty() == false;
        auto* check = new QCheckBox(table);
        check->setEnabled(usable && well.missing_required_curves.empty());
        check->setChecked(usable && selected.count(well.resource_id) != 0u);
        check->setToolTip(
            usable
                ? (well.missing_required_curves.empty()
                       ? QStringLiteral("资源 id: %1").arg(qs(well.resource_id))
                       : availability_text(well))
                : availability_text(well));
        table->setCellWidget(row, 0, check);
        auto* name = new QTableWidgetItem(qs(well.name));
        name->setToolTip(qs(well.resource_id));
        table->setItem(row, 1, name);
        table->setItem(
            row, 2,
            new QTableWidgetItem(
                well.version_count > 0
                    ? QStringLiteral("%1（%2 个版本）")
                          .arg(qs(well.version_id))
                          .arg(well.version_count)
                    : QStringLiteral("—")));
        auto* status = new QTableWidgetItem(availability_text(well));
        if (!usable) {
            status->setFlags(status->flags() & ~Qt::ItemIsEnabled);
        }
        table->setItem(row, 3, status);
    }
    table->resizeColumnsToContents();
    layout->addWidget(
        new QLabel(QStringLiteral("选择参与预测的井（稳定资源 id，多选）"), this));
    layout->addWidget(table);
    auto* buttons =
        new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel,
                             this);
    connect(buttons, &QDialogButtonBox::accepted, this, &QDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, this, &QDialog::reject);
    layout->addWidget(buttons);
    setMinimumSize(QSize(560, 360));
    // Cache the selection on accept: cell widgets die with the dialog, so
    // selected_resource_ids() must not re-read them after exec().
    connect(this, &QDialog::accepted, this, [this, table, wells] {
        selected_.clear();
        for (int row = 0; row < table->rowCount(); ++row) {
            auto* check = qobject_cast<QCheckBox*>(
                table->cellWidget(row, 0));
            if (check != nullptr && check->isEnabled() &&
                check->isChecked()) {
                selected_.push_back(
                    wells[static_cast<std::size_t>(row)].resource_id);
            }
        }
    });
}

std::vector<std::string> WellSelectionDialog::selected_resource_ids() const {
    return selected_;
}

// ---------------------------------------------------------------------------
// ModelSelectionDialog
// ---------------------------------------------------------------------------

ModelSelectionDialog::ModelSelectionDialog(
    const std::vector<ModelCandidate>& models,
    const std::map<std::string, ModelPackageSummary>& summaries,
    const std::string& initially_selected, QWidget* parent)
    : QDialog(parent),
      models_(models),
      summaries_(summaries),
      selected_(initially_selected) {
    setWindowTitle(QStringLiteral("选择预测模型"));
    setModal(true);
    auto* layout = new QVBoxLayout(this);
    auto* split = new QHBoxLayout();
    list_ = new QListWidget(this);
    detail_label_ = new QLabel(this);
    detail_label_->setAlignment(Qt::AlignTop | Qt::AlignLeft);
    detail_label_->setWordWrap(true);
    detail_label_->setMinimumWidth(280);
    split->addWidget(list_, 1);
    split->addWidget(detail_label_, 1);
    layout->addLayout(split);
    auto* buttons =
        new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel,
                             this);
    ok_ = buttons->button(QDialogButtonBox::Ok);
    connect(buttons, &QDialogButtonBox::accepted, this, &QDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, this, &QDialog::reject);
    layout->addWidget(buttons);
    setMinimumSize(QSize(680, 380));

    for (const auto& model : models_) {
        QListWidgetItem* item = new QListWidgetItem(list_);
        item->setText(QStringLiteral("%1  %2:%3  [%4]")
                          .arg(qs(model.name), qs(model.model_id),
                               qs(model.model_version), qs(model.provider)));
        item->setData(Qt::UserRole, qs(model.model_version_id));
        item->setSelected(model.model_version_id == selected_);
    }
    connect(list_, &QListWidget::itemSelectionChanged, this, [this] {
        const QList<QListWidgetItem*> chosen = list_->selectedItems();
        if (chosen.isEmpty()) {
            selected_.clear();
            ok_->setEnabled(false);
            return;
        }
        selected_ = chosen.front()->data(Qt::UserRole).toString().toStdString();
        show_details_for(selected_);
    });
    show_details_for(selected_);
}

void ModelSelectionDialog::show_details_for(
    const std::string& model_version_id) {
    const ModelCandidate* model = nullptr;
    for (const auto& candidate : models_) {
        if (candidate.model_version_id == model_version_id) {
            model = &candidate;
            break;
        }
    }
    if (model == nullptr) {
        detail_label_->setText(QStringLiteral("未选择模型"));
        ok_->setEnabled(false);
        return;
    }
    QString body;
    QTextStream stream(&body);
    stream << QStringLiteral("模型: ") << qs(model->name) << "\n"
           << QStringLiteral("标识: ") << qs(model->model_id) << " v"
           << qs(model->model_version) << "\n"
           << QStringLiteral("provider: ") << qs(model->provider)
           << QStringLiteral("  runtime: ") << qs(model->runtime) << "\n"
           << QStringLiteral("状态: ") << qs(model->status)
           << (model->demo_only ? QStringLiteral("（仅演示）") : QString())
           << "\n"
           << QStringLiteral("checksum: ")
           << (model->checksum.has_value() ? qs(*model->checksum)
                                           : QStringLiteral("（未登记）"))
           << "\n";
    const auto summary = summaries_.find(model_version_id);
    if (summary != summaries_.end()) {
        if (summary->second.ok) {
            stream << QStringLiteral("模型包: 有效\n")
                   << QStringLiteral("文件 sha256: ")
                   << qs(summary->second.checksum) << "\n"
                   << QStringLiteral("期望输入: ");
            if (summary->second.expected_inputs.empty()) {
                stream << QStringLiteral("（包未声明）");
            } else {
                for (const auto& input : summary->second.expected_inputs) {
                    stream << qs(input) << " ";
                }
            }
            stream << "\n" << QStringLiteral("相别词汇表: ");
            if (summary->second.class_names.empty()) {
                stream << QStringLiteral("（包未声明）");
            } else {
                for (const auto& name : summary->second.class_names) {
                    stream << qs(name) << " ";
                }
            }
            stream << "\n";
            if (!summary->second.declared_tile.empty()) {
                stream << QStringLiteral("包声明分块: ")
                       << qs(summary->second.declared_tile) << "\n";
            }
            if (model->checksum.has_value() && !model->checksum->empty() &&
                *model->checksum != summary->second.checksum) {
                stream << QStringLiteral("⚠ 校验和不一致：登记 ")
                       << qs(*model->checksum) << QStringLiteral(" ≠ 实际 ")
                       << qs(summary->second.checksum) << "\n";
            }
        } else {
            stream << QStringLiteral("模型包无效: ")
                   << qs(summary->second.error) << "\n";
        }
    } else if (model->provider == "tiled_onnx") {
        stream << QStringLiteral("模型包: 未检验（无 artifact 登记或读取失败）\n");
    }
    stream << QStringLiteral("执行器: ")
           << (model->executor_available
                   ? QStringLiteral("可用")
                   : QStringLiteral("不可用 — ") + qs(model->executor_note))
           << "\n";
    detail_label_->setText(body);
    // Selectable = executable provider + (for packages) a validated
    // package whose checksum matches the registered identity. A checksum
    // drift means the model FILE changed — running it is forbidden.
    bool package_ok = true;
    if (model->provider == "tiled_onnx") {
        const auto it = summaries_.find(model_version_id);
        package_ok = it != summaries_.end() && it->second.ok &&
                     (!model->checksum.has_value() ||
                      model->checksum->empty() ||
                      *model->checksum == it->second.checksum);
    }
    ok_->setEnabled(model->executor_available && package_ok);
}

std::string ModelSelectionDialog::selected_model_version_id() const {
    return selected_;
}

bool ModelSelectionDialog::selection_confirmable() const {
    return ok_ != nullptr && ok_->isEnabled();
}

// ---------------------------------------------------------------------------
// PredictionParamsDialog
// ---------------------------------------------------------------------------

PredictionParamsDialog::PredictionParamsDialog(
    const domain::Json& current_params, QWidget* parent)
    : QDialog(parent), initial_(current_params) {
    setWindowTitle(QStringLiteral("预测运行参数"));
    setModal(true);
    auto* layout = new QVBoxLayout(this);
    auto* form = new QVBoxLayout();
    layout->addWidget(new QLabel(
        QStringLiteral("参数范围/默认值与推理内核一致；分块为 0/重叠为 -1 表示"
                       "采用模型包声明值"),
        this));
    const auto schema = pwb::prediction::prediction_param_schema();
    for (const auto& spec : schema) {
        auto* row = new QHBoxLayout();
        row->addWidget(new QLabel(qs(spec.label) + QStringLiteral("："), this));
        if (spec.type == pwb::prediction::PredictionParamSpec::Type::Bool) {
            auto* check = new QCheckBox(this);
            check->setChecked(current_params.contains(spec.key) &&
                              current_params[spec.key].is_boolean() &&
                              current_params[spec.key].get<bool>());
            check->setObjectName(qs(spec.key));
            row->addWidget(check);
            editors_.emplace_back(spec.key, check);
        } else {
            auto* spin = new QSpinBox(this);
            spin->setObjectName(qs(spec.key));
            spin->setRange(static_cast<int>(spec.min_value),
                           static_cast<int>(spec.max_value));
            const long long value =
                current_params.contains(spec.key) &&
                        current_params[spec.key].is_number_integer()
                    ? current_params[spec.key].get<long long>()
                    : spec.default_int;
            spin->setValue(static_cast<int>(
                std::clamp(value, spec.min_value,
                           spec.max_value > 0 ? spec.max_value
                                              : spec.min_value)));
            if (!spec.unit.empty()) {
                spin->setSuffix(QStringLiteral(" ") + qs(spec.unit));
            }
            spin->setToolTip(qs(spec.description));
            row->addWidget(spin);
            editors_.emplace_back(spec.key, spin);
        }
        auto* hint = new QLabel(qs(spec.description), this);
        hint->setWordWrap(true);
        row->addWidget(hint, 1);
        form->addLayout(row);
    }
    layout->addLayout(form);
    error_label_ = new QLabel(this);
    error_label_->setStyleSheet(QStringLiteral("color: #b00020"));
    layout->addWidget(error_label_);
    auto* buttons = new QDialogButtonBox(
        QDialogButtonBox::Ok | QDialogButtonBox::Cancel |
            QDialogButtonBox::RestoreDefaults,
        this);
    ok_ = buttons->button(QDialogButtonBox::Ok);
    connect(buttons, &QDialogButtonBox::accepted, this, &QDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, this, &QDialog::reject);
    auto* reset = buttons->button(QDialogButtonBox::RestoreDefaults);
    if (reset != nullptr) {
        connect(reset, &QPushButton::clicked, this, [this] {
            reset_to_defaults();
        });
    }
    connect(this, &QDialog::accepted, this, [this] {
        domain::Json params = domain::Json::object();
        for (const auto& [key, editor] : editors_) {
            if (auto* spin = qobject_cast<QSpinBox*>(editor);
                spin != nullptr) {
                params[key] = static_cast<long long>(spin->value());
            } else if (auto* check = qobject_cast<QCheckBox*>(editor);
                       check != nullptr) {
                params[key] = check->isChecked();
            }
        }
        current_ = std::move(params);
        params_changed_ = current_ != initial_;
    });
    layout->addWidget(buttons);
    setMinimumSize(QSize(520, 480));
    revalidate();
    // Re-check on every editor change: an invalid state can never be OK'd.
    for (const auto& [key, editor] : editors_) {
        if (auto* spin = qobject_cast<QSpinBox*>(editor); spin != nullptr) {
            connect(spin, &QSpinBox::valueChanged, this,
                    [this](int) { revalidate(); });
        } else if (auto* check = qobject_cast<QCheckBox*>(editor);
                   check != nullptr) {
            connect(check, &QCheckBox::toggled, this,
                    [this](bool) { revalidate(); });
        }
    }
}

void PredictionParamsDialog::reset_to_defaults() {
    const domain::Json defaults = pwb::prediction::default_prediction_params();
    for (const auto& [key, editor] : editors_) {
        if (auto* spin = qobject_cast<QSpinBox*>(editor); spin != nullptr) {
            spin->setValue(static_cast<int>(defaults[key].get<long long>()));
        } else if (auto* check = qobject_cast<QCheckBox*>(editor);
                   check != nullptr) {
            check->setChecked(defaults[key].get<bool>());
        }
    }
    revalidate();
}

void PredictionParamsDialog::revalidate() {
    domain::Json params = domain::Json::object();
    for (const auto& [key, editor] : editors_) {
        if (auto* spin = qobject_cast<QSpinBox*>(editor); spin != nullptr) {
            params[key] = static_cast<long long>(spin->value());
        } else if (auto* check = qobject_cast<QCheckBox*>(editor);
                   check != nullptr) {
            params[key] = check->isChecked();
        }
    }
    const auto errors = pwb::prediction::validate_prediction_params(params);
    if (errors.empty()) {
        error_label_->clear();
        ok_->setEnabled(true);
        return;
    }
    QString joined;
    for (const auto& error : errors) {
        if (!joined.isEmpty()) joined += QStringLiteral("; ");
        joined += qs(error);
    }
    error_label_->setText(joined);
    ok_->setEnabled(false);
}

domain::Json PredictionParamsDialog::params() const { return current_; }

}  // namespace pwb::closure_science::qt
