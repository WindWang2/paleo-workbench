// VIZ-A — see viz_a_install.hpp. Compiled only in builds that resolved the
// WLE viewer stack and the worker/load bridge targets (PWB_WITH_VIZ_A).

#include "viz_a_install.hpp"

#include "job_center.hpp"

#include <pwb/ingest/preview/las_wle_bridge.hpp>
#include <pwb/job_runtime/qt/job_bridge.hpp>
#include <pwb/ui_workers/well_log_load.hpp>
#include <pwb/ui_workers/wle_load.hpp>
#include <pwb/viz/well_log_document_plan.hpp>
#include <pwb/viz/well_log_host_widget.hpp>
#include <welllog/core/document.hpp>

#include <QAction>
#include <QDockWidget>
#include <QFileDialog>
#include <QFileInfo>
#include <QMenu>
#include <QMenuBar>
#include <QMessageBox>
#include <QObject>
#include <QStatusBar>

#include <algorithm>
#include <any>
#include <cmath>
#include <limits>
#include <memory>
#include <string>
#include <vector>

namespace pwb::app::viz_a {

namespace {

using WellLogDocument = welllog::WellLogDocument;

// Worker payload -> the Workbench DTO the dock host consumes. Depth column
// re-pairs with each curve (shared copy); NaN values stay gap-honest.
bool to_document_input(const WellLogDocument& document,
                       const std::string& well_name,
                       pwb::viz::WellLogDocumentInput* input) {
    if (document.sampling_axes().empty()) return false;
    const auto& axis = document.sampling_axes().front();
    auto depth = std::make_shared<std::vector<double>>();
    depth->reserve(static_cast<std::size_t>(axis.coordinates.length()));
    double top = 0.0;
    double bottom = 0.0;
    for (std::uint64_t i = 0; i < axis.coordinates.length(); ++i) {
        const auto value = axis.coordinates.value_as_double(i);
        if (!value) return false;
        depth->push_back(*value);
        if (i == 0) {
            top = bottom = *value;
        } else {
            top = std::min(top, *value);
            bottom = std::max(bottom, *value);
        }
    }
    input->well_name = well_name;
    input->top_depth = top;
    input->bottom_depth = bottom;
    input->depth_unit = axis.unit.empty()
                            ? std::nullopt
                            : std::optional<std::string>(axis.unit);
    for (const auto& curve : document.curves()) {
        auto values = std::make_shared<std::vector<double>>();
        values->reserve(depth->size());
        for (std::uint64_t i = 0; i < curve.values.length(); ++i) {
            const auto value = curve.values.value_as_double(i);
            values->push_back(value ? *value
                                    : std::numeric_limits<double>::quiet_NaN());
        }
        pwb::viz::WellLogCurveInput curve_input;
        curve_input.mnemonic = curve.mnemonic;
        curve_input.unit = curve.unit;
        curve_input.depth = depth;
        curve_input.values = std::move(values);
        input->curves.push_back(std::move(curve_input));
    }
    return !input->curves.empty();
}

}  // namespace

bool install(QMainWindow* window, JobCenter* jobs) {
    // (1) Process-wide LAS preview capability: the ingest registry .las
    // branch and the well_log fallback branch become real previews.
    pwb::ingest::preview::install_wle_las_preview_provider();

    QDockWidget* dock = window->findChild<QDockWidget*>("well-log-dock");
    auto* host = dock != nullptr
                     ? static_cast<pwb::viz::WellLogHostWidget*>(dock->widget())
                     : nullptr;
    if (host == nullptr || jobs == nullptr) return false;

    auto* menu = window->menuBar()->addMenu(QObject::tr("测井"));
    auto* open_action = menu->addAction(QObject::tr("打开 LAS…（后台）"));
    QObject::connect(open_action, &QAction::triggered, window, [window, host, jobs] {
        const QString path = QFileDialog::getOpenFileName(
            window, QObject::tr("打开 LAS"),
            QString(), QObject::tr("LAS 文件 (*.las *.LAS);;所有文件 (*)"));
        if (path.isEmpty()) return;

        auto& owner = jobs->make_owner(window);
        auto phase = std::make_shared<pwb::ui_workers::WellLogLoadPhase>();
        pwb::ui_workers::WellLogLoadInput input;
        input.ref.kind = "well_log";
        input.ref.label = path.toStdString();
        pwb::ui_workers::ResourceSlice resource;
        resource.id = path.toStdString();
        resource.name = QFileInfo(path).fileName().toStdString();
        resource.path = path.toStdString();
        resource.type = "well_log";
        resource.format = "las";
        input.resources.push_back(resource);
        input.load_fn = pwb::ui_workers::make_wle_load_fn();
        input.phase = phase;

        auto spec = pwb::ui_workers::make_well_log_load_job_spec(
            std::move(input));

        window->statusBar()->showMessage(QObject::tr("测井曲线加载中…"));

        owner.start(
            jobs->scheduler(), std::move(spec),
            [window, host, path](const pwb::job::qtbridge::JobOutcome& outcome) {
                if (outcome.state == pwb::job::JobState::cancelled) {
                    window->statusBar()->showMessage(
                        QObject::tr("测井曲线加载已取消"), 4000);
                    return;
                }
                if (outcome.state == pwb::job::JobState::failed) {
                    QMessageBox::warning(
                        window, QObject::tr("测井"),
                        QObject::tr("LAS 加载失败: %1")
                            .arg(QString::fromStdString(outcome.error)));
                    return;
                }
                const auto* result =
                    std::any_cast<pwb::ui_workers::WellLogLoadResult>(
                        &outcome.result);
                if (result == nullptr ||
                    result->payload.kind != "well_log" ||
                    !result->payload.well_log.has_value()) {
                    window->statusBar()->showMessage(
                        QObject::tr("无法解析 LAS 井数据"), 4000);
                    return;
                }
                const auto document =
                    std::any_cast<std::shared_ptr<const WellLogDocument>>(
                        result->payload.well_log);
                pwb::viz::WellLogDocumentInput dto;
                if (document == nullptr ||
                    !to_document_input(*document,
                                       result->payload.well_names.empty()
                                           ? path.toStdString()
                                           : result->payload.well_names.front(),
                                       &dto)) {
                    window->statusBar()->showMessage(
                        QObject::tr("LAS 文档为空"), 4000);
                    return;
                }
                QString error;
                if (!host->load_document(
                        dto, pwb::viz::WellLogTrackLayout{}, &error)) {
                    QMessageBox::warning(
                        window, QObject::tr("测井"),
                        QObject::tr("加载到轨道失败: %1").arg(error));
                    return;
                }
                window->statusBar()->showMessage(
                    QObject::tr("测井已加载: %1（%2 条曲线）")
                        .arg(path)
                        .arg(dto.curves.size()),
                    5000);
            });
        // Cancel surface: the JobOwner cooperatively cancels via its token
        // (wired to shutdown_workers on close); the worker checks the token
        // plus `phase` at its checkpoints and drops late payloads.
    });
    return true;
}

}  // namespace pwb::app::viz_a
