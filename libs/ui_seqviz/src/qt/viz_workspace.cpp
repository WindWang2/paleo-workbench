#include <pwb/ui_seqviz/qt/viz_workspace.hpp>

#include <QComboBox>
#include <QHBoxLayout>
#include <QLabel>
#include <QScrollArea>
#include <QSizePolicy>
#include <QTabWidget>
#include <QVBoxLayout>

#include <pwb/ui_seqviz/page_tokens.hpp>

namespace pwb::ui_seqviz::qt {

namespace {

// _SectionCursorBand — the well-level linkage indicator (mouse-transparent,
// no layout participation; the engine has no per-track crosshair API).
class SectionCursorBand : public QWidget {
public:
    explicit SectionCursorBand(QWidget* parent) : QWidget(parent) {
        setObjectName("SectionCursorBand");
        setAttribute(Qt::WA_TransparentForMouseEvents);
        setMinimumWidth(6);
        setMaximumWidth(6);
        hide();
    }
};

// Python tab order verbatim (addTab sequence in __init__).
const std::vector<VizHostKind>& python_tab_order() {
    static const std::vector<VizHostKind> order = {
        VizHostKind::WellLog,     VizHostKind::WellSection,
        VizHostKind::Seismic,     VizHostKind::CrossWell,
        VizHostKind::PaleoMap,    VizHostKind::WellTie,
        VizHostKind::EnginePreview,
    };
    return order;
}

}  // namespace

VisualizationWorkspace::VisualizationWorkspace(QWidget* parent)
    : QFrame(parent) {
    setObjectName("CompositeVisualizationPanel");
    setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Expanding);
    setMinimumSize(100, 100);

    auto* layout = new QVBoxLayout(this);
    const int pad = tokens::PANEL_PADDING;
    layout->setContentsMargins(pad, pad, pad, pad);
    layout->setSpacing(tokens::SPACE_2);

    status_label_ = new QLabel("", this);
    status_label_->setObjectName("WorkFieldLabel");
    status_label_->setWordWrap(true);
    layout->addWidget(status_label_);

    // Multiscale (相/亚相/微相) level selector for the 古地理 map tab —
    // hidden unless the current map payload is a facies hierarchy.
    level_bar_ = new QWidget(this);
    auto* level_layout = new QHBoxLayout(level_bar_);
    level_layout->setContentsMargins(0, 0, 0, 0);
    level_layout->setSpacing(tokens::SPACE_2);
    auto* level_label = new QLabel("古地理层级", level_bar_);
    level_combo_ = new QComboBox(level_bar_);
    level_combo_->setMinimumWidth(180);
    level_combo_->setToolTip(QStringLiteral(
        "多尺度相带显示：自动按比例尺切换，或锁定到某一相级（来自 "
        "geo-viz-engine）"));
    level_layout->addWidget(level_label);
    level_layout->addWidget(level_combo_);
    level_layout->addStretch(1);
    level_bar_->setVisible(false);
    layout->addWidget(level_bar_);
    connect(level_combo_, &QComboBox::currentIndexChanged, this,
            &VisualizationWorkspace::on_level_changed);

    tabs_ = new QTabWidget(this);
    tabs_->setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Expanding);
    tabs_->setMinimumSize(100, 100);
    layout->addWidget(tabs_, 1);
}

void VisualizationWorkspace::set_seams(VizWorkspaceSeams seams) {
    seams_ = std::move(seams);
    rebuild_tabs();
}

const VizHostSurface* VisualizationWorkspace::host(VizHostKind kind) const {
    const auto it = seams_.hosts.find(kind);
    return it == seams_.hosts.end() ? nullptr : &it->second;
}

