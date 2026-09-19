#include <pwb/ui_wellseis/qt/project_well_map_page.hpp>

#include <algorithm>
#include <cmath>
#include <limits>

#include <QHBoxLayout>
#include <QHeaderView>
#include <QItemSelectionModel>
#include <QLabel>
#include <QLineEdit>
#include <QListView>
#include <QPushButton>
#include <QSortFilterProxyModel>
#include <QSplitter>
#include <QVBoxLayout>

#include <pwb/ui_wellseis/qt/object_table_model.hpp>
#include <pwb/ui_wellseis/qt/well_map_canvas.hpp>

namespace pwb::ui_wellseis::qt {

namespace {

QString qs(const std::string& text) {
    return QString::fromUtf8(text.data(), static_cast<int>(text.size()));
}

constexpr double kSelectionMarginRatio = 0.15;

}  // namespace

ProjectWellMapPage::ProjectWellMapPage(QWidget* parent,
                                       IWellMapSurface* surface)
    : QWidget(parent) {
    setObjectName(QStringLiteral("ProjectWellMapPage"));

    auto* root = new QHBoxLayout(this);
    root->setContentsMargins(16, 16, 16, 16);
    root->setSpacing(8);

    auto* splitter = new QSplitter(Qt::Horizontal, this);
    splitter->setObjectName(QStringLiteral("WellMapSplitter"));
    splitter->setChildrenCollapsible(false);
    root->addWidget(splitter);

    // ---- left: search + list -------------------------------------------
    auto* side = new QWidget(splitter);
    auto* side_layout = new QVBoxLayout(side);
    side_layout->setContentsMargins(0, 0, 0, 0);
    side_layout->setSpacing(4);

    list_model_ = new StringTableModel(this);
    list_model_->set_columns(
        {{QStringLiteral("name"), QStringLiteral("井")}});
    proxy_ = new QSortFilterProxyModel(this);
    proxy_->setSourceModel(list_model_);
    proxy_->setFilterCaseSensitivity(Qt::CaseInsensitive);

    search_box_ = new QLineEdit(side);
    search_box_->setPlaceholderText(
        QStringLiteral("搜索井名 / UWI…"));
    search_box_->setClearButtonEnabled(true);
    connect(search_box_, &QLineEdit::textChanged, proxy_,
            &QSortFilterProxyModel::setFilterFixedString);
    side_layout->addWidget(search_box_);

    well_list_ = new QListView(side);
    well_list_->setModel(proxy_);
    well_list_->setSelectionMode(QAbstractItemView::ExtendedSelection);
    well_list_->setUniformItemSizes(true);
    connect(well_list_->selectionModel(),
            &QItemSelectionModel::selectionChanged, this,
            [this] { on_list_selection_changed(); });
    connect(well_list_, &QListView::doubleClicked, this,
            [this](const QModelIndex& proxy_index) {
                const QModelIndex source =
                    proxy_->mapToSource(proxy_index);
                if (auto key = list_model_->key_for_index(source)) {
                    emit well_activated(qs(*key));
                }
            });
    side_layout->addWidget(well_list_, 1);
    splitter->addWidget(side);

    // ---- center: toolbar + surface -------------------------------------
    auto* center = new QWidget(splitter);
    auto* center_layout = new QVBoxLayout(center);
    center_layout->setContentsMargins(0, 0, 0, 0);
    center_layout->setSpacing(4);

    auto* toolbar = new QHBoxLayout();
    toolbar->setSpacing(4);
    btn_zoom_all_ = new QPushButton(QStringLiteral("缩放全部"), center);
    btn_zoom_selection_ =
        new QPushButton(QStringLiteral("缩放选中"), center);
    btn_reset_ = new QPushButton(QStringLiteral("复位"), center);
    btn_reference_ = new QPushButton(QStringLiteral("参考图层"), center);
    btn_reference_->setCheckable(true);
    btn_reference_->setToolTip(QStringLiteral(
        "叠加编图工程中的矢量参考图层（GDAL 重投影到工程 CRS）；"
        "栅格图层无法在此视图渲染"));
    connect(btn_reference_, &QPushButton::toggled, this,
            [this] { rebuild_scene(); });
    btn_labels_ = new QPushButton(QStringLiteral("井名标注"), center);
    btn_labels_->setCheckable(true);
    btn_labels_->setChecked(true);
    btn_labels_->setToolTip(QStringLiteral("在地图上显示井名标注"));
    connect(btn_labels_, &QPushButton::toggled, this,
            [this] { rebuild_scene(); });
    for (QPushButton* btn : {btn_zoom_all_, btn_zoom_selection_, btn_reset_,
                             btn_reference_, btn_labels_}) {
        toolbar->addWidget(btn);
    }
    toolbar->addStretch(1);
    crs_label_ = new QLabel(QString(), center);
    crs_label_->setStyleSheet(QStringLiteral("color: #6b6f76;"));
    toolbar->addWidget(crs_label_);
    coord_label_ = new QLabel(QString(), center);
    coord_label_->setMinimumWidth(220);
    coord_label_->setAlignment(Qt::AlignRight | Qt::AlignVCenter);
    coord_label_->setStyleSheet(QStringLiteral("color: #6b6f76;"));
    toolbar->addWidget(coord_label_);
    center_layout->addLayout(toolbar);

    crs_warning_label_ = new QLabel(QString(), center);
    crs_warning_label_->setWordWrap(true);
    crs_warning_label_->setStyleSheet(QStringLiteral("color: #b46a00;"));
    crs_warning_label_->setVisible(false);
    center_layout->addWidget(crs_warning_label_);

    // Map surface — injected seam or built-in fallback.
    if (surface != nullptr) {
        surface_ = surface;
    } else {
        owned_canvas_ = std::make_unique<WellMapCanvas>(center);
        surface_ = owned_canvas_.get();
    }
    surface_->on_point_hovered = [this](const std::string& series, int index,
                                        double x, double y) {
        on_point_hovered(series, index, x, y);
    };
    surface_->on_point_clicked = [this](const std::string& series, int index,
                                        double x, double y) {
        on_point_clicked(series, index, x, y);
    };
    connect(btn_zoom_all_, &QPushButton::clicked, this,
            &ProjectWellMapPage::zoom_to_all);
    connect(btn_zoom_selection_, &QPushButton::clicked, this,
            &ProjectWellMapPage::zoom_to_selection);
    connect(btn_reset_, &QPushButton::clicked, this,
            [this] { surface_->reset_view(); });
    center_layout->addWidget(surface_->widget(), 1);

    empty_label_ = new QLabel(
        QStringLiteral(
            "暂无测区井。在数据页导入井位文件后自动识别；其他参考井在数据树中"
            "单独管理。"),
        center);
    empty_label_->setAlignment(Qt::AlignCenter);
    empty_label_->setStyleSheet(QStringLiteral("color: #6b6f76;"));
    center_layout->addWidget(empty_label_);

    splitter->addWidget(center);
    splitter->setStretchFactor(0, 0);
    splitter->setStretchFactor(1, 1);
    splitter->setSizes({240, 760});
}

ProjectWellMapPage::~ProjectWellMapPage() = default;

void ProjectWellMapPage::set_project(const ProjectSlice& project) {
    project_ = project;
    model_ = build_well_map_model(project.wells);

    // Well list: "name + flag" rows in registry order (reference wells
    // already filtered inside the model).
    std::vector<std::string> keys;
    std::vector<std::vector<QString>> rows;
    list_row_ids_.clear();
    keys.reserve(model_.rows.size());
    rows.reserve(model_.rows.size());
    for (const WellMapListRow& row : model_.rows) {
        keys.push_back(row.well_id);
        list_row_ids_.push_back(row.well_id);
        rows.push_back({qs(row.display_name + row.flag)});
    }
    const auto captured =
        capture_selected_keys(well_list_->selectionModel(), list_model_);
    const auto current =
        current_key(well_list_->selectionModel(), list_model_);
    list_model_->set_rows(keys, rows);
    restore_selected_keys(well_list_->selectionModel(), list_model_,
                          captured, current);

    crs_label_->setText(qs(project_crs_label(project)));
    const std::string banner = crs_warning_banner(project);
    crs_warning_label_->setText(qs(banner));
    crs_warning_label_->setVisible(!banner.empty());
    empty_label_->setVisible(model_.rows.empty());
    rebuild_scene();
    surface_->autofit();
}

void ProjectWellMapPage::clear() {
    set_project(ProjectSlice{});
}

void ProjectWellMapPage::rebuild_scene() {
    WellMapScene scene;
    const std::size_t split = model_.ok_count;
    for (std::size_t i = 0; i < model_.scatter.size(); ++i) {
        const bool ok = i < split;
        auto& target = ok ? scene.ok_points : scene.flagged_points;
        auto& labels = ok ? scene.ok_labels : scene.flagged_labels;
        target.push_back(model_.scatter[i]);
        labels.push_back(model_.ordered_labels[i]);
    }
    for (const std::string& id : selected_ids_) {
        const int row = model_row_for_well(id);
        const auto it = model_.row_to_array.find(row);
        if (it != model_.row_to_array.end()) {
            scene.selected_points.push_back(model_.scatter[it->second]);
        }
    }
    scene.show_labels = btn_labels_->isChecked();
    scene.boundary = boundary_ring(project_);
    scene.survey_rings = survey_extent_rings(project_);
    if (btn_reference_->isChecked()) {
        std::size_t budget = kMaxReferenceVertices;
        for (const auto& ring : reference_rings_) {
            if (budget == 0) {
                break;
            }
            WellMapRing clipped;
            clipped.reserve(ring.size());
            for (const auto& point : ring) {
                if (budget == 0) {
                    break;
                }
                clipped.push_back(point);
                --budget;
            }
            scene.reference_rings.push_back(std::move(clipped));
        }
    }
    scene.spatial_cursor = spatial_cursor_;
    surface_->set_scene(scene);
}

int ProjectWellMapPage::model_row_for_well(const std::string& well_id) const {
    for (std::size_t i = 0; i < model_.rows.size(); ++i) {
        if (model_.rows[i].well_id == well_id) {
            return static_cast<int>(i);
        }
    }
    return -1;
}

std::optional<std::string> ProjectWellMapPage::well_id_for(
    const std::string& series, int index) const {
    // "wells_flagged" indices are offset past the OK block.
    const std::size_t offset = series == "wells_flagged" ? model_.ok_count : 0;
    if (series != "wells" && series != "wells_flagged") {
        return std::nullopt;
    }
    const std::size_t array_idx = offset + static_cast<std::size_t>(index);
    if (array_idx < model_.ordered_list_rows.size()) {
        const int row = model_.ordered_list_rows[array_idx];
        if (row >= 0 && row < static_cast<int>(model_.rows.size())) {
            return model_.rows[row].well_id;
        }
    }
    return std::nullopt;
}

std::string ProjectWellMapPage::display_name_for(const std::string& series,
                                                 int index) const {
    const std::size_t offset = series == "wells_flagged" ? model_.ok_count : 0;
    const std::size_t array_idx = offset + static_cast<std::size_t>(index);
    if (array_idx < model_.ordered_list_rows.size()) {
        const int row = model_.ordered_list_rows[array_idx];
        if (row >= 0 && row < static_cast<int>(model_.rows.size())) {
            return model_.rows[row].display_name;
        }
    }
    return "";
}

void ProjectWellMapPage::on_point_hovered(const std::string& series,
                                          int index, double x, double y) {
    const std::string name = display_name_for(series, index);
    const QString suffix = series == "wells_flagged"
                               ? QStringLiteral("（源坐标显示）")
                               : QString();
    coord_label_->setText(
        QStringLiteral("%1  X: %2  Y: %3%4")
            .arg(qs(name))
            .arg(x, 0, 'f', 2)
            .arg(y, 0, 'f', 2)
            .arg(suffix));
    if (well_id_for(series, index).has_value()) {
        well_list_->setToolTip(QStringLiteral("%1\nX: %2\nY: %3")
                                   .arg(qs(name))
                                   .arg(x, 0, 'f', 2)
                                   .arg(y, 0, 'f', 2));
    }
}

void ProjectWellMapPage::on_point_clicked(const std::string& series,
                                          int index, double, double) {
    const auto well_id = well_id_for(series, index);
    if (!well_id.has_value()) {
        return;
    }
    select_well(*well_id, /*zoom=*/false, /*emit_signal=*/true);
}

void ProjectWellMapPage::select_well(const std::string& well_id, bool zoom,
                                     bool emit_signal) {
    select_wells({well_id}, zoom, emit_signal);
}

void ProjectWellMapPage::select_wells(
    const std::vector<std::string>& well_ids, bool zoom, bool emit_single) {
    selected_ids_.clear();
    for (const std::string& id : well_ids) {
        if (model_row_for_well(id) >= 0) {
            selected_ids_.insert(id);
        }
    }
    sync_list_selection();
    rebuild_scene();
    if (emit_single && selected_ids_.size() == 1) {
        emit well_selected(qs(*selected_ids_.begin()));
    }
    if (zoom) {
        zoom_to_selection();
    }
}

std::vector<std::string> ProjectWellMapPage::selected_well_ids() const {
    return {selected_ids_.begin(), selected_ids_.end()};
}

void ProjectWellMapPage::clear_selection() {
    selected_ids_.clear();
    sync_list_selection();
    rebuild_scene();
}

void ProjectWellMapPage::sync_list_selection() {
    syncing_selection_ = true;
    auto* selection = well_list_->selectionModel();
    selection->clearSelection();
    QModelIndex first;
    for (const std::string& id : selected_ids_) {
        const int row = model_row_for_well(id);
        if (row < 0) {
            continue;
        }
        const QModelIndex proxy =
            proxy_->mapFromSource(list_model_->index(row, 0));
        if (proxy.isValid()) {
            selection->select(proxy, QItemSelectionModel::Select);
            if (!first.isValid()) {
                first = proxy;
            }
        }
    }
    if (first.isValid()) {
        well_list_->scrollTo(first, QAbstractItemView::EnsureVisible);
    }
    syncing_selection_ = false;
}

void ProjectWellMapPage::on_list_selection_changed() {
    if (syncing_selection_) {
        return;
    }
    std::vector<std::string> ids;
    for (const QModelIndex& proxy_index :
             well_list_->selectionModel()->selectedIndexes()) {
        const QModelIndex source = proxy_->mapToSource(proxy_index);
        if (auto key = list_model_->key_for_index(source)) {
            ids.push_back(*key);
        }
    }
    if (ids.empty()) {
        return;
    }
    selected_ids_ = {ids.begin(), ids.end()};
    rebuild_scene();
    if (ids.size() == 1) {
        emit well_selected(qs(ids.front()));
    }
}

void ProjectWellMapPage::zoom_to_well(const std::string& well_id,
                                      double zoom_factor) {
    const int row = model_row_for_well(well_id);
    const auto it = model_.row_to_array.find(row);
    if (row < 0 || it == model_.row_to_array.end() || model_.scatter.empty()) {
        return;
    }
    const auto& point = model_.scatter[it->second];
    surface_->focus_point(point.first, point.second, zoom_factor);
}

void ProjectWellMapPage::zoom_to_selection() {
    std::vector<std::size_t> indices;
    for (const std::string& id : selected_ids_) {
        const int row = model_row_for_well(id);
        const auto it = model_.row_to_array.find(row);
        if (row >= 0 && it != model_.row_to_array.end()) {
            indices.push_back(static_cast<std::size_t>(it->second));
        }
    }
    if (indices.empty()) {
        return;
    }
    double xmin = std::numeric_limits<double>::max();
    double ymin = std::numeric_limits<double>::max();
    double xmax = std::numeric_limits<double>::lowest();
    double ymax = std::numeric_limits<double>::lowest();
    for (const std::size_t i : indices) {
        const auto& [x, y] = model_.scatter[i];
        xmin = std::min(xmin, x);
        xmax = std::max(xmax, x);
        ymin = std::min(ymin, y);
        ymax = std::max(ymax, y);
    }
    const double dx =
        std::max({xmax - xmin, std::abs(xmin) * 1e-3, 1e-6}) *
        kSelectionMarginRatio;
    const double dy =
        std::max({ymax - ymin, std::abs(ymin) * 1e-3, 1e-6}) *
        kSelectionMarginRatio;
    surface_->set_view_bounds(xmin - dx, xmax + dx, ymin - dy, ymax + dy);
}

void ProjectWellMapPage::zoom_to_all() {
    surface_->autofit();
}

void ProjectWellMapPage::focus_well(const std::string& well_id) {
    select_well(well_id);
    zoom_to_well(well_id);
}

void ProjectWellMapPage::show_spatial_cursor(double x, double y) {
    spatial_cursor_ = {x, y};
    coord_label_->setText(QStringLiteral("地震光标  X: %1  Y: %2")
                              .arg(x, 0, 'f', 2)
                              .arg(y, 0, 'f', 2));
    rebuild_scene();
}

void ProjectWellMapPage::clear_spatial_cursor() {
    spatial_cursor_ = std::nullopt;
    rebuild_scene();
}

std::optional<std::pair<double, double>>
ProjectWellMapPage::spatial_cursor_position() const {
    return spatial_cursor_;
}

void ProjectWellMapPage::set_reference_rings(
    const std::vector<std::vector<std::pair<double, double>>>& rings) {
    reference_rings_ = rings;
    rebuild_scene();
}

IWellMapSurface* ProjectWellMapPage::surface() const {
    return surface_;
}

QString ProjectWellMapPage::crs_warning_text() const {
    return crs_warning_label_->text();
}

QString ProjectWellMapPage::crs_label_text() const {
    return crs_label_->text();
}

QString ProjectWellMapPage::coord_label_text() const {
    return coord_label_->text();
}

bool ProjectWellMapPage::empty_state_visible() const {
    return empty_label_->isVisible();
}

int ProjectWellMapPage::well_list_count() const {
    return proxy_->rowCount();
}

}  // namespace pwb::ui_wellseis::qt
