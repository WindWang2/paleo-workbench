#include <pwb/ui_composite/topology_checker_panel.hpp>

#include <pwb/ui_composite/composite_controller.hpp>
#include <pwb/ui_composite/topology_service.hpp>

#include <QColor>
#include <QFont>
#include <QHBoxLayout>
#include <QVariantMap>
#include <QVBoxLayout>

namespace pwb::ui_composite {

namespace {

const std::map<std::string, QString>& rule_labels() {
    static const std::map<std::string, QString> labels = {
        {"", QStringLiteral("全部规则")},
        {"overlap", QStringLiteral("面重叠")},
        {"gap", QStringLiteral("面缝隙")},
        {"is_valid", QStringLiteral("几何有效性")},
        {"workspace_remainder", QStringLiteral("工区余量")},
        {"dangle", QStringLiteral("线悬挂点")},
    };
    return labels;
}

std::string str_field(const Json& object, const char* key) {
    if (!object.is_object()) return "";
    auto it = object.find(key);
    if (it == object.end() || it->is_null()) return "";
    if (it->is_string()) return it->get<std::string>();
    if (it->is_number() || it->is_boolean()) return it->dump();
    return "";
}

QVariant json_to_variant(const Json& value) {
    if (value.is_null()) return {};
    if (value.is_boolean()) return value.get<bool>();
    if (value.is_number_integer()) {
        return QVariant::fromValue<qlonglong>(value.get<long long>());
    }
    if (value.is_number_unsigned()) {
        return QVariant::fromValue<qulonglong>(value.get<unsigned long long>());
    }
    if (value.is_number_float()) return value.get<double>();
    if (value.is_string()) {
        return QString::fromStdString(value.get<std::string>());
    }
    if (value.is_array()) {
        QVariantList list;
        for (const Json& entry : value) list.append(json_to_variant(entry));
        return list;
    }
    if (value.is_object()) {
        QVariantMap map;
        for (auto it = value.begin(); it != value.end(); ++it) {
            map[QString::fromStdString(it.key())] = json_to_variant(it.value());
        }
        return map;
    }
    return {};
}

QVariantMap json_to_map(const Json& object) {
    const QVariant variant = json_to_variant(object);
    return variant.toMap();
}

}  // namespace

TopologyCheckerPanel::TopologyCheckerPanel(QWidget* parent)
    : QWidget(parent) {
    setObjectName("TopologyCheckerPanel");

    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(8, 8, 8, 8);

    badge = new QLabel(QStringLiteral("尚未检查"), this);
    badge->setObjectName("TopologyCheckerBadge");
    layout->addWidget(badge);

    rule_filter = new QComboBox(this);
    for (const auto& [key, label] : rule_labels()) {
        rule_filter->addItem(label, QString::fromStdString(key));
    }
    connect(rule_filter, &QComboBox::currentIndexChanged, this,
            [this](int) { rebuild(); });
    layout->addWidget(rule_filter);

    error_list = new QListWidget(this);
    error_list->setObjectName("TopologyCheckerErrorList");
    error_list->setContextMenuPolicy(Qt::CustomContextMenu);
    connect(error_list, &QListWidget::itemClicked, this,
            &TopologyCheckerPanel::on_item_clicked);
    connect(error_list, &QListWidget::customContextMenuRequested, this,
            &TopologyCheckerPanel::on_menu);
    layout->addWidget(error_list, 1);

    auto* buttons = new QHBoxLayout();
    check_button = new QPushButton(QStringLiteral("检查"), this);
    fix_button = new QPushButton(QStringLiteral("修复"), this);
    fix_all_button = new QPushButton(QStringLiteral("全部修复"), this);
    ignore_button = new QPushButton(QStringLiteral("忽略"), this);
    restore_button = new QPushButton(QStringLiteral("恢复"), this);
    connect(check_button, &QPushButton::clicked, this,
            &TopologyCheckerPanel::on_check);
    connect(fix_button, &QPushButton::clicked, this,
            &TopologyCheckerPanel::on_fix);
    connect(fix_all_button, &QPushButton::clicked, this,
            &TopologyCheckerPanel::fix_all_requested);
    connect(ignore_button, &QPushButton::clicked, this,
            &TopologyCheckerPanel::on_ignore);
    connect(restore_button, &QPushButton::clicked, this,
            &TopologyCheckerPanel::on_restore);
    for (QPushButton* button :
         {check_button, fix_button, fix_all_button, ignore_button,
          restore_button}) {
        buttons->addWidget(button);
    }
    layout->addLayout(buttons);
}

void TopologyCheckerPanel::bind(CompositeEditController* controller) {
    controller_ = controller;
}

void TopologyCheckerPanel::set_errors(
    const std::vector<Json>& errors,
    const std::set<IgnoreKey>& ignored_keys,
    const std::string& last_run_at) {
    all_errors_ = errors;
    ignored_keys_ = ignored_keys;
    if (!last_run_at.empty()) last_run_at_ = last_run_at;
    int blocking = 0;
    for (const Json& error : all_errors_) {
        if (!ignored_keys_.count(ignore_key(error))) ++blocking;
    }
    const QString stamp = QString::fromStdString(last_run_at_);
    if (!stamp.isEmpty()) {
        badge->setText(QStringLiteral("%1 处未忽略 · %2")
                           .arg(blocking)
                           .arg(stamp));
    } else if (!all_errors_.empty()) {
        badge->setText(QStringLiteral("%1 处未忽略").arg(blocking));
    } else {
        badge->setText(QStringLiteral("尚未检查"));
    }
    rebuild();
}

void TopologyCheckerPanel::rebuild() {
    const std::string rule =
        rule_filter->currentData().toString().toStdString();
    error_list->clear();
    for (const Json& error : all_errors_) {
        if (!rule.empty() && str_field(error, "rule") != rule) continue;
        QString label = QString::fromStdString(
            !str_field(error, "message").empty()
                ? str_field(error, "message")
                : !str_field(error, "rule").empty()
                      ? str_field(error, "rule")
                      : "error");
        const std::string feature_id = str_field(error, "feature_id");
        if (!feature_id.empty()) {
            label += QStringLiteral("（%1）")
                         .arg(QString::fromStdString(feature_id));
        }
        auto* item = new QListWidgetItem(label, error_list);
        item->setData(Qt::UserRole, json_to_variant(error));
        if (ignored_keys_.count(ignore_key(error))) {
            item->setForeground(QColor(160, 160, 160));
            QFont font = item->font();
            font.setItalic(true);
            item->setFont(font);
        }
    }
}

Json TopologyCheckerPanel::current_error() const {
    QListWidgetItem* item = error_list->currentItem();
    if (item == nullptr) return Json();
    const QVariant payload = item->data(Qt::UserRole);
    // QVariant -> Json round-trip is lossy for nested payloads; keep the
    // vector<Json> lookup by id instead.
    const QVariantMap map = payload.toMap();
    const std::string id = map.value("id").toString().toStdString();
    for (const Json& error : all_errors_) {
        if (str_field(error, "id") == id) return error;
    }
    // Fallback: reconstitute a shallow record (menus need id/methods only).
    Json out = Json::object();
    for (auto it = map.begin(); it != map.end(); ++it) {
        const QVariant v = it.value();
        if (v.typeId() == QMetaType::QString) {
            out[it.key().toStdString()] = v.toString().toStdString();
        } else if (v.typeId() == QMetaType::Double ||
                   v.typeId() == QMetaType::Int ||
                   v.typeId() == QMetaType::LongLong) {
            out[it.key().toStdString()] = v.toDouble();
        } else if (v.typeId() == QMetaType::Bool) {
            out[it.key().toStdString()] = v.toBool();
        }
    }
    return out;
}

void TopologyCheckerPanel::on_item_clicked(QListWidgetItem* item) {
    const Json error = current_error();
    (void)item;
    if (!error.is_object()) return;
    const Json bbox = error.value("bbox", Json::array());
    if (bbox.is_array() && bbox.size() >= 4) {
        emit zoom_requested({bbox[0].get<double>(), bbox[1].get<double>(),
                             bbox[2].get<double>(), bbox[3].get<double>()});
    }
    const std::string error_id = str_field(error, "id");
    if (!error_id.empty()) {
        emit highlight_requested(QString::fromStdString(error_id));
    }
}

void TopologyCheckerPanel::on_check() {
    if (controller_ != nullptr) {
        const std::vector<Json> errors = controller_->run_topology_checks();
        TopologyChecker& checker = controller_->topology().checker();
        std::string stamp = checker.last_run_at.value_or("");
        set_errors(errors, checker.ignored_keys(), stamp);
        return;
    }
    emit check_requested();
}

QMenu* TopologyCheckerPanel::menu_for(const Json& error) {
    auto* menu = new QMenu(this);
    Json methods = error.value("methods", Json::array());
    if (!methods.is_array() || methods.empty()) {
        methods = Json::array({Json{{"id", 0}, {"name", "修复"}}});
    }
    for (const Json& method : methods) {
        const std::string name = str_field(method, "name").empty()
                                     ? "修复"
                                     : str_field(method, "name");
        const std::string desc = str_field(method, "description");
        const QString label =
            desc.empty()
                ? QString::fromStdString(name)
                : QStringLiteral("%1 — %2")
                      .arg(QString::fromStdString(name),
                           QString::fromStdString(desc));
        QAction* action = menu->addAction(label);
        const int method_id = method.value("id", 0);
        const QString error_id =
            QString::fromStdString(str_field(error, "id"));
        connect(action, &QAction::triggered, this,
                [this, error_id, method_id]() {
                    emit fix_requested(error_id, method_id);
                });
    }
    return menu;
}

void TopologyCheckerPanel::on_menu(const QPoint& pos) {
    Json error = current_error();
    if (!error.is_object()) {
        QListWidgetItem* item = error_list->itemAt(pos);
        if (item != nullptr) {
            error_list->setCurrentItem(item);
            error = current_error();
        }
    }
    if (!error.is_object()) return;
    menu_for(error)->exec(error_list->viewport()->mapToGlobal(pos));
}

void TopologyCheckerPanel::on_fix() {
    const Json error = current_error();
    if (!error.is_object()) return;
    Json methods = error.value("methods", Json::array());
    const int method_id = methods.is_array() && !methods.empty()
                              ? methods[0].value("id", 0)
                              : 0;
    emit fix_requested(QString::fromStdString(str_field(error, "id")),
                       method_id);
}

void TopologyCheckerPanel::on_ignore() {
    const Json error = current_error();
    if (error.is_object()) emit ignore_requested(json_to_map(error));
}

void TopologyCheckerPanel::on_restore() {
    const Json error = current_error();
    if (error.is_object()) emit restore_requested(json_to_map(error));
}

}  // namespace pwb::ui_composite
