// UI-06 — HomePage shell (see qt/home_page.hpp).
#include <pwb/ui_pages_data/qt/home_page.hpp>

#include <QFrame>
#include <QHBoxLayout>
#include <QLabel>
#include <QScrollArea>
#include <QSplitter>
#include <QVBoxLayout>

#include <cmath>

#include <pwb/ui_pages_data/home_model.hpp>
#include <pwb/ui_pages_data/qt/cards.hpp>
#include <pwb/ui_pages_data/qt/module_map_widget.hpp>
#include <pwb/ui_shell/style_registry.hpp>

namespace pwb::ui_pages_data::qt {

namespace {

constexpr int kSideColumnWidth = 340;
constexpr int kSideColumnMinWidth = 300;
constexpr int kMapMinHeight = 360;

QString pal(const char* key) {
    const auto p = ui_shell::style_palette();
    const auto it = p.find(key);
    return it != p.end() ? QString::fromStdString(it->second) : QString();
}

}  // namespace

HomePage::HomePage(QWidget* parent) : QWidget(parent) {
    setObjectName(QStringLiteral("HomePage"));
    auto* main_layout = new QVBoxLayout(this);
    main_layout->setContentsMargins(0, 0, 0, 0);
    main_layout->setSpacing(0);

    auto* scroll = new QScrollArea(this);
    scroll->setWidgetResizable(true);
    scroll->setStyleSheet(
        QStringLiteral("QScrollArea { border: none;"
                       " background: transparent; }"));
    main_layout->addWidget(scroll);

    auto* container = new QWidget();
    container->setObjectName(QStringLiteral("HomeContainer"));
    scroll->setWidget(container);
    auto* layout = new QVBoxLayout(container);
    layout->setContentsMargins(16, 16, 16, 16);
    layout->setSpacing(12);

    // ---- centerpiece: map + right column ----
    auto* map_row = new QSplitter(Qt::Orientation::Horizontal, container);
    map_row->setChildrenCollapsible(false);

    auto* map_panel = new QFrame(map_row);
    map_panel->setObjectName(QStringLiteral("PanelCard"));
    auto* map_layout = new QVBoxLayout(map_panel);
    map_layout->setContentsMargins(8, 8, 8, 8);
    map_layout->setSpacing(8);

    crs_warning_label_ = new QLabel(QString(), map_panel);
    crs_warning_label_->setWordWrap(true);
    ui_shell::style_bind(crs_warning_label_, [] {
        return QStringLiteral("color: %1; font-size: 11px;")
            .arg(pal("WARNING"));
    });
    crs_warning_label_->setVisible(false);
    map_layout->addWidget(crs_warning_label_);

    map_stack_ = new QStackedWidget(map_panel);
    map_stack_->setMinimumHeight(kMapMinHeight);
    map_stack_->addWidget(build_empty_state());  // index 0 pre-canvas
    map_layout->addWidget(map_stack_, 1);
    map_row->addWidget(map_panel);

    side_column_ = new QWidget(map_row);
    auto* side_layout = new QVBoxLayout(side_column_);
    side_layout->setContentsMargins(0, 0, 0, 0);
    side_layout->setSpacing(12);
    start_guide_card_ = new StartGuideCard(side_column_);
    connect(start_guide_card_, &StartGuideCard::new_project_requested,
            this, &HomePage::new_project_requested);
    connect(start_guide_card_, &StartGuideCard::open_project_requested,
            this, &HomePage::open_project_requested);
    connect(start_guide_card_, &StartGuideCard::open_sample_requested,
            this, &HomePage::open_sample_requested);
    onboarding_report_card_ = new OnboardingReportCard(side_column_);
    side_layout->addWidget(start_guide_card_);
    side_layout->addWidget(onboarding_report_card_);
    side_layout->addStretch(1);
    side_column_->setMinimumWidth(kSideColumnMinWidth);
    map_row->addWidget(side_column_);
    map_row->setStretchFactor(0, 1);
    map_row->setStretchFactor(1, 0);
    map_row->setSizes({900, kSideColumnWidth});

    auto* v_splitter =
        new QSplitter(Qt::Orientation::Vertical, container);
    v_splitter->setChildrenCollapsible(true);
    v_splitter->addWidget(map_row);

    auto* title_container = new QHBoxLayout();
    title_container->setContentsMargins(4, 0, 4, 0);
    auto* title_label = new QLabel(
        QStringLiteral("智能岩相古地理重建系统 - 模块关系图"), container);
    ui_shell::style_bind(title_label, [] {
        return QStringLiteral(
                   "font-size: 15px; font-weight: 600; color: %1;")
            .arg(pal("PRIMARY"));
    });
    title_container->addWidget(title_label);
    title_container->addStretch(1);

    auto* diagram_panel = new QWidget(v_splitter);
    auto* diagram_layout = new QVBoxLayout(diagram_panel);
    diagram_layout->setContentsMargins(0, 0, 0, 0);
    diagram_layout->setSpacing(12);
    diagram_layout->addLayout(title_container);
    relationship_widget_ = new ModuleRelationshipWidget(diagram_panel);
    relationship_widget_->setMinimumWidth(980);
    connect(relationship_widget_,
            &ModuleRelationshipWidget::navigation_requested, this,
            &HomePage::navigation_requested);
    diagram_layout->addWidget(relationship_widget_, 1);
    v_splitter->addWidget(diagram_panel);
    v_splitter->setStretchFactor(0, 1);
    v_splitter->setStretchFactor(1, 1);
    v_splitter->setSizes({420, 620});
    layout->addWidget(v_splitter, 1);

    container->setMinimumWidth(960);

    auto* bottom = new QHBoxLayout();
    bottom->setSpacing(12);
    activity_card_ = new RecentActivityCard(container);
    completeness_card_ = new DataCompletenessCard(container);
    bottom->addWidget(activity_card_, 1);
    // contract panel (seam) inserted by set_contract_panel at index 1.
    bottom->addWidget(completeness_card_, 0);
    bottom_layout_ = bottom;
    layout->addLayout(bottom, 0);
}

void HomePage::set_map_canvas(HomeMapCanvasApi* canvas) {
    map_canvas_ = canvas;
    if (canvas == nullptr) return;
    canvas->set_overlay_provider([this] { return map_overlay_state(); });
    connect(canvas, &HomeMapCanvasApi::map_clicked, this,
            &HomePage::on_map_clicked);
    // Canvas is index 0; the empty state shifts to index 1.
    map_stack_->insertWidget(0, canvas);
    map_stack_->setCurrentIndex(1);
}

void HomePage::set_contract_panel(WorkflowContractPanelApi* panel) {
    contract_panel_ = panel;
    if (panel != nullptr && bottom_layout_ != nullptr) {
        panel->setMinimumWidth(280);
        panel->setMaximumHeight(320);
        bottom_layout_->insertWidget(1, panel, 1);
    }
}

void HomePage::set_legend_widget(QWidget* /*legend*/) {}

void HomePage::set_domain_signature_fn(
    std::function<pwb::domain::Json(void*)> fn) {
    domain_signature_fn_ = std::move(fn);
}

void HomePage::set_snapshot_fn(
    std::function<pwb::domain::Json(void*)> fn) {
    snapshot_fn_ = std::move(fn);
}

void HomePage::set_extent_fn(
    std::function<pwb::domain::Json(const pwb::domain::Json&)> fn) {
    extent_fn_ = std::move(fn);
}

void HomePage::set_has_content_fn(
    std::function<bool(const pwb::domain::Json&)> fn) {
    has_content_fn_ = std::move(fn);
}

void HomePage::set_crs_warnings_fn(
    std::function<std::vector<std::string>(void*)> fn) {
    crs_warnings_fn_ = std::move(fn);
}

void HomePage::shutdown_workers() {
    if (map_canvas_ != nullptr) map_canvas_->shutdown();
}

QFrame* HomePage::build_empty_state() {
    auto* frame = new QFrame(this);
    frame->setObjectName(QStringLiteral("HomeMapEmptyState"));
    auto* layout = new QVBoxLayout(frame);
    auto* title = new QLabel(QStringLiteral("工区地图"), frame);
    ui_shell::style_bind(title, [] {
        return QStringLiteral("color: %1; font-weight: 600;")
            .arg(pal("TEXT_PRIMARY"));
    });
    title->setAlignment(Qt::AlignmentFlag::AlignCenter);
    auto* body = new QLabel(
        QStringLiteral(
            "暂无空间数据。导入井位与地震工区后，这里将展示\n"
            "工区边界、井位分布与地震测区范围。"),
        frame);
    ui_shell::style_bind(body, [] {
        return QStringLiteral("color: %1;").arg(pal("TEXT_SECONDARY"));
    });
    body->setAlignment(Qt::AlignmentFlag::AlignCenter);
    body->setWordWrap(true);
    layout->addStretch(1);
    layout->addWidget(title);
    layout->addWidget(body);
    layout->addStretch(1);
    return frame;
}

pwb::domain::Json HomePage::map_overlay_state() {
    // Decorations snapshot (Python _map_overlay_state verbatim).
    using pwb::domain::Json;
    Json legend_items = Json::array();
    // WORKAREA_LEGEND_ITEMS — static palette pairs in the Python module;
    // kept as a Json seam by the host when needed. The decorations only
    // label elements; colors come from the snapshot legend.
    return Json::object(
        {{"decorations",
          Json::object({{"title", "工区地图"},
                        {"elements",
                         Json::array({"标题栏", "比例尺", "指北针", "图例"})}})}});
}

void HomePage::refresh_map(void* project) {
    pwb::domain::Json signature;
    bool bound = false;
    if (project != nullptr && domain_signature_fn_) {
        signature = domain_signature_fn_(project);
        bound = true;
    }
    if (bound == signature_bound_ &&
        (!bound || signature == map_signature_)) {
        update_crs_banner(project);
        return;
    }
    signature_bound_ = bound;
    map_signature_ = signature;
    map_snapshot_ = project != nullptr && snapshot_fn_
                        ? snapshot_fn_(project)
                        : pwb::domain::Json();
    if (map_canvas_ != nullptr) {
        map_canvas_->set_layer_snapshot(map_snapshot_);
        if (extent_fn_) {
            const auto extent = extent_fn_(map_snapshot_);
            if (!extent.is_null()) map_canvas_->set_extent(extent);
        }
    }
    const bool has_content =
        has_content_fn_ && has_content_fn_(map_snapshot_);
    map_stack_->setCurrentIndex(has_content ? 0 : 1);
    update_crs_banner(project);
}

void HomePage::update_crs_banner(void* project) {
    const auto warnings =
        project != nullptr && crs_warnings_fn_
            ? crs_warnings_fn_(project)
            : std::vector<std::string>();
    if (warnings.empty()) {
        crs_warning_label_->setText(QString());
        crs_warning_label_->setVisible(false);
        return;
    }
    QString text = QStringLiteral("⚠ ");
    for (std::size_t i = 0; i < warnings.size(); ++i) {
        if (i) text += QStringLiteral("；");
        text += QString::fromStdString(warnings[i]);
    }
    crs_warning_label_->setText(text);
    crs_warning_label_->setVisible(true);
}

void HomePage::on_map_clicked(double x, double y) {
    if (map_snapshot_.is_null() || map_canvas_ == nullptr) return;
    bool ok = false;
    const QPointF click = map_canvas_->map_to_screen(x, y, &ok);
    if (!ok) return;
    const auto points = screen_points(map_snapshot_);
    const std::string well_id = ui_pages_data::pick_well(
        points, click.x(), click.y());
    if (!well_id.empty()) {
        Q_EMIT well_activated(QString::fromStdString(well_id));
    }
}

std::vector<ui_pages_data::WellPickPoint> HomePage::screen_points(
    const pwb::domain::Json& snapshot) {
    using pwb::domain::Json;
    std::vector<ui_pages_data::WellPickPoint> out;
    if (!snapshot.is_object() || map_canvas_ == nullptr) return out;
    const Json layers = snapshot.value("layers", Json::array());
    for (const auto& layer : layers) {
        const std::string layer_id =
            layer.value("id", std::string());
        if (layer_id != ui_pages_data::kWellsLayerId &&
            layer_id != ui_pages_data::kWellsFlaggedLayerId) {
            continue;
        }
        for (const auto& feature :
             layer.value("features", Json::array())) {
            const Json geometry = feature.value("geometry", Json());
            if (geometry.value("type", std::string()) != "Point") continue;
            const Json coords = geometry.value("coordinates", Json());
            if (!coords.is_array() || coords.size() < 2) continue;
            bool ok = false;
            const QPointF screen = map_canvas_->map_to_screen(
                coords[0].get<double>(), coords[1].get<double>(), &ok);
            if (!ok) continue;
            ui_pages_data::WellPickPoint point;
            point.x = screen.x();
            point.y = screen.y();
            const Json props = feature.value("properties", Json());
            if (props.is_object() && props.contains("well_id")) {
                if (props["well_id"].is_string()) {
                    point.well_id = props["well_id"].get<std::string>();
                }
            }
            out.push_back(std::move(point));
        }
    }
    return out;
}

void HomePage::update_state(
    const pwb::domain::Json& state,
    const std::vector<ui_pages_data::StepLike>& steps, void* project) {
    relationship_widget_->update_states(steps);
    std::vector<ui_pages_data::ActivityStep> activity_steps;
    activity_steps.reserve(steps.size());
    for (const auto& s : steps) {
        activity_steps.push_back({s.step_type, s.status});
    }
    activity_card_->update_state(state, activity_steps);
    completeness_card_->update_state(state);
    if (project != nullptr) project_ = project;
    if (project_ != nullptr && contract_panel_ != nullptr) {
        contract_panel_->set_project(project_);
        // First pending/stale-ish step → its contract id.
        const std::string contract =
            ui_pages_data::first_incomplete_contract(steps);
        if (!contract.empty()) {
            contract_panel_->set_contract_id(
                QString::fromStdString(contract));
        }
    }
    const long long total = ui_pages_data::sum_resource_counts(
        state.value("resource_counts", pwb::domain::Json()));
    const bool has_report =
        state.value("onboarding_report", pwb::domain::Json())
            .is_object() &&
        !state.value("onboarding_report", pwb::domain::Json()).empty();
    const bool guide_visible =
        ui_pages_data::start_guide_visible(total, has_report);
    start_guide_card_->setVisible(guide_visible);
    onboarding_report_card_->set_report(
        has_report ? state["onboarding_report"] : pwb::domain::Json());
    side_column_->setVisible(ui_pages_data::side_column_visible(
        guide_visible, !onboarding_report_card_->isHidden()));
    refresh_map(project != nullptr ? project : project_);
}

}  // namespace pwb::ui_pages_data::qt
