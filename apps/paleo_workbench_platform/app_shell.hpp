#pragma once

// AppShell — the page-navigation composition root (W5/UI-17), port of
// paleo_workbench/ui/app_shell.py's assembly contract:
//
//   outer layout: WorkstationFrame (internal QMainWindow dock host)
//   WorkstationFrame.central = CompositeDocument (编图文档: 宿主注入画布)
//   "hub" dock            = scroll-wrapped AdaptivePageStack (5 hubs, real
//                         pages; 功能页 dock — Python HubScrollArea parity)
//   composite_* docks     = CompositeDocument's own sub-panels
//   mapping_stage dock    = CompositeDocument's stage panel
//   nav/inspector/tasks/logs/console/agent = UI-12 default panels
//
// Navigation: explorer.navigation_requested -> navigate_to (flush deferred
// bindings, hub switch, hub dock show+raise — Python activate_legacy /
// show_hub_page parity). Ctrl+K opens the CommandPalette over the global
// CommandRegistry; 1..5 / Alt+1..3 hub/submodule shortcuts come from the
// central ShortcutRegistry like Python.
//
// Service seams stay host-injected (DataPageServices / PrepareBackend /
// JointHost / preview providers …). Where a real adapter exists the window
// binds it; absent seams leave the ported pages' honest unavailable
// fallbacks — no fabricated backends.

#include <functional>
#include <memory>
#include <string>

#include <QString>
#include <QWidget>

#include <pwb/ui_shell/deferred_page_bindings.hpp>

namespace pwb::ui_composite {
class CompositeDocument;
}
namespace pwb::ui_pages_data::qt {
class DataWorkspace;
class HomePage;
class HubPage;
}
namespace pwb::ui_wellseis::qt {
class GeologicalModeling3DPage;
class JointHostController;
class SeismicPredictionPage;
class WellLogPredictionPage;
}
namespace pwb::ui_seqviz::qt {
class SequenceFrameworkPage;
class StratigraphyCorrelationPage;
class VisualizationPage;
}
namespace pwb::ui_map {
class MappingPage;
}
namespace pwb::ui_review::qt {
class ReviewExportPage;
}
namespace pwb::ui_shell {
class AdaptivePageStack;
class CommandPalette;
class StatusBar;
}
namespace pwb::ui_workstation {
class WorkstationFrame;
}

namespace pwb::app {

class AppShell : public QWidget {
    Q_OBJECT
public:
    explicit AppShell(QWidget* parent = nullptr);
    ~AppShell() override;

    // Host assembly (call once, before show): the session map canvas becomes
    // the composite document's central canvas. The shell reparents the
    // widget — the owning session keeps its pointer (attachCanvas already
    // bound). uses_native_stack mirrors CompositeDocument::set_canvas.
    void install_canvas(QWidget* canvas, bool uses_native_stack = false);

    // Python navigate_to parity: flush deferred bindings for the hub,
    // switch the stack + in-hub submodule, dismiss the palette, then
    // show/raise the 功能页 dock titled after the submodule.
    void navigate_to(int hub_index, const QString& submodule_key = {});
    // 功能页 dock show+raise (activate_legacy/show_hub_page parity).
    void show_hub_page(const QString& title);

    void shutdown_workers();

    pwb::ui_workstation::WorkstationFrame* workstation() const {
        return workstation_;
    }
    pwb::ui_composite::CompositeDocument* composite() const {
        return composite_;
    }
    pwb::ui_shell::StatusBar* status_bar() const { return status_bar_; }
    pwb::ui_shell::AdaptivePageStack* page_stack() const {
        return page_stack_;
    }
    pwb::ui_shell::CommandPalette* command_palette() const {
        return palette_;
    }

