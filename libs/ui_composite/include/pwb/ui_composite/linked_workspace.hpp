#pragma once

// Port of paleo_workbench/ui/workstation/linked_workspace.py (UI-13).
// 测井轨道 / 地震剖面内容部件的协调器（mapping-centric 壳层）：
// DocumentPane 对（宿主装进 QDockWidget，默认隐藏）+ 井震联动开关 +
// L10 域状态条 + coordination bus 只读订阅。
//
// 域面板（SeismicViewPanel / WellLogCanvasPanel）在 C++ 侧尚不存在——
// Python 鸭子类型在本端口显式化为注入适配器（LinkedWellPanel /
// LinkedSeismicPanel + 工厂）。协调语义（联动开关、井绑定、剖面定位、
// 深度游标、覆盖投影、状态条）全部留在这里，面板实现留宿主。

#include <functional>
#include <map>
#include <memory>
#include <optional>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>

#include <QFrame>
#include <QHBoxLayout>
#include <QLabel>
#include <QVBoxLayout>

class QComboBox;
#include <QWidget>

namespace pwb::ui_controllers {
struct SelectionState;
namespace qt {
class ViewCoordinationController;
}  // namespace qt
}  // namespace pwb::ui_controllers

namespace pwb::ui_composite {

using pwb::domain::Json;

class DocumentPane;

// ---------------------------------------------------------------------------
// 域面板鸭子类型 → 显式适配器
// ---------------------------------------------------------------------------

// 测井轨道面板消费面（panel.* 调用点全部经此）。widget 为宿主创建的面
// 板控件；缺省 std::function = Python getattr-miss → no-op/false。
struct LinkedWellPanel {
    QWidget* widget = nullptr;
    std::function<void(int wait_ms)> shutdown;
    std::function<void(const Json& resource, const Json& project)>
        show_resource;
    std::function<void()> clear_state;          // update_state(None)
    std::function<void(const std::string&)> set_backend;
    std::function<std::string()> backend;
    std::function<bool()> depth_cursor_supported;
    std::function<bool(std::optional<double>)> set_link_cursor;
    std::function<std::string()> current_well_name;
    // depth_cursor_moved 信号的订阅缝（factory 已连好则空）。
    std::function<void(std::function<void(double)>)> on_depth_cursor_moved;
};

// 地震剖面面板消费面。
struct LinkedSeismicPanel {
    QWidget* widget = nullptr;
    std::function<void()> shutdown;
    std::function<void(const std::string&)> set_project_path;
    std::function<void(const Json& resource, const Json& project)>
        show_resource;
    std::function<void(pwb::ui_controllers::qt::
                           ViewCoordinationController*)>
        attach_coordination;
    std::function<void(int, int, std::optional<double>)> locate_position;
    std::function<bool(std::optional<std::string>)> set_well_overlay;
    std::function<std::string()> well_overlay_unavailable_reason;
    std::function<bool(const std::string&)> set_profile_orientation;
};

// 面板工厂 + 井位引擎后端解析（engine_adapter.resolve_default_backend
// parity → (backend, reason)）。
struct LinkedPanelFactories {
    std::function<LinkedWellPanel(DocumentPane*)> make_well_panel;
    std::function<LinkedSeismicPanel(DocumentPane*)> make_seismic_panel;
    std::function<std::pair<std::string, std::string>()>
        resolve_default_backend;
};

// 工程只读投影（project.resources / project.wells 鸭子类型 → Json
// records：{"id","name","path","type"}；document 为传给 show_resource
// 的不透明句柄）。
struct LinkedWorkspaceProject {
    std::function<std::vector<Json>()> resources;
    std::function<std::vector<Json>()> wells;
    std::function<Json()> document;
};

// coordinate_hub.time_depth_calibration(well) 读回缝（L10 状态条）。
struct LinkedTimeDepthCalibration {
    std::string provenance;
    std::vector<std::pair<double, double>> pairs;  // (md_m, twt_ms)
    std::function<std::optional<double>(double)> md_to_twt;
    Json metadata = Json::object();
};
using LinkedCalibrationProvider =
    std::function<std::optional<LinkedTimeDepthCalibration>(
        const std::string&)>;

// ---------------------------------------------------------------------------
// DocumentPane
// ---------------------------------------------------------------------------

class DocumentPane : public QFrame {
    Q_OBJECT
public:
    explicit DocumentPane(const QString& title, QWidget* parent = nullptr);

    void set_content(QWidget* content);
    void set_title(const QString& title);
    QWidget* content() const { return content_; }

