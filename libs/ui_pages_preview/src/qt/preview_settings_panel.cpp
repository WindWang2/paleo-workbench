#include <pwb/ui_pages_preview/qt/preview_settings_panel.hpp>

#include <QCheckBox>
#include <QComboBox>
#include <QFormLayout>
#include <QHBoxLayout>
#include <QLabel>
#include <QPushButton>
#include <QSpinBox>
#include <QStackedWidget>
#include <QVBoxLayout>

#include <pwb/ui_pages_preview/qt/preview_settings_store.hpp>
#include <pwb/ui_shell/style_registry.hpp>

#include "../qt/style_util.hpp"

namespace pwb::ui_pages_preview {

namespace {

QString panel_qss() {
    return QStringLiteral(
        "QFrame#PreviewSettingsPanel { background: %1; border: 1px solid %2;"
        " border-radius: %3px; }")
        .arg(qt_internal::token("BG_SIDEBAR"), qt_internal::token("BORDER"))
        .arg(qt_internal::RADIUS_CARD);
}

QString title_qss() {
    return QStringLiteral("color: %1; font-weight: 600;")
        .arg(qt_internal::token("TEXT_PRIMARY"));
}

}  // namespace

PreviewSettingsPanel::PreviewSettingsPanel(QWidget* parent,
                                           PreviewSettingsStore* store)
    : QFrame(parent) {
    setObjectName(QStringLiteral("PreviewSettingsPanel"));
    if (store != nullptr) {
        store_ = store;
    } else {
        owned_ = std::make_unique<PreviewSettingsStore>();
        store_ = owned_.get();
    }
    pwb::ui_shell::style_bind(this, panel_qss);  // E1: theme-switch re-render

    auto* outer = new QVBoxLayout(this);
    outer->setContentsMargins(qt_internal::SPACE_3, qt_internal::SPACE_3,
                              qt_internal::SPACE_3, qt_internal::SPACE_3);
    outer->setSpacing(qt_internal::SPACE_2);

    auto* heading = new QHBoxLayout();
    auto* title = new QLabel(QStringLiteral("预览内容设置"));
    title->setStyleSheet(title_qss());
    heading->addWidget(title);
    heading->addStretch();
    category_combo_ = new QComboBox();
    category_combo_->setObjectName(QStringLiteral("PreviewSettingsCategory"));
    heading->addWidget(category_combo_);
    outer->addLayout(heading);

    pages_ = new QStackedWidget();
    outer->addWidget(pages_);

    build_general_page();
    build_text_page();
    build_table_page();
    build_image_page();
    build_pdf_page();
    build_json_page();
    build_media_page();
    build_geoviz_page();
    connect(category_combo_, &QComboBox::currentIndexChanged, pages_,
            &QStackedWidget::setCurrentIndex);

    auto* actions = new QHBoxLayout();
    actions->addStretch();
    reset_btn_ = new QPushButton(QStringLiteral("恢复推荐默认"));
    reset_btn_->setObjectName(QStringLiteral("SecondaryButton"));
    apply_btn_ = new QPushButton(QStringLiteral("应用"));
    apply_btn_->setObjectName(QStringLiteral("PrimaryButton"));
    actions->addWidget(reset_btn_);
    actions->addWidget(apply_btn_);
    outer->addLayout(actions);

    connect(apply_btn_, &QPushButton::clicked, this, [this] { apply(); });
    connect(reset_btn_, &QPushButton::clicked, this, [this] { reset(); });
    set_settings(store_->load());
}

QWidget* PreviewSettingsPanel::make_page(QFormLayout** form_out) {
    auto* page = new QWidget();
    auto* form = new QFormLayout(page);
    form->setContentsMargins(0, 0, 0, 0);
    form->setHorizontalSpacing(qt_internal::SPACE_3);
    form->setVerticalSpacing(qt_internal::SPACE_2);
    *form_out = form;
    return page;
}

QSpinBox* PreviewSettingsPanel::make_spin(int minimum, int maximum,
                                          const QString& suffix) {
    auto* control = new QSpinBox();
    control->setRange(minimum, maximum);
    if (!suffix.isEmpty()) {
        control->setSuffix(suffix);
    }
    return control;
}

void PreviewSettingsPanel::add_page(const QString& key, const QString& label,
                                    QWidget* page) {
    category_combo_->addItem(label, key);
    pages_->addWidget(page);
}

void PreviewSettingsPanel::build_general_page() {
    QFormLayout* form = nullptr;
    QWidget* page = make_page(&form);
    font_size_spin_ = make_spin(8, 32, QStringLiteral(" pt"));
    show_metadata_check_ =
        new QCheckBox(QStringLiteral("显示类型、格式、状态和路径"));
    form->addRow(QStringLiteral("内容字号"), font_size_spin_);
    form->addRow(QStringLiteral("元数据"), show_metadata_check_);
    add_page(QStringLiteral("general"), QStringLiteral("通用"), page);
}

void PreviewSettingsPanel::build_text_page() {
    QFormLayout* form = nullptr;
    QWidget* page = make_page(&form);
    text_limit_spin_ = make_spin(16, 4096, QStringLiteral(" KiB"));
    wrap_text_check_ = new QCheckBox(QStringLiteral("自动换行"));
    form->addRow(QStringLiteral("读取上限"), text_limit_spin_);
    form->addRow(QStringLiteral("长行"), wrap_text_check_);
    add_page(QStringLiteral("text"), QStringLiteral("文本 / 富文本"), page);
}

void PreviewSettingsPanel::build_table_page() {
    QFormLayout* form = nullptr;
    QWidget* page = make_page(&form);
    table_rows_spin_ = make_spin(20, 2000, QStringLiteral(" 行"));
    table_columns_spin_ = make_spin(5, 200, QStringLiteral(" 列"));
    auto_fit_columns_check_ =
        new QCheckBox(QStringLiteral("按内容调整列宽"));
    form->addRow(QStringLiteral("最大行数"), table_rows_spin_);
    form->addRow(QStringLiteral("最大列数"), table_columns_spin_);
    form->addRow(QStringLiteral("列宽"), auto_fit_columns_check_);
    add_page(QStringLiteral("table"), QStringLiteral("表格 / 测井 / 地震"),
             page);
}

void PreviewSettingsPanel::build_image_page() {
    QFormLayout* form = nullptr;
    QWidget* page = make_page(&form);
    smooth_images_check_ = new QCheckBox(QStringLiteral("平滑缩放"));
    geotiff_thumbnail_spin_ = make_spin(128, 2048, QStringLiteral(" px"));
    show_geo_metadata_check_ =
        new QCheckBox(QStringLiteral("显示 CRS、范围和栅格信息"));
    form->addRow(QStringLiteral("图片"), smooth_images_check_);
    form->addRow(QStringLiteral("GeoTIFF 缩略图"), geotiff_thumbnail_spin_);
    form->addRow(QStringLiteral("GIS 元数据"), show_geo_metadata_check_);
    add_page(QStringLiteral("image"), QStringLiteral("图片 / GeoTIFF"), page);
}

void PreviewSettingsPanel::build_pdf_page() {
    QFormLayout* form = nullptr;
    QWidget* page = make_page(&form);
    pdf_fit_combo_ = new QComboBox();
    pdf_fit_combo_->addItem(QStringLiteral("适合整页"),
                          QStringLiteral("page"));
    pdf_fit_combo_->addItem(QStringLiteral("适合页宽"),
                          QStringLiteral("width"));
    pdf_fit_combo_->addItem(QStringLiteral("自定义缩放"),
                          QStringLiteral("custom"));
    pdf_zoom_spin_ = make_spin(25, 400, QStringLiteral("%"));
    form->addRow(QStringLiteral("打开方式"), pdf_fit_combo_);
    form->addRow(QStringLiteral("自定义缩放"), pdf_zoom_spin_);
    add_page(QStringLiteral("pdf"), QStringLiteral("PDF"), page);
}

void PreviewSettingsPanel::build_json_page() {
    QFormLayout* form = nullptr;
    QWidget* page = make_page(&form);
    json_limit_spin_ = make_spin(1, 64, QStringLiteral(" MiB"));
    json_collapse_spin_ = make_spin(10, 10000, QStringLiteral(" 项"));
    json_depth_spin_ = make_spin(0, 8, QStringLiteral(" 层"));
    form->addRow(QStringLiteral("解析上限"), json_limit_spin_);
    form->addRow(QStringLiteral("大数组折叠阈值"), json_collapse_spin_);
    form->addRow(QStringLiteral("初始展开深度"), json_depth_spin_);
    add_page(QStringLiteral("json"), QStringLiteral("JSON / GeoJSON"), page);
}

void PreviewSettingsPanel::build_media_page() {
    QFormLayout* form = nullptr;
    QWidget* page = make_page(&form);
    media_autoplay_check_ =
        new QCheckBox(QStringLiteral("加载后自动播放"));
    media_volume_spin_ = make_spin(0, 100, QStringLiteral("%"));
    form->addRow(QStringLiteral("播放"), media_autoplay_check_);
    form->addRow(QStringLiteral("默认音量"), media_volume_spin_);
    add_page(QStringLiteral("media"), QStringLiteral("音频媒体"), page);
}

void PreviewSettingsPanel::build_geoviz_page() {
    QFormLayout* form = nullptr;
    QWidget* page = make_page(&form);
    geoviz_curves_spin_ = make_spin(1, 64);
    geoviz_depth_spin_ = make_spin(100, 50000);
    geoviz_slice_spin_ = make_spin(64, 4096);
    geoviz_points_spin_ = make_spin(1000, 1000000);
    geoviz_grid_spin_ = make_spin(32, 1024);
    form->addRow(QStringLiteral("最大曲线数"), geoviz_curves_spin_);
    form->addRow(QStringLiteral("最大深度采样"), geoviz_depth_spin_);
    form->addRow(QStringLiteral("最大切片轴"), geoviz_slice_spin_);
    form->addRow(QStringLiteral("最大点数"), geoviz_points_spin_);
    form->addRow(QStringLiteral("表面网格"), geoviz_grid_spin_);
    add_page(QStringLiteral("geoviz"), QStringLiteral("GeoViz 专业预览"),
             page);
}

PreviewSettings PreviewSettingsPanel::settings() const {
    PreviewSettings s;
    s.font_size = font_size_spin_->value();
    s.show_metadata = show_metadata_check_->isChecked();
    s.text_limit_kib = text_limit_spin_->value();
    s.wrap_text = wrap_text_check_->isChecked();
    s.table_max_rows = table_rows_spin_->value();
    s.table_max_columns = table_columns_spin_->value();
    s.auto_fit_columns = auto_fit_columns_check_->isChecked();
    s.smooth_images = smooth_images_check_->isChecked();
    s.geotiff_thumbnail_px = geotiff_thumbnail_spin_->value();
    s.show_geo_metadata = show_geo_metadata_check_->isChecked();
    s.pdf_fit_mode =
        pdf_fit_combo_->currentData().toString().toStdString();
    s.pdf_zoom_percent = pdf_zoom_spin_->value();
    s.json_limit_mib = json_limit_spin_->value();
    s.json_array_collapse_threshold = json_collapse_spin_->value();
    s.json_expand_depth = json_depth_spin_->value();
    s.media_autoplay = media_autoplay_check_->isChecked();
    s.media_volume = media_volume_spin_->value();
    s.geoviz_max_curves = geoviz_curves_spin_->value();
    s.geoviz_max_depth_samples = geoviz_depth_spin_->value();
    s.geoviz_max_slice_axis = geoviz_slice_spin_->value();
    s.geoviz_max_points = geoviz_points_spin_->value();
    s.geoviz_surface_grid_size = geoviz_grid_spin_->value();
    return s;
}

void PreviewSettingsPanel::set_settings(const PreviewSettings& settings) {
    font_size_spin_->setValue(settings.font_size);
    show_metadata_check_->setChecked(settings.show_metadata);
    text_limit_spin_->setValue(settings.text_limit_kib);
    wrap_text_check_->setChecked(settings.wrap_text);
    table_rows_spin_->setValue(settings.table_max_rows);
    table_columns_spin_->setValue(settings.table_max_columns);
    auto_fit_columns_check_->setChecked(settings.auto_fit_columns);
    smooth_images_check_->setChecked(settings.smooth_images);
    geotiff_thumbnail_spin_->setValue(settings.geotiff_thumbnail_px);
    show_geo_metadata_check_->setChecked(settings.show_geo_metadata);
    const int fit_index = pdf_fit_combo_->findData(
        QString::fromStdString(settings.pdf_fit_mode));
    pdf_fit_combo_->setCurrentIndex(std::max(0, fit_index));
    pdf_zoom_spin_->setValue(settings.pdf_zoom_percent);
    json_limit_spin_->setValue(settings.json_limit_mib);
    json_collapse_spin_->setValue(settings.json_array_collapse_threshold);
    json_depth_spin_->setValue(settings.json_expand_depth);
    media_autoplay_check_->setChecked(settings.media_autoplay);
    media_volume_spin_->setValue(settings.media_volume);
    geoviz_curves_spin_->setValue(settings.geoviz_max_curves);
    geoviz_depth_spin_->setValue(settings.geoviz_max_depth_samples);
    geoviz_slice_spin_->setValue(settings.geoviz_max_slice_axis);
    geoviz_points_spin_->setValue(settings.geoviz_max_points);
    geoviz_grid_spin_->setValue(settings.geoviz_surface_grid_size);
}

void PreviewSettingsPanel::set_preview_mode(const QString& mode) {
    const QString category =
        QString::fromStdString(mode_category(mode.toStdString()));
    const int index = category_combo_->findData(category);
    if (index >= 0) {
        category_combo_->setCurrentIndex(index);
    }
}

void PreviewSettingsPanel::apply() {
    const PreviewSettings s = settings();
    store_->save(s);
    emit settings_applied(s);
}

void PreviewSettingsPanel::reset() {
    const PreviewSettings s = store_->reset();
    set_settings(s);
    emit settings_applied(s);
}

}  // namespace pwb::ui_pages_preview