    // Page accessors for host wiring (non-owning).
    pwb::ui_pages_data::qt::HomePage* home_page() const {
        return home_page_;
    }
    pwb::ui_pages_data::qt::DataWorkspace* data_workspace() const {
        return data_workspace_;
    }
    pwb::ui_wellseis::qt::WellLogPredictionPage* well_log_page() const {
        return well_log_page_;
    }
    pwb::ui_seqviz::qt::SequenceFrameworkPage* sequence_page() const {
        return sequence_page_;
    }
    pwb::ui_seqviz::qt::StratigraphyCorrelationPage* stratigraphy_page()
        const {
        return stratigraphy_page_;
    }
    pwb::ui_wellseis::qt::SeismicPredictionPage* seismic_page() const {
        return seismic_page_;
    }
    pwb::ui_wellseis::qt::GeologicalModeling3DPage* geomodel_page() const {
        return geomodel_page_;
    }
    pwb::ui_map::MappingPage* mapping_page() const { return mapping_page_; }

    // BEGIN CLOSURE-MAPPING (08-line function lease — registered in
    // codex-coordination/cpp-close-wave/08-line.json; mirrors the 04-line
    // adopt_data_page pattern) Swap the hub-3 preparation placeholder for
    // the real page assembled by the closure installer.
    void adopt_preparation_page(QWidget* page);
    // END CLOSURE-MAPPING
    pwb::ui_review::qt::ReviewExportPage* review_page() const {
        return review_page_;
    }
    pwb::ui_seqviz::qt::VisualizationPage* visualization_page() const {
        return visualization_page_;
    }

    void set_project_name(const QString& name);

signals:
    // App bar / home-page project actions forwarded to the host window
    // (Python AppShell.*_requested parity).
    void new_project_requested();
    void open_project_requested();
    void open_sample_project_requested();
    void save_project_requested();
    void properties_requested();
    void preview_settings_requested();
    void about_requested();
    // View-menu requests — the host owns the theme authority.
    void theme_requested(const QString& theme_value);
    void density_requested(const QString& density_value);
    void status_message(const QString& message);

private:
    void build_pages();
    void wire_workstation();
    void setup_shortcuts();
    void on_hub_page_activated(int hub_index, const QString& key);
    void handle_workstation_command(const QString& text);

    pwb::ui_workstation::WorkstationFrame* workstation_ = nullptr;
    pwb::ui_composite::CompositeDocument* composite_ = nullptr;
    pwb::ui_shell::AdaptivePageStack* page_stack_ = nullptr;
    pwb::ui_shell::StatusBar* status_bar_ = nullptr;
    pwb::ui_shell::CommandPalette* palette_ = nullptr;
    pwb::ui_shell::DeferredPageBindings deferred_;

    // Joint-host seam: a real engine host is still deferred — the stub
    // reports has_scene=false so GeologicalModeling3DPage renders its
    // honest engine-unavailable surface (Python parity, never fabricated).
    pwb::ui_wellseis::qt::JointHostController* joint_host_ = nullptr;

    pwb::ui_pages_data::qt::HubPage* hub_data_ = nullptr;
    pwb::ui_pages_data::qt::HubPage* hub_well_ = nullptr;
    pwb::ui_pages_data::qt::HubPage* hub_seismic_ = nullptr;
    pwb::ui_pages_data::qt::HubPage* hub_mapping_ = nullptr;

    pwb::ui_pages_data::qt::HomePage* home_page_ = nullptr;
    pwb::ui_pages_data::qt::DataWorkspace* data_workspace_ = nullptr;
    pwb::ui_wellseis::qt::WellLogPredictionPage* well_log_page_ = nullptr;
    pwb::ui_seqviz::qt::SequenceFrameworkPage* sequence_page_ = nullptr;
    pwb::ui_seqviz::qt::StratigraphyCorrelationPage* stratigraphy_page_ =
        nullptr;
    pwb::ui_wellseis::qt::SeismicPredictionPage* seismic_page_ = nullptr;
    pwb::ui_wellseis::qt::GeologicalModeling3DPage* geomodel_page_ = nullptr;
    pwb::ui_map::MappingPage* mapping_page_ = nullptr;
    pwb::ui_review::qt::ReviewExportPage* review_page_ = nullptr;
    pwb::ui_seqviz::qt::VisualizationPage* visualization_page_ = nullptr;
};

}  // namespace pwb::app
