#include <pwb/ui_map/map_canvas_panel.hpp>

#include <QLabel>
#include <QStackedLayout>
#include <QVBoxLayout>

#include <pwb/ui_map/display_map_canvas.hpp>
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

// _host_qss: MapCanvasHost card frame (theme-bound re-render).
QString host_qss() {
    return QStringLiteral(
               "QFrame { background: %1; border: 1px solid %2;"
               " border-radius: 4px; }")
        .arg(pal("BG_BODY", "#f5f7fa"), pal("BORDER_LIGHT", "#dfe4ea"));
}

// _empty_qss: empty-state label (TEXT_SECONDARY + title-size padding).
QString empty_qss() {
    return QStringLiteral(
               "color: %1; background: transparent; border: none;"
               " font-size: 14px; padding: 32px;")
        .arg(pal("TEXT_SECONDARY", "#616161"));
}

// Build a two-layer preview snapshot: facies features + well points —
// the display-canvas mirror's input shape.
Json preview_snapshot(const Json& features, const Json& wells,
                      const std::string& period_name) {
    Json layers = Json::array();
    if (features.is_array() && !features.empty()) {
        layers.push_back(Json{
            {"id", "preview:facies"},
            {"name", "相带"},
            {"layer_type", "vector"},
            {"features", features},
            {"style", Json{{"fill", "#7fb3d5"},
                           {"stroke", "#3d6d8f"},
                           {"stroke_width", 1.0}}},
            {"visible", true},
            {"opacity", 1.0}});
    }
    if (wells.is_array() && !wells.empty()) {
        Json well_features = Json::array();
        for (const auto& well : wells) {
            const Json lng = field_value(well, "lng", Json(nullptr));
            const Json lat = field_value(well, "lat", Json(nullptr));
            if (!lng.is_number() || !lat.is_number()) {
                continue;
            }
            well_features.push_back(Json{
                {"type", "Feature"},
                {"geometry",
                 Json{{"type", "Point"},
                      {"coordinates",
                       Json::array({lng, lat})}}},
                {"properties",
                 Json{{"name", field_value_str(well, "name", "")}}}});
        }
        layers.push_back(Json{
            {"id", "preview:wells"},
            {"name", "井位"},
            {"layer_type", "vector"},
            {"features", std::move(well_features)},
            {"style", Json{{"fill", "#409cff"},
                           {"stroke", "#182431"},
                           {"stroke_width", 1.4},
                           {"marker_size", 11.0}}},
            {"visible", true},
            {"opacity", 1.0}});
    }
    return Json{{"project_crs", ""},
                {"layers", std::move(layers)},
                {"period_name", period_name}};
}

}  // namespace

MapCanvasPanel::MapCanvasPanel(QWidget* parent) : QFrame(parent) {
    setObjectName(QStringLiteral("MapCanvasPanel"));

    auto* outer = new QVBoxLayout(this);
    outer->setContentsMargins(12, 12, 12, 12);  // SPACE_3
    outer->setSpacing(8);                       // SPACE_2

    auto* title_label = new QLabel(QStringLiteral("编图画布"), this);
    title_label->setObjectName(QStringLiteral("MapDockTitle"));
    outer->addWidget(title_label);

    auto* host = new QFrame(this);
    host->setObjectName(QStringLiteral("MapCanvasHost"));
    pwb::ui_shell::style_bind(host, host_qss);
    stack_ = new QStackedLayout(host);
    stack_->setContentsMargins(0, 0, 0, 0);

    empty_label_ = new QLabel(QStringLiteral("未选择古地理图"), host);
    empty_label_->setObjectName(QStringLiteral("EmptyStateLabel"));
    empty_label_->setAlignment(Qt::AlignCenter);
    pwb::ui_shell::style_bind(empty_label_, empty_qss);
    stack_->addWidget(empty_label_);

    canvas_ = new DisplayMapCanvas(host);
    stack_->addWidget(canvas_);
    outer->addWidget(host, 1);
}

void MapCanvasPanel::load_preview(const Json& features, const Json& wells,
                                  const std::string& period_name) {
    const bool empty =
        (!features.is_array() || features.empty()) &&
        (!wells.is_array() || wells.empty());
    if (empty) {
        canvas_->set_layer_snapshot(Json::object());
        empty_label_->setText(period_name.empty()
                                  ? QStringLiteral("未选择古地理图")
                                  : QStringLiteral("暂无图面要素"));
        empty_label_->setHidden(false);
        stack_->setCurrentWidget(empty_label_);
        return;
    }
    canvas_->set_layer_snapshot(
        preview_snapshot(features, wells, period_name));
    empty_label_->setHidden(true);
    stack_->setCurrentWidget(canvas_);
}

void MapCanvasPanel::load_native_scene(const Json& scene_snapshot) {
    canvas_->set_layer_snapshot(scene_snapshot);
    empty_label_->setHidden(true);
    stack_->setCurrentWidget(canvas_);
}

void MapCanvasPanel::update_state(const Json& document) {
    if (!document.is_object()) {
        load_preview(Json::array(), Json::array(), "");
        empty_label_->setText(QStringLiteral("未选择古地理图"));
        return;
    }
    const Json payload = preview_payload_from_document(document);
    load_preview(field_value(payload, "features", Json::array()),
                 field_value(payload, "wells", Json::array()),
                 field_value_str(payload, "period", ""));
}

QString MapCanvasPanel::current_surface() const {
    if (stack_ != nullptr && stack_->currentWidget() == canvas_) {
        return QStringLiteral("canvas");
    }
    return QStringLiteral("empty");
}

}  // namespace pwb::ui_map
