// UI-15 — one lightweight, renderer-neutral layer properties dialog
// (map_layer_properties.py parity).
//
// Callers remain responsible for applying the emitted payload to the scene
// and vector layers; the dialog intentionally holds no parallel layer
// state. The widget collects values into PropertiesForm; the payload shape
// lives in pwb::ui_canvas::layer_properties_core (Qt-free).
#pragma once

#include <functional>
#include <optional>
#include <string>
#include <vector>

#include <QDialog>
#include <QString>

#include <pwb/ui_canvas/layer_properties_core.hpp>
#include <pwb/ui_canvas/symbology_core.hpp>

class QComboBox;
class QDialogButtonBox;
class QDoubleSpinBox;
class QLabel;
class QLineEdit;
class QPlainTextEdit;
class QPushButton;
class QTabWidget;

namespace pwb::ui_canvas {

// The read-only layer view the dialog edits (Python `layer` duck parity —
// callers pass MapLayer/scene-layer fields; the dialog never mutates it).
struct LayerView {
    std::string id;
    std::string name;
    // Enum member name ("ScalarGrid" | "Vector" | ...) — the Python
    // layer.type.name parity that selects the scalar vs vector tabs.
    std::string type_name;
    std::string crs;
    double opacity = 1.0;
    std::string source_ref;
    std::uint64_t data_revision = 0;
    std::uint64_t style_revision = 0;
    std::string metadata_repr;   // display-only dict repr
    std::string provenance_ref;
};

// Injected seam for the native QGIS symbology editor — the qt target
// cannot link the qgis target, so the host (or the qgis library's
// symbology_bridge) provides the opener. `available` mirrors
// qgis_symbology_available(); `open` mirrors open_renderer_properties():
// it returns the {"qgis_style", "opacity"} result Json on accept, nullopt
// on cancel, and throws SymbologyBridgeError on failure.
struct SymbologyHooks {
    bool available = false;
    std::function<std::optional<Json>(QWidget* parent,
                                     const std::string& title,
                                     const Json& features,
                                     const std::string& crs,
                                     const std::vector<std::string>& fields,
                                     const Json& style)>
        open;
    // _renderer_info parity: display-only renderer-type lookup over the
    // payload's renderer_xml ("singleSymbol"/"categorizedSymbol"/...).
    // Returns nullopt when unavailable — the label falls back to
    // "QGIS renderer" (Python parity).
    std::function<std::optional<std::string>(
        const std::string& renderer_xml)>
        renderer_info;
};

class MapLayerPropertiesDialog : public QDialog {
    Q_OBJECT
public:
    // `features`/`fields` feed the native symbology editor's dialog
    // request (geometry detection + classification field list).
    MapLayerPropertiesDialog(const LayerView& layer,
                             const Json& style = Json::object(),
                             QWidget* parent = nullptr,
                             const Json& features = Json::array(),
                             const std::vector<std::string>& fields = {},
                             const SymbologyHooks& symbology = {});

    // The payload Apply/OK emits (Python payload() parity, Qt-free core).
    Json payload() const;

    // Inline error for the Classes (JSON) field, or nullopt
    // (classes_json_error parity).
    std::optional<QString> classes_json_error() const;

    // Apply the current form (emits properties_applied unless a
    // classes-JSON error gates it — Python apply() parity).
    void apply();

    QTabWidget* tabs() const { return tabs_; }
    // Test/self-check access to key controls (Python test parity).
    QLineEdit* name_edit() const { return name_edit_; }
    QLineEdit* crs_edit() const { return crs_edit_; }
    QDoubleSpinBox* opacity_spin() const { return opacity_spin_; }
    QLineEdit* fill_edit() const { return fill_edit_; }
    QLineEdit* stroke_edit() const { return stroke_edit_; }
    QDoubleSpinBox* stroke_width_spin() const {
        return stroke_width_spin_;
    }
    QComboBox* renderer_combo() const { return renderer_combo_; }
    QComboBox* line_pattern_combo() const {
        return line_pattern_combo_;
    }
    QComboBox* marker_combo() const { return marker_combo_; }
    QDoubleSpinBox* marker_size_spin() const {
        return marker_size_spin_;
    }
    QLineEdit* classification_field_edit() const {
        return classification_field_edit_;
    }
    QPlainTextEdit* classes_edit() const { return classes_edit_; }
    QLabel* classes_error_label() const { return classes_error_label_; }
    QLineEdit* label_field_edit() const { return label_field_edit_; }
    QDoubleSpinBox* label_size_spin() const { return label_size_spin_; }
    QComboBox* color_ramp_combo() const { return color_ramp_combo_; }
    QDoubleSpinBox* range_min_spin() const { return range_min_spin_; }
    QDoubleSpinBox* range_max_spin() const { return range_max_spin_; }
    QDoubleSpinBox* gamma_spin() const { return gamma_spin_; }
    QComboBox* nodata_combo() const { return nodata_combo_; }
    QPushButton* qgis_edit_button() const { return qgis_edit_button_; }
    QLabel* symbology_error_label() const {
        return symbology_error_label_;
    }
    // The pending native-editor payload (Python _pending_qgis_style).
    const Json& pending_qgis_style() const {
        return pending_qgis_style_;
    }

signals:
    void properties_applied(const QString& layer_id,
                            const pwb::ui_canvas::Json& payload);

private:
    void build_qgis_symbology_tab(QWidget* page);
    void build_legacy_symbology_tab(QWidget* page, const Json& style);
    void open_qgis_editor();
    void accept_after_apply();
    PropertiesForm collect_form() const;
    std::optional<pwb::cartography::QgisStylePayload> style_payload()
        const;

    LayerView layer_;
    bool is_scalar_ = false;
    bool qgis_symbology_ = false;
    Json style_;
    Json features_ = Json::array();
    std::vector<std::string> fields_;
    SymbologyHooks symbology_hooks_;
    Json pending_qgis_style_ = Json(nullptr);
    std::optional<pwb::cartography::QgisStylePayload> style_payload_;

    QTabWidget* tabs_ = nullptr;
    QLineEdit* name_edit_ = nullptr;
    QLineEdit* crs_edit_ = nullptr;
    QDoubleSpinBox* opacity_spin_ = nullptr;
    // legacy symbology
    QLineEdit* fill_edit_ = nullptr;
    QLineEdit* stroke_edit_ = nullptr;
    QDoubleSpinBox* stroke_width_spin_ = nullptr;
    QComboBox* line_pattern_combo_ = nullptr;
    QComboBox* marker_combo_ = nullptr;
    QDoubleSpinBox* marker_size_spin_ = nullptr;
    QComboBox* renderer_combo_ = nullptr;
    QLineEdit* classification_field_edit_ = nullptr;
    QPlainTextEdit* classes_edit_ = nullptr;
    QLabel* classes_error_label_ = nullptr;
    // qgis symbology
    QPushButton* qgis_edit_button_ = nullptr;
    QLabel* symbology_error_label_ = nullptr;
    // scalar symbology
    QComboBox* color_ramp_combo_ = nullptr;
    QDoubleSpinBox* range_min_spin_ = nullptr;
    QDoubleSpinBox* range_max_spin_ = nullptr;
    QDoubleSpinBox* gamma_spin_ = nullptr;
    QComboBox* nodata_combo_ = nullptr;
    // labels
    QLineEdit* label_field_edit_ = nullptr;
    QDoubleSpinBox* label_size_spin_ = nullptr;
    QDialogButtonBox* buttons_ = nullptr;
};

}  // namespace pwb::ui_canvas
