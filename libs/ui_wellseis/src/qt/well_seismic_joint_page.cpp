#include <pwb/ui_wellseis/qt/well_seismic_joint_page.hpp>

#include <QComboBox>
#include <QFileDialog>
#include <QFileInfo>
#include <QHBoxLayout>
#include <QLabel>
#include <QPushButton>
#include <QShowEvent>
#include <QVBoxLayout>

namespace pwb::ui_wellseis::qt {

WellSeismicJointPage::WellSeismicJointPage(
    QWidget* parent, JointHostController* host,
    const ProjectSlice* project,
    std::function<std::vector<std::string>(
        const std::vector<std::string>&)>
        resolve_resource_ids,
    std::function<void(const std::string&,
                       const std::vector<std::string>&)>
        register_snapshot_export)
    : QWidget(parent),
      host_(host),
      project_(project),
      resolve_resource_ids_(std::move(resolve_resource_ids)),
      register_snapshot_export_(std::move(register_snapshot_export)) {
    setObjectName(QStringLiteral("WellSeismicJointPage"));

    if (host_ != nullptr) {
        connect(host_, &JointHostController::status_changed, this,
                [this](const QString& text) { status_->setText(text); });
        connect(host_, &JointHostController::scene_updated, this,
                &WellSeismicJointPage::on_scene_updated);
    }

    auto* outer = new QVBoxLayout(this);
    outer->setContentsMargins(16, 16, 16, 16);
    outer->setSpacing(8);

    auto* header = new QHBoxLayout();
    auto* title = new QLabel(QStringLiteral("井震联合分析"), this);
    title->setObjectName(QStringLiteral("PageTitle"));
    header->addWidget(title);
    header->addStretch();

    domain_combo_ = new QComboBox(this);
    domain_combo_->addItems({QStringLiteral("Time"),
                             QStringLiteral("Depth")});
    connect(domain_combo_, &QComboBox::currentTextChanged, this,
            [this](const QString& text) {
                if (host_ == nullptr) {
                    return;
                }
                const bool applied =
                    host_->set_vertical_domain(text.toStdString());
                if (!applied) {
                    // Depth refused (no transform): revert to the scene's
                    // actual domain instead of showing a state it is not in.
                    const auto snap = host_->scene_snapshot();
                    const QString actual =
                        snap.has_scene && snap.depth_domain
                            ? QStringLiteral("Depth")
                            : QStringLiteral("Time");
                    domain_combo_->blockSignals(true);
                    const int idx = domain_combo_->findText(actual);
                    if (idx >= 0) {
                        domain_combo_->setCurrentIndex(idx);
                    }
                    domain_combo_->blockSignals(false);
                }
            });
    header->addWidget(new QLabel(QStringLiteral("竖直域"), this));
    header->addWidget(domain_combo_);

    well_a_ = new QComboBox(this);
    well_b_ = new QComboBox(this);
    header->addWidget(new QLabel(QStringLiteral("井间"), this));
    header->addWidget(well_a_);
    header->addWidget(well_b_);
    auto* fence_btn = new QPushButton(QStringLiteral("井间剖面"), this);
    connect(fence_btn, &QPushButton::clicked, this, [this] {
        if (host_ != nullptr) {
            host_->add_well_to_well_fence(
                well_a_->currentText().toStdString(),
                well_b_->currentText().toStdString());
        }
    });
    header->addWidget(fence_btn);

    auto* reload_btn = new QPushButton(QStringLiteral("重新加载"), this);
    connect(reload_btn, &QPushButton::clicked, this,
            &WellSeismicJointPage::reload);
    header->addWidget(reload_btn);
    auto* snapshot_btn =
        new QPushButton(QStringLiteral("导出快照"), this);
    connect(snapshot_btn, &QPushButton::clicked, this,
            [this] { export_snapshot(); });
    header->addWidget(snapshot_btn);
    outer->addLayout(header);

    status_ = new QLabel(QStringLiteral("就绪"), this);
    status_->setWordWrap(true);
    status_->setObjectName(QStringLiteral("WorkFieldValue"));
    outer->addWidget(status_);

    // Engine seam — nullptr renders the honest unavailable line (Python
    // `联合三维引擎不可用: {error}` parity), never a silent empty pane.
    if (host_ != nullptr && host_->has_scene()) {
        joint_widget_ = host_->joint_widget(this);
        if (joint_widget_ != nullptr) {
            outer->addWidget(joint_widget_, 1);
        } else {
            outer->addWidget(
                new QLabel(QStringLiteral("联合三维引擎不可用: %1")
                               .arg(QString::fromStdString(
                                   host_->engine_error())),
                           this),
                1);
        }
    } else {
        const std::string error =
            host_ != nullptr ? host_->engine_error() : "unknown";
        outer->addWidget(
            new QLabel(QStringLiteral("联合三维引擎不可用: %1")
                           .arg(QString::fromStdString(
                               error.empty() ? "unknown" : error)),
                       this),
            1);
    }
}

void WellSeismicJointPage::set_project(const ProjectSlice* project) {
    project_ = project;
}

bool WellSeismicJointPage::shutdown_workers(int wait_ms) {
    return host_ == nullptr || host_->shutdown(wait_ms);
}

void WellSeismicJointPage::showEvent(QShowEvent* event) {
    QWidget::showEvent(event);
    if (!loaded_once_ && isVisible()) {
        loaded_once_ = true;
        reload();
    }
}

void WellSeismicJointPage::reload() {
    if (host_ != nullptr) {
        host_->reload();
    }
    fill_well_combos();
}

void WellSeismicJointPage::on_scene_updated() {
    if (host_ == nullptr) {
        return;
    }
    if (joint_widget_ != nullptr && host_->has_scene()) {
        host_->push_scene_to_widget();
    }
    fill_well_combos();
}

void WellSeismicJointPage::fill_well_combos() {
    const QString a_sel = well_a_->currentText();
    const QString b_sel = well_b_->currentText();
    well_a_->clear();
    well_b_->clear();
    std::vector<std::pair<std::string, std::string>> options;
    if (host_ != nullptr) {
        options = host_->well_options();
    }
    QStringList names;
    for (const auto& [_id, display] : options) {
        names << QString::fromStdString(display);
    }
    well_a_->addItems(names);
    well_b_->addItems(names);
    // Preserve the user's selection across scene refreshes (fence creation,
    // LOD refinements re-emit scene_updated); fall back to the original
    // defaults only when the chosen well is no longer present.
    if (names.contains(a_sel)) {
        well_a_->setCurrentText(a_sel);
    } else if (!names.isEmpty()) {
        well_a_->setCurrentIndex(0);
    }
    if (names.contains(b_sel)) {
        well_b_->setCurrentText(b_sel);
    } else if (names.size() >= 2) {
        well_b_->setCurrentIndex(1);
    }
}

std::vector<std::string>
WellSeismicJointPage::loaded_source_resource_ids() const {
    if (project_ == nullptr || host_ == nullptr) {
        return {};
    }
    const auto wanted = host_->loaded_data_paths();
    if (wanted.empty() || !resolve_resource_ids_) {
        return {};
    }
    return resolve_resource_ids_(wanted);
}

QString WellSeismicJointPage::export_snapshot(const QString& path) {
    QString target = path;
    if (target.isEmpty()) {
        target = QFileDialog::getSaveFileName(
            this, QStringLiteral("导出快照"),
            QStringLiteral("well_seismic_joint.png"),
            QStringLiteral("PNG (*.png)"));
    }
    if (target.isEmpty()) {
        return {};
    }
    if (grab().save(target)) {
        status_->setText(QStringLiteral("已导出快照: %1")
                             .arg(QFileInfo(target).fileName()));
        // Best-effort OUTPUT DataVersion registration (no hook → no-op).
        if (register_snapshot_export_ && project_ != nullptr) {
            register_snapshot_export_(target.toStdString(),
                                      loaded_source_resource_ids());
        }
        return target;
    }
    status_->setText(QStringLiteral("快照导出失败"));
    return {};
}

}  // namespace pwb::ui_wellseis::qt