void VisualizationWorkspace::rebuild_tabs() {
    while (tabs_->count() > 0) {
        tabs_->removeTab(0);
    }
    tab_order_.clear();
    delete cross_well_scroll_;
    cross_well_scroll_ = nullptr;
    section_cursor_band_ = nullptr;

    for (const VizHostKind kind : python_tab_order()) {
        const VizHostSurface* surface = host(kind);
        if (surface == nullptr || surface->widget == nullptr) {
            continue;
        }
        const QString title =
            QString::fromStdString(host_tab_title(kind));
        if (kind == VizHostKind::CrossWell) {
            cross_well_scroll_ = new QScrollArea(this);
            cross_well_scroll_->setObjectName("CrossWellTabScrollArea");
            cross_well_scroll_->setWidgetResizable(true);
            cross_well_scroll_->setFrameShape(QFrame::NoFrame);
            cross_well_scroll_->setHorizontalScrollBarPolicy(
                Qt::ScrollBarAsNeeded);
            cross_well_scroll_->setVerticalScrollBarPolicy(
                Qt::ScrollBarAsNeeded);
            cross_well_scroll_->setWidget(surface->widget);
            tabs_->addTab(cross_well_scroll_, title);
            // The cursor band parents to the host's inner widget (the
            // canvas container) exactly like Python.
            QWidget* band_parent = surface->inner_widget != nullptr
                                       ? surface->inner_widget
                                       : surface->widget;
            section_cursor_band_ = new SectionCursorBand(band_parent);
        } else {
            tabs_->addTab(surface->widget, title);
        }
        tab_order_.push_back(kind);
    }
}

int VisualizationWorkspace::tab_index_of(VizHostKind kind) const {
    for (int index = 0; index < tabs_->count(); ++index) {
        if (tabs_->tabText(index) ==
            QString::fromStdString(host_tab_title(kind))) {
            return index;
        }
    }
    return 0;
}

bool VisualizationWorkspace::has_well_log_loaded() const {
    const VizHostSurface* well = host(VizHostKind::WellLog);
    return well != nullptr && well->has_data && well->has_data();
}

void VisualizationWorkspace::set_project(
    const std::any& project, const std::string& project_path) {
    project_ = project;
    project_path_ = project_path;
    const VizHostSurface* well = host(VizHostKind::WellLog);
    if (well != nullptr && well->set_project) {
        well->set_project(project, project_path);
    }
}

void VisualizationWorkspace::update_state(
    const std::vector<PredictionTaskSlice>& tasks) {
    // active_prediction_task — last task wins (prediction_helpers parity).
    if (tasks.empty() || !seams_.prediction_resolver) {
        clear_all();
        status_label_->setText(QStringLiteral("选择左侧资产或等待预测任务…"));
        return;
    }
    load_payload(seams_.prediction_resolver(tasks.back()));
}

UiVizPayload VisualizationWorkspace::load(const UiVizPayload& payload) {
    load_payload(payload);
    return payload;
}

UiVizPayload VisualizationWorkspace::load_ref(const VizRefSlice& ref) {
    UiVizPayload payload;
    if (seams_.ref_resolver) {
        payload = seams_.ref_resolver(ref);
    } else {
        payload.kind = "message";
        payload.message = "无可视化数据";
    }
    load_payload(payload);
    return payload;
}

void VisualizationWorkspace::load_payload(const UiVizPayload& payload) {
    if (payload.kind == "message") {
        clear_all();
        status_label_->setText(QString::fromStdString(
            payload.message.empty() ? "无可视化数据" : payload.message));
        return;
    }

    clear_all(/*preserve_well=*/keep_well_session(payload));

    std::vector<std::string> applied_titles;
    for (const VizHostKind kind : hosts_to_apply(payload)) {
        const VizHostSurface* surface = host(kind);
        if (surface == nullptr || !surface->apply) {
            continue;
        }
        if (surface->apply(payload)) {
            const std::string title = host_tab_title(kind);
            // dict.fromkeys dedup — first-seen order.
            if (std::find(applied_titles.begin(), applied_titles.end(),
                          title) == applied_titles.end()) {
                applied_titles.push_back(title);
            }
        }
    }

    if (const auto focus = focus_tab_for(payload); focus.has_value()) {
        tabs_->setCurrentIndex(tab_index_of(*focus));
    }

    status_label_->setText(QString::fromStdString(workspace_status_text(
        payload.label, payload.warning, applied_titles)));
    refresh_level_selector();
}

