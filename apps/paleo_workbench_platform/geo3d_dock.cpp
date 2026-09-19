#include "geo3d_dock.hpp"

#ifdef PWB_WITH_UI_WELLSEIS
#include <QMainWindow>
#include <QMetaType>

#include "job_center.hpp"
#include "viz_c_joint_host.hpp"
#endif

#include <QCheckBox>
#include <QComboBox>
#include <QDateTime>
#include <QDir>
#include <QHBoxLayout>
#include <QLabel>
#include <QListWidget>
#include <QPushButton>
#include <QSlider>
#include <QSplitter>
#include <QStatusBar>
#include <QTemporaryDir>
#include <QTimer>
#include <QVBoxLayout>
#include <QWidget>

using pwb::geo3d_viz::Geo3DViewportWidget;
using pwb::geo3d_viz::Geo3DWorkspaceController;

namespace {

constexpr const char* kClipAxis[3] = {"x", "y", "z"};

}  // namespace

Geo3DDock::Geo3DDock(QWidget* parent) : QDockWidget(tr("三维地质视图"), parent) {
    setObjectName("Geo3DDock");
    viewport_ = new Geo3DViewportWidget(this);
    controller_ = std::make_unique<Geo3DWorkspaceController>(
        [this]() { return &viewport_->scene_manager(); });
    controller_->set_viewport(viewport_);

    auto* central = new QWidget(this);
    auto* layout = new QHBoxLayout(central);

    // Left tool column: fit/clip/measure + object list + status.
    auto* tools = new QWidget(central);
    auto* tool_layout = new QVBoxLayout(tools);
    tool_layout->setContentsMargins(4, 4, 4, 4);
    build_toolbar(tools);

    object_list_ = new QListWidget(tools);
    object_list_->setToolTip(tr("场景对象（勾选控制可见性）"));
    tool_layout->addWidget(object_list_, 1);

    status_label_ = new QLabel(tr("就绪"), tools);
    status_label_->setWordWrap(true);
    tool_layout->addWidget(status_label_);

    layout->addWidget(tools, 1);
    layout->addWidget(viewport_, 4);
    setWidget(central);

    // Interaction wiring: clicks feed the controller state machines
    // (measurement accumulation / select-on-click), well selections are
    // re-broadcast to the 2D map seam.
    connect(viewport_, &Geo3DViewportWidget::viewport_clicked, this,
            [this](double px, double py) {
                controller_->handle_viewport_click(px, py);
            });
    connect(controller_.get(), &Geo3DWorkspaceController::status_message, this,
            &Geo3DDock::show_status);
    connect(controller_.get(), &Geo3DWorkspaceController::measurements_changed,
            this, &Geo3DDock::refresh_objects);
    connect(controller_.get(), &Geo3DWorkspaceController::qc_updated, this,
            &Geo3DDock::refresh_objects);
    connect(controller_.get(), &Geo3DWorkspaceController::well_selected, this,
            [this](const QString& well) {
                show_status(tr("选中井: %1（已同步 2D）").arg(well));
                emit well_selected(well);
            });
    connect(viewport_, &Geo3DViewportWidget::coordinate_hovered, this,
            [this](const QString& text) {
                if (!text.isEmpty()) status_label_->setText(text);
            });
    connect(viewport_, &Geo3DViewportWidget::gl_available_changed, this,
            [this](bool available) {
                if (!available) {
                    show_status(tr("3D 上下文不可用（offscreen/软件渲染缺 "
                                   "GL）— 场景状态与拾取仍可用"));
                }
            });
    connect(object_list_, &QListWidget::itemChanged, this,
            [this](QListWidgetItem* item) {
                const QString oid = item->data(Qt::UserRole).toString();
                if (!oid.isEmpty()) {
                    controller_->set_visibility(oid.toStdString(),
                                                item->checkState() ==
                                                    Qt::Checked);
                }
            });

    refresh_objects();
}

