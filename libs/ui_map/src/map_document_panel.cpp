#include <pwb/ui_map/map_document_panel.hpp>

#include <QLabel>
#include <QListWidget>
#include <QVBoxLayout>

#include <pwb/ui_map/item_reconcile.hpp>
#include <pwb/ui_shell/style_registry.hpp>

namespace pwb::ui_map {

namespace {

QString qstr(const std::string& s) {
    return QString::fromUtf8(s.data(), static_cast<qsizetype>(s.size()));
}

QString pal(const char* key, const char* fallback) {
    const auto palette = pwb::ui_shell::style_palette();
    const auto it = palette.find(key);
    return it == palette.end() ? QString::fromLatin1(fallback)
                               : qstr(it->second);
}

QString panel_qss() {
    return QStringLiteral(
               "QFrame#MapDocumentPanel { background: %1;"
               " border: 1px solid %2; border-radius: 4px; }")
        .arg(pal("BG_SIDEBAR", "#eceff3"), pal("BORDER", "#d0d5dd"));
}

QString title_qss() {
    return QStringLiteral(
               "color: %1; font-size: 14px; font-weight: 600;"
               " border: none; background: transparent;")
        .arg(pal("TEXT_PRIMARY", "#212121"));
}

QString secondary_label_qss() {
    return QStringLiteral(
               "color: %1; font-size: 11px;"
               " border: none; background: transparent;")
        .arg(pal("TEXT_SECONDARY", "#616161"));
}

QString value_qss() {
    return QStringLiteral(
               "color: %1; font-size: 14px; font-weight: 500;"
               " border: none; background: transparent;")
        .arg(pal("TEXT_PRIMARY", "#212121"));
}

QString list_qss() {
    return QStringLiteral(
               "QListWidget { background: %1; border: 1px solid %2;"
               " border-radius: 4px; padding: 2px; }")
        .arg(pal("BG_SIDEBAR", "#eceff3"), pal("BORDER", "#d0d5dd"));
}

QLabel* add_value(QVBoxLayout* layout, const QString& label_text,
                  const QString& value_text, QWidget* parent) {
    auto* label = new QLabel(label_text, parent);
    pwb::ui_shell::style_bind(label, secondary_label_qss);
    layout->addWidget(label);
    auto* value = new QLabel(value_text, parent);
    pwb::ui_shell::style_bind(value, value_qss);
    layout->addWidget(value);
    return value;
}

}  // namespace

MapDocumentPanel::MapDocumentPanel(QWidget* parent) : QFrame(parent) {
    setObjectName(QStringLiteral("MapDocumentPanel"));
    // V9：固定 240 → 最小 200 地板（可自由调整宽度）。
    setMinimumWidth(200);
    pwb::ui_shell::style_bind(this, panel_qss);

    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(16, 16, 16, 16);  // PAGE_MARGIN
    layout->setSpacing(12);                      // SPACE_3

    auto* title = new QLabel(QStringLiteral("古地理图文档"), this);
    pwb::ui_shell::style_bind(title, title_qss);
    layout->addWidget(title);

    name_value_ = add_value(layout, QStringLiteral("当前图件"),
                            QStringLiteral("未选择古地理图"), this);
    horizon_value_ = add_value(layout, QStringLiteral("目标层位"),
                               QStringLiteral("未设置"), this);
    polygon_count_value_ = add_value(layout, QStringLiteral("相带多边形"),
                                     QStringLiteral("0 个相带"), this);
    well_count_value_ = add_value(layout, QStringLiteral("井位叠加"),
                                  QStringLiteral("0 口井"), this);

    auto* list_label = new QLabel(QStringLiteral("图件列表"), this);
    pwb::ui_shell::style_bind(list_label, secondary_label_qss);
    layout->addWidget(list_label);
    document_list_ = new QListWidget(this);
    pwb::ui_shell::style_bind(document_list_, list_qss);
    layout->addWidget(document_list_, 1);
}

void MapDocumentPanel::update_state(
    const std::vector<Json>& map_documents) {
    documents_ = map_documents;
    const Json* document = active_map_document(documents_);
    const std::string name =
        document != nullptr
            ? field_value_str(*document, "name", "未选择古地理图")
            : std::string("未选择古地理图");
    const std::string horizon =
        document != nullptr
            ? field_value_str(*document, "linked_target_horizon", "未设置")
            : std::string("未设置");
    const Json polygons =
        document != nullptr
            ? field_value(*document, "facies_polygons", Json::array())
            : Json::array();
    const Json wells =
        document != nullptr
            ? field_value(*document, "well_overlays", Json::array())
            : Json::array();
    const int polygon_count =
        polygons.is_array() ? static_cast<int>(polygons.size()) : 0;
    const int well_count =
        wells.is_array() ? static_cast<int>(wells.size()) : 0;

    name_value_->setText(qstr(name.empty() ? "未选择古地理图" : name));
    horizon_value_->setText(qstr(horizon.empty() ? "未设置" : horizon));
    polygon_count_value_->setText(
        QStringLiteral("%1 个相带").arg(polygon_count));
    well_count_value_->setText(QStringLiteral("%1 口井").arg(well_count));

    // V11 D2 ⑮ keyed diff — items keep identity/selection/scroll across
    // refreshes; labels update in place.
    std::vector<std::string> keys;
    keys.reserve(documents_.size());
    for (std::size_t i = 0; i < documents_.size(); ++i) {
        keys.push_back(document_list_key(
            documents_[i], reinterpret_cast<const void*>(i + 1)));
    }
    reconcile_list_items(
        document_list_, keys,
        [](const std::string&) { return new QListWidgetItem(QString()); },
        [this](QListWidgetItem* item, const std::string& key) {
            const Json* source = nullptr;
            for (std::size_t i = 0; i < documents_.size(); ++i) {
                if (document_list_key(
                        documents_[i],
                        reinterpret_cast<const void*>(i + 1)) == key) {
                    source = &documents_[i];
                    break;
                }
            }
            if (source == nullptr) {
                return;
            }
            const std::string item_name =
                field_value_str(*source, "name", "未命名图件");
            const std::string item_horizon = field_value_str(
                *source, "linked_target_horizon", "未设置");
            const QString label = qstr(
                (item_name.empty() ? "未命名图件" : item_name) + " · " +
                (item_horizon.empty() ? "未设置" : item_horizon));
            if (item->text() != label) {
                item->setText(label);
            }
        });
}

std::string MapDocumentPanel::name_text() const {
    return name_value_->text().toStdString();
}

std::string MapDocumentPanel::horizon_text() const {
    return horizon_value_->text().toStdString();
}

std::string MapDocumentPanel::polygon_count_text() const {
    return polygon_count_value_->text().toStdString();
}

std::string MapDocumentPanel::well_count_text() const {
    return well_count_value_->text().toStdString();
}

}  // namespace pwb::ui_map
