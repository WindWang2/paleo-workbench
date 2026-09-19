// UI-15 — layer properties dialog (map_layer_properties.py parity).

#include <pwb/ui_canvas/qt/map_layer_properties.hpp>

#include <QComboBox>
#include <QDialogButtonBox>
#include <QDoubleSpinBox>
#include <QFormLayout>
#include <QJsonDocument>
#include <QLabel>
#include <QLineEdit>
#include <QPlainTextEdit>
#include <QPushButton>
#include <QTabWidget>
#include <QVBoxLayout>
#include <QWidget>

#include <pwb/ui_widgets/ui_context.hpp>

namespace pwb::ui_canvas {

namespace {

QString qstr(const std::string& s) { return QString::fromStdString(s); }

std::string json_str_or(const Json& object, const char* key,
                        const std::string& fallback = "") {
    if (!object.is_object()) return fallback;
    const auto it = object.find(key);
    if (it == object.end() || it->is_null()) return fallback;
    if (it->is_string()) return it->get<std::string>();
    if (it->is_number() || it->is_boolean()) return it->dump();
    return fallback;
}

double json_num_or(const Json& object, const char* key, double fallback) {
    if (!object.is_object()) return fallback;
    const auto it = object.find(key);
    if (it != object.end() && it->is_number()) return it->get<double>();
    return fallback;
}

}  // namespace

MapLayerPropertiesDialog::MapLayerPropertiesDialog(
    const LayerView& layer, const Json& style, QWidget* parent,
    const Json& features, const std::vector<std::string>& fields,
    const SymbologyHooks& symbology)
    : QDialog(parent),
      layer_(layer),
      is_scalar_(layer.type_name == "ScalarGrid"),
      qgis_symbology_(symbology.available && !is_scalar_),
      style_(style.is_object() ? style : Json::object()),
      features_(features),
      fields_(fields),
      symbology_hooks_(symbology) {
    setObjectName(QStringLiteral("MapLayerPropertiesDialog"));
    setWindowTitle(
        QStringLiteral("Layer Properties — %1").arg(qstr(layer.name)));

    auto* layout = new QVBoxLayout(this);
    tabs_ = new QTabWidget(this);
    layout->addWidget(tabs_);

    // ---- General -------------------------------------------------------
    auto* general = new QWidget(this);
    auto* general_form = new QFormLayout(general);
    name_edit_ = new QLineEdit(qstr(layer.name), general);
    crs_edit_ = new QLineEdit(qstr(layer.crs), general);
    opacity_spin_ = new QDoubleSpinBox(general);
    opacity_spin_->setRange(0.0, 1.0);
    opacity_spin_->setSingleStep(0.05);
    opacity_spin_->setValue(layer.opacity);
    general_form->addRow(QStringLiteral("Name"), name_edit_);
    general_form->addRow(QStringLiteral("CRS"), crs_edit_);
    general_form->addRow(QStringLiteral("Opacity"), opacity_spin_);
    tabs_->addTab(general, QStringLiteral("General"));

    // ---- Source --------------------------------------------------------
    auto* source = new QWidget(this);
    auto* source_form = new QFormLayout(source);
    source_form->addRow(
        QStringLiteral("Source"),
        new QLabel(qstr(layer.source_ref.empty() ? "managed"
                                                 : layer.source_ref),
                   source));
    source_form->addRow(QStringLiteral("Layer type"),
                        new QLabel(qstr(layer.type_name), source));
    tabs_->addTab(source, QStringLiteral("Source"));

    // ---- Symbology -----------------------------------------------------
    auto* symbology_page = new QWidget(this);
    if (is_scalar_) {
        auto* form = new QFormLayout(symbology_page);
        double range_min = 0.0, range_max = 1.0;
        const auto range_it = style_.find("color_range");
        if (range_it != style_.end() && range_it->is_array() &&
            range_it->size() >= 2) {
            range_min = range_it->at(0).get<double>();
            range_max = range_it->at(1).get<double>();
        }
        color_ramp_combo_ = new QComboBox(symbology_page);
        color_ramp_combo_->addItems(
            {QStringLiteral("default"), QStringLiteral("grayscale"),
             QStringLiteral("warm_cool")});
        color_ramp_combo_->setCurrentText(
            qstr(json_str_or(style_, "color_ramp", "default")));
        range_min_spin_ = new QDoubleSpinBox(symbology_page);
        range_max_spin_ = new QDoubleSpinBox(symbology_page);
        for (auto* control : {range_min_spin_, range_max_spin_}) {
            control->setRange(-1.0e18, 1.0e18);
            control->setDecimals(8);
        }
        range_min_spin_->setValue(range_min);
        range_max_spin_->setValue(range_max);
        gamma_spin_ = new QDoubleSpinBox(symbology_page);
        gamma_spin_->setRange(0.01, 100.0);
        gamma_spin_->setDecimals(4);
        gamma_spin_->setValue(json_num_or(style_, "gamma", 1.0));
        nodata_combo_ = new QComboBox(symbology_page);
        nodata_combo_->addItems({QStringLiteral("transparent")});
        nodata_combo_->setCurrentText(
            qstr(json_str_or(style_, "nodata", "transparent")));
        form->addRow(QStringLiteral("Color ramp"), color_ramp_combo_);
        form->addRow(QStringLiteral("Range minimum"), range_min_spin_);
        form->addRow(QStringLiteral("Range maximum"), range_max_spin_);
        form->addRow(QStringLiteral("Gamma"), gamma_spin_);
        form->addRow(QStringLiteral("NoData"), nodata_combo_);
    } else {
        // Parse any incoming authoritative payload (Python
        // QgisStylePayload.from_dict(style.get("qgis_style"))).
        const auto payload_it = style_.find("qgis_style");
        if (payload_it != style_.end()) {
            style_payload_ =
                pwb::cartography::QgisStylePayload::from_dict(*payload_it);
        }
        if (qgis_symbology_) {
            build_qgis_symbology_tab(symbology_page);
        } else {
            build_legacy_symbology_tab(symbology_page, style_);
        }
    }
    tabs_->addTab(symbology_page, QStringLiteral("Symbology"));

    // ---- Labels ---------------------------------------------------------
    auto* labels_page = new QWidget(this);
    auto* labels_form = new QFormLayout(labels_page);
    const Json label_style = style_.value("labels", Json::object());
    label_field_edit_ =
        new QLineEdit(qstr(json_str_or(label_style, "field")), labels_page);
    label_size_spin_ = new QDoubleSpinBox(labels_page);
    label_size_spin_->setRange(1.0, 96.0);
    label_size_spin_->setValue(json_num_or(label_style, "size", 10.0));
    labels_form->addRow(QStringLiteral("Label field"), label_field_edit_);
    labels_form->addRow(QStringLiteral("Label size"), label_size_spin_);
    if (is_scalar_) {
        label_field_edit_->setEnabled(false);
        label_size_spin_->setEnabled(false);
    }
    tabs_->addTab(labels_page, QStringLiteral("Labels"));

    // ---- Rendering ------------------------------------------------------
    auto* rendering = new QWidget(this);
    auto* rendering_form = new QFormLayout(rendering);
    rendering_form->addRow(
        QStringLiteral("Data revision"),
        new QLabel(QString::number(layer.data_revision), rendering));
    rendering_form->addRow(
        QStringLiteral("Style revision"),
        new QLabel(QString::number(layer.style_revision), rendering));
    tabs_->addTab(rendering, QStringLiteral("Rendering"));

    // ---- Metadata / Provenance -------------------------------------------
    auto* metadata = new QWidget(this);
    auto* metadata_form = new QFormLayout(metadata);
    metadata_form->addRow(QStringLiteral("Metadata"),
                          new QLabel(qstr(layer.metadata_repr), metadata));
    metadata_form->addRow(
        QStringLiteral("Provenance"),
        new QLabel(qstr(layer.provenance_ref.empty()
                            ? "managed"
                            : layer.provenance_ref),
                   metadata));
    tabs_->addTab(metadata, QStringLiteral("Metadata / Provenance"));

    // ---- Buttons ---------------------------------------------------------
    buttons_ = new QDialogButtonBox(
        QDialogButtonBox::Apply | QDialogButtonBox::Ok |
            QDialogButtonBox::Cancel,
        this);
    connect(buttons_->button(QDialogButtonBox::Apply), &QPushButton::clicked,
            this, &MapLayerPropertiesDialog::apply);
    connect(buttons_, &QDialogButtonBox::accepted, this,
            &MapLayerPropertiesDialog::accept_after_apply);
    connect(buttons_, &QDialogButtonBox::rejected, this, &QDialog::reject);
    layout->addWidget(buttons_);
}

void MapLayerPropertiesDialog::build_qgis_symbology_tab(QWidget* page) {
    // Professional path: the native QGIS editors own symbology editing.
    auto* form = new QFormLayout(page);
    QString renderer_name = QStringLiteral("QGIS renderer");
    if (style_payload_.has_value() &&
        symbology_hooks_.renderer_info != nullptr) {
        // _renderer_info parity: display-only lookup must never raise —
        // a nullopt/exception keeps the generic label.
        try {
            const auto info = symbology_hooks_.renderer_info(
                style_payload_->renderer_xml);
            if (info.has_value() && !info->empty()) {
                renderer_name = QString::fromStdString(*info);
            }
        } catch (...) {
        }
    }
    auto* status = new QLabel(
        QStringLiteral("Authoritative style: %1\n%2")
            .arg(renderer_name,
                 symbology_hooks_.available
                     ? QStringLiteral(
                           "Editing opens the native QGIS symbology editor.")
                     : QStringLiteral(
                           "The QGIS bridge is not built; symbology "
                           "editing is unavailable.")),
        page);
    status->setWordWrap(true);
    form->addRow(QString(), status);
    qgis_edit_button_ = new QPushButton(
        QStringLiteral("Open QGIS Symbology Editor…"), page);
    qgis_edit_button_->setEnabled(symbology_hooks_.available &&
                                  symbology_hooks_.open != nullptr);
    connect(qgis_edit_button_, &QPushButton::clicked, this,
            &MapLayerPropertiesDialog::open_qgis_editor);
    form->addRow(QString(), qgis_edit_button_);
    symbology_error_label_ = new QLabel(QString(), page);
    symbology_error_label_->setWordWrap(true);
    symbology_error_label_->setStyleSheet(
        QStringLiteral("color: %1; font-size: 11px;")
            .arg(pwb::ui_widgets::palette_token("ERROR_RED")));
    symbology_error_label_->hide();
    form->addRow(QString(), symbology_error_label_);
}

void MapLayerPropertiesDialog::build_legacy_symbology_tab(
    QWidget* page, const Json& style) {
    auto* form = new QFormLayout(page);
    fill_edit_ =
        new QLineEdit(qstr(json_str_or(style, "fill")), page);
    stroke_edit_ =
        new QLineEdit(qstr(json_str_or(style, "stroke")), page);
    stroke_width_spin_ = new QDoubleSpinBox(page);
    stroke_width_spin_->setRange(0.0, 100.0);
    stroke_width_spin_->setValue(json_num_or(style, "stroke_width", 1.0));
    line_pattern_combo_ = new QComboBox(page);
    // LinePattern vocabulary (map_styles.LinePattern values).
    for (const char* pattern : {"solid", "dash", "dot", "dash_dot",
                                "fault", "boundary"}) {
        line_pattern_combo_->addItem(QString::fromLatin1(pattern),
                                     QString::fromLatin1(pattern));
    }
    line_pattern_combo_->setCurrentText(
        qstr(json_str_or(style, "line_pattern", "solid")));
    marker_combo_ = new QComboBox(page);
    // MarkerSymbol vocabulary (map_styles.MarkerSymbol values).
    for (const char* marker : {"circle", "square", "triangle", "diamond",
                               "cross", "star", "well"}) {
        marker_combo_->addItem(QString::fromLatin1(marker),
                               QString::fromLatin1(marker));
    }
    marker_combo_->setCurrentText(
        qstr(json_str_or(style, "marker", "circle")));
    marker_size_spin_ = new QDoubleSpinBox(page);
    marker_size_spin_->setRange(0.5, 96.0);
    marker_size_spin_->setValue(json_num_or(style, "marker_size", 6.0));
    renderer_combo_ = new QComboBox(page);
    renderer_combo_->addItems({QStringLiteral("single"),
                               QStringLiteral("categorized"),
                               QStringLiteral("graduated")});
    renderer_combo_->setCurrentText(
        qstr(json_str_or(style, "renderer", "single")));
    classification_field_edit_ =
        new QLineEdit(qstr(json_str_or(style, "field")), page);
    classes_edit_ = new QPlainTextEdit(page);
    classes_edit_->setPlaceholderText(
        QStringLiteral(
            "{\"delta\": \"#6c8ebf\"} or [{\"lower\": 0, \"upper\": 1, "
            "\"color\": \"#6c8ebf\"}]"));
    const std::string renderer = json_str_or(style, "renderer");
    if (renderer == "categorized") {
        const auto it = style.find("categories");
        classes_edit_->setPlainText(qstr(
            it != style.end() ? it->dump() : std::string("{}")));
    } else if (renderer == "graduated") {
        const auto it = style.find("ranges");
        classes_edit_->setPlainText(qstr(
            it != style.end() ? it->dump() : std::string("[]")));
    }
    form->addRow(QStringLiteral("Fill / ramp"), fill_edit_);
    form->addRow(QStringLiteral("Stroke"), stroke_edit_);
    form->addRow(QStringLiteral("Stroke width"), stroke_width_spin_);
    form->addRow(QStringLiteral("Line pattern"), line_pattern_combo_);
    form->addRow(QStringLiteral("Marker"), marker_combo_);
    form->addRow(QStringLiteral("Marker size"), marker_size_spin_);
    form->addRow(QStringLiteral("Renderer"), renderer_combo_);
    form->addRow(QStringLiteral("Classification field"),
                 classification_field_edit_);
    form->addRow(QStringLiteral("Classes (JSON)"), classes_edit_);
    classes_error_label_ = new QLabel(QString(), page);
    classes_error_label_->setWordWrap(true);
    classes_error_label_->setStyleSheet(
        QStringLiteral("color: %1; font-size: 11px;")
            .arg(pwb::ui_widgets::palette_token("ERROR_RED")));
    classes_error_label_->hide();
    form->addRow(QString(), classes_error_label_);
    connect(classes_edit_, &QPlainTextEdit::textChanged,
            classes_error_label_, &QLabel::hide);
}

std::optional<pwb::cartography::QgisStylePayload>
MapLayerPropertiesDialog::style_payload() const {
    return style_payload_;
}

void MapLayerPropertiesDialog::open_qgis_editor() {
    if (symbology_hooks_.open == nullptr) {
        return;
    }
    Json style = style_;
    if (!pending_qgis_style_.is_null()) {
        style["qgis_style"] = pending_qgis_style_;
    } else if (style_payload_.has_value()) {
        style["qgis_style"] = style_payload_->to_dict();
    }
    std::optional<Json> result;
    try {
        result = symbology_hooks_.open(
            this, "Symbology — " + layer_.name, features_, layer_.crs,
            fields_, style);
    } catch (const SymbologyBridgeError& exc) {
        symbology_error_label_->setText(
            QString::fromStdString(exc.what()));
        symbology_error_label_->show();
        return;
    }
    if (!result.has_value()) {
        return;  // cancelled
    }
    const Json& res = *result;
    pending_qgis_style_ = res.value("qgis_style", Json::object());
    const auto opacity_it = res.find("opacity");
    const double opacity =
        opacity_it != res.end() && opacity_it->is_number()
            ? opacity_it->get<double>()
            : 1.0;
    if (opacity >= 0.0 && opacity <= 1.0) {
        opacity_spin_->setValue(opacity);
    }
    apply();
}

PropertiesForm MapLayerPropertiesDialog::collect_form() const {
    PropertiesForm form;
    form.layer_id = layer_.id;
    form.is_scalar = is_scalar_;
    form.qgis_symbology = qgis_symbology_;
    form.name = name_edit_->text().toStdString();
    form.crs = crs_edit_->text().toStdString();
    form.opacity = opacity_spin_->value();
    if (is_scalar_) {
        form.color_ramp = color_ramp_combo_->currentText().toStdString();
        form.range_min = range_min_spin_->value();
        form.range_max = range_max_spin_->value();
        form.gamma = gamma_spin_->value();
        form.nodata = nodata_combo_->currentText().toStdString();
    } else if (!qgis_symbology_) {
        form.fill = fill_edit_->text().toStdString();
        form.stroke = stroke_edit_->text().toStdString();
        form.stroke_width = stroke_width_spin_->value();
        form.line_pattern =
            line_pattern_combo_->currentText().toStdString();
        form.marker = marker_combo_->currentText().toStdString();
        form.marker_size = marker_size_spin_->value();
        form.renderer = renderer_combo_->currentText().toStdString();
        form.classification_field =
            classification_field_edit_->text().toStdString();
        form.classes_text = classes_edit_->toPlainText().toStdString();
    }
    form.label_field = label_field_edit_->text().toStdString();
    form.label_size = label_size_spin_->value();
    form.pending_qgis_style = pending_qgis_style_;
    form.existing_style = style_;
    return form;
}

Json MapLayerPropertiesDialog::payload() const {
    return build_properties_payload(collect_form());
}

std::optional<QString>
MapLayerPropertiesDialog::classes_json_error() const {
    const auto error = ui_canvas::classes_json_error(collect_form());
    if (!error.has_value()) {
        return std::nullopt;
    }
    return QString::fromStdString(*error);
}

void MapLayerPropertiesDialog::apply() {
    const auto error = classes_json_error();
    if (error.has_value()) {
        classes_error_label_->setText(*error);
        classes_error_label_->show();
        return;
    }
    emit properties_applied(qstr(layer_.id), payload());
}

void MapLayerPropertiesDialog::accept_after_apply() {
    // Never close the dialog over a silently discarded structured input:
    // show an inline error next to the Classes field instead (#426).
    const auto error = classes_json_error();
    if (error.has_value()) {
        classes_error_label_->setText(*error);
        classes_error_label_->show();
        return;
    }
    apply();
    accept();
}

}  // namespace pwb::ui_canvas
