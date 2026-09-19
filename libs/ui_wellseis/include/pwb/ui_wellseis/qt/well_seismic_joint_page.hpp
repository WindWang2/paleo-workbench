#pragma once

// UI-09 — WellSeismicJointPage Qt shell (well_seismic_joint_page.py).
// Thin toolbar + status + joint engine widget; all scene lifecycle lives
// on the injected JointHostController (WellSeismicJointHost seam). The
// page owns: domain combo (revert-on-refuse), well A/B combos (selection
// preserved across scene refreshes), 井间剖面/重新加载/导出快照 buttons,
// and the honest "联合三维引擎不可用" placeholder.

#include <functional>
#include <optional>
#include <string>
#include <vector>

#include <QWidget>

#include <pwb/ui_wellseis/qt/engine_seams.hpp>
#include <pwb/ui_wellseis/slices.hpp>

class QComboBox;
class QLabel;
class QPushButton;

namespace pwb::ui_wellseis::qt {

class WellSeismicJointPage : public QWidget {
    Q_OBJECT
public:
    // `host` is borrowed (never owned). `resolve_resource_ids` maps the
    // host's loaded data paths to catalog resource ids
    // (resource_ids_for_paths parity, PROJECT-dir anchored).
    // `register_snapshot_export` is the best-effort OUTPUT lineage seam —
    // an empty hook is a no-op like the Python catalog-missing path.
    WellSeismicJointPage(
        QWidget* parent, JointHostController* host,
        const ProjectSlice* project = nullptr,
        std::function<std::vector<std::string>(
            const std::vector<std::string>& data_paths)>
            resolve_resource_ids = {},
        std::function<void(const std::string& path,
                           const std::vector<std::string>& source_ids)>
            register_snapshot_export = {});

    void set_project(const ProjectSlice* project);
    // AppShell bounded teardown (#1158 parity).
    bool shutdown_workers(int wait_ms = 400);
    void reload();
    // export_snapshot parity — grabs the page; path may be pre-set (tests).
    QString export_snapshot(const QString& path = {});

protected:
    void showEvent(QShowEvent* event) override;

private:
    void fill_well_combos();
    void on_scene_updated();
    std::vector<std::string> loaded_source_resource_ids() const;

    JointHostController* host_ = nullptr;
    const ProjectSlice* project_ = nullptr;
    std::function<std::vector<std::string>(const std::vector<std::string>&)>
        resolve_resource_ids_;
    std::function<void(const std::string&, const std::vector<std::string>&)>
        register_snapshot_export_;
    QComboBox* domain_combo_ = nullptr;
    QComboBox* well_a_ = nullptr;
    QComboBox* well_b_ = nullptr;
    QLabel* status_ = nullptr;
    QWidget* joint_widget_ = nullptr;
    bool loaded_once_ = false;
};

}  // namespace pwb::ui_wellseis::qt
