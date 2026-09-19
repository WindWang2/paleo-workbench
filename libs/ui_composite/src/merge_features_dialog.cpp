#include <pwb/ui_composite/merge_features_dialog.hpp>

#include <pwb/ui_composite/merge_plan.hpp>

#include <QDialogButtonBox>
#include <QLabel>
#include <QVBoxLayout>

namespace pwb::ui_composite {

namespace {

// Python str(v) parity for JSON scalars; null -> "".
std::string json_text(const Json& value) {
    if (value.is_null()) return "";
    if (value.is_string()) return value.get<std::string>();
    if (value.is_boolean()) return value.get<bool>() ? "True" : "False";
    if (value.is_number()) {
        if (value.is_number_integer()) {
            return std::to_string(value.get<long long>());
        }
        if (value.is_number_unsigned()) {
            return std::to_string(value.get<unsigned long long>());
        }
        std::string text = value.dump();
        // Python prints floats without trailing ".0" only via repr —
        // Json dump already matches (e.g. 12.0 -> "12.0").
        return text;
    }
    return value.dump();
}

QString qstr(const std::string& text) {
    return QString::fromStdString(text);
}

}  // namespace

MergeFeaturesDialog::MergeFeaturesDialog(
    std::vector<Json> records, std::vector<std::string> facies_fields,
    QWidget* parent)
    : QDialog(parent),
      records_(std::move(records)),
      plan_(plan_merge_attributes(records_, facies_fields)),
      attributes_(plan_.value("attributes", Json::object())) {
    setObjectName("MergeFeaturesDialog");
    setWindowTitle(QStringLiteral("合并要素"));

    auto* layout = new QVBoxLayout(this);
    auto* intro = new QLabel(
        QStringLiteral("合并后保留一块几何。属性默认取面积最大的要素，可改源或改值。"),
        this);
    intro->setWordWrap(true);
    layout->addWidget(intro);

    source_ = new QComboBox(this);
    for (const Json& record : records_) {
        const std::string feature_id =
            json_text(record.value("id", Json()));
        source_->addItem(qstr(feature_id), qstr(feature_id));
    }
    const std::string target = plan_.value("target_id", "");
    const int index = source_->findData(qstr(target));
    if (index >= 0) source_->setCurrentIndex(index);
    connect(source_, &QComboBox::currentIndexChanged, this,
            &MergeFeaturesDialog::on_source_changed);
    layout->addWidget(new QLabel(QStringLiteral("属性来源："), this));
    layout->addWidget(source_);

    form_ = new QFormLayout();
    layout->addLayout(form_);
    rebuild_form();

    auto* buttons = new QDialogButtonBox(
        QDialogButtonBox::Ok | QDialogButtonBox::Cancel, this);
    connect(buttons, &QDialogButtonBox::accepted, this,
            &MergeFeaturesDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, this,
            &MergeFeaturesDialog::reject);
    layout->addWidget(buttons);
}

std::set<std::string> MergeFeaturesDialog::conflicts() const {
    std::set<std::string> out;
    const Json conflicts = plan_.value("conflicts", Json::object());
    if (conflicts.is_object()) {
        for (auto it = conflicts.begin(); it != conflicts.end(); ++it) {
            out.insert(it.key());
        }
    }
    return out;
}

std::set<std::string> MergeFeaturesDialog::facies_field_names() const {
    std::set<std::string> out;
    const Json fields = plan_.value("facies_fields", Json::array());
    if (fields.is_array()) {
        for (const Json& name : fields) {
            if (name.is_string()) out.insert(name.get<std::string>());
        }
    }
    if (out.empty()) out.insert("facies");
    return out;
}

void MergeFeaturesDialog::rebuild_form() {
    while (form_->rowCount() > 0) form_->removeRow(0);
    edits_.clear();
    std::vector<std::string> keys;
    if (attributes_.is_object()) {
        for (auto it = attributes_.begin(); it != attributes_.end(); ++it) {
            keys.push_back(it.key());
        }
    }
    for (const std::string& key : conflicts()) {
        if (std::find(keys.begin(), keys.end(), key) == keys.end()) {
            keys.push_back(key);
        }
    }
    const std::set<std::string> conflict_set = conflicts();
    const std::set<std::string> facies = facies_field_names();
    for (const std::string& key : keys) {
        auto* edit = new QLineEdit(this);
        const Json value =
            attributes_.is_object() && attributes_.contains(key)
                ? attributes_[key]
                : Json();
        edit->setText(qstr(json_text(value)));
        connect(edit, &QLineEdit::textChanged, this,
                [this, key](const QString& text) {
                    attributes_[key] = text.toStdString();
                });
        if (conflict_set.count(key)) {
            // 冲突高亮：相分类字段更醒目。
            const QString color = facies.count(key) ? "#fde8a0" : "#fff3cd";
            edit->setStyleSheet(
                QStringLiteral("QLineEdit { background: %1; }").arg(color));
            edit->setToolTip(QStringLiteral("所选要素该字段值不一致"));
        }
        form_->addRow(qstr(key), edit);
        edits_[key] = edit;
    }
}

void MergeFeaturesDialog::on_source_changed(int index) {
    if (index < 0 || index >= static_cast<int>(records_.size())) return;
    const Json& record = records_[static_cast<size_t>(index)];
    plan_["target_id"] = json_text(record.value("id", Json()));
    const Json properties = record.value("properties", Json::object());
    attributes_ = properties.is_object() ? properties : Json::object();
    rebuild_form();
}

void MergeFeaturesDialog::set_field_value(const std::string& field,
                                          const Json& value) {
    const std::string text = json_text(value);
    attributes_[field] = text;
    auto it = edits_.find(field);
    if (it != edits_.end() && it->second != nullptr) {
        it->second->setText(qstr(text));
    } else {
        rebuild_form();
    }
}

Json MergeFeaturesDialog::result_payload() const {
    return {{"target_id", plan_.value("target_id", "")},
            {"attributes", attributes_}};
}

}  // namespace pwb::ui_composite