void VisualizationWorkspace::clear_all(bool preserve_well) {
    const auto call_clear = [this](VizHostKind kind) {
        const VizHostSurface* surface = host(kind);
        if (surface != nullptr && surface->clear) {
            surface->clear();
        }
    };
    if (!preserve_well) {
        call_clear(VizHostKind::WellLog);
    }
    call_clear(VizHostKind::WellSection);
    call_clear(VizHostKind::Seismic);
    call_clear(VizHostKind::CrossWell);
    call_clear(VizHostKind::PaleoMap);
    level_combo_->blockSignals(true);
    level_combo_->clear();
    level_combo_->blockSignals(false);
    level_bar_->setVisible(false);
    call_clear(VizHostKind::WellTie);
    call_clear(VizHostKind::EnginePreview);
}

void VisualizationWorkspace::refresh_level_selector() {
    const VizHostSurface* map_host = host(VizHostKind::PaleoMap);
    const domain::Json features =
        map_host != nullptr && map_host->current_features
            ? map_host->current_features()
            : domain::Json::array();
    const auto choices = facies_level_choices(features);
    const bool hierarchical =
        map_host != nullptr && map_host->hierarchy_active &&
        map_host->hierarchy_active();

    level_combo_->blockSignals(true);
    level_combo_->clear();
    if (!hierarchical || choices.empty()) {
        level_combo_->blockSignals(false);
        level_bar_->setVisible(false);
        return;
    }
    for (const auto& [value, label] : choices) {
        level_combo_->addItem(QString::fromStdString(label),
                              QString::fromStdString(value));
    }
    level_combo_->setCurrentIndex(0);  // "auto" by default
    level_combo_->blockSignals(false);
    level_bar_->setVisible(true);
}

void VisualizationWorkspace::on_level_changed(int index) {
    const VizHostSurface* map_host = host(VizHostKind::PaleoMap);
    if (map_host == nullptr || !map_host->set_level) {
        return;
    }
    const QString value = level_combo_->itemData(index).toString();
    map_host->set_level(value.isEmpty() ? std::string(kAutoLevel)
                                      : value.toStdString());
}

void VisualizationWorkspace::show_section_cursor(
    const std::string& well_name) {
    if (section_cursor_band_ == nullptr) {
        return;
    }
    std::string name = well_name;
    const auto first = name.find_first_not_of(" \t\r\n");
    const auto last = name.find_last_not_of(" \t\r\n");
    name = first == std::string::npos
               ? std::string{}
               : name.substr(first, last - first + 1);
    const VizHostSurface* cross = host(VizHostKind::CrossWell);
    const std::vector<std::string> names =
        cross != nullptr && cross->last_well_names
            ? cross->last_well_names()
            : std::vector<std::string>{};
    QWidget* band_parent = section_cursor_band_->parentWidget();
    const auto rect = section_cursor_geometry(
        name, names, band_parent != nullptr ? band_parent->width() : 0,
        band_parent != nullptr ? band_parent->height() : 0);
    if (!rect.has_value()) {
        section_cursor_band_->hide();
        return;
    }
    section_cursor_band_->setGeometry(rect->x, rect->y, rect->w, rect->h);
    section_cursor_band_->raise();
    section_cursor_band_->show();
}

std::set<std::string> VisualizationWorkspace::export_capabilities() const {
    QWidget* widget = tabs_->currentWidget();
    if (widget == nullptr || !seams_.export_caps_fn) {
        return {};
    }
    return seams_.export_caps_fn(widget);
}

bool VisualizationWorkspace::export_snapshot(const std::string& path,
                                             const std::string& format) {
    QWidget* widget = tabs_->currentWidget();
    if (widget == nullptr || path.empty()) {
        return false;
    }
    if (!seams_.export_fn) {
        return false;
    }
    return seams_.export_fn(widget, path, format);
}

}  // namespace pwb::ui_seqviz::qt
