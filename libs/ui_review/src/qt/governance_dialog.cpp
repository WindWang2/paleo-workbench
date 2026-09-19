#include "pwb/ui_review/qt/governance_dialog.hpp"

#include "pwb/catalog/policies.hpp"
#include "pwb/ui_review/tokens.hpp"

#include <QComboBox>
#include <QFormLayout>
#include <QHBoxLayout>
#include <QLabel>
#include <QLineEdit>
#include <QPushButton>
#include <QVBoxLayout>

namespace pwb::ui_review::qt {

namespace {

std::string current_str(const domain::Json& current, const char* key) {
    const auto it = current.find(key);
    return (it != current.end() && it->is_string())
               ? it->get<std::string>()
               : "";
}

}  // namespace

GovernanceMetadataDialog::GovernanceMetadataDialog(
    QWidget* parent, const QString& asset_name, const domain::Json& current)
    : QDialog(parent) {
    setWindowTitle(asset_name.isEmpty()
                       ? QStringLiteral("编辑治理信息")
                       : QStringLiteral("编辑治理信息 — ") + asset_name);
    setMinimumWidth(420);

    auto* layout = new QVBoxLayout(this);
    layout->setSpacing(tokens::kSpace2);

    auto* form = new QFormLayout();
    source_edit_ =
        new QLineEdit(QString::fromStdString(current_str(current, "source")),
                      this);
    source_edit_->setPlaceholderText(
        QStringLiteral("数据来源说明（如: 甲方移交 / 野外采集）"));
    form->addRow(QStringLiteral("来源 (source):"), source_edit_);

    region_edit_ =
        new QLineEdit(QString::fromStdString(current_str(current, "region")),
                      this);
    region_edit_->setPlaceholderText(
        QStringLiteral("研究区域（如: 塔里木盆地）"));
    form->addRow(QStringLiteral("区域 (region):"), region_edit_);

    creator_edit_ = new QLineEdit(
        QString::fromStdString(current_str(current, "creator")), this);
    creator_edit_->setPlaceholderText(
        QStringLiteral("负责人 / 解释工程师"));
    form->addRow(QStringLiteral("负责人 (creator):"), creator_edit_);

    discipline_combo_ =
        vocab_combo("discipline", current_str(current, "discipline"));
    form->addRow(QStringLiteral("学科方向 (discipline):"),
                 discipline_combo_);
    confidence_combo_ =
        vocab_combo("confidence", current_str(current, "confidence"));
    form->addRow(QStringLiteral("可信等级 (confidence):"),
                 confidence_combo_);
    review_combo_ =
        vocab_combo("review_status", current_str(current, "review_status"));
    form->addRow(QStringLiteral("审核状态 (review_status):"), review_combo_);
    layout->addLayout(form);

    auto* hint = new QLabel(
        QStringLiteral(
            "提示: 留空/选“未设置”表示清除该字段；受控字段将按词表归一化存储。"
            "版本数据保持不可变 — 治理信息仅记录在资产级别。"),
        this);
    hint->setWordWrap(true);
    hint->setStyleSheet(
        QStringLiteral("font-size: 12px; color: palette(mid);"));
    layout->addWidget(hint);

    error_label_ = new QLabel(QString(), this);
    error_label_->setWordWrap(true);
    error_label_->setStyleSheet(
        QString::fromUtf8(tokens::kErrorRed.data(),
                          int(tokens::kErrorRed.size()))
            .prepend("color: "));
    error_label_->hide();
    layout->addWidget(error_label_);

    auto* buttons = new QHBoxLayout();
    auto* cancel = new QPushButton(QStringLiteral("取消"), this);
    connect(cancel, &QPushButton::clicked, this, &QDialog::reject);
    buttons->addWidget(cancel);
    auto* ok = new QPushButton(QStringLiteral("保存"), this);
    ok->setObjectName(QStringLiteral("PrimaryButton"));
    connect(ok, &QPushButton::clicked, this,
            &GovernanceMetadataDialog::on_save);
    buttons->addWidget(ok);
    layout->addLayout(buttons);
}

QComboBox*
GovernanceMetadataDialog::vocab_combo(const std::string& key,
                                      const std::string& current) {
    auto* combo = new QComboBox(this);
    combo->addItem(QStringLiteral("未设置"), QString());
    // GOVERNANCE_FIELDS[key] — vocabulary + zh display labels.
    for (const auto& spec : catalog::governance_fields()) {
        if (spec.key != key) {
            continue;
        }
        for (const auto& value : spec.vocabulary) {
            QString display = QString::fromStdString(value);
            for (const auto& [v, zh] : spec.display) {
                if (v == value) {
                    display = QString::fromStdString(zh);
                    break;
                }
            }
            combo->addItem(display, QString::fromStdString(value));
        }
        break;
    }
    if (!current.empty()) {
        const int index =
            combo->findData(QString::fromStdString(current));
        if (index >= 0) {
            combo->setCurrentIndex(index);
        }
    }
    return combo;
}

domain::Result<domain::Json> GovernanceMetadataDialog::patch() const {
    // Ordered like the Python dict literal: source, region, creator,
    // discipline, confidence, review_status.
    const std::pair<const char*, std::string> values[] = {
        {"source", source_edit_->text().trimmed().toStdString()},
        {"region", region_edit_->text().trimmed().toStdString()},
        {"creator", creator_edit_->text().trimmed().toStdString()},
        {"discipline",
         discipline_combo_->currentData().toString().toStdString()},
        {"confidence",
         confidence_combo_->currentData().toString().toStdString()},
        {"review_status",
         review_combo_->currentData().toString().toStdString()},
    };
    domain::Json out = domain::Json::object();
    for (const auto& [key, value] : values) {
        auto normalized =
            catalog::normalize_governance_value(key, domain::Json(value));
        if (!normalized) {
            return normalized.error();
        }
        out[key] = normalized.value();
    }
    return out;
}

void GovernanceMetadataDialog::on_save() {
    const auto result = patch();
    if (!result) {
        error_label_->setText(
            QString::fromStdString(result.error().message));
        error_label_->show();
        return;
    }
    accept();
}

}  // namespace pwb::ui_review::qt