void Geo3DDock::build_toolbar(QWidget* tools) {
    auto* row1 = new QHBoxLayout();
    auto* fit_all = new QPushButton(tr("适配全部"), tools);
    connect(fit_all, &QPushButton::clicked, this,
            [this]() { controller_->fit_all(); });
    auto* reset_clip = new QPushButton(tr("重置剖切"), tools);
    connect(reset_clip, &QPushButton::clicked, this, [this]() {
        controller_->reset_clip();
        sync_clip_ui();
    });
    auto* screenshot = new QPushButton(tr("截图"), tools);
    connect(screenshot, &QPushButton::clicked, this, [this]() {
        const QImage image = viewport_->grab_scene_screenshot();
        if (image.isNull()) {
            show_status(tr("截图不可用（无 GL 上下文）"));
            return;
        }
        const QString path = QDir::tempPath() + "/geo3d-" +
                             QDateTime::currentDateTime().toString(
                                 "yyyyMMdd-HHmmss") +
                             ".png";
        image.save(path);
        show_status(tr("截图已保存: %1").arg(path));
    });
    row1->addWidget(fit_all);
    row1->addWidget(reset_clip);
    row1->addWidget(screenshot);
    qobject_cast<QVBoxLayout*>(tools->layout())->addLayout(row1);

    // measurement mode picker (6 modes + off), labels from the frozen table
    measure_combo_ = new QComboBox(tools);
    measure_combo_->addItem(tr("测量: 关"));
    for (const auto& spec : pwb::geo3d_viz::measure_modes()) {
        measure_combo_->addItem(QString("%1 (%2 点)")
                                    .arg(spec.label)
                                    .arg(spec.points_needed));
    }
    connect(measure_combo_, &QComboBox::currentIndexChanged, this,
            [this](int index) {
                if (index <= 0) {
                    controller_->set_measure_mode(std::nullopt);
                    return;
                }
                const auto& modes = pwb::geo3d_viz::measure_modes();
                controller_->set_measure_mode(
                    std::string(modes[static_cast<std::size_t>(index - 1)]
                                    .mode));
            });
    qobject_cast<QVBoxLayout*>(tools->layout())->addWidget(measure_combo_);

    // X/Y/Z clip controls: 0-1 slider over live bounds (Python contract).
    auto* clip_box = new QWidget(tools);
    auto* clip_layout = new QVBoxLayout(clip_box);
    clip_layout->setContentsMargins(0, 0, 0, 0);
    for (int i = 0; i < 3; ++i) {
        auto* row = new QHBoxLayout();
        auto* enabled = new QCheckBox(QString("%1 剖切").arg(kClipAxis[i][0]));
        auto* slider = new QSlider(Qt::Horizontal, clip_box);
        slider->setRange(0, 100);
        slider->setValue(50);
        auto* invert = new QCheckBox(tr("反向"), clip_box);
        row->addWidget(enabled);
        row->addWidget(slider, 1);
        row->addWidget(invert);
        clip_layout->addLayout(row);
        clip_enabled_[i] = enabled;
        clip_slider_[i] = slider;
        clip_invert_[i] = invert;
        const auto apply = [this, i]() {
            controller_->set_axis_clip(
                kClipAxis[i], clip_enabled_[i]->isChecked(),
                clip_slider_[i]->value() / 100.0,
                clip_invert_[i]->isChecked());
        };
        connect(enabled, &QCheckBox::toggled, this, apply);
        connect(invert, &QCheckBox::toggled, this, apply);
        connect(slider, &QSlider::valueChanged, this, apply);
    }
    qobject_cast<QVBoxLayout*>(tools->layout())->addWidget(clip_box);
}

void Geo3DDock::refresh_objects() {
    if (object_list_ == nullptr) return;
    const QSignalBlocker blocker(object_list_);
    object_list_->clear();
    for (const auto& object : controller_->assembly().objects()) {
        auto* item = new QListWidgetItem(
            QString::fromStdString(object.name), object_list_);
        item->setData(Qt::UserRole,
                      QString::fromStdString(object.object_id));
        item->setFlags(item->flags() | Qt::ItemIsUserCheckable);
        item->setCheckState(controller_->visibility(object.object_id)
                                ? Qt::Checked
                                : Qt::Unchecked);
        const QString worst = QString::fromStdString(
            controller_->qc_report().worst(object.object_id));
        if (worst == "blocker" || worst == "error") {
            item->setForeground(Qt::red);
        } else if (worst == "warning") {
            item->setForeground(QColor(200, 140, 0));
        }
    }
}

void Geo3DDock::show_status(const QString& message) {
    if (status_label_ != nullptr) status_label_->setText(message);
}

void Geo3DDock::sync_clip_ui() {
    const auto& clip = controller_->clip_state();
    for (int i = 0; i < 3; ++i) {
        const auto it = clip.find(kClipAxis[i]);
        if (it == clip.end()) continue;
        const QSignalBlocker block_enabled(clip_enabled_[i]);
        const QSignalBlocker block_slider(clip_slider_[i]);
        const QSignalBlocker block_invert(clip_invert_[i]);
        clip_enabled_[i]->setChecked(it->second.enabled);
        clip_slider_[i]->setValue(
            static_cast<int>(it->second.value * 100.0 + 0.5));
        clip_invert_[i]->setChecked(it->second.invert);
    }
}

#ifdef PWB_WITH_UI_WELLSEIS
// VIZ-C — joint host composition root. The JobCenter arrives through the
// MainWindow (the dock is parented to it); the host shares this dock's
// viewport/controller so joint objects and geomodel objects render in one
// scene graph.
pwb::app::viz_c::VizCJointHost* Geo3DDock::joint_host() {
    if (joint_host_ != nullptr) return joint_host_.get();
    // The owning MainWindow exposes its JobCenter through the dynamic
    // property set in init_shell (typed includes stay out of the dock
    // header). A standalone dock (tests) has no JobCenter and no joint
    // host — tests construct the host directly with their own center.
    auto* center = property("pwb_job_center").value<pwb::app::JobCenter*>();
    if (center == nullptr) return nullptr;
    joint_host_ = std::make_unique<pwb::app::viz_c::VizCJointHost>(
        *center, controller_.get(), viewport_, this);
    connect(joint_host_.get(),
            &pwb::app::viz_c::VizCJointHost::scene_updated, this,
            &Geo3DDock::refresh_objects);
    return joint_host_.get();
}
#endif