    QLabel* title_label = nullptr;
    QLabel* link_label = nullptr;
    QHBoxLayout* header_layout = nullptr;
    QFrame* host = nullptr;
    QVBoxLayout* host_layout = nullptr;

private:
    QWidget* content_ = nullptr;
};

// ---------------------------------------------------------------------------
// LinkedInterpretationWorkspace
// ---------------------------------------------------------------------------

class LinkedInterpretationWorkspace : public QWidget {
    Q_OBJECT
public:
    explicit LinkedInterpretationWorkspace(QWidget* parent = nullptr);

    // 注入缝（宿主装配；panel factories 缺省时视图保持 empty-state）。
    void set_project_source(LinkedWorkspaceProject source);
    void set_panel_factories(LinkedPanelFactories factories);
    void set_calibration_provider(LinkedCalibrationProvider provider);
    void set_project_path(const std::string& project_path);
    void set_project(const std::string& project_path = "");

    void attach_coordination(
        pwb::ui_controllers::qt::ViewCoordinationController* controller);

    // 协调动作（全部吃 _linked 开关）。
    void locate_seismic(int il, int xl, std::optional<double> twt);
    bool apply_link_cursor(const std::string& well_name,
                           std::optional<double> md);
    void ensure_views(bool load_defaults = true);
    DocumentPane* make_well_pane();
    DocumentPane* make_seismic_pane();
    void drop_extra_panes();

    std::string bind_well(DocumentPane* pane,
                          const std::string& well_name_or_id);
    std::string bind_seismic(DocumentPane* pane, const Json& resource);
    void open_well(const std::string& well_name_or_id);
    void show_all_wells();
    void focus_joint();

    void set_linked(bool enabled);
    bool is_linked() const { return linked_; }

    // 井位引擎后端（B9 honest degradation）。
    void apply_default_well_backend();
    void set_well_backend(const std::string& name,
                          const std::string& reason = "");
    std::string well_backend() const;
    std::optional<std::string> well_backend_note() const {
        return well_backend_note_;
    }

    void refresh_domain_status();
    bool shutdown_workers(int wait_ms = 3000);

    DocumentPane* seismic_pane = nullptr;
    DocumentPane* well_pane = nullptr;
    // 主 pane 绑定面板（ensure_views 后非空）。
    LinkedSeismicPanel seismic_panel;
    LinkedWellPanel well_panel;
    QLabel* domain_badge = nullptr;
    QLabel* conversion_status_label = nullptr;
    QLabel* sync_status_label = nullptr;

signals:
    void object_selected(const QVariantMap& selection);
    void status_changed(const QString& message);
    void well_focused(const QString& well_name);
    void show_all_wells_requested();

private:
    void install_domain_status_bar(QVBoxLayout* outer);
    void install_empty_states();
    void fill_empty_state(DocumentPane* pane, const QString& text);
    void sync_link_badge(DocumentPane* pane);
    bool native_platform_ok() const;
    bool can_create_native_views() const;

    void on_depth_cursor_from(LinkedWellPanel* panel, double depth);
    void apply_well_overlay(const std::string& well_name);
    void on_orientation_changed_for(LinkedSeismicPanel* panel,
                                    ::QComboBox* combo, int index);
    void install_profile_orientation_selector(
        DocumentPane* pane, LinkedSeismicPanel* panel);

    Json find_well(const std::string& name_or_id) const;
    Json well_resource(const std::string& well_name) const;
    Json first_resource(const std::string& resource_type) const;
    std::string preferred_well_name() const;

    static QString elide(const QString& text, int limit = 14);

    LinkedWorkspaceProject project_source_;
    LinkedPanelFactories factories_;
    LinkedCalibrationProvider calibration_provider_;
    pwb::ui_controllers::qt::ViewCoordinationController* coordination_ =
        nullptr;

    std::string project_path_;
    bool views_created_ = false;
    bool linked_ = true;
    std::string active_well_name_ = "A12";
    std::optional<std::string> well_backend_note_;
    class QComboBox* orientation_combo_ = nullptr;

    std::vector<std::unique_ptr<DocumentPane>> extra_well_panes_;
    std::vector<std::unique_ptr<DocumentPane>> extra_seismic_panes_;
    std::map<DocumentPane*, LinkedWellPanel> well_panels_;
    std::map<DocumentPane*, LinkedSeismicPanel> seismic_panels_;
    std::map<DocumentPane*, std::string> well_names_;
    std::string default_seismic_key_;
};

}  // namespace pwb::ui_composite
