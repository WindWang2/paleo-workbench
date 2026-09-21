#include <pwb/ui_composite/linked_workspace.hpp>

#include <tuple>

#include <pwb/ui_controllers/qt/view_coordination_controller.hpp>
#include <pwb/ui_controllers/selection_bus.hpp>
#include <pwb/ui_controllers/view_coordination.hpp>
#include <pwb/ui_widgets/ui_context.hpp>

#include <QApplication>
#include <QComboBox>
#include <QDockWidget>
#include <QVariantMap>

namespace pwb::ui_composite {

namespace {

std::string rec_str(const Json& record, const char* key) {
    if (!record.is_object()) return "";
    auto it = record.find(key);
    if (it == record.end() || it->is_null()) return "";
    if (it->is_string()) return it->get<std::string>();
    if (it->is_number() || it->is_boolean()) return it->dump();
    return "";
}

std::string path_stem_upper(const std::string& name) {
    const size_t slash = name.find_last_of("/\\");
    std::string stem = slash == std::string::npos ? name : name.substr(slash + 1);
    const size_t dot = stem.find_last_of('.');
    if (dot != std::string::npos) stem = stem.substr(0, dot);
    for (char& c : stem) c = static_cast<char>(std::toupper(c));
    return stem;
}

std::string upper(std::string value) {
    for (char& c : value) c = static_cast<char>(std::toupper(c));
    return value;
}

}  // namespace

// ---------------------------------------------------------------------------
// DocumentPane
// ---------------------------------------------------------------------------

DocumentPane::DocumentPane(const QString& title, QWidget* parent)
    : QFrame(parent) {
    setObjectName("WorkstationDocumentPane");

    auto* outer = new QVBoxLayout(this);
    outer->setContentsMargins(0, 0, 0, 0);
    outer->setSpacing(0);

    auto* header = new QFrame(this);
    header->setObjectName("WorkstationDocumentPaneHeader");
    header_layout = new QHBoxLayout(header);
    header_layout->setContentsMargins(8, 0, 4, 0);
    header_layout->setSpacing(4);
    title_label = new QLabel(title, header);
    title_label->setObjectName("WorkstationDocumentPaneTitle");
    header_layout->addWidget(title_label);
    header_layout->addStretch(1);
    link_label = new QLabel(QStringLiteral("联动"), header);
    link_label->setObjectName("WorkstationLinkBadge");
    header_layout->addWidget(link_label);
    outer->addWidget(header);

    host = new QFrame(this);
    host->setObjectName("WorkstationDocumentPaneHost");
    host_layout = new QVBoxLayout(host);
    host_layout->setContentsMargins(0, 0, 0, 0);
    host_layout->setSpacing(0);
    outer->addWidget(host, 1);
}

void DocumentPane::set_content(QWidget* content) {
    if (content_ == content) return;
    if (content_ != nullptr) {
        host_layout->removeWidget(content_);
        content_->setParent(nullptr);
    }
    content_ = content;
    content->setParent(host);
    host_layout->addWidget(content);
    content->show();
}

void DocumentPane::set_title(const QString& title) {
    title_label->setText(title);
    // dock 化后标题同时写到 dock 标题栏。
    if (auto* dock = qobject_cast<QDockWidget*>(parentWidget())) {
        dock->setWindowTitle(title);
    }
}

// ---------------------------------------------------------------------------
// LinkedInterpretationWorkspace
// ---------------------------------------------------------------------------

LinkedInterpretationWorkspace::LinkedInterpretationWorkspace(QWidget* parent)
    : QWidget(parent) {
    setObjectName("LinkedInterpretationWorkspace");

    auto* outer = new QVBoxLayout(this);
    outer->setContentsMargins(0, 0, 0, 0);
    outer->setSpacing(0);

    seismic_pane = new DocumentPane(QStringLiteral("地震剖面"), this);
    well_pane = new DocumentPane(QStringLiteral("测井轨道"), this);
    outer->addWidget(seismic_pane, 1);
    outer->addWidget(well_pane, 1);
    install_domain_status_bar(outer);
    install_empty_states();
}

void LinkedInterpretationWorkspace::install_domain_status_bar(
    QVBoxLayout* outer) {
    // L10: current-domain badge + conversion availability + sync status。
    auto* bar = new QFrame(this);
    bar->setObjectName("WorkstationDomainStatusBar");
    auto* layout = new QHBoxLayout(bar);
    layout->setContentsMargins(8, 2, 8, 2);
    layout->setSpacing(8);
    domain_badge = new QLabel(QStringLiteral("MD · m"), bar);
    domain_badge->setObjectName("WorkstationDomainBadge");
    domain_badge->setToolTip(
        QStringLiteral("当前深度游标域（井侧发布 MD 米）"));
    conversion_status_label =
        new QLabel(QStringLiteral("TWT 换算：—"), bar);
    conversion_status_label->setObjectName("WorkstationConversionStatus");
    sync_status_label = new QLabel(QStringLiteral("同步：—"), bar);
    sync_status_label->setObjectName("WorkstationSyncStatus");
    layout->addWidget(domain_badge);
    layout->addWidget(conversion_status_label, 1);
    layout->addWidget(sync_status_label);
    outer->addWidget(bar);
}

void LinkedInterpretationWorkspace::refresh_domain_status() {
    std::string well;
    std::optional<double> depth;
    QString cal_text = QStringLiteral("TWT 换算：—");
    if (coordination_ != nullptr &&
        coordination_->selection() != nullptr) {
        const pwb::ui_controllers::SelectionState snapshot =
            coordination_->selection()->snapshot();
        if (snapshot.depth_cursor.has_value()) {
            well = snapshot.depth_cursor->first;
            depth = snapshot.depth_cursor->second;
            domain_badge->setText(QStringLiteral("MD · m"));
        } else if (snapshot.active_well_id.has_value()) {
            well = *snapshot.active_well_id;
        }
        if (!well.empty() && calibration_provider_) {
            const auto cal = calibration_provider_(well);
            if (!cal.has_value()) {
                cal_text = QStringLiteral("TWT 换算：不可用（%1 无时深校准）")
                               .arg(QString::fromStdString(well));
            } else {
                cal_text = QStringLiteral("TWT 换算：%1")
                               .arg(QString::fromStdString(cal->provenance));
                if (depth.has_value()) {
                    // 当前深度的覆盖度，不只是存在性（review R3-M2）。
                    const auto twt =
                        cal->md_to_twt ? cal->md_to_twt(*depth) : std::nullopt;
                    if (!twt.has_value() && !cal->pairs.empty()) {
                        cal_text = QStringLiteral(
                                       "TWT 换算：超出校准范围 "
                                       "(%1–%2 m)")
                                       .arg(cal->pairs.front().first, 0, 'f',
                                            0)
                                       .arg(cal->pairs.back().first, 0, 'f',
                                            0);
                    }
                }
                // review R3-M3：未复核校准显式标注，绝不静默。
                const Json& metadata = cal->metadata;
                const bool verified =
                    metadata.is_object() && metadata.contains("verified")
                        ? metadata["verified"].get<bool>()
                        : false;
                if (!verified) {
                    cal_text += QStringLiteral("（未复核）");
                }
            }
        }
    }
    conversion_status_label->setText(cal_text);
    QStringList parts{is_linked() ? QStringLiteral("开启")
                                  : QStringLiteral("关闭")};
    if (!is_linked()) parts.append(QStringLiteral("不跟随其它视图"));
    if (!well.empty()) {
        parts.append(QStringLiteral("当前井 %1")
                         .arg(elide(QString::fromStdString(well))));
    }
    sync_status_label->setText(QStringLiteral("同步：") +
                               parts.join(QStringLiteral(" · ")));
}

QString LinkedInterpretationWorkspace::elide(const QString& text,
                                             int limit) {
    return text.size() <= limit
               ? text
               : text.left(limit - 1) + QStringLiteral("…");
}

void LinkedInterpretationWorkspace::install_empty_states() {
    fill_empty_state(
        seismic_pane,
        QStringLiteral("打开包含 SEG-Y 的工程后加载地震解释视图"));
    fill_empty_state(well_pane,
                     QStringLiteral("选择井数据后加载测井轨道"));
}

void LinkedInterpretationWorkspace::fill_empty_state(DocumentPane* pane,
                                                   const QString& text) {
    auto* holder = new QWidget(pane);
    auto* holder_layout = new QVBoxLayout(holder);
    holder_layout->setContentsMargins(10, 10, 10, 10);
    auto* label = new QLabel(text, holder);
    label->setObjectName("WorkstationDocumentEmptyState");
    label->setAlignment(Qt::AlignCenter);
    label->setWordWrap(true);
    holder_layout->addWidget(label);
    pane->set_content(holder);
}

// -- injection seams ----------------------------------------------------------

void LinkedInterpretationWorkspace::set_project_source(
    LinkedWorkspaceProject source) {
    project_source_ = std::move(source);
}

void LinkedInterpretationWorkspace::set_panel_factories(
    LinkedPanelFactories factories) {
    factories_ = std::move(factories);
}

void LinkedInterpretationWorkspace::set_calibration_provider(
    LinkedCalibrationProvider provider) {
    calibration_provider_ = std::move(provider);
}

void LinkedInterpretationWorkspace::set_project_path(
    const std::string& project_path) {
    project_path_ = project_path;
    if (seismic_panel.set_project_path) {
        seismic_panel.set_project_path(project_path_);
    }
}

void LinkedInterpretationWorkspace::set_project(
    const std::string& project_path) {
    drop_extra_panes();
    if (!project_path.empty()) project_path_ = project_path;
}

void LinkedInterpretationWorkspace::attach_coordination(
    pwb::ui_controllers::qt::ViewCoordinationController* controller) {
    coordination_ = controller;
    if (seismic_panel.attach_coordination) {
        seismic_panel.attach_coordination(controller);
    }
    for (auto& [_pane, panel] : seismic_panels_) {
        if (panel.attach_coordination) {
            panel.attach_coordination(controller);
        }
    }
    // Status-only bus subscription (L10)：badge/conversion 跟随每次选择
    // 变化，从不反向 publish。
    if (controller != nullptr && controller->selection() != nullptr) {
        connect(controller->selection(),
                &pwb::ui_controllers::qt::QtSelectionContext::
                    selection_changed,
                this,
                [this](pwb::ui_controllers::qt::QtSelectionContext*) {
                    refresh_domain_status();
                });
    }
    refresh_domain_status();
}

// -- coordination actions -------------------------------------------------------

void LinkedInterpretationWorkspace::locate_seismic(
    int il, int xl, std::optional<double> twt) {
    if (!linked_) return;
    std::vector<LinkedSeismicPanel*> panels;
    if (seismic_panel.widget != nullptr) panels.push_back(&seismic_panel);
    for (auto& [_pane, panel] : seismic_panels_) panels.push_back(&panel);
    for (LinkedSeismicPanel* panel : panels) {
        if (panel->locate_position) {
            try {
                panel->locate_position(il, xl, twt);
            } catch (...) {
            }
        }
    }
}

bool LinkedInterpretationWorkspace::apply_link_cursor(
    const std::string& well_name, std::optional<double> md) {
    if (!linked_ || well_name.empty()) return false;
    bool driven = false;
    std::vector<std::tuple<DocumentPane*, std::string, LinkedWellPanel*>>
        link_slots;
    link_slots.emplace_back(well_pane, active_well_name_, &well_panel);
    for (auto& pane : extra_well_panes_) {
        link_slots.emplace_back(pane.get(), well_names_[pane.get()],
                           &well_panels_[pane.get()]);
    }
    for (auto& [_pane, bound, panel] : link_slots) {
        if (panel == nullptr || bound != well_name ||
            !panel->set_link_cursor) {
            continue;
        }
        driven = panel->set_link_cursor(md) || driven;
    }
    if (driven) {
        const QString value =
            md.has_value()
                ? QString::number(*md, 'f', 1)
                : QStringLiteral("已清除");
        const QString unit = md.has_value() ? QStringLiteral("m") : QString();
        emit status_changed(
            QStringLiteral("井震联动游标 · %1 %2 %3")
                .arg(QString::fromStdString(well_name), value, unit)
                .trimmed());
    }
    return driven;
}

void LinkedInterpretationWorkspace::ensure_views(bool load_defaults) {
    if (views_created_ || !can_create_native_views()) return;
    if (!native_platform_ok()) return;
    if (!factories_.make_seismic_panel || !factories_.make_well_panel) {
        return;
    }

    seismic_panel = factories_.make_seismic_panel(seismic_pane);
    well_panel = factories_.make_well_panel(well_pane);
    if (seismic_panel.widget != nullptr) {
        seismic_pane->set_content(seismic_panel.widget);
    }
    if (well_panel.widget != nullptr) {
        well_pane->set_content(well_panel.widget);
    }
    views_created_ = true;

    if (well_panel.on_depth_cursor_moved) {
        LinkedWellPanel* panel = &well_panel;
        well_panel.on_depth_cursor_moved(
            [this, panel](double depth) { on_depth_cursor_from(panel, depth); });
    }
    if (coordination_ != nullptr && seismic_panel.attach_coordination) {
        seismic_panel.attach_coordination(coordination_);
    }

    if (load_defaults) {
        const Json seismic = first_resource("seismic");
        if (!seismic.is_null() && seismic_panel.show_resource) {
            if (seismic_panel.set_project_path) {
                seismic_panel.set_project_path(project_path_);
            }
            seismic_panel.show_resource(
                seismic,
                project_source_.document ? project_source_.document() : Json{});
            default_seismic_key_ = rec_str(seismic, "id").empty()
                                       ? rec_str(seismic, "path").empty()
                                             ? rec_str(seismic, "name")
                                             : rec_str(seismic, "path")
                                       : rec_str(seismic, "id");
        }
        open_well(preferred_well_name());
    }
    const auto note = well_backend_note();
    emit status_changed(
        !note.has_value()
            ? QStringLiteral("井震视图已加载")
            : QStringLiteral("井震视图已加载 · 测井轨道 %1")
                  .arg(QString::fromStdString(*note)));
}

bool LinkedInterpretationWorkspace::native_platform_ok() const {
    QApplication* app = qobject_cast<QApplication*>(QApplication::instance());
    const QString platform = app != nullptr ? app->platformName() : QString();
    return app != nullptr && platform != "offscreen" && platform != "minimal";
}

bool LinkedInterpretationWorkspace::can_create_native_views() const {
    return project_source_.resources &&
           !project_source_.resources().empty();
}

DocumentPane* LinkedInterpretationWorkspace::make_well_pane() {
    auto pane = std::make_unique<DocumentPane>(QStringLiteral("测井轨道"));
    DocumentPane* ptr = pane.get();
    fill_empty_state(ptr, QStringLiteral("选择井数据后加载测井轨道"));
    sync_link_badge(ptr);
    if (native_platform_ok() && can_create_native_views() &&
        factories_.make_well_panel) {
        LinkedWellPanel panel = factories_.make_well_panel(ptr);
        if (panel.widget != nullptr) {
            ptr->set_content(panel.widget);
            LinkedWellPanel* bound = &well_panels_[ptr];
            *bound = std::move(panel);
            if (bound->on_depth_cursor_moved) {
                bound->on_depth_cursor_moved(
                    [this, bound](double depth) {
                        on_depth_cursor_from(bound, depth);
                    });
            }
        }
    }
    extra_well_panes_.push_back(std::move(pane));
    return ptr;
}

DocumentPane* LinkedInterpretationWorkspace::make_seismic_pane() {
    auto pane = std::make_unique<DocumentPane>(QStringLiteral("地震剖面"));
    DocumentPane* ptr = pane.get();
    fill_empty_state(
        ptr, QStringLiteral("打开包含 SEG-Y 的工程后加载地震解释视图"));
    sync_link_badge(ptr);
    if (native_platform_ok() && can_create_native_views() &&
        factories_.make_seismic_panel) {
        LinkedSeismicPanel panel = factories_.make_seismic_panel(ptr);
        if (panel.widget != nullptr) {
            ptr->set_content(panel.widget);
            seismic_panels_[ptr] = std::move(panel);
            install_profile_orientation_selector(ptr, &seismic_panels_[ptr]);
            if (coordination_ != nullptr &&
                seismic_panels_[ptr].attach_coordination) {
                seismic_panels_[ptr].attach_coordination(coordination_);
            }
        }
    }
    extra_seismic_panes_.push_back(std::move(pane));
    return ptr;
}

void LinkedInterpretationWorkspace::drop_extra_panes() {
    for (auto& pane : extra_well_panes_) {
        auto it = well_panels_.find(pane.get());
        if (it != well_panels_.end() && it->second.shutdown) {
            try {
                it->second.shutdown(0);
            } catch (...) {
            }
        }
        well_panels_.erase(pane.get());
        well_names_.erase(pane.get());
    }
    for (auto& pane : extra_seismic_panes_) {
        auto it = seismic_panels_.find(pane.get());
        if (it != seismic_panels_.end() && it->second.shutdown) {
            try {
                it->second.shutdown();
            } catch (...) {
            }
        }
        seismic_panels_.erase(pane.get());
    }
    extra_well_panes_.clear();
    extra_seismic_panes_.clear();
}

void LinkedInterpretationWorkspace::install_profile_orientation_selector(
    DocumentPane* pane, LinkedSeismicPanel* panel) {
    // L5: 2-D 解释面方向切换（Inline / Crossline / Time 切片）。
    if (pane == nullptr || panel == nullptr ||
        !panel->set_profile_orientation) {
        return;
    }
    if (pane == seismic_pane && orientation_combo_ != nullptr) return;
    auto* combo = new QComboBox(pane);
    combo->setObjectName("SeismicProfileOrientationCombo");
    combo->setToolTip(
        QStringLiteral("二维解释面方向（联动档位仅改变显示，不重读体积）"));
    for (const auto& [label, key] :
         {std::pair{QStringLiteral("Inline 剖面"), std::string("inline")},
          {QStringLiteral("Crossline 剖面"), std::string("crossline")},
          {QStringLiteral("Time 切片"), std::string("time")}}) {
        combo->addItem(label, QString::fromStdString(key));
    }
    connect(combo, &QComboBox::currentIndexChanged, this,
            [this, panel, combo](int index) {
                on_orientation_changed_for(panel, combo, index);
            });
    if (pane->header_layout != nullptr) {
        pane->header_layout->insertWidget(pane->header_layout->count() - 1,
                                          combo);
    }
    if (pane == seismic_pane) orientation_combo_ = combo;
}

void LinkedInterpretationWorkspace::on_orientation_changed_for(
    LinkedSeismicPanel* panel, QComboBox* combo, int index) {
    if (panel == nullptr || combo == nullptr) return;
    const std::string key =
        combo->itemData(index).toString().toStdString();
    const bool ok = panel->set_profile_orientation(key);
    emit status_changed(
        ok ? QStringLiteral("解释面方向：%1").arg(combo->itemText(index))
           : QStringLiteral("未知解释面方向 '%1'，已忽略")
                 .arg(QString::fromStdString(key)));
}

// -- well backend (B9) ----------------------------------------------------------

void LinkedInterpretationWorkspace::apply_default_well_backend() {
    if (well_panel.widget == nullptr || !well_panel.set_backend) return;
    std::string backend = "legacy";
    std::string reason;
    if (factories_.resolve_default_backend) {
        const auto [resolved, why] = factories_.resolve_default_backend();
        backend = resolved;
        reason = why;
    }
    set_well_backend(backend, reason);
    const auto note = well_backend_note();
    if (note.has_value()) {
        emit status_changed(QStringLiteral("测井轨道使用 Legacy 渲染: %1")
                                .arg(QString::fromStdString(*note)));
    } else if (well_panel.depth_cursor_supported &&
               !well_panel.depth_cursor_supported()) {
        emit status_changed(QStringLiteral(
            "测井轨道使用 WellLogEngine：当前绑定缺少 crosshair 通道，"
            "深度游标联动不可用（更新 well-log-engine 绑定可恢复）"));
    }
}

void LinkedInterpretationWorkspace::set_well_backend(
    const std::string& name, const std::string& reason) {
    if (well_panel.widget == nullptr || !well_panel.set_backend) return;
    well_panel.set_backend(name);
    if (well_panel.backend && well_panel.backend() == "engine") {
        well_backend_note_.reset();
        return;
    }
    well_backend_note_ =
        reason.empty() ? "已切换到 Legacy (QPainter)" : reason;
}

std::string LinkedInterpretationWorkspace::well_backend() const {
    return well_panel.backend ? well_panel.backend() : "";
}

// -- well / seismic binding -------------------------------------------------------

void LinkedInterpretationWorkspace::open_well(
    const std::string& well_name_or_id) {
    if (!views_created_) ensure_views(false);
    bind_well(well_pane, well_name_or_id);
}

std::string LinkedInterpretationWorkspace::bind_well(
    DocumentPane* pane, const std::string& well_name_or_id) {
    const Json well = find_well(well_name_or_id);
    if (well.is_null()) return "";
    const std::string name = !rec_str(well, "name").empty()
                                 ? rec_str(well, "name")
                                 : well_name_or_id;
    const Json resource = well_resource(name);
    LinkedWellPanel* panel =
        pane == well_pane ? &well_panel : &well_panels_[pane];
    std::string active_name;
    if (!resource.is_null() && panel != nullptr &&
        panel->show_resource) {
        panel->show_resource(
            resource, project_source_.document ? project_source_.document()
                                               : Json{});
        active_name = name;
        pane->set_title(QStringLiteral("测井轨道 · %1")
                            .arg(QString::fromStdString(name)));
    } else {
        // R3-M1：无测井资源的井不得沿用上一井的曲线。
        if (panel != nullptr && panel->clear_state) panel->clear_state();
        active_name = "";
        pane->set_title(
            resource.is_null()
                ? QStringLiteral("测井轨道 · %1（无测井数据）")
                      .arg(QString::fromStdString(name))
                : QStringLiteral("测井轨道 · %1")
                      .arg(QString::fromStdString(name)));
    }
    if (pane == well_pane) {
        active_well_name_ = active_name;
    } else {
        well_names_[pane] = active_name;
    }
    apply_well_overlay(name);
    emit object_selected(
        QVariantMap{{"kind", QStringLiteral("well")},
                    {"well_name", QString::fromStdString(name)}});
    emit well_focused(QString::fromStdString(name));
    emit status_changed(QStringLiteral("已打开井 %1")
                            .arg(QString::fromStdString(name)));
    refresh_domain_status();
    return name;
}

std::string LinkedInterpretationWorkspace::bind_seismic(
    DocumentPane* pane, const Json& resource) {
    const std::string name = rec_str(resource, "name");
    const std::string key = !rec_str(resource, "id").empty()
                                ? rec_str(resource, "id")
                                : !rec_str(resource, "path").empty()
                                      ? rec_str(resource, "path")
                                      : name;
    LinkedSeismicPanel* panel =
        pane == seismic_pane ? &seismic_panel : &seismic_panels_[pane];
    if (panel != nullptr && panel->show_resource) {
        if (panel->set_project_path) {
            panel->set_project_path(project_path_);
        }
        panel->show_resource(
            resource, project_source_.document ? project_source_.document()
                                               : Json{});
        if (coordination_ != nullptr && panel->attach_coordination) {
            panel->attach_coordination(coordination_);
        }
    }
    pane->set_title(name.empty()
                        ? QStringLiteral("地震剖面")
                        : QStringLiteral("地震剖面 · %1")
                              .arg(QString::fromStdString(name)));
    return key;
}

void LinkedInterpretationWorkspace::apply_well_overlay(
    const std::string& well_name) {
    // L5/R1-M2：活动井投影到剖面——面板自报不可用原因并落状态条。
    bool reported = false;
    std::vector<LinkedSeismicPanel*> panels;
    if (seismic_panel.widget != nullptr) panels.push_back(&seismic_panel);
    for (auto& [_pane, panel] : seismic_panels_) panels.push_back(&panel);
    for (LinkedSeismicPanel* panel : panels) {
        if (!panel->set_well_overlay) continue;
        bool active = false;
        try {
            active = panel->set_well_overlay(
                well_name.empty()
                    ? std::nullopt
                    : std::optional<std::string>(well_name));
        } catch (...) {
            if (!reported) {
                emit status_changed(
                    QStringLiteral("井迹投影不可用（剖面板异常）"));
                reported = true;
            }
            continue;
        }
        if (!active && !reported &&
            panel->well_overlay_unavailable_reason) {
            const std::string reason =
                panel->well_overlay_unavailable_reason();
            if (!reason.empty()) {
                emit status_changed(QStringLiteral("井迹投影不可用：%1")
                                        .arg(QString::fromStdString(reason)));
                reported = true;
            }
        }
    }
}

void LinkedInterpretationWorkspace::show_all_wells() {
    emit show_all_wells_requested();
    emit status_changed(QStringLiteral("已显示全部工区井位"));
}

void LinkedInterpretationWorkspace::focus_joint() {
    ensure_views();
    emit status_changed(QStringLiteral("井震视图已聚焦"));
}

void LinkedInterpretationWorkspace::set_linked(bool enabled) {
    linked_ = enabled;
    sync_link_badge(seismic_pane);
    sync_link_badge(well_pane);
    for (auto& pane : extra_well_panes_) sync_link_badge(pane.get());
    for (auto& pane : extra_seismic_panes_) sync_link_badge(pane.get());
    refresh_domain_status();
}

void LinkedInterpretationWorkspace::sync_link_badge(DocumentPane* pane) {
    pane->link_label->setText(linked_ ? QStringLiteral("联动")
                                      : QStringLiteral("独立"));
    pane->link_label->setProperty("linked", linked_);
    pwb::ui_widgets::repolish(pane->link_label);
}

void LinkedInterpretationWorkspace::on_depth_cursor_from(
    LinkedWellPanel* panel, double depth) {
    // Case C producer（link-gated）：dock 井游标 → coordination bus。
    if (!linked_) return;
    emit status_changed(QStringLiteral("联动深度 %1 m")
                            .arg(depth, 0, 'f', 1));
    if (coordination_ == nullptr || panel == nullptr ||
        !panel->current_well_name) {
        return;
    }
    const std::string well = panel->current_well_name();
    if (well.empty()) return;
    coordination_->publish_depth_cursor(
        QString::fromStdString(well), depth,
        QString::fromUtf8(pwb::ui_controllers::ViewCoordinationCore::
                              SOURCE_WELL_LOG));
}

// -- project queries ----------------------------------------------------------

Json LinkedInterpretationWorkspace::find_well(
    const std::string& name_or_id) const {
    const std::string target = upper(name_or_id);
    if (!project_source_.wells) return Json();
    for (const Json& well : project_source_.wells()) {
        if (upper(rec_str(well, "id")) == target ||
            upper(rec_str(well, "name")) == target) {
            return well;
        }
    }
    return Json();
}

Json LinkedInterpretationWorkspace::well_resource(
    const std::string& well_name) const {
    const std::string target = upper(well_name);
    if (!project_source_.resources) return Json();
    for (const Json& resource : project_source_.resources()) {
        if (rec_str(resource, "type") != "well_log") continue;
        if (path_stem_upper(rec_str(resource, "name")) == target) {
            return resource;
        }
    }
    return Json();
}

Json LinkedInterpretationWorkspace::first_resource(
    const std::string& resource_type) const {
    if (!project_source_.resources) return Json();
    for (const Json& resource : project_source_.resources()) {
        if (rec_str(resource, "type") == resource_type) return resource;
    }
    return Json();
}

std::string LinkedInterpretationWorkspace::preferred_well_name() const {
    if (!find_well("A12").is_null() && !well_resource("A12").is_null()) {
        return "A12";
    }
    if (project_source_.wells) {
        for (const Json& well : project_source_.wells()) {
            const std::string name = rec_str(well, "name");
            if (!name.empty() && !well_resource(name).is_null()) {
                return name;
            }
        }
    }
    return "A12";
}

bool LinkedInterpretationWorkspace::shutdown_workers(int wait_ms) {
    drop_extra_panes();
    if (seismic_panel.shutdown) seismic_panel.shutdown();
    if (well_panel.shutdown) well_panel.shutdown(wait_ms);
    return true;
}

}  // namespace pwb::ui_composite
