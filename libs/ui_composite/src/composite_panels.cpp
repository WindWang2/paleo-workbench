#include <pwb/ui_composite/composite_panels.hpp>

#include <pwb/ui_composite/composite_controller.hpp>
#include <pwb/ui_composite/map_interaction.hpp>
#include <pwb/ui_composite/roles.hpp>
#include <pwb/ui_composite/vector_layer.hpp>
#include <pwb/ui_widgets/icon_factory.hpp>

#include <QDialogButtonBox>
#include <QFormLayout>
#include <QHBoxLayout>
#include <QHeaderView>
#include <QMenu>
#include <QMouseEvent>
#include <QTableWidgetItem>
#include <QTreeWidgetItem>
#include <QVBoxLayout>

namespace pwb::ui_composite {

namespace {

const std::map<std::string, QString>& geometry_type_labels() {
    static const std::map<std::string, QString> labels = {
        {"Point", QStringLiteral("点")},
        {"MultiPoint", QStringLiteral("点（多）")},
        {"LineString", QStringLiteral("线")},
        {"MultiLineString", QStringLiteral("线（多）")},
        {"Polygon", QStringLiteral("面")},
        {"MultiPolygon", QStringLiteral("面（多）")},
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

QString value_text(const Json& value) {
    if (value.is_null()) return QString();
    if (value.is_string()) return QString::fromStdString(value.get<std::string>());
    return QString::fromStdString(value.dump());
}

// Clickable label closing the results panel (rb-clear.svg affordance).
class ClearLabel : public QLabel {
public:
    explicit ClearLabel(QWidget* parent = nullptr) : QLabel(parent) {}
    std::function<void()> on_press;
protected:
    void mousePressEvent(QMouseEvent* event) override {
        if (on_press) on_press();
        QLabel::mousePressEvent(event);
    }
};

}  // namespace

// ---------------------------------------------------------------------------
// IdentifyResultsPanel
// ---------------------------------------------------------------------------

IdentifyResultsPanel::IdentifyResultsPanel(QWidget* parent)
    : QFrame(parent) {
    setObjectName("CompositeIdentifyResults");
    setVisible(false);

    auto* outer = new QVBoxLayout(this);
    outer->setContentsMargins(4, 4, 4, 4);
    outer->setSpacing(2);

    auto* header = new QHBoxLayout();
    auto* title = new QLabel(QStringLiteral("识别结果"), this);
    title->setObjectName("WorkstationPanelFootnote");
    header->addWidget(title);
    header->addStretch(1);
    auto* clear_button = new ClearLabel(this);
    clear_button->setPixmap(
        pwb::ui_widgets::workstation_icon("rb-clear.svg").pixmap(14, 14));
    clear_button->setToolTip(QStringLiteral("关闭识别结果"));
    clear_button->setCursor(Qt::PointingHandCursor);
    clear_button->on_press = [this]() { set_results({}); };
    header->addWidget(clear_button);
    outer->addLayout(header);

    tree = new QTreeWidget(this);
    tree->setObjectName("CompositeIdentifyTree");
    tree->setHeaderLabels({QStringLiteral("图层"),
                           QStringLiteral("要素"),
                           QStringLiteral("几何")});
    tree->setRootIsDecorated(true);
    tree->setAlternatingRowColors(true);
    tree->header()->setSectionResizeMode(0, QHeaderView::Stretch);
    connect(tree, &QTreeWidget::itemDoubleClicked, this,
            &IdentifyResultsPanel::on_item_double_clicked);
    outer->addWidget(tree, 1);
}

void IdentifyResultsPanel::set_results(const std::vector<Json>& results) {
    tree->clear();
    for (const Json& result : results) {
        const std::string geometry_kind_key =
            str_field(result, "geometry_type");
        auto label_it = geometry_type_labels().find(geometry_kind_key);
        const QString geometry_kind =
            label_it == geometry_type_labels().end() ? QString()
                                                     : label_it->second;
        auto* item = new QTreeWidgetItem(
            {QString::fromStdString(str_field(result, "layer_name")),
             QString::fromStdString(str_field(result, "feature_id")),
             geometry_kind});
        item->setData(0, Qt::UserRole, json_to_variant(result));
        const Json attributes =
            result.value("attributes", Json::object());
        std::vector<std::pair<QString, QString>> meta = {
            {QStringLiteral("来源"),
             QString::fromStdString(str_field(result, "source"))},
        };
        const std::string tpl = str_field(result, "template");
        if (!tpl.empty()) {
            meta.emplace_back(QStringLiteral("模板角色"),
                              QString::fromStdString(tpl));
        }
        const bool editable = result.value("editable", false);
        meta.emplace_back(QStringLiteral("可编辑"),
                          editable ? QStringLiteral("是")
                                   : QStringLiteral("否"));
        for (const auto& [key, value] : meta) {
            auto* child = new QTreeWidgetItem({key, value});
            child->setFirstColumnSpanned(false);
            item->addChild(child);
        }
        if (attributes.is_object()) {
            // sorted(attributes.items()) parity — ordered map iteration.
            std::map<std::string, Json> sorted_attrs(
                attributes.begin(), attributes.end());
            for (const auto& [key, value] : sorted_attrs) {
                auto* child = new QTreeWidgetItem(
                    {QString::fromStdString(key), value_text(value)});
                child->setFirstColumnSpanned(false);
                item->addChild(child);
            }
        }
        tree->addTopLevelItem(item);
    }
    setVisible(tree->topLevelItemCount() > 0);
}

void IdentifyResultsPanel::on_item_double_clicked(QTreeWidgetItem* item,
                                                  int column) {
    (void)column;
    const QVariant payload = item->data(0, Qt::UserRole);
    if (payload.isValid()) {
        emit result_activated(payload.toMap());
    }
}

// ---------------------------------------------------------------------------
// SnappingSettingsDialog cell proxies
// ---------------------------------------------------------------------------

void SnappingSettingsDialog::CheckCell::set_checked(bool checked) {
    item->setCheckState(checked ? Qt::Checked : Qt::Unchecked);
}

bool SnappingSettingsDialog::CheckCell::is_checked() const {
    return item->checkState() == Qt::Checked;
}

double SnappingSettingsDialog::NumericCell::value() const {
    const QString text = item->text().trimmed();
    if (text.isEmpty() || text == zero_label) return 0.0;
    bool ok = false;
    const double parsed = text.toDouble(&ok);
    if (!ok) return 0.0;
    return std::max(0.0, std::min(parsed, maximum));
}

void SnappingSettingsDialog::NumericCell::set_value(double value) {
    const double clamped = std::max(0.0, std::min(value, maximum));
    if (clamped <= 0.0 && !zero_label.isEmpty()) {
        item->setText(zero_label);
    } else {
        item->setText(QString::number(clamped, 'f', decimals));
    }
}

// ---------------------------------------------------------------------------
// SnappingSettingsDialog
// ---------------------------------------------------------------------------

SnappingSettingsDialog::SnappingSettingsDialog(
    CompositeEditController* controller, QWidget* parent,
    const std::vector<MapPoint>& well_points)
    : QDialog(parent),
      controller_(controller),
      well_points_(well_points) {
    setObjectName("CompositeSnappingSettingsDialog");
    setWindowTitle(QStringLiteral("捕捉设置"));

    SnappingService& snapping = controller_->snapping();

    auto* outer = new QVBoxLayout(this);
    outer->setContentsMargins(10, 10, 10, 10);
    outer->setSpacing(8);

    auto* global_form = new QFormLayout();
    global_enable_ = new QCheckBox(QStringLiteral("启用捕捉"), this);
    global_enable_->setChecked(snapping.enabled);
    global_tolerance_ = new QDoubleSpinBox(this);
    global_tolerance_->setRange(1.0, 100.0);
    global_tolerance_->setDecimals(1);
    global_tolerance_->setSuffix(QStringLiteral(" px"));
    global_tolerance_->setValue(snapping.pixel_tolerance);
    global_form->addRow(global_enable_);
    // V12 M1-6：容差单位（像素 / 地图单位 / 层单位；原生 QGIS 对照）。
    units_combo_ = new QComboBox(this);
    for (const auto& [key, label] :
         {std::pair{"px", QStringLiteral("像素")},
          {"map", QStringLiteral("地图单位")},
          {"layer", QStringLiteral("层单位")}}) {
        units_combo_->addItem(label, QString::fromUtf8(key));
    }
    const std::map<std::string, int> unit_index = {
        {"px", 0}, {"map", 1}, {"layer", 2}};
    auto unit_it = unit_index.find(snapping.tolerance_units);
    units_combo_->setCurrentIndex(unit_it == unit_index.end() ? 0
                                                            : unit_it->second);
    units_combo_->setToolTip(QStringLiteral(
        "捕捉容差的单位：像素（屏幕）/ 地图单位（随缩放）/ 层单位"));
    global_form->addRow(QStringLiteral("容差单位"), units_combo_);
    // V12 M4-3a：比例依赖捕捉（只在放大到该比例尺时捕捉）。
    scale_spin_ = new QSpinBox(this);
    scale_spin_->setRange(0, 10000000);
    scale_spin_->setSingleStep(1000);
    scale_spin_->setSpecialValueText(QStringLiteral("关闭（全比例捕捉）"));
    scale_spin_->setValue(
        snapping.scale_minimum.has_value() && *snapping.scale_minimum > 0.0
            ? static_cast<int>(*snapping.scale_minimum)
            : 0);
    scale_spin_->setToolTip(QStringLiteral(
        "最小比例尺分母：画布比例尺 >= 该值时才捕捉（0 = 关闭）"));
    global_form->addRow(QStringLiteral("比例依赖（1:）"), scale_spin_);
    global_form->addRow(QStringLiteral("默认容差（像素）"),
                        global_tolerance_);
    auto* modes_row = new QHBoxLayout();
    for (const auto& [mode, label] :
         {std::pair{"vertex", QStringLiteral("顶点")},
          {"segment", QStringLiteral("线段")},
          {"midpoint", QStringLiteral("中点")},
          {"endpoint", QStringLiteral("端点")},
          {"intersection", QStringLiteral("交点")}}) {
        auto* box = new QCheckBox(label, this);
        box->setChecked(snapping.modes.count(mode) > 0);
        mode_boxes_[mode] = box;
        modes_row->addWidget(box);
    }
    auto* modes_container = new QWidget(this);
    modes_container->setLayout(modes_row);
    global_form->addRow(QStringLiteral("捕捉类型"), modes_container);
    // V12 M1-1：捕捉范围（All Layers / Active Layer）。
    scope_combo_ = new QComboBox(this);
    scope_combo_->addItem(QStringLiteral("所有图层"));
    scope_combo_->addItem(QStringLiteral("仅当前图层"));
    scope_combo_->setCurrentIndex(snapping.current_layer_only ? 1 : 0);
    scope_combo_->setToolTip(QStringLiteral(
        "所有图层：捕捉全部可见图层（跨层拓扑拼接）\n"
        "仅当前图层：只捕捉活动图层（避免误吸邻层）"));
    global_form->addRow(QStringLiteral("捕捉范围"), scope_combo_);
    outer->addLayout(global_form);

    outer->addWidget(new QLabel(
        QStringLiteral("每图层覆盖（矢量图层；容差留空使用全局值）"),
        this));

    table_ = new QTableWidget(0, 6, this);
    table_->setObjectName("CompositeSnappingTable");
    table_->setHorizontalHeaderLabels(
        {QStringLiteral("图层"), QStringLiteral("启用"),
         QStringLiteral("顶点"), QStringLiteral("线段"),
         QStringLiteral("容差(px)"), QStringLiteral("优先级")});
    table_->verticalHeader()->setVisible(false);
    table_->horizontalHeader()->setSectionResizeMode(0,
                                                     QHeaderView::Stretch);
    table_->setContextMenuPolicy(Qt::CustomContextMenu);
    connect(table_, &QTableWidget::customContextMenuRequested, this,
            &SnappingSettingsDialog::show_row_menu);
    outer->addWidget(table_, 1);
    hint_ = new QLabel(QString(), this);
    hint_->setObjectName("WorkstationPanelFootnote");
    hint_->setWordWrap(true);
    outer->addWidget(hint_);

    well_snap_ = new QCheckBox(
        !well_points_.empty()
            ? QStringLiteral(
                  "参考点捕捉（井位 / 参与捕捉的引用图层，%1 个）")
                  .arg(well_points_.size())
            : QStringLiteral("参考点捕捉（当前无井点 / 引用参考点）"),
        this);
    well_snap_->setEnabled(!well_points_.empty());
    well_snap_->setChecked(snapping.modes.count("reference") > 0);
    outer->addWidget(well_snap_);

    auto* buttons = new QDialogButtonBox(
        QDialogButtonBox::Ok | QDialogButtonBox::Cancel, this);
    connect(buttons, &QDialogButtonBox::accepted, this,
            [this]() { accept(); });
    connect(buttons, &QDialogButtonBox::rejected, this, &QDialog::reject);
    outer->addWidget(buttons);

    populate_layers();

    table_->setMinimumHeight(150);
    const int rows = table_->rowCount();
    resize(std::min(760, std::max(560, 140 + rows * 26)),
           std::min(700, std::max(470, 370 + rows * 30)));
}

void SnappingSettingsDialog::populate_layers() {
    SnappingService& snapping = controller_->snapping();
    std::vector<std::pair<std::string, QString>> rows;
    for (const std::string& layer_id : controller_->layer_ids()) {
        const VectorLayer* layer = controller_->layer(layer_id);
        if (layer == nullptr) continue;
        const QString kind =
            QString::fromStdString(controller_->kind_of(layer_id));
        rows.emplace_back(
            layer_id, QStringLiteral("%1（%2）")
                          .arg(QString::fromStdString(layer->name()), kind));
    }
    table_->setRowCount(static_cast<int>(rows.size()));
    int row = 0;
    for (const auto& [layer_id, label] : rows) {
        auto enabled_it = snapping.layer_enabled.find(layer_id);
        const bool enabled =
            enabled_it == snapping.layer_enabled.end() ? true
                                                       : enabled_it->second;
        auto modes_it = snapping.layer_modes.find(layer_id);
        const std::set<std::string> modes =
            modes_it == snapping.layer_modes.end() ? snapping.modes
                                                   : modes_it->second;
        auto tol_it = snapping.layer_tolerance.find(layer_id);
        const double tolerance_override =
            tol_it == snapping.layer_tolerance.end() ? 0.0 : tol_it->second;
        auto prio_it = snapping.layer_priority.find(layer_id);
        const int priority =
            prio_it == snapping.layer_priority.end() ? 0 : prio_it->second;

        auto* name_item = new QTableWidgetItem(label);
        name_item->setFlags(name_item->flags() & ~Qt::ItemIsEditable);
        // V9 W4：角色捕捉推荐可解释——行 tooltip 携带完整推荐语。
        if (const SnappingProfile* profile = role_profile(layer_id)) {
            name_item->setToolTip(
                QString::fromStdString(profile_summary(*profile)));
        }
        table_->setItem(row, 0, name_item);

        LayerRow entries;
        const std::array<std::pair<const char*, bool>, 3> checks = {{
            {"enabled", enabled},
            {"vertex", modes.count("vertex") > 0},
            {"segment", modes.count("segment") > 0},
        }};
        CheckCell* targets[3] = {&entries.enabled, &entries.vertex,
                                 &entries.segment};
        for (int column = 0; column < 3; ++column) {
            auto* box_item = new QTableWidgetItem();
            box_item->setFlags(
                (box_item->flags() | Qt::ItemIsUserCheckable) &
                ~Qt::ItemIsEditable);
            box_item->setCheckState(checks[column].second ? Qt::Checked
                                                          : Qt::Unchecked);
            table_->setItem(row, column + 1, box_item);
            targets[column]->item = box_item;
        }

        auto* tolerance_item = new QTableWidgetItem();
        table_->setItem(row, 4, tolerance_item);
        entries.tolerance = NumericCell{tolerance_item, 100.0, 1,
                                        QStringLiteral("全局")};
        entries.tolerance.set_value(tolerance_override);

        auto* priority_item = new QTableWidgetItem();
        table_->setItem(row, 5, priority_item);
        entries.priority = NumericCell{priority_item, 99.0, 0, QString()};
        entries.priority.set_value(priority);

        layer_rows_.emplace_back(layer_id, entries);
        ++row;
    }
}

void SnappingSettingsDialog::show_row_menu(const QPoint& position) {
    const int row = table_->rowAt(position.y());
    if (row < 0 || row >= static_cast<int>(layer_rows_.size())) return;
    const std::string& layer_id = layer_rows_[row].first;
    const SnappingProfile* profile = role_profile(layer_id);
    QMenu menu(this);
    if (profile == nullptr) {
        QAction* action =
            menu.addAction(QStringLiteral("该图层无角色捕捉推荐"));
        action->setEnabled(false);
    } else {
        menu.addAction(QStringLiteral("按「%1」推荐设置")
                           .arg(QString::fromStdString(
                               role_label(profile->role))),
                       this, [this, layer_id]() {
                           apply_role_profile_to_row(layer_id);
                       });
    }
    menu.exec(table_->viewport()->mapToGlobal(position));
}

const SnappingProfile* SnappingSettingsDialog::role_profile(
    const std::string& layer_id) const {
    return recommended_profile_for_role(
        controller_->role_of_layer(layer_id));
}

void SnappingSettingsDialog::apply_role_profile_to_row(
    const std::string& layer_id) {
    const SnappingProfile* profile = role_profile(layer_id);
    if (profile == nullptr) return;
    for (const auto& [mode, box] : mode_boxes_) {
        box->setChecked(profile->modes.count(mode) > 0);
    }
    for (auto& [id, entries] : layer_rows_) {
        if (id != layer_id) continue;
        entries.vertex.set_checked(profile->modes.count("vertex") > 0 ||
                                   profile->modes.count("endpoint") > 0);
        entries.segment.set_checked(profile->modes.count("segment") > 0);
        entries.tolerance.set_value(profile->tolerance_px);
        entries.enabled.set_checked(true);
        break;
    }
    hint_->setText(QString::fromStdString(profile_summary(*profile)));
}

void SnappingSettingsDialog::accept() {
    SnappingService& snapping = controller_->snapping();
    snapping.enabled = global_enable_->isChecked();
    snapping.pixel_tolerance = global_tolerance_->value();
    // V12 M1-6/M4-3a：容差单位与比例依赖随对话框落权威。
    snapping.tolerance_units =
        units_combo_->currentData().toString().toStdString();
    const int scale_value = scale_spin_->value();
    snapping.scale_minimum =
        scale_value > 0 ? std::optional<double>(scale_value) : std::nullopt;
    // V12 M1-1：范围随对话框落权威。
    snapping.current_layer_only = scope_combo_->currentIndex() == 1;
    snapping.modes.clear();
    for (const auto& [mode, box] : mode_boxes_) {
        if (box->isChecked()) snapping.modes.insert(mode);
    }
    for (const auto& [layer_id, entries] : layer_rows_) {
        snapping.layer_enabled[layer_id] = entries.enabled.is_checked();
        std::set<std::string> modes = snapping.modes;
        if (entries.vertex.is_checked()) {
            modes.insert("vertex");
        } else {
            modes.erase("vertex");
        }
        if (entries.segment.is_checked()) {
            modes.insert("segment");
        } else {
            modes.erase("segment");
        }
        if (!modes.empty()) {
            snapping.layer_modes[layer_id] = modes;
        } else {
            snapping.layer_modes.erase(layer_id);
        }
        const double tolerance = entries.tolerance.value();
        if (tolerance > 0.0) {
            snapping.layer_tolerance[layer_id] = tolerance;
        } else {
            snapping.layer_tolerance.erase(layer_id);
        }
        snapping.layer_priority[layer_id] =
            static_cast<int>(entries.priority.value());
    }
    // 井位参考点：勾选时进入 reference 捕捉候选。
    if (well_snap_->isEnabled() && well_snap_->isChecked()) {
        snapping.modes.insert("reference");
        snapping.set_reference_points(well_points_);
    } else {
        snapping.modes.erase("reference");
        snapping.set_reference_points({});
    }
    controller_->set_snapping(snapping.enabled);
    // Qt TU: `emit` is the Qt macro — invoke the events sink directly
    // (same "optional callback" semantics the core's emit() encodes).
    if (controller_->events.state_changed)
        controller_->events.state_changed();
    QDialog::accept();
}

}  // namespace pwb::ui_composite
