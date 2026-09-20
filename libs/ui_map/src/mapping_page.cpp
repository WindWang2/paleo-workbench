#include <pwb/ui_map/mapping_page.hpp>

#include <QFrame>
#include <QHBoxLayout>
#include <QLabel>
#include <QLayout>
#include <QPointer>
#include <QPushButton>
#include <QShowEvent>
#include <QSize>
#include <QSplitter>
#include <QStackedWidget>
#include <QToolButton>
#include <QVBoxLayout>

#include <pwb/ui_map/display_map_canvas.hpp>
#include <pwb/ui_map/map_canvas_panel.hpp>
#include <pwb/ui_map/map_chrome_panel.hpp>
#include <pwb/ui_map/map_dock_manager.hpp>
#include <pwb/ui_map/map_layer_tree.hpp>
#include <pwb/ui_shell/float_controller.hpp>
#include <pwb/ui_shell/layout_persistence.hpp>
#include <pwb/ui_shell/map_status_bar.hpp>

namespace pwb::ui_map {

namespace {

QString qstr(const std::string& s) {
    return QString::fromUtf8(s.data(), static_cast<qsizetype>(s.size()));
}

// Placeholder dock panel for widgets owned by other slices — a titled
// frame with the panel's objectName so rail/menu/float behaviour is
// identical to the final wiring.
QFrame* placeholder_panel(const QString& object_name, const QString& text,
                          QWidget* parent = nullptr) {
    auto* frame = new QFrame(parent);
    frame->setObjectName(object_name);
    auto* layout = new QVBoxLayout(frame);
    auto* label = new QLabel(text, frame);
    label->setAlignment(Qt::AlignCenter);
    layout->addWidget(label);
    return frame;
}

}  // namespace

MappingPage::MappingPage(QWidget* parent) : QWidget(parent) {
    setObjectName(QStringLiteral("MappingPage"));

    auto* outer = new QVBoxLayout(this);
    outer->setContentsMargins(0, 0, 0, 0);
    outer->setSpacing(4);

    // Command strip: the full MapActionController/QToolBar surface is
    // deferred (other slices); the strip carries the panels menu button so
    // the 面板 menu exists from day one.
    auto* strip = new QFrame(this);
    strip->setObjectName(QStringLiteral("MapAuthoringToolbars"));
    auto* strip_layout = new QHBoxLayout(strip);
    strip_layout->setContentsMargins(0, 0, 0, 0);
    strip_layout->setSpacing(4);
    strip_layout->addStretch(1);
    outer->addWidget(strip);

    // Panel manager: collapsible side docks (icon rails) around the
    // central canvas, plus a checkable 面板 menu on the strip.
    dock_manager_ = new MapDockManager(this);

    layer_tree_stack_ = new QStackedWidget();
    layer_tree_ = new MapLayerTree();
    layer_tree_stack_->addWidget(layer_tree_);
    dock_manager_->add_panel("layers", QStringLiteral("图层面板"),
                             QStringLiteral("panel-layers"),
                             layer_tree_stack_, "left", true,
                             "mapping:layers");

    center_stack_ = new QStackedWidget();
    center_stack_->setObjectName(QStringLiteral("MappingCenterStack"));
    center_stack_->setMinimumWidth(360);

    edit_view_ = placeholder_panel(QStringLiteral("MapEditView"),
                                   QStringLiteral("编辑视图（未迁移）"));
    center_stack_->addWidget(edit_view_);

    auto* preview_host = new QWidget();
    preview_host->setObjectName(QStringLiteral("MappingPreviewHost"));
    auto* preview_layout = new QHBoxLayout(preview_host);
    preview_layout->setContentsMargins(0, 0, 0, 0);
    preview_layout->setSpacing(4);
    preview_canvas_stack_ = new QStackedWidget();
    canvas_panel_ = new MapCanvasPanel();
    unified_canvas_ = new DisplayMapCanvas();
    unified_canvas_->set_overlay_provider(
        [this] { return unified_overlay_state(); });
    preview_canvas_stack_->addWidget(canvas_panel_);
    preview_canvas_stack_->addWidget(unified_canvas_);
    preview_layout->addWidget(preview_canvas_stack_, 1);
    center_stack_->addWidget(preview_host);

    reference_panel_ =
        placeholder_panel(QStringLiteral("MapReferencePanel"),
                          QStringLiteral("参考图面板（未迁移）"));
    dock_manager_->add_panel("reference", QStringLiteral("参考图面板"),
                             QStringLiteral("panel-reference"),
                             reference_panel_, "right", true,
                             "mapping:reference");
    chrome_panel_ = new MapChromePanel();
    dock_manager_->add_panel("chrome", QStringLiteral("图面要素面板"),
                             QStringLiteral("panel-chrome"), chrome_panel_,
                             "right", false, "mapping:chrome");
    composition_panel_ =
        placeholder_panel(QStringLiteral("CompositionPanel"),
                          QStringLiteral("组图面板（未迁移）"));
    dock_manager_->add_panel("composer", QStringLiteral("组图面板"),
                             QStringLiteral("panel-chrome"),
                             composition_panel_, "right", false,
                             "mapping:composer");

    // Rails sit outside the splitter so collapsing a docked panel area
    // returns its space to the central canvas.
    auto* mid = new QHBoxLayout();
    mid->setContentsMargins(0, 0, 0, 0);
    mid->setSpacing(4);
    mid->addWidget(dock_manager_->left_dock()->rail, 0);
    mid_splitter_ = new QSplitter(Qt::Horizontal);
    mid_splitter_->setObjectName(QStringLiteral("MappingDockSplitter"));
    mid_splitter_->addWidget(dock_manager_->left_dock()->area);
    mid_splitter_->addWidget(center_stack_);
    mid_splitter_->addWidget(dock_manager_->right_dock()->area);
    mid_splitter_->setStretchFactor(0, 0);
    mid_splitter_->setStretchFactor(1, 1);
    mid_splitter_->setStretchFactor(2, 0);
    mid_splitter_->setSizes({300, 1000, 280});
    connect(mid_splitter_, &QSplitter::splitterMoved, this,
            [this](int, int) { save_dock_splitter_sizes(); });
    mid->addWidget(mid_splitter_, 1);
    mid->addWidget(dock_manager_->right_dock()->rail, 0);
    outer->addLayout(mid, 1);

    status_bar_ = new pwb::ui_shell::MapStatusBar(this);
    outer->addWidget(status_bar_);

    // Bottom workbench placeholder: MapWorkbenchBottom (attribute table /
    // factor shelf / topology panel) is another slice; the dock slot,
    // float key and height-cap behaviour are wired identically.
    bottom_workbench_ =
        placeholder_panel(QStringLiteral("MapWorkbenchBottom"),
                          QStringLiteral("底部工作区（未迁移）"));
    bottom_workbench_->setMaximumHeight(kBottomDockedMaxHeight);
    outer->addWidget(bottom_workbench_, 0);
    dock_manager_->register_bottom(
        "bottom", QStringLiteral("底部工作区"),
        QStringLiteral("panel-bottom"), bottom_workbench_,
        [this] { apply_mode_ui(); }, "mapping:bottom");

    // Panels menu lives on the right end of the command strip.
    panels_button_ = new QToolButton(strip);
    panels_button_->setObjectName(QStringLiteral("MapPanelsMenuButton"));
    panels_button_->setIconSize(QSize(18, 18));
    panels_button_->setToolTip(QStringLiteral("面板"));
    panels_button_->setAccessibleName(QStringLiteral("面板"));
    panels_button_->setPopupMode(QToolButton::InstantPopup);
    panels_button_->setMenu(dock_manager_->panels_menu(panels_button_));
    strip_layout->addWidget(panels_button_, 0);

    wire_float_controller();

    connect(chrome_panel_, &MapChromePanel::chrome_changed, this,
            [this](const Json& payload) { on_chrome_changed(payload); });
    connect(chrome_panel_->save_button(), &QPushButton::clicked, this,
            [this] {
                if (active_document_ != nullptr) {
                    emit draft_saved(*active_document_);
                }
            });
    connect(layer_tree_, &MapLayerTree::document_selected, this,
            [this](const Json& document) { on_document_selected(document); });
    connect(unified_canvas_, &DisplayMapCanvas::map_position_changed, this,
            [this](double x, double y) {
                status_bar_->update_coordinate({x, y});
            });

    apply_mode_ui();
    for (const char* key : kFloatKeys) {
        float_controller_->restore_saved(key);
    }
    emit_mapping_context();
}

MappingPage::~MappingPage() {
    // Release the QGIS session before the widget tree tears down.
    unified_canvas_->shutdown();
}

// ---------------------------------------------------------------------------
// mode flags
// ---------------------------------------------------------------------------

void MappingPage::set_preview_mode(bool enabled) {
    if (preview_mode_ == enabled) {
        if (enabled) {
            refresh_preview();
        }
        return;
    }
    preview_mode_ = enabled;
    apply_mode_ui();
    if (enabled) {
        refresh_preview();
    }
    emit_mapping_context();
}

void MappingPage::set_canvas_priority(bool enabled) {
    if (canvas_priority_ == enabled) {
        return;
    }
    canvas_priority_ = enabled;
    // Preserve the established explicit-widget visibility contract for the
    // legacy tree, while the dock manager reflects the same state on its
    // rail buttons.
    dock_manager_->set_panel_visible("layers", !enabled);
    layer_tree_->setVisible(!enabled);
    dock_manager_->set_panel_visible("reference", !enabled);
    apply_mode_ui();
    emit_mapping_context();
}

bool MappingPage::is_dirty() const {
    // Authoring/scene dirty sources are deferred with the authoring slice.
    return pwb::ui_map::is_dirty(presentation_dirty_, false, false);
}

// ---------------------------------------------------------------------------
// documents
// ---------------------------------------------------------------------------

void MappingPage::update_state(const std::vector<Json>& documents,
                               const std::string& prefer_id) {
    // Capture the previous id BEFORE the documents_ copy — the old
    // pointer would dangle after reassignment.
    const std::string previous_id =
        active_document_ != nullptr
            ? field_value_str(*active_document_, "id", "")
            : std::string();
    documents_ = documents;
    std::string prefer = prefer_id;
    if (prefer.empty()) {
        prefer = previous_id;
    }
    active_document_ = active_map_document(documents_, prefer);
    const std::string active_id =
        active_document_ != nullptr
            ? field_value_str(*active_document_, "id", "")
            : std::string();
    if (active_id != previous_id) {
        presentation_dirty_ = false;
    }
    layer_tree_->set_documents(documents_);
    layer_tree_->set_active_document(active_document_);
    if (active_document_ != nullptr) {
        chrome_panel_->update_state(*active_document_);
        canvas_panel_->update_state(*active_document_);
    } else {
        chrome_panel_->update_state(Json::object());
        canvas_panel_->update_state(Json::object());
    }
    apply_mode_ui();
    if (preview_mode_) {
        refresh_preview();
    }
    emit_mapping_context();
}

Json MappingPage::mapping_context() const {
    return pwb::ui_map::mapping_context(active_document_,
                                        presentation_dirty_, preview_mode_);
}

// ---------------------------------------------------------------------------
// mode UI + persistence
// ---------------------------------------------------------------------------

void MappingPage::apply_mode_ui() {
    // Python's _unified_authoring_mode is true while a document is bound
    // (the unified canvas is the normal authoring surface); the legacy
    // edit view only shows with no document loaded.
    const ModeUiState state = resolve_mode_ui(
        preview_mode_, /*unified_authoring_mode=*/active_document_ != nullptr,
        canvas_priority_, dock_manager_->bottom_user_visible());
    center_stack_->setCurrentIndex(state.center_index);
    if (state.preview_shows_unified) {
        preview_canvas_stack_->setCurrentWidget(unified_canvas_);
    }
    // While floating, show/hide the floating window itself — hiding the
    // bare widget inside a visible window would only draw an empty frame.
    if (dock_manager_->is_floating("bottom")) {
        dock_manager_->set_bottom_window_visible(state.bottom_visible);
    } else {
        bottom_workbench_->setVisible(state.bottom_visible);
    }
}

std::vector<int> MappingPage::saved_dock_splitter_sizes() const {
    const pwb::ui_shell::PanelLayoutRecord dock_record =
        persistence_->load(kDockSplitterKey);
    const pwb::ui_shell::PanelLayoutRecord layers_record =
        persistence_->load("mapping:layers");
    return pwb::ui_map::saved_dock_splitter_sizes(
        dock_record.docked_sizes, layers_record.docked_sizes,
        last_dock_sizes_);
}

void MappingPage::save_dock_splitter_sizes() {
    const QList<int> sizes = mid_splitter_->sizes();
    last_dock_sizes_.assign(sizes.begin(), sizes.end());
    persistence_->save_docked_sizes(kDockSplitterKey, last_dock_sizes_);
}

void MappingPage::set_bottom_height_cap(int height) {
    bottom_workbench_->setMaximumHeight(height);
}

// ---------------------------------------------------------------------------
// float integration
// ---------------------------------------------------------------------------

void MappingPage::wire_float_controller() {
    float_widgets_ = {
        {"mapping:layers", layer_tree_stack_},
        {"mapping:reference", reference_panel_},
        {"mapping:chrome", chrome_panel_},
        {"mapping:composer", composition_panel_},
        {"mapping:bottom", bottom_workbench_},
    };
    float_hosts_ = {
        {"mapping:layers", dock_manager_->left_dock()->area},
        {"mapping:reference", dock_manager_->right_dock()->area},
        {"mapping:chrome", dock_manager_->right_dock()->area},
        {"mapping:composer", dock_manager_->right_dock()->area},
        {"mapping:bottom", this},
    };
    persistence_ = std::make_unique<pwb::ui_shell::LayoutPersistence>();
    float_controller_ = new pwb::ui_shell::FloatController(
        [this](const std::string& key) -> QWidget* {
            const auto it = float_widgets_.find(key);
            return it != float_widgets_.end() ? it->second.data() : nullptr;
        },
        persistence_.get(),
        [this](const std::string& key) -> QString {
            return qstr(dock_manager_->panel_title(key));
        },
        this);
    dock_manager_->attach_float_controller(float_controller_);
    // Dock-manager slot first (fixes up rail/menu state), then the page's
    // dock-back recovery, caps and mode-visibility handling.
    connect(float_controller_,
            &pwb::ui_shell::FloatController::float_changed, this,
            [this](const QString& key, bool floating) {
                on_float_changed(key, floating);
            });
}

void MappingPage::on_float_changed(const QString& float_key_q,
                                   bool floating) {
    const std::string float_key = float_key_q.toStdString();
    QWidget* widget = float_widgets_.count(float_key)
                          ? float_widgets_[float_key].data()
                          : nullptr;
    if (widget == nullptr) {
        return;
    }
    if (floating) {
        if (float_key == "mapping:bottom") {
            set_bottom_height_cap(kWidgetSizeMax);
        }
        return;
    }
    QWidget* host = float_hosts_.count(float_key)
                        ? float_hosts_[float_key].data()
                        : nullptr;
    if (host == nullptr) {
        return;
    }
    QLayout* host_layout = host->layout();
    if (host_layout == nullptr || host_layout->indexOf(widget) < 0) {
        // The framework's generic reinsert leaves the widget parented to
        // the host but outside its layout (or in the wrong container):
        // put it back at its registered slot. Dock areas add their panels
        // with stretch 1.
        if (host == this) {
            this->layout()->addWidget(widget);
        } else {
            auto* box = qobject_cast<QVBoxLayout*>(host_layout);
            if (box != nullptr) {
                box->addWidget(widget, 1);
            } else {
                host_layout->addWidget(widget);
            }
        }
        dock_manager_->left_dock()->sync_area_visibility();
        dock_manager_->right_dock()->sync_area_visibility();
        if (float_key != "mapping:bottom") {
            // The rail button is the visibility source of truth.
            const std::string panel_key =
                float_key.substr(float_key.rfind(':') + 1);
            widget->setVisible(dock_manager_->is_panel_visible(panel_key));
        }
    }
    if (float_key == "mapping:bottom") {
        set_bottom_height_cap(kBottomDockedMaxHeight);
        apply_mode_ui();
    } else {
        const std::vector<int> sizes = saved_dock_splitter_sizes();
        if (sizes.size() ==
            static_cast<std::size_t>(mid_splitter_->count())) {
            mid_splitter_->setSizes(
                QList<int>(sizes.begin(), sizes.end()));
        }
    }
}

// ---------------------------------------------------------------------------
// document / chrome slots
// ---------------------------------------------------------------------------

void MappingPage::on_document_selected(const Json& document) {
    if (document.is_object()) {
        for (auto& doc : documents_) {
            if (field_value_str(doc, "id", "") ==
                field_value_str(document, "id", "")) {
                active_document_ = &doc;
                break;
            }
        }
    }
    emit_mapping_context();
}

void MappingPage::on_chrome_changed(const Json& payload) {
    if (active_document_ == nullptr || !payload.is_object()) {
        return;
    }
    // document.map_chrome = dict(chrome) — documents_ owns the records;
    // active_document_ points into it (Python mutates in place).
    for (auto& doc : documents_) {
        if (&doc == active_document_) {
            doc["map_chrome"] = payload;
            break;
        }
    }
    presentation_dirty_ = true;
    chrome_panel_->update_state(*active_document_);
    // Decorations are a Qt overlay and must not schedule a QGIS data rebuild.
    unified_canvas_->update();
    emit_mapping_context();
}

void MappingPage::refresh_preview() {
    if (active_document_ == nullptr) {
        return;
    }
    canvas_panel_->update_state(*active_document_);
}

Json MappingPage::unified_overlay_state() const {
    const Json chrome =
        active_document_ != nullptr
            ? field_value(*active_document_, "map_chrome", Json::object())
            : Json::object();
    const std::string name =
        active_document_ != nullptr
            ? field_value_str(*active_document_, "name", "")
            : std::string();
    return pwb::ui_map::unified_overlay_state(
        Json::array(), Json::array(), Json(nullptr), chrome, name, {});
}

void MappingPage::emit_mapping_context() {
    emit mapping_context_changed(mapping_context());
}

void MappingPage::showEvent(QShowEvent* event) {
    QWidget::showEvent(event);
}

// BEGIN CLOSURE-MAPPING (08-line adopt implementations)
namespace {

// Swap `old_widget` for `replacement` inside its parent layout and retire
// the placeholder (replaceWidget does not delete the removed widget).
void swap_in_parent_layout(QWidget* old_widget, QWidget* replacement) {
    QWidget* parent = old_widget->parentWidget();
    QLayout* layout = parent != nullptr ? parent->layout() : nullptr;
    if (layout == nullptr) return;
    if (QLayoutItem* removed = layout->replaceWidget(old_widget, replacement);
        removed != nullptr) {
        delete removed;
    }
    old_widget->deleteLater();
}

}  // namespace

void MappingPage::adopt_edit_view(QWidget* view) {
    if (view == nullptr || edit_view_ == view) return;
    // The edit view is center_stack_ index 0 (authoring surface);
    // QStackedWidget has no replaceWidget — swap via index.
    const int index = center_stack_->indexOf(edit_view_);
    if (index < 0) return;
    center_stack_->removeWidget(edit_view_);
    center_stack_->insertWidget(index, view);
    edit_view_->deleteLater();
    edit_view_ = view;
}

void MappingPage::adopt_reference_panel(QWidget* panel) {
    if (panel == nullptr || reference_panel_ == panel) return;
    swap_in_parent_layout(reference_panel_, panel);
    reference_panel_ = panel;
    float_widgets_["mapping:reference"] = QPointer<QWidget>(panel);
    dock_manager_->adopt_panel_widget("reference", panel);
}

void MappingPage::adopt_composition_panel(QWidget* panel) {
    if (panel == nullptr || composition_panel_ == panel) return;
    swap_in_parent_layout(composition_panel_, panel);
    composition_panel_ = panel;
    float_widgets_["mapping:composer"] = QPointer<QWidget>(panel);
    dock_manager_->adopt_panel_widget("composer", panel);
}

void MappingPage::adopt_bottom_workbench(QWidget* panel) {
    if (panel == nullptr || bottom_workbench_ == panel) return;
    // The bottom slot sits in the page's own layout (not a stack): swap
    // at the same index, keep the height cap and the dock registration.
    swap_in_parent_layout(bottom_workbench_, panel);
    panel->setMaximumHeight(kBottomDockedMaxHeight);
    bottom_workbench_ = panel;
    float_widgets_["mapping:bottom"] = QPointer<QWidget>(panel);
    float_hosts_["mapping:bottom"] = QPointer<QWidget>(this);
    dock_manager_->adopt_panel_widget("bottom", panel);
}
// END CLOSURE-MAPPING

}  // namespace pwb::ui_map
