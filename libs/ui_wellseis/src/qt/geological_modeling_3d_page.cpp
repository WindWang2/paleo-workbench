#include <pwb/ui_wellseis/qt/geological_modeling_3d_page.hpp>

#include <QCheckBox>
#include <QCloseEvent>
#include <QComboBox>
#include <QDoubleSpinBox>
#include <QFileDialog>
#include <QFrame>
#include <QGridLayout>
#include <QHBoxLayout>
#include <QLabel>
#include <QListWidget>
#include <QPushButton>
#include <QShowEvent>
#include <QSlider>
#include <QSpinBox>
#include <QSplitter>
#include <QStandardItemModel>
#include <QTabWidget>
#include <QTextBrowser>
#include <QTreeWidget>
#include <QTreeWidgetItem>
#include <QVBoxLayout>

namespace pwb::ui_wellseis::qt {

namespace {

QString qs(const std::string& text) {
    return QString::fromUtf8(text.data(), static_cast<int>(text.size()));
}

// The geoviz layer names are the persisted tree_checks keys — keep them
// byte-identical with the Python literals.
constexpr const char* kJointRoot = "井震联合 (geoviz)";
constexpr const char* kJointWells = "联合井轨迹 (geoviz)";

bool is_depth_domain(const JointSceneSnapshot& snap) {
    return snap.has_scene && snap.depth_domain;
}

}  // namespace

GeologicalModeling3DPage::GeologicalModeling3DPage(
    QWidget* parent, JointHostController* host, Geo3DController* geo3d,
    Geo3DAnalysisHooks hooks)
    : QWidget(parent), host_(host), geo3d_(geo3d),
      hooks_(std::move(hooks)) {
    setObjectName(QStringLiteral("GeologicalModeling3DPage"));
    setFocusPolicy(Qt::StrongFocus);

    auto* main_layout = new QHBoxLayout(this);
    main_layout->setContentsMargins(8, 8, 8, 8);
    main_layout->setSpacing(8);

    auto* splitter = new QSplitter(Qt::Horizontal, this);

    // 1. Left: geoviz scene tree + Geo3D inspector panel.
    auto* left_widget = new QWidget(splitter);
    auto* left_layout = new QVBoxLayout(left_widget);
    left_layout->setContentsMargins(0, 0, 0, 0);
    left_layout->setSpacing(8);
    auto* left_header = new QLabel(QStringLiteral("场景对象"), left_widget);
    left_header->setObjectName(QStringLiteral("PanelHeader"));
    left_layout->addWidget(left_header);
    model_tree_ = new QTreeWidget(left_widget);
    model_tree_->setHeaderLabel(QStringLiteral("井震联合图层"));
    populate_model_tree();
    left_layout->addWidget(model_tree_, 1);

    // Geo3D inspector (measure / clip / views / QC / inspector) — all
    // forwarded to the controller seam.
    auto* geo_panel = new QFrame(left_widget);
    geo_panel->setObjectName(QStringLiteral("Geo3DPanel"));
    auto* geo_layout = new QVBoxLayout(geo_panel);
    geo_layout->setContentsMargins(8, 8, 8, 8);
    geo_layout->setSpacing(4);

    auto* measure_row = new QHBoxLayout();
    measure_row->setSpacing(4);
    measure_combo_ = new QComboBox(geo_panel);
    measure_combo_->addItem(QStringLiteral("测量: 关"), QString());
    measure_combo_->addItem(QStringLiteral("测量: 距离"),
                            QStringLiteral("distance"));
    measure_combo_->addItem(QStringLiteral("测量: 面积"),
                            QStringLiteral("area"));
    connect(measure_combo_, &QComboBox::currentIndexChanged, this,
            [this](int) {
                if (geo3d_ != nullptr) {
                    geo3d_->set_measure_mode(
                        measure_combo_->currentData().toString());
                }
            });
    measure_row->addWidget(measure_combo_, 1);
    auto* measure_clear =
        new QPushButton(QStringLiteral("清除测量"), geo_panel);
    connect(measure_clear, &QPushButton::clicked, this, [this] {
        if (geo3d_ == nullptr) {
            return;
        }
        const int removed = geo3d_->clear(QStringLiteral("measure"));
        status_->setText(removed > 0
                             ? QStringLiteral("已清除 %1 条测量记录")
                                   .arg(removed)
                             : QStringLiteral("暂无测量记录"));
    });
    measure_row->addWidget(measure_clear);
    geo_layout->addLayout(measure_row);

    auto* clip_grid = new QGridLayout();
    clip_grid->setSpacing(4);
    const QStringList axes = {QStringLiteral("x"), QStringLiteral("y"),
                              QStringLiteral("z")};
    for (int row = 0; row < axes.size(); ++row) {
        auto* check = new QCheckBox(axes[row].toUpper(), geo_panel);
        auto* slide = new QSlider(Qt::Horizontal, geo_panel);
        slide->setRange(0, 100);
        slide->setValue(50);
        connect(check, &QCheckBox::toggled, this, [this](bool) {
            if (geo3d_ == nullptr) {
                return;
            }
            for (const auto& [axis, pair] : clip_rows_) {
                geo3d_->set_axis_clip(axis, pair.first->isChecked(),
                                      pair.second->value() / 100.0,
                                      /*invert=*/false);
            }
        });
        connect(slide, &QSlider::valueChanged, this, [this](int) {
            if (geo3d_ == nullptr) {
                return;
            }
            for (const auto& [axis, pair] : clip_rows_) {
                geo3d_->set_axis_clip(axis, pair.first->isChecked(),
                                      pair.second->value() / 100.0,
                                      /*invert=*/false);
            }
        });
        clip_grid->addWidget(check, row, 0);
        clip_grid->addWidget(slide, row, 1);
        clip_rows_[axes[row]] = {check, slide};
    }
    auto* clip_reset =
        new QPushButton(QStringLiteral("重置剖切"), geo_panel);
    connect(clip_reset, &QPushButton::clicked, this, [this] {
        if (geo3d_ != nullptr) {
            geo3d_->reset_clip();
        }
        for (const auto& [_axis, pair] : clip_rows_) {
            pair.first->setChecked(false);
            pair.second->setValue(50);
        }
    });
    clip_grid->addWidget(clip_reset, 3, 0, 1, 2);
    geo_layout->addLayout(clip_grid);

    auto* view_row = new QHBoxLayout();
    view_row->setSpacing(4);
    auto* fit_btn = new QPushButton(QStringLiteral("适配全部"), geo_panel);
    connect(fit_btn, &QPushButton::clicked, this, [this] {
        if (geo3d_ != nullptr) {
            geo3d_->fit_all();
        }
    });
    view_row->addWidget(fit_btn);
    view_combo_ = new QComboBox(geo_panel);
    view_combo_->setMinimumWidth(90);
    connect(view_combo_, &QComboBox::currentTextChanged, this,
            [this](const QString& name) {
                if (geo3d_ != nullptr && !name.isEmpty()) {
                    geo3d_->apply_view(name);
                }
            });
    view_row->addWidget(view_combo_, 1);
    auto* save_view_btn =
        new QPushButton(QStringLiteral("存视图"), geo_panel);
    connect(save_view_btn, &QPushButton::clicked, this, [this] {
        if (geo3d_ == nullptr) {
            return;
        }
        geo3d_->save_view(view_combo_->currentText());
        view_combo_->clear();
        for (const QString& name : geo3d_->saved_view_names()) {
            view_combo_->addItem(name);
        }
    });
    view_row->addWidget(save_view_btn);
    geo_layout->addLayout(view_row);

    auto* qc_label = new QLabel(QStringLiteral("质检 (QC)"), geo_panel);
    qc_label->setObjectName(QStringLiteral("SectionLabel"));
    geo_layout->addWidget(qc_label);
    qc_list_ = new QListWidget(geo_panel);
    qc_list_->setMaximumHeight(96);
    geo_layout->addWidget(qc_list_);

    auto* insp_label =
        new QLabel(QStringLiteral("对象检查器"), geo_panel);
    insp_label->setObjectName(QStringLiteral("SectionLabel"));
    geo_layout->addWidget(insp_label);
    inspector_ = new QTextBrowser(geo_panel);
    inspector_->setMaximumHeight(120);
    geo_layout->addWidget(inspector_);
    left_layout->addWidget(geo_panel);

    splitter->addWidget(left_widget);

    if (geo3d_ != nullptr) {
        connect(geo3d_, &Geo3DController::qc_updated, this,
                [this](const QStringList& lines) {
                    qc_list_->clear();
                    qc_list_->addItems(lines);
                });
        connect(geo3d_, &Geo3DController::inspector_updated, this,
                [this](const QString& text) {
                    inspector_->setPlainText(text);
                });
        connect(geo3d_, &Geo3DController::status_message, this,
                [this](const QString& text) { status_->setText(text); });
        connect(model_tree_, &QTreeWidget::itemSelectionChanged, this,
                [this] {
                    const auto items = model_tree_->selectedItems();
                    if (geo3d_ != nullptr && !items.isEmpty()) {
                        geo3d_->inspect(items.first()->text(0));
                    }
                });
    }

    // 2. Center: toolbar + joint host + slice card + analysis card +
    // collapsible 2D strip.
    auto* center_column = new QWidget(splitter);
    auto* center_layout = new QVBoxLayout(center_column);
    center_layout->setContentsMargins(0, 0, 0, 0);
    center_layout->setSpacing(0);
    auto* center_v_split = new QSplitter(Qt::Vertical, center_column);

    auto* view_container = new QFrame(center_v_split);
    view_container->setFrameShape(QFrame::StyledPanel);
    auto* view_layout = new QVBoxLayout(view_container);
    view_layout->setContentsMargins(4, 4, 4, 4);
    view_layout->setSpacing(4);

    auto* toolbar = new QFrame(view_container);
    toolbar->setObjectName(QStringLiteral("JointTopToolbar"));
    auto* t_layout = new QHBoxLayout(toolbar);
    t_layout->setContentsMargins(8, 4, 8, 4);
    t_layout->setSpacing(4);

    t_layout->addWidget(new QLabel(QStringLiteral("域"), toolbar));
    domain_combo_ = new QComboBox(toolbar);
    domain_combo_->addItems({QStringLiteral("Time"),
                             QStringLiteral("Depth")});
    connect(domain_combo_, &QComboBox::currentTextChanged, this,
            &GeologicalModeling3DPage::on_joint_domain_changed);
    t_layout->addWidget(domain_combo_);

    t_layout->addWidget(new QLabel(QStringLiteral("3D"), toolbar));
    mode_3d_combo_ = new QComboBox(toolbar);
    mode_3d_combo_->setObjectName(QStringLiteral("Joint3DMode"));
    mode_3d_combo_->addItem(QStringLiteral("正交切片"),
                            QStringLiteral("planes"));
    mode_3d_combo_->addItem(QStringLiteral("三维体"),
                            QStringLiteral("volume"));
    mode_3d_combo_->setToolTip(
        QStringLiteral("三维视口显示正交切片或三维体"));
    connect(mode_3d_combo_, &QComboBox::currentIndexChanged, this,
            [this](int) {
                if (host_ != nullptr) {
                    host_->set_3d_mode(
                        mode_3d_combo_->currentData()
                            .toString()
                            .toStdString());
                }
            });
    t_layout->addWidget(mode_3d_combo_);

    slice_card_btn_ = new QPushButton(QStringLiteral("切片位置"), toolbar);
    slice_card_btn_->setCheckable(true);
    slice_card_btn_->setChecked(true);
    slice_card_btn_->setToolTip(
        QStringLiteral("打开 Inline / Crossline / Time 切片位置条"));
    t_layout->addWidget(slice_card_btn_);

    analysis_btn_ = new QPushButton(QStringLiteral("分析"), toolbar);
    analysis_btn_->setCheckable(true);
    analysis_btn_->setChecked(false);
    analysis_btn_->setObjectName(QStringLiteral("JointAnalysisBtn"));
    analysis_btn_->setToolTip(QStringLiteral(
        "等时/比例地层切片、井震标定、沉积相、导出与诊断"));
    t_layout->addWidget(analysis_btn_);

    t_layout->addWidget(new QLabel(QStringLiteral("交互"), toolbar));
    pick_mode_combo_ = new QComboBox(toolbar);
    pick_mode_combo_->setObjectName(QStringLiteral("JointPickMode"));
    pick_mode_combo_->addItem(QStringLiteral("选井两点"),
                              QStringLiteral("pick"));
    pick_mode_combo_->addItem(QStringLiteral("画线吸附"),
                              QStringLiteral("draw"));
    t_layout->addWidget(pick_mode_combo_);

    t_layout->addWidget(new QLabel(QStringLiteral("井间"), toolbar));
    well_a_ = new QComboBox(toolbar);
    well_b_ = new QComboBox(toolbar);
    t_layout->addWidget(well_a_);
    t_layout->addWidget(well_b_);
    auto* fence_btn =
        new QPushButton(QStringLiteral("井间剖面"), toolbar);
    connect(fence_btn, &QPushButton::clicked, this, [this] {
        if (host_ == nullptr) {
            return;
        }
        const QString a = well_a_->currentData().isValid()
                              ? well_a_->currentData().toString()
                              : well_a_->currentText();
        const QString b = well_b_->currentData().isValid()
                              ? well_b_->currentData().toString()
                              : well_b_->currentText();
        host_->add_well_to_well_fence(a.toStdString(), b.toStdString());
    });
    t_layout->addWidget(fence_btn);
    auto* del_fence_btn =
        new QPushButton(QStringLiteral("删 active"), toolbar);
    del_fence_btn->setToolTip(
        QStringLiteral("删除当前活动井间剖面（保留其它 fence）"));
    connect(del_fence_btn, &QPushButton::clicked, this, [this] {
        if (host_ != nullptr) {
            host_->delete_active_fence();
        }
    });
    t_layout->addWidget(del_fence_btn);
    auto* refresh_btn =
        new QPushButton(QStringLiteral("从工程/数据刷新"), toolbar);
    refresh_btn->setToolTip(QStringLiteral(
        "重新解析并挂载 SEGY / 井 / tops / LAS（hybrid）"));
    connect(refresh_btn, &QPushButton::clicked, this, [this] {
        if (host_ != nullptr) {
            host_->reload();
        }
    });
    t_layout->addWidget(refresh_btn);

    t_layout->addSpacing(8);
    auto* orbit_btn =
        new QPushButton(QStringLiteral("透视视角"), toolbar);
    connect(orbit_btn, &QPushButton::clicked, this, [this] {
        if (host_ != nullptr) {
            host_->apply_camera_preset("perspective");
        }
    });
    t_layout->addWidget(orbit_btn);
    auto* pan_btn = new QPushButton(QStringLiteral("俯瞰视角"), toolbar);
    connect(pan_btn, &QPushButton::clicked, this, [this] {
        if (host_ != nullptr) {
            host_->apply_camera_preset("top");
        }
    });
    t_layout->addWidget(pan_btn);
    auto* reset_btn = new QPushButton(QStringLiteral("复位"), toolbar);
    connect(reset_btn, &QPushButton::clicked, this, [this] {
        if (host_ != nullptr) {
            host_->apply_camera_preset("perspective");
        }
    });
    t_layout->addWidget(reset_btn);
    t_layout->addStretch(1);
    view_layout->addWidget(toolbar);

    // Joint engine widget (nullptr → honest unavailable placeholder).
    // Inserted last in view_layout below, matching the Python order:
    // toolbar / slice card / analysis card / status row / 3D host.
    if (host_ != nullptr && host_->has_scene()) {
        joint_widget_ = host_->joint_widget(view_container);
    }

    // Orthogonal slice card (IL / XL / time slices / opacity).
    auto* slice_card = new QFrame(view_container);
    slice_card->setObjectName(QStringLiteral("JointOrthogonalSliceCard"));
    slice_card->setMaximumHeight(52);
    auto* sc_layout = new QHBoxLayout(slice_card);
    sc_layout->setContentsMargins(8, 4, 8, 4);
    sc_layout->setSpacing(4);
    sc_layout->addWidget(new QLabel(QStringLiteral("IL"), slice_card));
    inline_slice_ = new QSpinBox(slice_card);
    inline_slice_->setRange(0, 0);
    inline_slice_->setMaximumWidth(92);
    inline_slice_->setAccessibleName(
        QStringLiteral("Inline 切片位置"));
    sc_layout->addWidget(inline_slice_);
    sc_layout->addWidget(new QLabel(QStringLiteral("XL"), slice_card));
    crossline_slice_ = new QSpinBox(slice_card);
    crossline_slice_->setRange(0, 0);
    crossline_slice_->setMaximumWidth(92);
    crossline_slice_->setAccessibleName(
        QStringLiteral("Crossline 切片位置"));
    sc_layout->addWidget(crossline_slice_);
    sc_layout->addSpacing(4);
    sc_layout->addWidget(new QLabel(QStringLiteral("Time"), slice_card));
    time_selector_ = new QComboBox(slice_card);
    time_selector_->setMaximumWidth(126);
    time_selector_->setAccessibleName(
        QStringLiteral("活动 Time 切片"));
    time_selector_->setToolTip(
        QStringLiteral("选择当前要编辑和交互的 Time 切片"));
    sc_layout->addWidget(time_selector_);
    active_time_editor_ = new QDoubleSpinBox(slice_card);
    active_time_editor_->setDecimals(3);
    active_time_editor_->setRange(0.0, 0.0);
    active_time_editor_->setSuffix(QStringLiteral(" ms"));
    active_time_editor_->setMaximumWidth(126);
    active_time_editor_->setAccessibleName(
        QStringLiteral("活动 Time 切片时间"));
    sc_layout->addWidget(active_time_editor_);
    active_time_visible_ = new QCheckBox(QStringLiteral("显示"), slice_card);
    active_time_visible_->setAccessibleName(
        QStringLiteral("活动 Time 切片可见性"));
    sc_layout->addWidget(active_time_visible_);
    auto* delete_time_btn =
        new QPushButton(QStringLiteral("删除"), slice_card);
    delete_time_btn->setAccessibleName(
        QStringLiteral("删除活动 Time 切片"));
    connect(delete_time_btn, &QPushButton::clicked, this, [this] {
        if (host_ != nullptr && time_selector_->currentData().isValid()) {
            host_->remove_time_slice(
                time_selector_->currentData().toDouble());
        }
    });
    sc_layout->addWidget(delete_time_btn);
    sc_layout->addSpacing(4);
    sc_layout->addWidget(new QLabel(QStringLiteral("新增"), slice_card));
    new_time_ = new QDoubleSpinBox(slice_card);
    new_time_->setDecimals(3);
    new_time_->setRange(0.0, 0.0);
    new_time_->setSuffix(QStringLiteral(" ms"));
    new_time_->setMaximumWidth(126);
    new_time_->setAccessibleName(QStringLiteral("新增 Time 切片时间"));
    sc_layout->addWidget(new_time_);
    auto* add_time_btn = new QPushButton(QStringLiteral("+"), slice_card);
    add_time_btn->setToolTip(QStringLiteral("添加 Time 切片"));
    add_time_btn->setAccessibleName(QStringLiteral("添加 Time 切片"));
    connect(add_time_btn, &QPushButton::clicked, this, [this] {
        if (host_ != nullptr) {
            host_->add_time_slice(new_time_->value());
        }
    });
    sc_layout->addWidget(add_time_btn);
    sc_layout->addSpacing(4);
    sc_layout->addWidget(new QLabel(QStringLiteral("透明度"), slice_card));
    time_opacity_ = new QSpinBox(slice_card);
    time_opacity_->setRange(10, 100);
    time_opacity_->setValue(80);
    time_opacity_->setSuffix(QStringLiteral("%"));
    time_opacity_->setMaximumWidth(84);
    time_opacity_->setAccessibleName(
        QStringLiteral("Time 切片透明度"));
    sc_layout->addWidget(time_opacity_);
    time_domain_note_ = new QLabel(QString(), slice_card);
    time_domain_note_->setToolTip(
        QStringLiteral("时间会自动吸附到可显示的 SEG-Y 样点"));
    sc_layout->addWidget(time_domain_note_);
    sc_layout->addStretch(1);

    connect(slice_card_btn_, &QAbstractButton::toggled, slice_card,
            &QWidget::setVisible);
    connect(inline_slice_, &QSpinBox::valueChanged, this, [this](int v) {
        if (host_ != nullptr) {
            host_->set_orthogonal_slice_indices(v, std::nullopt);
        }
    });
    connect(crossline_slice_, &QSpinBox::valueChanged, this,
            [this](int v) {
                if (host_ != nullptr) {
                    host_->set_orthogonal_slice_indices(std::nullopt, v);
                }
            });
    connect(time_selector_, &QComboBox::currentIndexChanged, this,
            [this](int) {
                if (host_ != nullptr &&
                    time_selector_->currentData().isValid()) {
                    host_->set_active_time_slice(
                        time_selector_->currentData().toDouble());
                }
            });
    connect(active_time_editor_, &QDoubleSpinBox::editingFinished, this,
            [this] {
                if (host_ != nullptr &&
                    time_selector_->currentData().isValid()) {
                    const double old_ms =
                        time_selector_->currentData().toDouble();
                    const double new_ms = active_time_editor_->value();
                    if (new_ms != old_ms) {
                        // Move the active slice: retime it (engine
                        // removes the old entry + adds the new).
                        const bool visible =
                            active_time_visible_->isChecked();
                        host_->remove_time_slice(old_ms);
                        host_->add_time_slice(new_ms);
                        host_->set_time_slice_visible(new_ms, visible);
                        host_->set_active_time_slice(new_ms);
                    }
                }
            });
    connect(active_time_visible_, &QCheckBox::toggled, this,
            [this](bool checked) {
                if (host_ != nullptr &&
                    time_selector_->currentData().isValid()) {
                    host_->set_time_slice_visible(
                        time_selector_->currentData().toDouble(), checked);
                }
            });
    connect(time_opacity_, &QSpinBox::valueChanged, this, [this](int v) {
        if (host_ != nullptr) {
            host_->set_time_opacity(v / 100.0);
        }
    });
    view_layout->addWidget(slice_card);

    // Analysis card (4 tabs, lazily the same controls the legacy rail had).
    analysis_card_ = new QFrame(view_container);
    analysis_card_->setObjectName(QStringLiteral("JointAnalysisCard"));
    auto* ac_layout = new QVBoxLayout(analysis_card_);
    ac_layout->setContentsMargins(4, 4, 4, 4);
    ac_layout->setSpacing(4);
    analysis_tabs_ = new QTabWidget(analysis_card_);
    analysis_tabs_->setObjectName(QStringLiteral("JointAnalysisTabs"));
    analysis_tabs_->addTab(build_stratal_tab(),
                           QStringLiteral("等时切片与属性"));
    analysis_tabs_->addTab(build_welltie_tab(),
                           QStringLiteral("井震标定"));
    analysis_tabs_->addTab(build_facies_tab(),
                           QStringLiteral("沉积相解释"));
    analysis_tabs_->addTab(build_export_diag_tab(),
                           QStringLiteral("导出与诊断"));
    ac_layout->addWidget(analysis_tabs_);
    analysis_card_->setVisible(false);
    connect(analysis_btn_, &QAbstractButton::toggled, analysis_card_,
            &QWidget::setVisible);
    view_layout->addWidget(analysis_card_);

    center_v_split->addWidget(view_container);

    // Collapsible 2D strip (fence/time-slice host + color-scale card).
    joint_2d_panel_ = new QFrame(center_v_split);
    joint_2d_panel_->setObjectName(QStringLiteral("JointFence2DPanel"));
    auto* j2_layout = new QVBoxLayout(joint_2d_panel_);
    j2_layout->setContentsMargins(4, 4, 4, 4);
    j2_layout->setSpacing(4);
    auto* j2_header = new QHBoxLayout();
    auto* j2_title =
        new QLabel(QStringLiteral("Time 平面 / 井间剖面"), joint_2d_panel_);
    j2_header->addWidget(j2_title);
    time_chip_ =
        new QLabel(QStringLiteral("域: Time · 2D/3D 联动"), joint_2d_panel_);
    time_chip_->setObjectName(QStringLiteral("Joint2DTimeChip"));
    j2_header->addWidget(time_chip_);
    j2_header->addStretch();
    auto* color_card_btn = new QPushButton(QStringLiteral("色标"),
                                           joint_2d_panel_);
    color_card_btn->setCheckable(true);
    color_card_btn->setToolTip(
        QStringLiteral("选择地震/GR 色标并调整井轨迹宽度"));
    j2_header->addWidget(color_card_btn);
    auto* toggle_2d = new QPushButton(QStringLiteral("折叠"),
                                      joint_2d_panel_);
    toggle_2d->setCheckable(true);
    toggle_2d->setChecked(false);
    connect(toggle_2d, &QPushButton::clicked, this,
            [this, toggle_2d](bool checked) {
                joint_2d_host_->setVisible(!checked);
                toggle_2d->setText(checked ? QStringLiteral("展开")
                                           : QStringLiteral("折叠"));
            });
    j2_header->addWidget(toggle_2d);
    j2_layout->addLayout(j2_header);

    joint_color_card_ = new QFrame(joint_2d_panel_);
    joint_color_card_->setObjectName(
        QStringLiteral("JointColorScaleCard"));
    auto* color_layout = new QGridLayout(joint_color_card_);
    color_layout->setContentsMargins(8, 4, 8, 4);
    color_layout->setHorizontalSpacing(8);
    color_layout->setVerticalSpacing(4);
    color_layout->addWidget(new QLabel(QStringLiteral("地震振幅"),
                                       joint_color_card_),
                            0, 0);
    seismic_color_combo_ = new QComboBox(joint_color_card_);
    for (const auto& [label, id] :
         {std::pair{QStringLiteral("蓝—白—红"), QStringLiteral("blue-white-red")},
          std::pair{QStringLiteral("灰度"), QStringLiteral("gray")},
          std::pair{QStringLiteral("红—白—蓝"), QStringLiteral("red-white-blue")}}) {
        seismic_color_combo_->addItem(label, id);
    }
    color_layout->addWidget(seismic_color_combo_, 0, 1);
    color_layout->addWidget(new QLabel(QStringLiteral("GR 井轨迹"),
                                       joint_color_card_),
                            1, 0);
    gr_color_combo_ = new QComboBox(joint_color_card_);
    for (const QString& name :
         {QStringLiteral("viridis"), QStringLiteral("cividis"),
          QStringLiteral("plasma"), QStringLiteral("turbo")}) {
        gr_color_combo_->addItem(name, name);
    }
    color_layout->addWidget(gr_color_combo_, 1, 1);
    color_layout->addWidget(new QLabel(QStringLiteral("井轨迹宽度"),
                                       joint_color_card_),
                            0, 2);
    well_width_spin_ = new QSpinBox(joint_color_card_);
    well_width_spin_->setRange(2, 10);
    well_width_spin_->setValue(5);
    well_width_spin_->setSuffix(QStringLiteral(" px"));
    color_layout->addWidget(well_width_spin_, 0, 3);
    color_layout->setColumnStretch(1, 1);
    color_layout->setColumnStretch(3, 1);
    joint_color_card_->setVisible(false);
    connect(color_card_btn, &QAbstractButton::toggled, joint_color_card_,
            &QWidget::setVisible);
    connect(seismic_color_combo_, &QComboBox::currentIndexChanged, this,
            [this](int) { apply_display_settings(); });
    connect(gr_color_combo_, &QComboBox::currentIndexChanged, this,
            [this](int) { apply_display_settings(); });
    connect(well_width_spin_, &QSpinBox::valueChanged, this,
            [this](int) { apply_display_settings(); });
    j2_layout->addWidget(joint_color_card_);

    joint_2d_host_ = new QWidget(joint_2d_panel_);
    joint_2d_host_->setObjectName(QStringLiteral("Joint2DHost"));
    auto* j2_host_layout = new QVBoxLayout(joint_2d_host_);
    j2_host_layout->setContentsMargins(0, 0, 0, 0);
    joint_2d_placeholder_ = new QLabel(
        QStringLiteral(
            "无活动剖面。加载后在左侧 Time 平面或 3D Time 面上点击井点连线；"
            "也可用顶栏井对 +「井间剖面」。Esc 撤销最后一口井。"),
        joint_2d_host_);
    joint_2d_placeholder_->setAlignment(Qt::AlignCenter);
    joint_2d_placeholder_->setWordWrap(true);
    joint_2d_placeholder_->setObjectName(
        QStringLiteral("Joint2DEmptyHint"));
    j2_host_layout->addWidget(joint_2d_placeholder_);
    j2_layout->addWidget(joint_2d_host_, 1);
    center_v_split->addWidget(joint_2d_panel_);
    center_v_split->setStretchFactor(0, 3);
    center_v_split->setStretchFactor(1, 1);
    center_v_split->setSizes({700, 220});

    center_layout->addWidget(center_v_split);
    splitter->addWidget(center_column);
    splitter->setStretchFactor(0, 0);
    splitter->setStretchFactor(1, 1);
    splitter->setSizes({320, 980});
    main_layout->addWidget(splitter);

    status_ = new QLabel(QString(), view_container);
    status_->setWordWrap(true);
    status_->setObjectName(QStringLiteral("JointStatusRow"));
    // Status row lives inside the view container (Python view_layout).
    view_layout->addWidget(status_);

    if (joint_widget_ != nullptr) {
        view_layout->addWidget(joint_widget_, 1);
    } else {
        const std::string error =
            host_ != nullptr ? host_->engine_error() : "unknown";
        auto* placeholder = new QLabel(
            QStringLiteral("联合三维引擎不可用: %1")
                .arg(qs(error.empty() ? "unknown" : error)),
            view_container);
        placeholder->setAlignment(Qt::AlignCenter);
        placeholder->setWordWrap(true);
        view_layout->addWidget(placeholder, 1);
    }

    if (host_ != nullptr) {
        connect(host_, &JointHostController::status_changed, this,
                [this](const QString& text) { status_->setText(text); });
        connect(host_, &JointHostController::scene_updated, this,
                &GeologicalModeling3DPage::on_scene_updated);
        connect(host_, &JointHostController::well_picked, this,
                [this](const QString& name) { emit well_selected(name); });
    }
    sync_analysis_actions();
}

void GeologicalModeling3DPage::set_project(
    const ProjectSlice* project,
    const std::optional<JointAnalysisSlice>& joint_state) {
    project_ = project;
    joint_state_ = joint_state;
    joint_well_visibility_restored_ = false;
}

void GeologicalModeling3DPage::set_project_path(const QString& path) {
    project_path_ = path;
}

bool GeologicalModeling3DPage::shutdown_workers(int wait_ms) {
    return host_ == nullptr || host_->shutdown(wait_ms);
}

void GeologicalModeling3DPage::activate_page() {
    ensure_joint_data_loaded();
}

void GeologicalModeling3DPage::showEvent(QShowEvent* event) {
    QWidget::showEvent(event);
    ensure_joint_data_loaded();
}

void GeologicalModeling3DPage::closeEvent(QCloseEvent* event) {
    shutdown_workers();
    event->accept();
}

void GeologicalModeling3DPage::ensure_joint_data_loaded() {
    if (loaded_once_) {
        return;
    }
    loaded_once_ = true;
    // Apply tree checks first; domain via preferred_domain so reload does
    // not force Time (code-review Spec fix parity).
    apply_joint_tree_checks_from_project();
    QString domain = QStringLiteral("Time");
    if (joint_state_.has_value() &&
        !joint_state_->vertical_domain.empty()) {
        domain = qs(joint_state_->vertical_domain);
    }
    const auto snap =
        host_ != nullptr ? host_->scene_snapshot() : JointSceneSnapshot{};
    if (snap.has_scene && domain.startsWith(QStringLiteral("depth"),
                                            Qt::CaseInsensitive) &&
        !snap.depth_available) {
        // Saved Depth is unrealizable without a transform.
        domain = QStringLiteral("Time");
    }
    {
        domain_combo_->blockSignals(true);
        const int idx = domain_combo_->findText(domain);
        if (idx >= 0) {
            domain_combo_->setCurrentIndex(idx);
        }
        domain_combo_->blockSignals(false);
    }
    update_domain_combo_availability();
    restore_joint_slice_settings();
    if (host_ != nullptr) {
        host_->reload();
    }
    if (joint_state_.has_value()) {
        restore_fence(*joint_state_);
    }
    update_domain_z_guard(domain);
    // Re-sync the combo from the scene so UI and scene cannot diverge.
    const auto after =
        host_ != nullptr ? host_->scene_snapshot() : JointSceneSnapshot{};
    if (after.has_scene) {
        const QString actual = after.depth_domain
                                   ? QStringLiteral("Depth")
                                   : QStringLiteral("Time");
        if (domain_combo_->currentText() != actual) {
            domain_combo_->blockSignals(true);
            const int idx = domain_combo_->findText(actual);
            if (idx >= 0) {
                domain_combo_->setCurrentIndex(idx);
            }
            domain_combo_->blockSignals(false);
        }
        update_domain_combo_availability();
    }
}

// -- model tree --------------------------------------------------------

void GeologicalModeling3DPage::populate_model_tree() {
    model_tree_->clear();
    joint_root_ = new QTreeWidgetItem(
        model_tree_, {QString::fromUtf8(kJointRoot)});
    add_checkable_child(joint_root_,
                        QStringLiteral("地震预览体 (geoviz)"));
    joint_wells_item_ =
        add_checkable_child(joint_root_, QString::fromUtf8(kJointWells));
    add_checkable_child(joint_root_,
                        QStringLiteral("井间剖面 fence (geoviz)"));
    stratal_item_ = add_checkable_child(
        joint_root_, QStringLiteral("地层切片体 (geoviz)"));
    add_checkable_child(joint_root_, QStringLiteral("井震 3D 视口"));
    add_checkable_child(joint_root_, QStringLiteral("井震 2D 剖面条"));

    geo3d_root_ = new QTreeWidgetItem(
        model_tree_, {QStringLiteral("工作区对象 (geo3d)")});
    geo3d_root_->setFlags(geo3d_root_->flags() | Qt::ItemIsUserCheckable |
                          Qt::ItemIsEnabled);
    geo3d_root_->setCheckState(0, Qt::Checked);
    if (geo3d_ != nullptr) {
        geo3d_->rebuild_tree(geo3d_root_);
    }
    model_tree_->expandAll();
    connect(model_tree_, &QTreeWidget::itemChanged, this,
            &GeologicalModeling3DPage::on_tree_item_changed);
}

QTreeWidgetItem* GeologicalModeling3DPage::add_checkable_child(
    QTreeWidgetItem* parent, const QString& name) {
    auto* item = new QTreeWidgetItem(parent, {name});
    item->setFlags(item->flags() | Qt::ItemIsUserCheckable |
                   Qt::ItemIsEnabled);
    item->setCheckState(0, Qt::Checked);
    return item;
}

void GeologicalModeling3DPage::refresh_joint_well_tree() {
    if (joint_wells_item_ == nullptr || host_ == nullptr) {
        return;
    }
    const auto snap = host_->scene_snapshot();
    if (!snap.has_scene) {
        return;
    }
    auto presentations = snap.well_presentations;
    if (!presentations.empty() && !joint_well_visibility_restored_ &&
        joint_state_.has_value()) {
        // First restore wins: saved visibility, else the legacy
        // "联合井轨迹 (geoviz)" check migrates all wells off.
        const auto& saved = joint_state_->well_visibility;
        bool any_saved = false;
        for (const auto& p : presentations) {
            const auto it = saved.find(p.id);
            if (it != saved.end()) {
                host_->set_well_visibility(p.id, it->second);
                any_saved = true;
            }
        }
        if (!any_saved) {
            const auto it =
                joint_state_->tree_checks.find(kJointWells);
            if (it != joint_state_->tree_checks.end() && !it->second) {
                for (const auto& p : presentations) {
                    host_->set_well_visibility(p.id, false);
                }
            }
        }
        joint_well_visibility_restored_ = true;
        presentations = host_->scene_snapshot().well_presentations;
    }
    model_tree_->blockSignals(true);
    joint_wells_item_->takeChildren();
    int checked = 0;
    for (const auto& p : presentations) {
        auto* item =
            add_checkable_child(joint_wells_item_, qs(p.display_name));
        item->setData(0, Qt::UserRole, qs(p.id));
        item->setCheckState(0, p.visible ? Qt::Checked : Qt::Unchecked);
        checked += p.visible ? 1 : 0;
    }
    if (!presentations.empty()) {
        const Qt::CheckState parent_state =
            checked == static_cast<int>(presentations.size())
                ? Qt::Checked
            : checked == 0 ? Qt::Unchecked
                           : Qt::PartiallyChecked;
        joint_wells_item_->setCheckState(0, parent_state);
    }
    model_tree_->blockSignals(false);
    joint_wells_item_->setExpanded(true);
}

void GeologicalModeling3DPage::on_tree_item_changed(
    QTreeWidgetItem* item, int column) {
    if (suppress_tree_signals_ || column != 0 || item == nullptr) {
        return;
    }
    // Parent 联合井轨迹 toggles every well child; a well child writes back
    // its own visibility and refreshes the parent's partial state.
    if (item == joint_wells_item_) {
        const bool checked = item->checkState(0) == Qt::Checked;
        suppress_tree_signals_ = true;
        for (int i = 0; i < item->childCount(); ++i) {
            item->child(i)->setCheckState(
                0, checked ? Qt::Checked : Qt::Unchecked);
        }
        suppress_tree_signals_ = false;
        if (host_ != nullptr) {
            for (int i = 0; i < item->childCount(); ++i) {
                host_->set_well_visibility(
                    item->child(i)
                        ->data(0, Qt::UserRole)
                        .toString()
                        .toStdString(),
                    checked);
            }
        }
        return;
    }
    if (is_tree_descendant(item, joint_wells_item_) && host_ != nullptr) {
        host_->set_well_visibility(
            item->data(0, Qt::UserRole).toString().toStdString(),
            item->checkState(0) == Qt::Checked);
        // Refresh the parent's partial state.
        int checked = 0;
        const int total = joint_wells_item_->childCount();
        for (int i = 0; i < total; ++i) {
            checked += joint_wells_item_->child(i)->checkState(0) ==
                               Qt::Checked
                           ? 1
                           : 0;
        }
        suppress_tree_signals_ = true;
        joint_wells_item_->setCheckState(
            0,
            checked == total
                ? Qt::Checked
                : checked == 0 ? Qt::Unchecked : Qt::PartiallyChecked);
        suppress_tree_signals_ = false;
        return;
    }
    // Other geoviz layer checks -> host layer visibility; geo3d children
    // -> controller.
    if (is_tree_descendant(item, joint_root_) && host_ != nullptr) {
        host_->set_layer_visibility(
            item->text(0).toStdString(),
            item->checkState(0) == Qt::Checked);
    } else if (is_tree_descendant(item, geo3d_root_) &&
               geo3d_ != nullptr) {
        geo3d_->set_tree_visibility(
            item->text(0), item->checkState(0) == Qt::Checked);
    }
}

bool GeologicalModeling3DPage::is_tree_descendant(
    QTreeWidgetItem* item, QTreeWidgetItem* ancestor) const {
    if (item == nullptr || ancestor == nullptr) {
        return false;
    }
    for (QTreeWidgetItem* p = item->parent(); p != nullptr;
         p = p->parent()) {
        if (p == ancestor) {
            return true;
        }
    }
    return false;
}

void GeologicalModeling3DPage::sync_joint_visibility_from_tree() {
    // Push the whole tree's check state into the host (post-reload sync).
    if (host_ == nullptr || joint_root_ == nullptr) {
        return;
    }
    suppress_tree_signals_ = true;
    for (int i = 0; i < joint_root_->childCount(); ++i) {
        QTreeWidgetItem* child = joint_root_->child(i);
        if (child == joint_wells_item_) {
            continue;  // per-well children handle this group
        }
        host_->set_layer_visibility(
            child->text(0).toStdString(),
            child->checkState(0) == Qt::Checked);
    }
    for (int i = 0; i < joint_wells_item_->childCount(); ++i) {
        QTreeWidgetItem* child = joint_wells_item_->child(i);
        host_->set_well_visibility(
            child->data(0, Qt::UserRole).toString().toStdString(),
            child->checkState(0) == Qt::Checked);
    }
    suppress_tree_signals_ = false;
}

// -- joint scene sync ---------------------------------------------------

void GeologicalModeling3DPage::on_scene_updated() {
    if (host_ == nullptr) {
        return;
    }
    const auto snap = host_->scene_snapshot();
    if (!snap.has_scene) {
        // Engine unavailable: nothing to sync; widgets keep their
        // placeholder states instead of crashing the flush path.
        return;
    }
    apply_pending_slice_numbers();
    apply_display_settings();
    if (joint_widget_ != nullptr) {
        host_->push_scene_to_widget();
    }
    refresh_joint_well_tree();
    fill_joint_well_combos();
    if (geo3d_ != nullptr) {
        geo3d_->sync_scene();
    }
    sync_joint_visibility_from_tree();
    refresh_joint_slice_card();
    if (!snap.slice_state_warning.empty() &&
        !status_->text().contains(qs(snap.slice_state_warning))) {
        const QString combined =
            (status_->text() + QStringLiteral(" · ") +
             qs(snap.slice_state_warning))
                .trimmed();
        status_->setText(combined.startsWith(QStringLiteral("·"))
                             ? combined.mid(1).trimmed()
                             : combined);
    }
    sync_2d_time_chip();
}

void GeologicalModeling3DPage::fill_joint_well_combos() {
    QString prev_a = well_a_->currentData().isValid()
                         ? well_a_->currentData().toString()
                         : well_a_->currentText();
    QString prev_b = well_b_->currentData().isValid()
                         ? well_b_->currentData().toString()
                         : well_b_->currentText();
    // Prefer the project-saved pair over "first two wells" (Python
    // parity: active_fence_wells seed the selectors).
    if (joint_state_.has_value() &&
        joint_state_->active_fence_wells.size() >= 2) {
        prev_a = qs(joint_state_->active_fence_wells[0]);
        prev_b = qs(joint_state_->active_fence_wells[1]);
    }
    rebuild_joint_well_combos(prev_a, prev_b);
}

void GeologicalModeling3DPage::rebuild_joint_well_combos(
    const QString& preferred_a, const QString& preferred_b) {
    const auto options =
        host_ != nullptr
            ? host_->well_options()
            : std::vector<std::pair<std::string, std::string>>{};
    well_a_->blockSignals(true);
    well_b_->blockSignals(true);
    well_a_->clear();
    well_b_->clear();
    for (const auto& [id, display] : options) {
        well_a_->addItem(qs(display), qs(id));
        well_b_->addItem(qs(display), qs(id));
    }
    const int ia =
        preferred_a.isEmpty() ? -1 : well_a_->findData(preferred_a);
    const int ib =
        preferred_b.isEmpty() ? -1 : well_b_->findData(preferred_b);
    if (ia >= 0) {
        well_a_->setCurrentIndex(ia);
    }
    if (ib >= 0) {
        well_b_->setCurrentIndex(ib);
    } else if (options.size() >= 2) {
        well_b_->setCurrentIndex(1);
    }
    well_a_->blockSignals(false);
    well_b_->blockSignals(false);
}

void GeologicalModeling3DPage::on_joint_domain_changed(
    const QString& text) {
    // One authoritative display domain: 3D scene AND 2D profile follow.
    bool applied = false;
    if (host_ != nullptr) {
        applied = host_->set_vertical_domain(text.toStdString());
    }
    if (!applied) {
        // Depth refused (no transform): revert to the scene's actual
        // domain instead of showing a fake state.
        const auto snap = host_ != nullptr
                              ? host_->scene_snapshot()
                              : JointSceneSnapshot{};
        const QString actual = is_depth_domain(snap)
                                   ? QStringLiteral("Depth")
                                   : QStringLiteral("Time");
        domain_combo_->blockSignals(true);
        const int idx = domain_combo_->findText(actual);
        if (idx >= 0) {
            domain_combo_->setCurrentIndex(idx);
        }
        domain_combo_->blockSignals(false);
    }
    update_domain_z_guard(applied ? text : QStringLiteral("Time"));
    sync_2d_time_chip();
    refresh_joint_slice_card();
}

void GeologicalModeling3DPage::update_domain_combo_availability() {
    const auto snap =
        host_ != nullptr ? host_->scene_snapshot() : JointSceneSnapshot{};
    const bool depth_ok = snap.has_scene && snap.depth_available;
    const int idx = domain_combo_->findText(QStringLiteral("Depth"));
    if (idx < 0) {
        return;
    }
    if (auto* item =
            qobject_cast<QStandardItemModel*>(domain_combo_->model())) {
        if (auto* entry = item->item(idx)) {
            entry->setEnabled(depth_ok);
        }
    }
    domain_combo_->setToolTip(
        depth_ok
            ? QStringLiteral(
                  "切换竖直显示域（Time/Depth 同域应用于 2D 与 3D）")
            : QStringLiteral(
                  "Depth 不可用：缺少时深转换（速度模型/checkshot/深度域数据体）"));
}

void GeologicalModeling3DPage::update_domain_z_guard(
    const QString& domain) {
    // Warn / soft-hide model volume when joint domain is Time (#97).
    const bool is_time =
        !domain.toLower().startsWith(QStringLiteral("depth"));
    const QString note =
        is_time ? QStringLiteral(
                      "竖直域=Time：已弱化深度网格体（Z 语义可能不一致）")
                : QString();
    QString msg = status_->text();
    if (!domain_guard_note_.isEmpty() && msg.contains(domain_guard_note_)) {
        msg = msg.remove(domain_guard_note_).trimmed();
        while (msg.startsWith(QStringLiteral("·"))) {
            msg = msg.mid(1).trimmed();
        }
        while (msg.endsWith(QStringLiteral("·"))) {
            msg.chop(1);
            msg = msg.trimmed();
        }
    }
    if (!note.isEmpty()) {
        msg = msg.isEmpty() ? note : msg + QStringLiteral(" · ") + note;
    }
    status_->setText(msg);
    domain_guard_note_ = note;
}

void GeologicalModeling3DPage::refresh_joint_slice_card() {
    const auto snap =
        host_ != nullptr ? host_->scene_snapshot() : JointSceneSnapshot{};
    if (!snap.has_scene) {
        return;
    }
    const bool ready = snap.n_inline > 0 || snap.n_crossline > 0;
    const bool time_domain = !snap.depth_domain;
    for (QWidget* control :
         {static_cast<QWidget*>(inline_slice_),
          static_cast<QWidget*>(crossline_slice_),
          static_cast<QWidget*>(time_selector_),
          static_cast<QWidget*>(active_time_editor_),
          static_cast<QWidget*>(active_time_visible_),
          static_cast<QWidget*>(new_time_),
          static_cast<QWidget*>(time_opacity_)}) {
        control->setEnabled(ready);
    }
    time_selector_->setEnabled(ready && time_domain);
    active_time_editor_->setEnabled(ready && time_domain);
    active_time_visible_->setEnabled(ready && time_domain);
    new_time_->setEnabled(ready && time_domain);
    time_opacity_->setEnabled(ready && time_domain);
    time_domain_note_->setText(
        time_domain ? QString() : QStringLiteral("Depth 域下隐藏 Time"));
    if (!ready) {
        return;
    }
    inline_slice_->blockSignals(true);
    inline_slice_->setRange(0, snap.n_inline > 0 ? snap.n_inline - 1 : 0);
    if (snap.inline_index.has_value()) {
        inline_slice_->setValue(*snap.inline_index);
    }
    inline_slice_->blockSignals(false);
    crossline_slice_->blockSignals(true);
    crossline_slice_->setRange(
        0, snap.n_crossline > 0 ? snap.n_crossline - 1 : 0);
    if (snap.crossline_index.has_value()) {
        crossline_slice_->setValue(*snap.crossline_index);
    }
    crossline_slice_->blockSignals(false);

    time_selector_->blockSignals(true);
    const QString active_key =
        snap.active_time_ms.has_value()
            ? QString::number(*snap.active_time_ms)
            : QString();
    time_selector_->clear();
    int active_row = -1;
    for (std::size_t i = 0; i < snap.time_slices.size(); ++i) {
        const auto& slice = snap.time_slices[i];
        const QString label =
            QStringLiteral("%1 ms%2")
                .arg(slice.time_ms)
                .arg(slice.visible ? QString()
                                   : QStringLiteral(" (隐藏)"));
        time_selector_->addItem(label, slice.time_ms);
        if (snap.active_time_ms.has_value() &&
            slice.time_ms == *snap.active_time_ms) {
            active_row = static_cast<int>(i);
        }
    }
    if (active_row >= 0) {
        time_selector_->setCurrentIndex(active_row);
    }
    time_selector_->blockSignals(false);
    active_time_editor_->blockSignals(true);
    active_time_editor_->setRange(snap.time_min_ms, snap.time_max_ms);
    if (snap.active_time_ms.has_value()) {
        active_time_editor_->setValue(*snap.active_time_ms);
    }
    active_time_editor_->blockSignals(false);
    new_time_->setRange(snap.time_min_ms, snap.time_max_ms);
    active_time_visible_->blockSignals(true);
    if (active_row >= 0) {
        active_time_visible_->setChecked(
            snap.time_slices[static_cast<std::size_t>(active_row)]
                .visible);
    }
    active_time_visible_->blockSignals(false);
    time_opacity_->blockSignals(true);
    time_opacity_->setValue(static_cast<int>(snap.time_opacity * 100.0));
    time_opacity_->blockSignals(false);
}

void GeologicalModeling3DPage::apply_display_settings() {
    if (host_ == nullptr) {
        return;
    }
    host_->set_color_scales(
        seismic_color_combo_->currentData().isValid()
            ? seismic_color_combo_->currentData().toString().toStdString()
            : "blue-white-red",
        gr_color_combo_->currentData().isValid()
            ? gr_color_combo_->currentData().toString().toStdString()
            : "viridis");
    host_->set_well_width(well_width_spin_->value());
}

void GeologicalModeling3DPage::apply_joint_tree_checks_from_project() {
    if (!joint_state_.has_value() || joint_state_->tree_checks.empty()) {
        return;
    }
    apply_tree_checks(joint_state_->tree_checks);
    sync_joint_visibility_from_tree();
}

void GeologicalModeling3DPage::apply_tree_checks(
    const std::map<std::string, bool>& checks) {
    // Restore known geoviz check keys only; unknown keys are ignored.
    model_tree_->blockSignals(true);
    for (int i = 0; i < joint_root_->childCount(); ++i) {
        QTreeWidgetItem* child = joint_root_->child(i);
        const auto it = checks.find(child->text(0).toStdString());
        if (it != checks.end()) {
            child->setCheckState(
                0, it->second ? Qt::Checked : Qt::Unchecked);
        }
    }
    model_tree_->blockSignals(false);
}

void GeologicalModeling3DPage::restore_fence(
    const JointAnalysisSlice& state) {
    if (host_ == nullptr || state.active_fence_wells.size() < 2) {
        return;
    }
    const std::string name =
        state.active_fence_name.value_or("Wells");
    host_->add_well_to_well_fence(state.active_fence_wells[0],
                                  state.active_fence_wells[1], name);
    rebuild_joint_well_combos(qs(state.active_fence_wells[0]),
                              qs(state.active_fence_wells[1]));
}

void GeologicalModeling3DPage::restore_joint_slice_settings() {
    if (!joint_state_.has_value() || host_ == nullptr) {
        return;
    }
    const JointAnalysisSlice& state = *joint_state_;
    pending_slice_numbers_.reset();
    if (state.orthogonal_inline_number.has_value() &&
        state.orthogonal_crossline_number.has_value()) {
        pending_slice_numbers_ = std::make_pair(
            *state.orthogonal_inline_number,
            *state.orthogonal_crossline_number);
    }
    std::vector<JointTimeSliceEntry> slices;
    slices.reserve(state.time_slices.size());
    for (const auto& item : state.time_slices) {
        slices.push_back({item.time_ms, item.visible});
    }
    if (host_->has_scene()) {
        // Joint engine failed to construct → skip instead of aborting
        // the binding flush (Python parity).
        host_->restore_orthogonal_slice_state(
            state.orthogonal_inline_index,
            state.orthogonal_crossline_index, slices,
            state.active_time_slice_ms,
            state.time_slice_opacity / 100.0);
        refresh_joint_slice_card();
    }
}

void GeologicalModeling3DPage::apply_pending_slice_numbers() {
    if (!pending_slice_numbers_.has_value() || host_ == nullptr) {
        return;
    }
    // Consumed exactly once the registration exists — the physical line
    // numbers are stable across sessions and LOD refinements.
    if (host_->apply_slice_line_numbers(pending_slice_numbers_->first,
                                        pending_slice_numbers_->second)) {
        pending_slice_numbers_.reset();
        refresh_joint_slice_card();
    }
}

void GeologicalModeling3DPage::sync_2d_time_chip() {
    const auto snap =
        host_ != nullptr ? host_->scene_snapshot() : JointSceneSnapshot{};
    const QString domain =
        snap.has_scene && snap.depth_domain ? QStringLiteral("Depth")
                                            : QStringLiteral("Time");
    time_chip_->setText(
        QStringLiteral("域: %1 · 2D/3D 联动").arg(domain));
}

// -- collect / save -----------------------------------------------------

JointAnalysisSlice
GeologicalModeling3DPage::collect_joint_analysis_state() const {
    JointAnalysisSlice state;
    // Tree checks (井震联合 children only).
    if (joint_root_ != nullptr) {
        for (int i = 0; i < joint_root_->childCount(); ++i) {
            QTreeWidgetItem* child = joint_root_->child(i);
            state.tree_checks[child->text(0).toStdString()] =
                child->checkState(0) == Qt::Checked;
        }
    }
    const auto snap =
        host_ != nullptr ? host_->scene_snapshot() : JointSceneSnapshot{};
    state.vertical_domain = snap.has_scene && snap.depth_domain
                                ? "Depth"
                                : "Time";
    // Active fence wells — scene fence ids else the toolbar pair.
    if (!snap.fence_well_ids.empty()) {
        state.active_fence_wells = snap.fence_well_ids;
    } else {
        const QString a = well_a_->currentData().isValid()
                              ? well_a_->currentData().toString()
                              : well_a_->currentText();
        const QString b = well_b_->currentData().isValid()
                              ? well_b_->currentData().toString()
                              : well_b_->currentText();
        if (!a.isEmpty() && !b.isEmpty()) {
            state.active_fence_wells = {a.toStdString(),
                                        b.toStdString()};
        }
    }
    // Active fence name.
    if (!snap.fences.empty()) {
        for (const auto& [id, name] : snap.fences) {
            if (id == snap.active_fence_id) {
                state.active_fence_name =
                    name.empty() ? id : name;
                break;
            }
        }
        if (!state.active_fence_name.has_value()) {
            state.active_fence_name = snap.fences.front().second;
        }
    }
    if (host_ != nullptr) {
        state.path_hints = host_->path_hints();
        state.well_identity_asset_id = host_->well_identity_asset_id();
        state.well_identity_map = host_->well_identity_map();
    }
    for (const auto& p : snap.well_presentations) {
        state.well_visibility[p.id] = p.visible;
    }
    state.seismic_color_scale =
        seismic_color_combo_->currentData().isValid()
            ? seismic_color_combo_->currentData()
                  .toString()
                  .toStdString()
            : "blue-white-red";
    state.gr_color_scale =
        gr_color_combo_->currentData().isValid()
            ? gr_color_combo_->currentData().toString().toStdString()
            : "viridis";
    state.well_width_px = well_width_spin_->value();
    state.orthogonal_inline_index = snap.inline_index;
    state.orthogonal_crossline_index = snap.crossline_index;
    state.orthogonal_inline_number = snap.inline_number;
    state.orthogonal_crossline_number = snap.crossline_number;
    for (const auto& item : snap.time_slices) {
        state.time_slices.push_back({item.time_ms, item.visible});
    }
    state.active_time_slice_ms = snap.active_time_ms;
    state.time_slice_opacity =
        static_cast<int>(snap.time_opacity * 100.0 + 0.5);
    return state;
}

void GeologicalModeling3DPage::save_joint_analysis_to_project() {
    if (project_ == nullptr || !hooks_.save_state) {
        return;
    }
    joint_state_ = collect_joint_analysis_state();
    hooks_.save_state(*joint_state_);
    // geo3d workspace state persists alongside (best-effort like Python).
    if (geo3d_ != nullptr) {
        try {
            geo3d_->save_state();
        } catch (...) {
            // best-effort — save failures must not break the flow
        }
    }
}

bool GeologicalModeling3DPage::highlight_well(
    const std::string& well_name) {
    return host_ != nullptr && host_->highlight_well(well_name);
}

bool GeologicalModeling3DPage::focus_seismic_position(
    int il, int xl, std::optional<double> twt) {
    return host_ != nullptr && host_->focus_position(il, xl, twt);
}

QTreeWidget* GeologicalModeling3DPage::model_tree() const {
    return model_tree_;
}

QString GeologicalModeling3DPage::status_text() const {
    return status_->text();
}

// -- analysis tabs --------------------------------------------------------

QWidget* GeologicalModeling3DPage::build_stratal_tab() {
    auto* tab = new QWidget(analysis_tabs_);
    auto* form = new QGridLayout(tab);
    form->setContentsMargins(8, 4, 8, 4);
    form->setHorizontalSpacing(8);
    form->setVerticalSpacing(4);

    auto* hint = new QLabel(
        QStringLiteral(
            "在两个 horizon 之间生成比例地层切片，沿地层格架揭示沉积相。"
            "无 SEGY 时可用合成演示体预览。"),
        tab);
    hint->setWordWrap(true);
    form->addWidget(hint, 0, 0, 1, 3);

    form->addWidget(new QLabel(QStringLiteral("顶部 horizon"), tab), 1, 0);
    stratal_top_combo_ = new QComboBox(tab);
    stratal_top_combo_->setObjectName(QStringLiteral("StratalTopCombo"));
    stratal_top_combo_->addItem(QStringLiteral("（未选择）"), QString());
    form->addWidget(stratal_top_combo_, 1, 1);
    auto* top_browse = new QPushButton(QStringLiteral("浏览…"), tab);
    connect(top_browse, &QPushButton::clicked, this, [this] {
        const QString path =
            hooks_.pick_horizon_file
                ? hooks_.pick_horizon_file(
                      QStringLiteral("顶部 horizon"))
                : QFileDialog::getOpenFileName(
                      this, QStringLiteral("顶部 horizon"), QString(),
                      QStringLiteral("Horizon (*.dat);;All files (*)"));
        if (!path.isEmpty()) {
            stratal_top_combo_->clear();
            stratal_top_combo_->addItem(path, path);
        }
    });
    form->addWidget(top_browse, 1, 2);

    form->addWidget(new QLabel(QStringLiteral("底部 horizon"), tab), 2, 0);
    stratal_bot_combo_ = new QComboBox(tab);
    stratal_bot_combo_->setObjectName(QStringLiteral("StratalBotCombo"));
    stratal_bot_combo_->addItem(QStringLiteral("（未选择）"), QString());
    form->addWidget(stratal_bot_combo_, 2, 1);
    auto* bot_browse = new QPushButton(QStringLiteral("浏览…"), tab);
    connect(bot_browse, &QPushButton::clicked, this, [this] {
        const QString path =
            hooks_.pick_horizon_file
                ? hooks_.pick_horizon_file(
                      QStringLiteral("底部 horizon"))
                : QFileDialog::getOpenFileName(
                      this, QStringLiteral("底部 horizon"), QString(),
                      QStringLiteral("Horizon (*.dat);;All files (*)"));
        if (!path.isEmpty()) {
            stratal_bot_combo_->clear();
            stratal_bot_combo_->addItem(path, path);
        }
    });
    form->addWidget(bot_browse, 2, 2);

    form->addWidget(new QLabel(QStringLiteral("比例切片"), tab), 3, 0);
    stratal_fractions_ = new QComboBox(tab);
    stratal_fractions_->setObjectName(QStringLiteral("StratalFractions"));
    stratal_fractions_->addItem(QStringLiteral("1/4, 1/2, 3/4"),
                                QStringLiteral("0.25,0.5,0.75"));
    stratal_fractions_->addItem(QStringLiteral("1/3, 2/3"),
                                QStringLiteral("0.3333333,0.6666667"));
    stratal_fractions_->addItem(QStringLiteral("仅 1/2"),
                                QStringLiteral("0.5"));
    stratal_fractions_->addItem(QStringLiteral("顶 + 底"),
                                QStringLiteral("0.0,1.0"));
    form->addWidget(stratal_fractions_, 3, 1, 1, 2);

    stratal_demo_check_ =
        new QCheckBox(QStringLiteral("用合成演示体（无 SEGY 时预览）"),
                      tab);
    stratal_demo_check_->setChecked(false);
    stratal_demo_check_->setObjectName(QStringLiteral("StratalDemoCheck"));
    form->addWidget(stratal_demo_check_, 4, 0, 1, 3);

    auto* btn_row = new QHBoxLayout();
    stratal_generate_btn_ =
        new QPushButton(QStringLiteral("生成地层切片"), tab);
    stratal_generate_btn_->setObjectName(
        QStringLiteral("StratalGenerateBtn"));
    stratal_generate_btn_->setToolTip(QStringLiteral(
        "在两个 horizon 之间按比例生成地层切片并叠加到 3D 视口"));
    connect(stratal_generate_btn_, &QPushButton::clicked, this, [this] {
        if (!hooks_.generate_stratal) {
            stratal_status_->setText(
                QStringLiteral("地层切片功能未接入"));
            return;
        }
        std::vector<double> fractions;
        for (const QString& part :
             stratal_fractions_->currentData()
                 .toString()
                 .split(QLatin1Char(','))) {
            fractions.push_back(part.toDouble());
        }
        stratal_status_->setText(
            QStringLiteral("正在生成地层切片…"));
        hooks_.generate_stratal(
            stratal_top_combo_->currentData().toString().toStdString(),
            stratal_bot_combo_->currentData().toString().toStdString(),
            fractions, stratal_demo_check_->isChecked());
    });
    btn_row->addWidget(stratal_generate_btn_);
    stratal_clear_btn_ = new QPushButton(QStringLiteral("清除"), tab);
    stratal_clear_btn_->setObjectName(QStringLiteral("StratalClearBtn"));
    connect(stratal_clear_btn_, &QPushButton::clicked, this, [this] {
        if (hooks_.clear_stratal) {
            hooks_.clear_stratal();
        }
        stratal_status_->setText(QStringLiteral("尚未生成地层切片"));
    });
    btn_row->addWidget(stratal_clear_btn_);
    form->addLayout(btn_row, 5, 0, 1, 3);

    stratal_status_ =
        new QLabel(QStringLiteral("尚未生成地层切片"), tab);
    stratal_status_->setWordWrap(true);
    form->addWidget(stratal_status_, 6, 0, 1, 3);
    form->addWidget(new QLabel(QString(), tab), 7, 0);
    form->setRowStretch(7, 1);
    return tab;
}

QWidget* GeologicalModeling3DPage::build_welltie_tab() {
    auto* tab = new QWidget(analysis_tabs_);
    auto* layout = new QVBoxLayout(tab);
    layout->setContentsMargins(8, 4, 8, 4);
    auto* hint = new QLabel(
        QStringLiteral(
            "井震标定：Ricker 合成记录、互相关自动对齐（Auto-Tie）、时深偏移。"),
        tab);
    hint->setWordWrap(true);
    layout->addWidget(hint);
    auto* row = new QHBoxLayout();
    layout->addLayout(row);
    wtie_freq_ = new QSlider(Qt::Horizontal, tab);
    wtie_freq_->setRange(10, 80);
    wtie_freq_->setValue(30);
    connect(wtie_freq_, &QSlider::valueChanged, this, [this](int v) {
        if (hooks_.tie_params_changed) {
            hooks_.tie_params_changed(v, wtie_shift_->value());
        }
    });
    row->addWidget(new QLabel(QStringLiteral("子波频率"), tab));
    row->addWidget(wtie_freq_);
    wtie_shift_ = new QSlider(Qt::Horizontal, tab);
    wtie_shift_->setRange(-200, 200);
    wtie_shift_->setValue(0);
    connect(wtie_shift_, &QSlider::valueChanged, this, [this](int v) {
        if (hooks_.tie_params_changed) {
            hooks_.tie_params_changed(wtie_freq_->value(), v);
        }
    });
    auto* row2 = new QHBoxLayout();
    layout->addLayout(row2);
    row2->addWidget(new QLabel(QStringLiteral("时深偏移"), tab));
    row2->addWidget(wtie_shift_);
    auto* auto_tie = new QPushButton(
        QStringLiteral("自动互相关对齐 (Auto-Tie)"), tab);
    connect(auto_tie, &QPushButton::clicked, this, [this] {
        if (hooks_.run_auto_tie) {
            hooks_.run_auto_tie();
        } else {
            wtie_corr_label_->setText(
                QStringLiteral("井震标定功能未接入"));
        }
    });
    row2->addWidget(auto_tie);
    wtie_corr_label_ = new QLabel(QString(), tab);
    layout->addWidget(wtie_corr_label_);
    layout->addStretch(1);
    return tab;
}

QWidget* GeologicalModeling3DPage::build_facies_tab() {
    auto* tab = new QWidget(analysis_tabs_);
    auto* layout = new QVBoxLayout(tab);
    layout->setContentsMargins(8, 4, 8, 4);
    auto* hint = new QLabel(
        QStringLiteral(
            "沉积相解释：RGB 多属性混色、岩性交会图统计。"
            "（高级分析入口在「高级地震与井震综合分析」卡片中）"),
        tab);
    hint->setWordWrap(true);
    layout->addWidget(hint);
    auto* row = new QHBoxLayout();
    layout->addLayout(row);
    auto* rgb_btn =
        new QPushButton(QStringLiteral("RGB 多属性混色"), tab);
    rgb_btn->setToolTip(
        QStringLiteral("混合多地震属性以辅助沉积相边界识别"));
    connect(rgb_btn, &QPushButton::clicked, this, [this] {
        if (hooks_.run_rgb_fusion) {
            hooks_.run_rgb_fusion();
        }
    });
    row->addWidget(rgb_btn);
    auto* crossplot_btn =
        new QPushButton(QStringLiteral("岩性交会图"), tab);
    connect(crossplot_btn, &QPushButton::clicked, this, [this] {
        if (hooks_.run_crossplot) {
            hooks_.run_crossplot();
        }
    });
    row->addWidget(crossplot_btn);
    layout->addStretch(1);
    return tab;
}

QWidget* GeologicalModeling3DPage::build_export_diag_tab() {
    auto* tab = new QWidget(analysis_tabs_);
    auto* layout = new QVBoxLayout(tab);
    layout->setContentsMargins(8, 4, 8, 4);
    auto* hint = new QLabel(
        QStringLiteral(
            "导出与诊断：FLAC3D / Abaqus 数值模拟网格导出，一致性诊断顾问。"),
        tab);
    hint->setWordWrap(true);
    layout->addWidget(hint);
    auto* row = new QHBoxLayout();
    layout->addLayout(row);
    auto* export_btn =
        new QPushButton(QStringLiteral("导出数值模拟模型"), tab);
    connect(export_btn, &QPushButton::clicked, this, [this] {
        if (hooks_.run_export) {
            hooks_.run_export();
        }
    });
    row->addWidget(export_btn);
    auto* advisor_btn =
        new QPushButton(QStringLiteral("开启一致性诊断"), tab);
    connect(advisor_btn, &QPushButton::clicked, this, [this] {
        if (hooks_.run_advisor) {
            hooks_.run_advisor();
        }
    });
    layout->addLayout(row);
    auto* advisor_row = new QHBoxLayout();
    advisor_row->addWidget(advisor_btn);
    layout->addLayout(advisor_row);
    layout->addStretch(1);
    return tab;
}

void GeologicalModeling3DPage::sync_analysis_actions() {
    // _sync_analysis_actions parity: generation needs a scene or the
    // explicit demo checkbox; advisors stay off until data loads.
    const bool has_scene = host_ != nullptr && host_->has_scene();
    if (stratal_generate_btn_ != nullptr) {
        stratal_generate_btn_->setEnabled(has_scene);
    }
    populate_stratal_interpretations();
}

void GeologicalModeling3DPage::populate_stratal_interpretations() {
    if (!hooks_.horizon_interpretations) {
        return;
    }
    const auto entries =
        hooks_.horizon_interpretations(project_path_);
    for (QComboBox* combo : {stratal_top_combo_, stratal_bot_combo_}) {
        if (combo == nullptr) {
            continue;
        }
        // Drop stale interpretation entries, keep file entries.
        for (int i = combo->count() - 1; i >= 0; --i) {
            if (combo->itemData(i).toString().startsWith(
                    QStringLiteral("interp:"))) {
                combo->removeItem(i);
            }
        }
        for (const auto& [label, artifact] : entries) {
            combo->addItem(qs(label), qs(artifact));
        }
    }
}

}  // namespace pwb::ui_wellseis::qt
