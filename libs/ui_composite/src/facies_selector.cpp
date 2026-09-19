#include <pwb/ui_composite/facies_selector.hpp>

#include <pwb/ui_widgets/core/facies_taxonomy.hpp>

#include <QDialogButtonBox>
#include <QFileDialog>
#include <QHBoxLayout>
#include <QLabel>
#include <QListWidgetItem>
#include <QMessageBox>
#include <QPushButton>
#include <QVBoxLayout>

#include <algorithm>
#include <fstream>
#include <sstream>

namespace pwb::ui_composite {

namespace {

using pwb::ui_widgets::core::kFaciesLevelKeys;
using pwb::ui_widgets::core::kLevelLabels;

const QString kEmpty;  // 子级「不填/清空」哨兵

int level_index(const std::string& level) {
    for (size_t i = 0; i < kFaciesLevelKeys.size(); ++i) {
        if (kFaciesLevelKeys[i] == level) return static_cast<int>(i);
    }
    return -1;
}

QString level_label(const std::string& level) {
    auto it = kLevelLabels.find(level);
    return it == kLevelLabels.end()
               ? QString::fromStdString(level)
               : QString::fromStdString(it->second);
}

QString source_label(const FaciesTaxonomy& taxonomy) {
    return taxonomy.source == "project" ? QStringLiteral("工程覆盖")
                                        : QStringLiteral("内置默认");
}

}  // namespace

// ---------------------------------------------------------------------------
// FaciesCascadeSelector
// ---------------------------------------------------------------------------

FaciesCascadeSelector::FaciesCascadeSelector(const FaciesTaxonomy& taxonomy,
                                             QWidget* parent)
    : QWidget(parent), taxonomy_(taxonomy) {
    setObjectName("FaciesCascadeSelector");

    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->setSpacing(6);
    for (const std::string& level : kFaciesLevelKeys) {
        auto* row = new QHBoxLayout();
        auto* label =
            new QLabel(level_label(level) + QStringLiteral("："), this);
        label->setMinimumWidth(48);
        auto* combo = new QComboBox(this);
        combo->setObjectName(
            QStringLiteral("FaciesLevel_%1").arg(QString::fromStdString(level)));
        row->addWidget(label);
        row->addWidget(combo, 1);
        layout->addLayout(row);
        combos[level] = combo;
    }
    connect(combos["facies"], &QComboBox::currentTextChanged, this,
            [this](const QString&) { repopulate_level("sub_facies"); });
    connect(combos["sub_facies"], &QComboBox::currentTextChanged, this,
            [this](const QString&) { repopulate_level("micro_facies"); });
    repopulate();
}

void FaciesCascadeSelector::repopulate() {
    for (const std::string& level : kFaciesLevelKeys) {
        repopulate_level(level);
    }
}

void FaciesCascadeSelector::repopulate_level(const std::string& level) {
    const int index = level_index(level);
    if (index < 0) return;
    QComboBox* combo = combos[level];
    std::vector<std::string> parents;
    for (int i = 0; i < index; ++i) {
        parents.push_back(
            combos[kFaciesLevelKeys[i]]->currentText().trimmed().toStdString());
    }
    const QString current = combo->currentText();
    combo->blockSignals(true);
    combo->clear();
    if (level != "facies") {
        combo->addItem(kEmpty, kEmpty);  // 不填：任一级可停
    }
    for (const std::string& name : taxonomy_.names(level, parents)) {
        combo->addItem(QString::fromStdString(name),
                       QString::fromStdString(name));
    }
    // 父链变化后原值可能不在候选里——保不住就清空。
    const int found = current.isEmpty() ? -1 : combo->findText(current);
    combo->setCurrentIndex(found >= 0 ? found : 0);
    combo->blockSignals(false);
    // 子级联动清理由 currentTextChanged 在取消阻塞后统一触发；此处手工
    // 级联（Python 同语义）。
    if (index + 1 < static_cast<int>(kFaciesLevelKeys.size()) &&
        combo->currentText() != current) {
        repopulate_level(kFaciesLevelKeys[index + 1]);
    }
}

std::map<std::string, std::string> FaciesCascadeSelector::selection() const {
    std::map<std::string, std::string> out;
    for (const std::string& level : kFaciesLevelKeys) {
        out[level] =
            combos.at(level)->currentText().trimmed().toStdString();
    }
    return out;
}

void FaciesCascadeSelector::set_selection(const Json& attributes) {
    const auto values =
        FaciesTaxonomy::selection_from_attributes(attributes);
    auto value_of = [&](const char* key) -> QString {
        auto it = values.find(key);
        return it == values.end() ? QString()
                                  : QString::fromStdString(it->second);
    };
    combos["facies"]->setCurrentText(value_of("facies"));
    repopulate_level("sub_facies");
    combos["sub_facies"]->setCurrentText(value_of("sub_facies"));
    repopulate_level("micro_facies");
    combos["micro_facies"]->setCurrentText(value_of("micro_facies"));
}

// ---------------------------------------------------------------------------
// FaciesSelectionDialog
// ---------------------------------------------------------------------------

FaciesSelectionDialog::FaciesSelectionDialog(
    const FaciesTaxonomy& taxonomy, const Json& current,
    const QString& title, const std::string& anchor_level, QWidget* parent)
    : QDialog(parent) {
    setObjectName("FaciesSelectionDialog");
    static const std::map<std::string, QString> depth_hints = {
        {"facies", QStringLiteral("（本图层为相图：一般选到相即可）")},
        {"sub_facies", QStringLiteral("（本图层为亚相图：建议选到亚相）")},
        {"micro_facies",
         QStringLiteral("（本图层为微相图：建议选到微相）")},
    };
    auto hint = depth_hints.find(anchor_level);
    setWindowTitle(title + QStringLiteral(" ") +
                   (hint == depth_hints.end() ? QString() : hint->second));
    auto* layout = new QVBoxLayout(this);
    selector_ = new FaciesCascadeSelector(taxonomy, this);
    if (current.is_object() && !current.empty()) {
        selector_->set_selection(current);
    }
    layout->addWidget(selector_);
    auto* buttons = new QDialogButtonBox(
        QDialogButtonBox::Ok | QDialogButtonBox::Cancel, this);
    buttons->button(QDialogButtonBox::Ok)
        ->setText(QStringLiteral("确定"));
    buttons->button(QDialogButtonBox::Cancel)
        ->setText(QStringLiteral("取消"));
    connect(buttons, &QDialogButtonBox::accepted, this, &QDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, this, &QDialog::reject);
    layout->addWidget(buttons);
}

std::map<std::string, std::string> FaciesSelectionDialog::selection() const {
    auto values = selector_->selection();
    values["level"] = FaciesTaxonomy::selection_level(values);
    return values;
}

// ---------------------------------------------------------------------------
// FaciesChangeDialog
// ---------------------------------------------------------------------------

FaciesChangeDialog::FaciesChangeDialog(
    const FaciesTaxonomy& taxonomy, const Json& current,
    const QString& title, int count, const std::string& anchor_level,
    QWidget* parent)
    : QDialog(parent), taxonomy_(taxonomy) {
    setObjectName("FaciesChangeDialog");
    anchor_ = level_index(anchor_level) >= 0 ? anchor_level : "facies";
    const int anchor_index = level_index(anchor_);
    for (size_t i = anchor_index + 1; i < kFaciesLevelKeys.size(); ++i) {
        lower_.push_back(kFaciesLevelKeys[i]);
    }
    all_names_ = taxonomy.names(anchor_);
    const auto values =
        FaciesTaxonomy::selection_from_attributes(
            current.is_object() ? current : Json::object());
    setWindowTitle(title);
    setMinimumWidth(360);

    auto* layout = new QVBoxLayout(this);
    auto* scope = new QLabel(
        count > 1
            ? QStringLiteral("将修改 %1 个要素的%2属性")
                  .arg(count)
                  .arg(level_label(anchor_))
            : QStringLiteral("修改该要素的%1属性").arg(level_label(anchor_)),
        this);
    scope->setObjectName("FaciesChangeScope");
    layout->addWidget(scope);

    search_ = new QLineEdit(this);
    search_->setPlaceholderText(
        QStringLiteral("搜索%1…").arg(level_label(anchor_)));
    search_->setClearButtonEnabled(true);
    connect(search_, &QLineEdit::textChanged, this,
            [this](const QString&) { refill(); });
    layout->addWidget(search_);

    list_ = new QListWidget(this);
    list_->setObjectName("FaciesChangeList");
    list_->setMinimumHeight(220);
    connect(list_, &QListWidget::currentTextChanged, this,
            [this](const QString&) {
                repopulate_lower(lower_.empty() ? "" : lower_.front());
            });
    layout->addWidget(list_, 1);

    if (!lower_.empty()) {
        auto* refine = new QHBoxLayout();
        auto* hint = new QLabel(QStringLiteral("细化（可选）："), this);
        hint->setMinimumWidth(84);
        refine->addWidget(hint);
        for (const std::string& level : lower_) {
            auto* combo = new QComboBox(this);
            combo->setObjectName(QStringLiteral("FaciesRefine_%1")
                                     .arg(QString::fromStdString(level)));
            connect(combo, &QComboBox::currentTextChanged, this,
                    [this, level](const QString&) {
                        repopulate_lower(level);
                    });
            refine->addWidget(combo, 1);
            refine_rows_[level] = combo;
        }
        refine->addStretch(1);
        layout->addLayout(refine);
    }

    auto* buttons = new QDialogButtonBox(
        QDialogButtonBox::Ok | QDialogButtonBox::Cancel, this);
    buttons->button(QDialogButtonBox::Ok)
        ->setText(QStringLiteral("确定"));
    buttons->button(QDialogButtonBox::Cancel)
        ->setText(QStringLiteral("取消"));
    connect(buttons, &QDialogButtonBox::accepted, this, &QDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, this, &QDialog::reject);
    layout->addWidget(buttons);

    auto it = values.find(anchor_);
    refill(it == values.end() ? QString()
                              : QString::fromStdString(it->second));
}

void FaciesChangeDialog::refill(const QString& preselected) {
    const QString needle = search_->text().trimmed();
    QString keep = preselected.isEmpty() ? selected_facies() : preselected;
    list_->blockSignals(true);
    list_->clear();
    for (const std::string& name : all_names_) {
        const QString text = QString::fromStdString(name);
        if (!needle.isEmpty() && !text.contains(needle)) continue;
        list_->addItem(new QListWidgetItem(text));
    }
    list_->blockSignals(false);
    const QString target =
        !keep.isEmpty()
            ? keep
            : (list_->count() ? list_->item(0)->text() : QString());
    if (!target.isEmpty()) select_facies(target);
    repopulate_lower(lower_.empty() ? "" : lower_.front());
}

void FaciesChangeDialog::repopulate_lower(const std::string& level) {
    auto row_it = refine_rows_.find(level);
    if (level.empty() || row_it == refine_rows_.end()) return;
    const int index = level_index(level);
    const std::vector<std::string> chain = selection_chain();
    std::vector<std::string> parents(chain.begin(),
                                     chain.begin() +
                                         std::min<int>(index,
                                                       chain.size()));
    QComboBox* combo = row_it->second;
    const QString current = combo->currentText();
    combo->blockSignals(true);
    combo->clear();
    combo->addItem(kEmpty, kEmpty);  // 任一级可停（不逼假数据）
    for (const std::string& name : taxonomy_.names(level, parents)) {
        combo->addItem(QString::fromStdString(name),
                       QString::fromStdString(name));
    }
    const int found = current.isEmpty() ? -1 : combo->findText(current);
    combo->setCurrentIndex(found >= 0 ? found : 0);
    combo->blockSignals(false);
    auto lower_it = std::find(lower_.begin(), lower_.end(), level);
    if (lower_it != lower_.end() && lower_it + 1 != lower_.end()) {
        repopulate_lower(*(lower_it + 1));
    }
}

std::vector<std::string> FaciesChangeDialog::selection_chain() const {
    std::vector<std::string> chain = {
        selected_facies().toStdString()};
    for (const std::string& level : lower_) {
        auto it = refine_rows_.find(level);
        chain.push_back(it == refine_rows_.end()
                            ? ""
                            : it->second->currentText()
                                  .trimmed()
                                  .toStdString());
    }
    return chain;
}

std::vector<QString> FaciesChangeDialog::listed_facies() const {
    std::vector<QString> out;
    for (int row = 0; row < list_->count(); ++row) {
        out.push_back(list_->item(row)->text());
    }
    return out;
}

QString FaciesChangeDialog::selected_facies() const {
    QListWidgetItem* item = list_->currentItem();
    return item != nullptr ? item->text() : QString();
}

void FaciesChangeDialog::select_facies(const QString& name) {
    for (int row = 0; row < list_->count(); ++row) {
        if (list_->item(row)->text() == name) {
            list_->setCurrentRow(row);
            return;
        }
    }
}

void FaciesChangeDialog::set_search_text(const QString& text) {
    search_->setText(text);
}

std::map<std::string, std::string> FaciesChangeDialog::selection() const {
    const std::vector<std::string> chain = selection_chain();
    std::map<std::string, std::string> values;
    for (size_t i = 0; i < kFaciesLevelKeys.size(); ++i) {
        values[kFaciesLevelKeys[i]] =
            i < chain.size() ? chain[i] : "";
    }
    // 锚定级别以下才允许细化：锚定级别以上保持空。
    for (int i = 0; i < level_index(anchor_); ++i) {
        values[kFaciesLevelKeys[i]] = "";
    }
    values["level"] = FaciesTaxonomy::selection_level(values);
    return values;
}

// ---------------------------------------------------------------------------
// FaciesTaxonomyDialog
// ---------------------------------------------------------------------------

FaciesTaxonomyDialog::FaciesTaxonomyDialog(
    const FaciesTaxonomy& taxonomy,
    std::function<FaciesTaxonomy()> make_builtin, QWidget* parent)
    : QDialog(parent), make_builtin_(std::move(make_builtin)) {
    setObjectName("FaciesTaxonomyDialog");
    setWindowTitle(QStringLiteral("相分类词表"));

    auto* layout = new QVBoxLayout(this);
    const auto [n_f, n_s, n_m] = taxonomy.counts();
    summary_ = new QLabel(
        QStringLiteral("当前词表（%1）：相 %2 · 亚相 %3 · 微相 %4")
            .arg(source_label(taxonomy))
            .arg(n_f)
            .arg(n_s)
            .arg(n_m),
        this);
    layout->addWidget(summary_);

    tree_ = new QTreeWidget(this);
    tree_->setHeaderLabels(
        {QStringLiteral("名称"), QStringLiteral("子级数")});
    tree_->setColumnWidth(0, 260);
    layout->addWidget(tree_, 1);
    fill_tree(taxonomy);

    auto* actions = new QHBoxLayout();
    auto* import_button =
        new QPushButton(QStringLiteral("从 GeoJSON 导入…"), this);
    connect(import_button, &QPushButton::clicked, this,
            &FaciesTaxonomyDialog::on_import);
    auto* reset_button =
        new QPushButton(QStringLiteral("恢复内置默认"), this);
    connect(reset_button, &QPushButton::clicked, this,
            &FaciesTaxonomyDialog::on_reset);
    actions->addWidget(import_button);
    actions->addWidget(reset_button);
    actions->addStretch(1);
    layout->addLayout(actions);

    auto* buttons = new QDialogButtonBox(
        QDialogButtonBox::Ok | QDialogButtonBox::Cancel, this);
    buttons->button(QDialogButtonBox::Ok)
        ->setText(QStringLiteral("确定"));
    buttons->button(QDialogButtonBox::Cancel)
        ->setText(QStringLiteral("取消"));
    connect(buttons, &QDialogButtonBox::accepted, this,
            &FaciesTaxonomyDialog::on_accept);
    connect(buttons, &QDialogButtonBox::rejected, this, &QDialog::reject);
    layout->addWidget(buttons);

    tree_->setMinimumHeight(300);
    resize(560, 560);
}

void FaciesTaxonomyDialog::fill_tree(const FaciesTaxonomy& taxonomy) {
    tree_->clear();
    const nlohmann::ordered_json doc = taxonomy.to_project_dict();
    const nlohmann::ordered_json tree =
        doc.value("tree", nlohmann::ordered_json::object());

    std::function<void(const nlohmann::ordered_json&, QTreeWidgetItem*)>
        walk = [&](const nlohmann::ordered_json& node,
                   QTreeWidgetItem* parent) {
            for (auto it = node.begin(); it != node.end(); ++it) {
                const auto& children = it.value();
                const int child_count =
                    children.is_object() ? static_cast<int>(children.size()) : 0;
                auto* item = new QTreeWidgetItem(
                    {QString::fromStdString(it.key()),
                     QString::number(child_count)});
                if (parent != nullptr) {
                    parent->addChild(item);
                } else {
                    tree_->addTopLevelItem(item);
                }
                if (children.is_object()) walk(children, item);
            }
        };
    if (tree.is_object()) walk(tree, nullptr);
    tree_->expandToDepth(0);
}

void FaciesTaxonomyDialog::on_import() {
    const QStringList paths = QFileDialog::getOpenFileNames(
        this,
        QStringLiteral(
            "导入参考相图 GeoJSON（相/亚相/微相兄弟组，可多选）"),
        QString(), QStringLiteral("GeoJSON (*.geojson *.json)"));
    if (paths.isEmpty()) return;
    nlohmann::json features = nlohmann::json::array();
    for (const QString& path : paths) {
        std::ifstream stream(path.toStdString());
        nlohmann::json payload;
        try {
            stream >> payload;
        } catch (const std::exception& exc) {
            QMessageBox::warning(
                this, QStringLiteral("导入失败"),
                QStringLiteral("%1：%2").arg(path, exc.what()));
            return;
        }
        if (payload.is_object() && payload.contains("features") &&
            payload["features"].is_array()) {
            for (const auto& feature : payload["features"]) {
                features.push_back(feature);
            }
        }
    }
    FaciesTaxonomy taxonomy =
        FaciesTaxonomy::from_geojson_features(features);
    const auto [n_f, n_s, n_m] = taxonomy.counts();
    if (!n_f) {
        QMessageBox::warning(
            this, QStringLiteral("导入失败"),
            QStringLiteral(
                "所选文件没有带 level/parent_id 属性的相图要素——"
                "无法重建三级词表"));
        return;
    }
    incoming_ = taxonomy;
    fill_tree(taxonomy);
    summary_->setText(
        QStringLiteral(
            "待应用（%1·导入预览）：相 %2 · 亚相 %3 · 微相 %4 —— "
            "点「确定」生效")
            .arg(source_label(taxonomy))
            .arg(n_f)
            .arg(n_s)
            .arg(n_m));
}

void FaciesTaxonomyDialog::on_reset() {
    if (!make_builtin_) return;
    FaciesTaxonomy taxonomy = make_builtin_();
    incoming_ = taxonomy;
    fill_tree(taxonomy);
    const auto [n_f, n_s, n_m] = taxonomy.counts();
    summary_->setText(
        QStringLiteral(
            "待应用（内置默认·恢复预览）：相 %1 · 亚相 %2 · 微相 %3"
            " —— 点「确定」生效")
            .arg(n_f)
            .arg(n_s)
            .arg(n_m));
}

void FaciesTaxonomyDialog::on_accept() {
    taxonomy_accepted = true;
    accept();
}

std::optional<FaciesTaxonomy> FaciesTaxonomyDialog::result_taxonomy() const {
    return taxonomy_accepted ? incoming_ : std::nullopt;
}

}  // namespace pwb::ui_composite
