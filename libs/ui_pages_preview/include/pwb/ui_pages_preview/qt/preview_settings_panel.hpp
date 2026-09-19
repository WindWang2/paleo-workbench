#pragma once

// Port of paleo_workbench/ui/pages/preview_settings_panel.py (UI-07):
// compact category-based QFrame editor for every supported preview mode —
// 8 category pages (general/text/table/image/pdf/json/media/geoviz), a
// mode→category combo, apply → store.save + settings_applied, reset →
// store.reset + defaults + settings_applied.

#include <QFrame>
#include <QString>
#include <memory>

class QCheckBox;
class QComboBox;
class QFormLayout;
class QHBoxLayout;
class QLabel;
class QPushButton;
class QSpinBox;
class QStackedWidget;
class QVBoxLayout;
class QWidget;

#include <pwb/ui_pages_preview/preview_settings.hpp>
// Complete type required: AUTOMOC-generated metatype code instantiates the
// panel's destructor, which needs a complete PreviewSettingsStore for the
// unique_ptr member.
#include <pwb/ui_pages_preview/qt/preview_settings_store.hpp>

namespace pwb::ui_pages_preview {

class PreviewSettingsPanel : public QFrame {
    Q_OBJECT
public:
    // `store` may be injected (tests pass a temp-file-backed store); when
    // null the panel constructs the default platform store. Not owned.
    explicit PreviewSettingsPanel(QWidget* parent = nullptr,
                                  PreviewSettingsStore* store = nullptr);

    // Read/write the editor state (control values ↔ PreviewSettings).
    PreviewSettings settings() const;
    void set_settings(const PreviewSettings& settings);

    // set_preview_mode(mode): category = _MODE_CATEGORY.get(mode,"general").
    void set_preview_mode(const QString& mode);

    PreviewSettingsStore* store() const { return store_; }

    // UI-15: PreviewSettingsDialog wraps this panel modally and accepts on
    // Apply only (reset keeps the dialog open — Python apply_btn.clicked
    // parity).
    QPushButton* apply_button() const { return apply_btn_; }
    QPushButton* reset_button() const { return reset_btn_; }

signals:
    void settings_applied(const pwb::ui_pages_preview::PreviewSettings& s);

private:
    QWidget* make_page(QFormLayout** form_out);
    QSpinBox* make_spin(int minimum, int maximum,
                        const QString& suffix = QString());
    void add_page(const QString& key, const QString& label, QWidget* page);

    void build_general_page();
    void build_text_page();
    void build_table_page();
    void build_image_page();
    void build_pdf_page();
    void build_json_page();
    void build_media_page();
    void build_geoviz_page();

    void apply();
    void reset();

    PreviewSettingsStore* store_ = nullptr;        // not owned when injected
    std::unique_ptr<PreviewSettingsStore> owned_;

    QComboBox* category_combo_ = nullptr;
    QStackedWidget* pages_ = nullptr;
    QPushButton* reset_btn_ = nullptr;
    QPushButton* apply_btn_ = nullptr;

    // general
    QSpinBox* font_size_spin_ = nullptr;
    QCheckBox* show_metadata_check_ = nullptr;
    // text
    QSpinBox* text_limit_spin_ = nullptr;
    QCheckBox* wrap_text_check_ = nullptr;
    // table
    QSpinBox* table_rows_spin_ = nullptr;
    QSpinBox* table_columns_spin_ = nullptr;
    QCheckBox* auto_fit_columns_check_ = nullptr;
    // image
    QCheckBox* smooth_images_check_ = nullptr;
    QSpinBox* geotiff_thumbnail_spin_ = nullptr;
    QCheckBox* show_geo_metadata_check_ = nullptr;
    // pdf
    QComboBox* pdf_fit_combo_ = nullptr;
    QSpinBox* pdf_zoom_spin_ = nullptr;
    // json
    QSpinBox* json_limit_spin_ = nullptr;
    QSpinBox* json_collapse_spin_ = nullptr;
    QSpinBox* json_depth_spin_ = nullptr;
    // media
    QCheckBox* media_autoplay_check_ = nullptr;
    QSpinBox* media_volume_spin_ = nullptr;
    // geoviz
    QSpinBox* geoviz_curves_spin_ = nullptr;
    QSpinBox* geoviz_depth_spin_ = nullptr;
    QSpinBox* geoviz_slice_spin_ = nullptr;
    QSpinBox* geoviz_points_spin_ = nullptr;
    QSpinBox* geoviz_grid_spin_ = nullptr;
};

}  // namespace pwb::ui_pages_preview
