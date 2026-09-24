#include "ribbon_command_install.hpp"

// M4 ribbon command fill — the 58-id mapping table lives here. Real
// backends delegate to the existing implementations; no-backend entries
// register disabled with an honest reason (see the header).
//
// Lifetime contract: every callback/applicability captures the Ctx struct
// BY VALUE (long-lived window/shell/context/jobs pointers) — the Builder
// is stack-allocated during install() and must never be captured.

#include <functional>
#include <optional>
#include <string>
#include <utility>

#include <QCheckBox>
#include <QMessageBox>
#include <QPushButton>
#include <QTabWidget>
#include <QString>

#include "app_context.hpp"
#include "app_shell.hpp"
#include "comparison_view.hpp"
#include "data_lineage_panel.hpp"
#include "main_window.hpp"
#include "m5_validation_install.hpp"
#include "review_disposition_panel.hpp"
#include "validation_workspace_page.hpp"

#include <QFileDialog>
#include <QInputDialog>
#include <QTextStream>

#include "factor_method_config.hpp"
#include "factor_method_dialogs.hpp"
#include "workspace_compose.hpp"

#include <pwb/application/adapters/data_store.hpp>
#include <pwb/application/project_session.hpp>
#include <pwb/domain/json.hpp>
#include <pwb/ui_composite/composite_document.hpp>
#include <pwb/ui_map/mapping_page.hpp>
#include <pwb/ui_pages_data/qt/data_toolbar.hpp>
#include <pwb/ui_review/qt/qc_issue_table.hpp>
#include <pwb/ui_review/qt/review_export_page.hpp>
#include <pwb/ui_review/review_core.hpp>
#include <pwb/ui_shell/command_registry.hpp>
#include <pwb/ui_pages_data/asset_view.hpp>
#include <pwb/ui_pages_data/qt/data_workspace.hpp>
#include <pwb/ui_pages_data/qt/asset_selection_bus.hpp>
#include <pwb/ui_wellseis/qt/well_log_prediction_page.hpp>
#include <pwb/ui_workstation/workstation_frame.hpp>

#if defined(PWB_WITH_CLOSURE_MAPPING)
#include "closure_mapping_install.hpp"
#include <pwb/ui_pages_data/qt/preparation_page.hpp>
#endif
#if defined(PWB_WITH_CONV_30)
#include "job_center.hpp"
#endif

#if defined(PWB_WITH_CLOSURE_MAPPING)
#include "closure_mapping_document.hpp"
#include "closure_mapping_install.hpp"
// AUTOMOC scans #include lines textually (it does not evaluate #if) and
// would emit a moc for this Q_OBJECT header in builds where the guarded
// .cpp compiles empty — the macro-indirect include hides it from moc.
#define PWB_M5_LAYOUT_COMPOSE_PANEL_HPP "layout_compose_panel.hpp"
#include PWB_M5_LAYOUT_COMPOSE_PANEL_HPP
#include "m5_compose_install.hpp"
#include <pwb/ui_pages_mapedit/map_edit_scene.hpp>
#endif

namespace pwb::app::ribbon_commands {

namespace {

using ui_shell::CommandContext;
using ui_shell::CommandSpec;



// Long-lived host pointers — captured BY VALUE into every registry lambda.
struct Ctx {
    MainWindow* window = nullptr;
    AppShell* shell = nullptr;
    AppContext* context = nullptr;
    JobCenter* jobs = nullptr;
};

std::optional<std::string> needs_project(const Ctx& c) {
    if (c.context == nullptr || c.context->projectStore() == nullptr) {
        return std::string("需要先打开工程");
    }
    return std::nullopt;
}

// M5 widget/test surface lookups (lazily resolved at trigger/evaluate
// time — the install that creates these widgets runs after registration).
ComparisonView* find_compare_view(const Ctx& c) {
    auto* page = c.shell != nullptr ? c.shell->validation_page() : nullptr;
    return page != nullptr
               ? qobject_cast<ComparisonView*>(page->compare_view())
               : nullptr;
}

ReviewDispositionPanel* find_review_panel(const Ctx& c) {
    auto* page = c.shell != nullptr ? c.shell->validation_page() : nullptr;
    return page != nullptr
               ? qobject_cast<ReviewDispositionPanel*>(
                     page->review_panel())
               : nullptr;
}

QAction* find_validation_action(const Ctx& c, const char* name) {
    auto* page = c.shell != nullptr ? c.shell->validation_page() : nullptr;
    return page != nullptr
               ? page->findChild<QAction*>(QString::fromLatin1(name))
               : nullptr;
}

void focus_right_tab(const Ctx& c, QWidget* widget) {
    auto* page = c.shell != nullptr ? c.shell->validation_page() : nullptr;
    if (page == nullptr || widget == nullptr) return;
    if (auto* tabs =
            page->findChild<QTabWidget*>(QStringLiteral("ValidationRightTabs"));
        tabs != nullptr) {
        tabs->setCurrentWidget(widget);
    }
}

std::optional<std::string> needs_compare_data(const Ctx& c) {
    if (auto problem = needs_project(c); problem.has_value()) {
        return problem;
    }
    const auto counts = m5_validation::source_counts(c.context);
    if (counts.interpretations == 0 || counts.predictions == 0) {
        return std::string(
            "无对比数据：需要至少一个解释版本和一个预测成果");
    }
    return std::nullopt;
}

#if defined(PWB_WITH_CLOSURE_MAPPING)
// M5-2 surfaces (resolved lazily — the install that creates the panel
// runs after registration).
LayoutComposePanel* find_compose_panel(const Ctx& c) {
    return c.shell != nullptr ? c.shell->findChild<LayoutComposePanel*>()
                              : nullptr;
}

ui_pages_mapedit::MapEditScene* find_edit_scene(const Ctx& c) {
    if (c.window == nullptr) return nullptr;
    auto* bank = closure_mapping::document_bank(c.window);
    return bank != nullptr ? bank->edit_scene() : nullptr;
}

void enter_compose_mode(const Ctx& c) {
    c.shell->navigate_workspace(3);
    c.shell->set_compose_mode(true);
}
#endif  // CLOSURE_MAPPING

// M5-3 data 工作区 surfaces: the data workspace's selection bus is the
// SINGLE selection authority (the lineage panel and the commands read
// it, never a second copy).
pwb::ui_pages_data::qt::AssetSelectionBus* data_bus(const Ctx& c) {
    if (c.shell == nullptr || c.shell->data_workspace() == nullptr) {
        return nullptr;
    }
    return c.shell->data_workspace()->selection_bus();
}

std::optional<std::string> needs_selection(const Ctx& c) {
    if (auto problem = needs_project(c); problem.has_value()) {
        return problem;
    }
    const auto* bus = data_bus(c);
    if (bus == nullptr || !bus->current_asset().has_value()) {
        return std::string("先在资产表中选择资产");
    }
    return std::nullopt;
}

void focus_lineage_tab(const Ctx& c, int tab_index) {
    c.shell->navigate_workspace(0);
    if (auto* panel =
            c.shell->findChild<DataLineagePanel*>("DataLineagePanel");
        panel != nullptr) {
        panel->tabs()->setCurrentIndex(tab_index);
    }
}


bool running_tasks(const Ctx& c) {
#ifdef PWB_WITH_CONV_30
    return c.jobs != nullptr && c.jobs->task_count() > 0;
#else
    (void)c;
    return false;
#endif
}

void open_task_center(const Ctx& c) {
    auto* ws = c.shell != nullptr ? c.shell->workstation() : nullptr;
    if (ws != nullptr && ws->dock("tasks") != nullptr) {
        ws->set_dock_visible("tasks", true);
    }
}

void emit_stage_action(const Ctx& c, const QString& stage,
                       const QString& action) {
    if (c.shell != nullptr && c.shell->composite() != nullptr) {
        emit c.shell->composite()->stage_action_requested(stage, action);
    }
}

void trigger_governed(const Ctx& c, const QString& action_id) {
    if (c.window == nullptr) return;
    if (QAction* action = c.window->governedAction(action_id);
        action != nullptr) {
        action->trigger();
    }
}

using Applicability =
    std::function<std::optional<std::string>(const CommandContext&)>;

void register_real(ui_shell::CommandRegistry& registry,
                   std::vector<std::string>* ids, const std::string& id,
                   const QString& label, const QString& hint,
                   const QString& keywords, std::function<void()> callback,
                   Applicability applicability = nullptr,
                   std::vector<std::string> stages = {}) {
    CommandSpec spec;
    spec.id = id;
    spec.label = label.toStdString();
    spec.hint = hint.toStdString();
    spec.keywords = keywords.toStdString();
    spec.group = "工作区命令";
    spec.stages = std::move(stages);
    spec.requires_write = false;
    spec.callback = std::move(callback);
    spec.applicability = std::move(applicability);
    registry.register_command(spec);
    if (ids != nullptr) ids->push_back(id);
}

// Honest disabled entry — registered (discoverable, the palette/ribbon
// shows the reason) but never enabled until the named milestone lands.
void register_disabled(ui_shell::CommandRegistry& registry,
                       std::vector<std::string>* ids, const std::string& id,
                       const QString& label, const QString& hint,
                       const QString& keywords, const QString& reason) {
    CommandSpec spec;
    spec.id = id;
    spec.label = label.toStdString();
    spec.hint = hint.toStdString();
    spec.keywords = keywords.toStdString();
    spec.group = "工作区命令";
    spec.applicability = [reason](const CommandContext&)
        -> std::optional<std::string> { return reason.toStdString(); };
    registry.register_command(spec);
    if (ids != nullptr) ids->push_back(id);
}

// ---------------------------------------------------------------------------
// ws0 数据管理
// ---------------------------------------------------------------------------

void data_commands(ui_shell::CommandRegistry& registry,
                   std::vector<std::string>* ids, const Ctx& c) {
    auto toolbar_emit = [c](void (ui_pages_data::qt::DataToolbar::*signal)()) {
        return [c, signal]() {
            auto* toolbar =
                c.shell->findChild<ui_pages_data::qt::DataToolbar*>();
            if (toolbar == nullptr) {
                emit c.shell->status_message(
                    QStringLiteral("导入工具条未装配（数据装配切片未接入）"));
                return;
            }
            emit (toolbar->*signal)();
        };
    };
    register_real(registry, ids, "data.import", QStringLiteral("导入数据"),
                  QStringLiteral("导入文件并创建项目受管的不可变 RAW 副本"),
                  QStringLiteral("导入 import 数据 文件"),
                  toolbar_emit(&ui_pages_data::qt::DataToolbar::
                                   import_files_requested),
                  [c](const CommandContext&) { return needs_project(c); });
    register_real(registry, ids, "data.scan", QStringLiteral("扫描目录"),
                  QStringLiteral("扫描目录并登记可导入资产"),
                  QStringLiteral("扫描 scan 目录 导入"),
                  toolbar_emit(&ui_pages_data::qt::DataToolbar::
                                   import_folder_requested),
                  [c](const CommandContext&) { return needs_project(c); });
    register_real(registry, ids, "data.plan", QStringLiteral("导入计划"),
                  QStringLiteral("扫描/分类/查重 → 逐项确认 → 分块执行"),
                  QStringLiteral("计划 导入 plan ingest"),
                  toolbar_emit(&ui_pages_data::qt::DataToolbar::
                                   plan_import_requested),
                  [c](const CommandContext&) { return needs_project(c); });
    // M5-3: link_well/set_role 保持禁用（原因改准确）——生产侧无实体
    // 关联/角色写入后端（导航树仅只读展示 entity_asset_links）。
    register_disabled(registry, ids, "data.link_well",
                      QStringLiteral("关联到井"),
                      QStringLiteral("把数据版本关联到井对象"),
                      QStringLiteral("关联 link 井"),
                      QStringLiteral("能力未接入生产（实体关联当前仅导航树只读展示）"));
    register_disabled(registry, ids, "data.set_role",
                      QStringLiteral("设置角色"), QStringLiteral("设置资产角色"),
                      QStringLiteral("角色 role"),
                      QStringLiteral("能力未接入生产（角色词汇只读，无编辑后端）"));
    // data.check / data.units: 工程级真实概览（目录快照真实计数），
    // 范围诚实标注（非逐资产深度检查）。
    register_real(registry, ids, "data.check", QStringLiteral("检查数据"),
                  QStringLiteral("工程级数据概览（格式/状态/完整性分布）"),
                  QStringLiteral("检查 qc 质量"),
                  [c] {
                      const auto* bus = data_bus(c);
                      const auto rows = bus != nullptr ? bus->assets()
                                                       : std::vector<ui_pages_data::AssetRow>{};
                      QStringList lines;
                      lines << QStringLiteral("工程级数据概览（%1 项资产，非逐资产深度检查）")
                                   .arg(rows.size());
                      std::map<QString, int> by_status;
                      std::map<QString, int> by_format;
                      int with_path = 0;
                      for (const auto& row : rows) {
                          ++by_status[QString::fromStdString(
                              row.view.status.empty() ? "未知" : row.view.status)];
                          ++by_format[QString::fromStdString(
                              row.view.format.empty() ? "未知" : row.view.format)];
                          if (!row.view.path.empty()) ++with_path;
                      }
                      QStringList status_parts;
                      for (const auto& [k, v] : by_status) {
                          status_parts << QStringLiteral("%1 %2").arg(k).arg(v);
                      }
                      QStringList format_parts;
                      for (const auto& [k, v] : by_format) {
                          format_parts << QStringLiteral("%1 %2").arg(k).arg(v);
                      }
                      lines << QStringLiteral("状态分布：%1")
                                   .arg(status_parts.join(QStringLiteral(" · ")));
                      lines << QStringLiteral("格式分布：%1")
                                   .arg(format_parts.join(QStringLiteral(" · ")));
                      lines << QStringLiteral("路径可达：%1/%2")
                                   .arg(with_path).arg(rows.size());
                      QMessageBox::information(
                          c.window, QStringLiteral("检查数据"), lines.join("\n"));
                  },
                  [c](const CommandContext&) { return needs_project(c); });
    register_real(registry, ids, "data.units",
                  QStringLiteral("单位与坐标"),
                  QStringLiteral("元数据覆盖度（目录暴露级）"),
                  QStringLiteral("单位 crs 坐标"),
                  [c] {
                      const auto* bus = data_bus(c);
                      const auto rows = bus != nullptr ? bus->assets()
                                                       : std::vector<ui_pages_data::AssetRow>{};
                      QStringList lines;
                      lines << QStringLiteral("元数据覆盖度（%1 项资产）").arg(rows.size());
                      lines << QStringLiteral("· 格式元数据：目录级可用（见检查数据）");
                      lines << QStringLiteral("· 逐资产单位/坐标元数据：目录未暴露——"
                                              "覆盖度仅到格式/状态级（诚实范围）");
                      QMessageBox::information(
                          c.window, QStringLiteral("单位与坐标"), lines.join("\n"));
                  },
                  [c](const CommandContext&) { return needs_project(c); });
    // data.history / data.lineage: 聚焦右侧版本历史/来源关系页签
    // （M5-3 DataLineagePanel，血缘 = catalog 真实 build_lineage_chain）。
#if defined(PWB_WITH_V14_DATA_LINEAGE)
    register_real(registry, ids, "data.history",
                  QStringLiteral("版本历史"), QStringLiteral("资产的版本来历链"),
                  QStringLiteral("版本 history"),
                  [c] { focus_lineage_tab(c, 0); },
                  [c](const CommandContext&) { return needs_selection(c); });
    register_real(registry, ids, "data.lineage",
                  QStringLiteral("来源关系"), QStringLiteral("版本的下游影响链"),
                  QStringLiteral("来源 lineage"),
                  [c] { focus_lineage_tab(c, 1); },
                  [c](const CommandContext&) { return needs_selection(c); });
#else
    register_disabled(registry, ids, "data.history",
                      QStringLiteral("版本历史"), QStringLiteral("资产的版本来历链"),
                      QStringLiteral("版本 history"),
                      QStringLiteral("血缘查询切片未接入本次构建"));
    register_disabled(registry, ids, "data.lineage",
                      QStringLiteral("来源关系"), QStringLiteral("版本的下游影响链"),
                      QStringLiteral("来源 lineage"),
                      QStringLiteral("血缘查询切片未接入本次构建"));
#endif
    // data.export_table: 导出当前资产表（bus 里的真实行）为 CSV。
    register_real(registry, ids, "data.export_table",
                  QStringLiteral("导出"), QStringLiteral("导出当前资产表 CSV"),
                  QStringLiteral("导出 export csv"),
                  [c] {
                      const auto* bus = data_bus(c);
                      if (bus == nullptr) {
                          emit c.shell->status_message(
                              QStringLiteral("资产表未装配"));
                          return;
                      }
                      const QString path = QFileDialog::getSaveFileName(
                          c.window, QStringLiteral("导出资产表"),
                          QStringLiteral("assets.csv"),
                          QStringLiteral("CSV (*.csv)"));
                      if (path.isEmpty()) return;
                      QFile file(path);
                      if (!file.open(QIODevice::WriteOnly | QIODevice::Text)) {
                          emit c.shell->status_message(
                              QStringLiteral("导出失败：无法写入 %1").arg(path));
                          return;
                      }
                      QTextStream out(&file);
                      out << "名称,类型,格式,状态,阶段,版本,路径\n";
                      for (const auto& row : bus->assets()) {
                          auto cell = [](const std::string& value) {
                              QString text = QString::fromStdString(value);
                              if (text.contains(QLatin1Char(','))) {
                                  text = QStringLiteral("\"%1\"").arg(text);
                              }
                              return text;
                          };
                          out << cell(row.view.name) << ','
                              << cell(row.view.type) << ','
                              << cell(row.view.format) << ','
                              << cell(row.view.status) << ','
                              << cell(row.view.stage) << ','
                              << cell(row.view.version_label) << ','
                              << cell(row.view.path) << '\n';
                      }
                      file.close();
                      emit c.shell->status_message(
                          QStringLiteral("资产表已导出：%1（%2 行）")
                              .arg(path)
                              .arg(bus->assets().size()));
                  },
                  [c](const CommandContext&) { return needs_project(c); });
    // 稿式新增：标签/影响分析/回收站 —— 资产标签与影响分析
    // 后端未接入，回收站（软删除区）无实现。
    register_disabled(registry, ids, "data.tags", QStringLiteral("标签"),
                      QStringLiteral("资产标签管理"),
                      QStringLiteral("标签 tag"),
                      QStringLiteral("资产标签后端未接入"));
    register_disabled(registry, ids, "data.impact",
                      QStringLiteral("影响分析"),
                      QStringLiteral("版本的下游影响分析"),
                      QStringLiteral("影响 impact 分析"),
                      QStringLiteral("影响分析后端未接入"));
    register_disabled(registry, ids, "data.trash",
                      QStringLiteral("回收站"),
                      QStringLiteral("软删除资产回收区"),
                      QStringLiteral("回收站 trash 删除"),
                      QStringLiteral("回收站（软删除）未实现"));
}

// ---------------------------------------------------------------------------
// ws1 智能预测
// ---------------------------------------------------------------------------

void predict_commands(ui_shell::CommandRegistry& registry,
                      std::vector<std::string>* ids, const Ctx& c) {
    register_disabled(registry, ids, "predict.select_well",
                      QStringLiteral("选择井数据"), QStringLiteral("选择参与预测的井"),
                      QStringLiteral("井 well"), QStringLiteral("M5 接入"));
#if defined(PWB_WITH_SEISMIC_VIEWER) && defined(PWB_WITH_DATA_INTEGRATION)
    register_real(registry, ids, "predict.select_seismic",
                  QStringLiteral("选择地震"),
                  QStringLiteral("打开体版本…（工程内 PWBVOL1）"),
                  QStringLiteral("地震 seismic 体"),
                  [c] {
                      if (c.window != nullptr) {
                          c.window->openVolumeDialogForCommands();
                      }
                  },
                  [c](const CommandContext&) { return needs_project(c); });
#else
    register_disabled(registry, ids, "predict.select_seismic",
                      QStringLiteral("选择地震"),
                      QStringLiteral("打开体版本…（工程内 PWBVOL1）"),
                      QStringLiteral("地震 seismic 体"),
                      QStringLiteral("构建未含地震查看器/数据集成切片"));
#endif
    register_disabled(registry, ids, "predict.model_params",
                      QStringLiteral("相预测 v2"), QStringLiteral("预测模型/版本选择"),
                      QStringLiteral("相预测 模型 model 版本"), QStringLiteral("M5 接入"));
    register_real(registry, ids, "predict.run", QStringLiteral("运行预测"),
                  QStringLiteral("对所选井运行真实 ONNX 相预测"),
                  QStringLiteral("运行 run 预测 prediction"),
                  [c] {
                      if (c.shell->well_log_page() != nullptr) {
                          c.shell->well_log_page()->on_run();
                      }
                  },
                  [c](const CommandContext&) { return needs_project(c); });
    register_real(registry, ids, "predict.cancel", QStringLiteral("取消"),
                  QStringLiteral("打开任务中心取消运行中的任务"),
                  QStringLiteral("取消 cancel"), [c] { open_task_center(c); },
                  [c](const CommandContext&) -> std::optional<std::string> {
                      if (!running_tasks(c)) {
                          return std::string("当前没有可取消的运行中任务");
                      }
                      return needs_project(c);
                  });
    register_disabled(registry, ids, "predict.params", QStringLiteral("参数"),
                      QStringLiteral("预测运行参数"), QStringLiteral("参数 params"),
                      QStringLiteral("M5 接入"));
    register_real(registry, ids, "predict.overlay_seismic",
                  QStringLiteral("地震叠加"), QStringLiteral("叠加地震相预测成果"),
                  QStringLiteral("叠加 overlay"),
                  [c] {
                      emit_stage_action(c, QStringLiteral("facies_calibration"),
                                        QStringLiteral(
                                            "add_seismic_prediction_overlay"));
                  },
                  [c](const CommandContext&) { return needs_project(c); });
    register_real(registry, ids, "predict.overlay_well",
                  QStringLiteral("测井叠加"), QStringLiteral("叠加测井相预测成果"),
                  QStringLiteral("叠加 overlay"),
                  [c] {
                      emit_stage_action(c, QStringLiteral("facies_calibration"),
                                        QStringLiteral(
                                            "add_well_prediction_overlay"));
                  },
                  [c](const CommandContext&) { return needs_project(c); });
    register_disabled(registry, ids, "predict.link", QStringLiteral("联动"),
                      QStringLiteral("井震联动开关"), QStringLiteral("联动 link"),
                      QStringLiteral("M5 接入"));
    register_real(registry, ids, "predict.save", QStringLiteral("保存结果"),
                  QStringLiteral("保存当前阶段成果"), QStringLiteral("保存 save"),
                  [c] {
                      emit_stage_action(c, QStringLiteral("facies_calibration"),
                                        QStringLiteral("stage_save"));
                  },
                  [c](const CommandContext&) { return needs_project(c); });
    register_real(registry, ids, "predict.submit", QStringLiteral("送交验证"),
                  QStringLiteral("切换到验证工作区"), QStringLiteral("验证 verify"),
                  [c] { c.shell->navigate_workspace(4); });
}

// ---------------------------------------------------------------------------
// ws2 约束与单因素
// ---------------------------------------------------------------------------

void factor_commands(ui_shell::CommandRegistry& registry,
                     std::vector<std::string>* ids, const Ctx& c) {
    // M5-2: 约束线编辑接编图场景真实工具（"line"）与捕捉真实状态
    // （场景 snap_manager，QAction 单一绑定）；上下文 Ribbon 组随选中
    // 出现（m5_compose install）。
#if defined(PWB_WITH_CLOSURE_MAPPING) && defined(PWB_WITH_STAGE_FLOW) \
    && defined(PWB_WITH_DATA_INTEGRATION)
    // 约束线/点编辑接 QGIS 权威栈（createStageConstraint/EnterConstraint
    // Editing 的 GPKG 约束层 + EditController 编辑会话）；治理化
    // add_line/add_point 捕获工具按活动图层几何类型路由。自绘场景
    // 的 "line" 工具不再冒充约束编辑（断链修复）。
    const auto enter_constraint_editing = [c](const char* kind,
                                              const char* capture_tool,
                                              const char* what) {
        c.shell->navigate_workspace(2);
        auto* window = c.window;
        if (window == nullptr) return;
        const QString problem =
            window->enterConstraintEditing(QString::fromLatin1(kind));
        if (!problem.isEmpty()) {
            emit c.shell->status_message(problem);
            return;
        }
        trigger_governed(c, QString::fromLatin1(capture_tool));
        emit c.shell->status_message(
            QStringLiteral("%1：在地图画布数字化（顶点自动捕捉到约束层"
                           "要素，数字化后保存生效）")
                .arg(QString::fromUtf8(what)));
    };
    register_real(registry, ids, "factor.edit_sourcing",
                  QStringLiteral("编辑物源线"),
                  QStringLiteral("进入物源线编辑（QGIS 约束层 + 治理捕获工具）"),
                  QStringLiteral("物源 sourcing 约束"),
                  [enter_constraint_editing] {
                      enter_constraint_editing(
                          "provenance_line", "add_line", "物源线编辑");
                  },
                  [c](const CommandContext&) { return needs_project(c); });
    register_real(registry, ids, "factor.edit_trend", QStringLiteral("展布线"),
                  QStringLiteral("进入展布线编辑（QGIS 约束层 + 治理捕获工具）"),
                  QStringLiteral("展布 trend"),
                  [enter_constraint_editing] {
                      enter_constraint_editing(
                          "distribution_line", "add_line", "展布线编辑");
                  },
                  [c](const CommandContext&) { return needs_project(c); });
    register_real(registry, ids, "factor.snap", QStringLiteral("捕捉"),
                  QStringLiteral("约束捕捉开关（QGIS 工程捕捉配置限定约束图层集）"),
                  QStringLiteral("捕捉 snap"),
                  [c] {
                      if (auto* action = c.shell->findChild<QAction*>(
                              QStringLiteral("FactorSnapToggle"));
                          action != nullptr) {
                          action->trigger();
                      }
                  });
    // 约束点（值锚定控制点）：QGIS 点约束层（value 属性）→ 保存采集进
    // constraint_layers[].points → 插值样本合并（全部后端真实消费）。
    register_real(registry, ids, "factor.constraint_point",
                  QStringLiteral("约束点"),
                  QStringLiteral("进入约束点编辑（值锚定控制点，参与插值）"),
                  QStringLiteral("约束点 constraint point 钉 pin"),
                  [enter_constraint_editing] {
                      enter_constraint_editing(
                          "constraint_pin", "add_point", "约束点编辑");
                  },
                  [c](const CommandContext&) { return needs_project(c); });
#else
    register_disabled(registry, ids, "factor.edit_sourcing",
                      QStringLiteral("编辑物源线"), QStringLiteral("物源线约束编辑"),
                      QStringLiteral("物源 sourcing 约束"),
                      QStringLiteral("编图场景切片未接入本次构建"));
    register_disabled(registry, ids, "factor.edit_trend",
                      QStringLiteral("展布线"), QStringLiteral("展布线约束编辑"),
                      QStringLiteral("展布 trend"),
                      QStringLiteral("编图场景切片未接入本次构建"));
    register_disabled(registry, ids, "factor.snap", QStringLiteral("捕捉"),
                      QStringLiteral("约束线捕捉开关"), QStringLiteral("捕捉 snap"),
                      QStringLiteral("编图场景切片未接入本次构建"));
#endif
#if !defined(PWB_WITH_CLOSURE_MAPPING)
    // 无编图闭包切片的构建：点约束编辑能力不在场，诚实禁用。
    register_disabled(registry, ids, "factor.constraint_point",
                      QStringLiteral("约束点"),
                      QStringLiteral("约束点要素编辑"),
                      QStringLiteral("约束点 constraint point"),
                      QStringLiteral("编图场景切片未接入本次构建"));
#endif
    // 插值方法：注册表驱动的真实选择（对话框只列 native 内核真正实现
    // 的后端）→ 文档权威 root["factor_settings"].method + 制备页面板
    // （compute 读取的单一状态面）同步。
#if defined(PWB_WITH_CLOSURE_MAPPING)
    register_real(registry, ids, "factor.method",
                  QStringLiteral("插值方法"),
                  QStringLiteral("选择插值方法（注册表驱动，随工程保存）"),
                  QStringLiteral("插值 方法 idw kriging method"),
                  [c] {
                      QString current;
                      if (auto* preparation =
                              closure_mapping::preparation_page(c.window);
                          preparation != nullptr
                          && preparation->task_panel() != nullptr) {
                          current = preparation->task_panel()
                                        ->selected_method();
                      }
                      if (const std::string saved = factor_config::read_method(
                              c.context->projectStore().get());
                          !saved.empty()) {
                          current = QString::fromStdString(saved);
                      }
                      FactorMethodDialog dialog(current, c.window);
                      if (dialog.exec() != QDialog::Accepted) return;
                      const QString method = dialog.selected_method();
                      std::string error;
                      if (!factor_config::write_method(
                              c.context->projectStore().get(),
                              method.toStdString(), &error)) {
                          emit c.shell->status_message(
                              QStringLiteral("方法保存失败：%1")
                                  .arg(QString::fromStdString(error)));
                          return;
                      }
                      if (auto* preparation =
                              closure_mapping::preparation_page(c.window);
                          preparation != nullptr
                          && preparation->task_panel() != nullptr) {
                          preparation->task_panel()->set_selected_method(
                              method);
                      }
                      emit c.shell->status_message(
                          QStringLiteral("插值方法已设为 %1（随工程保存）")
                              .arg(method));
                  },
                  [c](const CommandContext&) { return needs_project(c); });
#else
    register_disabled(registry, ids, "factor.method",
                      QStringLiteral("插值方法"),
                      QStringLiteral("插值方法选择"),
                      QStringLiteral("插值 方法 idw kriging"),
                      QStringLiteral("编图场景切片未接入本次构建"));
#endif
    register_real(registry, ids, "factor.compute",
                  QStringLiteral("计算单因素"),
                  QStringLiteral("按所选方法运行真实插值核（idw/kriging/约束 IDW）"),
                  QStringLiteral("计算 compute 单因素 factor"),
                  [c] {
#if defined(PWB_WITH_CLOSURE_MAPPING)
                      auto* preparation =
                          closure_mapping::preparation_page(c.window);
                      if (preparation == nullptr ||
                          preparation->task_panel() == nullptr) {
                          emit c.shell->status_message(
                              QStringLiteral("数据制备页未装配"));
                          return;
                      }
                      auto* panel = preparation->task_panel();
                      emit panel->generate_requested(panel->selected_method());
#else
                      emit c.shell->status_message(
                          QStringLiteral("单因素内核切片未参与本次构建"));
#endif
                  },
                  [c](const CommandContext&) { return needs_project(c); });
    // 插值参数：schema 驱动（按所选方法启用字段），写文档权威
    // root["factor_settings"].params；compute 快照读取同一状态。
#if defined(PWB_WITH_CLOSURE_MAPPING)
    register_real(registry, ids, "factor.params", QStringLiteral("参数"),
                  QStringLiteral("插值计算参数（网格/幂/种子，随工程保存）"),
                  QStringLiteral("参数 params 网格 幂"),
                  [c] {
                      QString method;
                      if (auto* preparation =
                              closure_mapping::preparation_page(c.window);
                          preparation != nullptr
                          && preparation->task_panel() != nullptr) {
                          method = preparation->task_panel()
                                       ->selected_method();
                      }
                      const auto current = factor_config::read_params(
                          c.context->projectStore().get());
                      FactorParamsDialog dialog(current, method, c.window);
                      if (dialog.exec() != QDialog::Accepted) return;
                      std::string error;
                      if (!factor_config::write_params(
                              c.context->projectStore().get(), dialog.params(),
                              &error)) {
                          emit c.shell->status_message(
                              QStringLiteral("参数保存失败：%1")
                                  .arg(QString::fromStdString(error)));
                          return;
                      }
                      emit c.shell->status_message(
                          QStringLiteral("插值参数已保存：网格 %1 × N%2"
                                         "（下一次计算生效并触发重算）")
                              .arg(dialog.params().grid_n)
                              .arg(method.isEmpty()
                                       ? QString()
                                       : QStringLiteral(" · 方法 %1")
                                             .arg(method)));
                  },
                  [c](const CommandContext&) { return needs_project(c); });
#else
    register_disabled(registry, ids, "factor.params", QStringLiteral("参数"),
                      QStringLiteral("插值计算参数"), QStringLiteral("参数 params"),
                      QStringLiteral("编图场景切片未接入本次构建"));
#endif
    register_real(registry, ids, "factor.cancel", QStringLiteral("取消"),
                  QStringLiteral("打开任务中心取消运行中的计算"),
                  QStringLiteral("取消 cancel"), [c] { open_task_center(c); },
                  [c](const CommandContext&) -> std::optional<std::string> {
                      if (!running_tasks(c)) {
                          return std::string("当前没有可取消的运行中任务");
                      }
                      return needs_project(c);
                  });
    register_real(registry, ids, "factor.select_wells", QStringLiteral("选井"),
                  QStringLiteral("切到约束工作区并聚焦连井剖面"),
                  QStringLiteral("选井 well 连井"),
                  [c] {
                      // 连井剖面 = ws2 页内阶段窗格（随工作区进入自明）。
                      c.shell->navigate_workspace(2);
                  });
    // 连井剖面路径（井序编辑 + 自动 PCA 排列；井序随剖面 sidecar 以
    // stable well ids 持久化）。联动开关在 ws2 剖面窗格（同一 QAction）。
#if defined(PWB_WITH_VIZ_B)
    register_real(registry, ids, "factor.crosswell_path",
                  QStringLiteral("连井剖面"),
                  QStringLiteral("编辑连井剖面路径（井序，随剖面保存）"),
                  QStringLiteral("连井 路径 path 排列"),
                  [c] {
                      c.shell->navigate_workspace(2);
                      if (!workspace_compose::run_crosswell_path_dialog(
                              c.window)) {
                          emit c.shell->status_message(
                              QStringLiteral(
                                  "剖面尚未装配或未加载井数据——先载入井"));
                      }
                  },
                  [c](const CommandContext&) { return needs_project(c); });
    register_real(registry, ids, "factor.link", QStringLiteral("联动"),
                  QStringLiteral("地图井选择 ↔ 连井剖面双向联动开关"),
                  QStringLiteral("联动 link 剖面 井"),
                  [c] {
                      if (auto* action = c.shell->findChild<QAction*>(
                              QStringLiteral("FactorLinkToggle"));
                          action != nullptr) {
                          action->trigger();
                          emit c.shell->status_message(
                              action->isChecked()
                                  ? QStringLiteral(
                                        "联动已开启：地图选井 → 剖面过滤；"
                                        "剖面勾选 → 地图高亮")
                                  : QStringLiteral("联动已关闭"));
                      } else {
                          emit c.shell->status_message(
                              QStringLiteral("剖面窗格未装配（VIZ-B 切片）"));
                      }
                  },
                  [c](const CommandContext&) { return needs_project(c); });
#else
    register_disabled(registry, ids, "factor.crosswell_path",
                      QStringLiteral("连井剖面"),
                      QStringLiteral("按路径自动排列连井剖面"),
                      QStringLiteral("连井 路径 path"),
                      QStringLiteral("连井剖面切片未参与本次构建"));
    register_disabled(registry, ids, "factor.link", QStringLiteral("联动"),
                      QStringLiteral("剖面联动开关"), QStringLiteral("联动 link"),
                      QStringLiteral("连井剖面切片未参与本次构建"));
#endif
    register_real(registry, ids, "factor.contour", QStringLiteral("生成等值线"),
                  QStringLiteral("从已完成单因素任务提取等值线草稿"),
                  QStringLiteral("等值线 contour"),
                  [c] {
#if defined(PWB_WITH_CLOSURE_MAPPING)
                      auto* preparation =
                          closure_mapping::preparation_page(c.window);
                      if (preparation == nullptr ||
                          preparation->task_panel() == nullptr) {
                          emit c.shell->status_message(
                              QStringLiteral("数据制备页未装配"));
                          return;
                      }
                      emit preparation->task_panel()->contour_draft_requested();
#else
                      emit c.shell->status_message(
                          QStringLiteral("数据制备页切片未参与本次构建"));
#endif
                  },
                  [c](const CommandContext&) { return needs_project(c); });
    // 等值线间距：真实参数（米），单一权威 root["contour_settings"]
    // .interval_m —— 等值线 worker 读取同一状态（固定间距层级策略，
    // 生成结果记录 source_interval 出处）。
#if defined(PWB_WITH_CLOSURE_MAPPING)
    register_real(registry, ids, "factor.contour_interval",
                  QStringLiteral("等值线间距"),
                  QStringLiteral("等值线固定间距（米，随工程保存）"),
                  QStringLiteral("间距 等值线 interval contour"),
                  [c] {
                      const double current = factor_config::read_contour_interval(
                          c.context->projectStore().get());
                      bool ok = false;
                      const double interval = QInputDialog::getDouble(
                          c.window, QStringLiteral("等值线间距"),
                          QStringLiteral("间距（米，>0；留空取消保持现状）"),
                          current > 0.0 ? current : 20.0, 0.01, 100000.0, 2,
                          &ok);
                      if (!ok) return;
                      std::string error;
                      if (!factor_config::write_contour_interval(
                              c.context->projectStore().get(), interval, &error)) {
                          emit c.shell->status_message(
                              QStringLiteral("间距保存失败：%1")
                                  .arg(QString::fromStdString(error)));
                          return;
                      }
                      emit c.shell->status_message(
                          QStringLiteral("等值线间距已设为 %1 m"
                                         "（下一次生成等值线生效）")
                          .arg(interval, 0, 'f', 2));
                  },
                  [c](const CommandContext&) { return needs_project(c); });
#else
    register_disabled(registry, ids, "factor.contour_interval",
                      QStringLiteral("等值线间距"),
                      QStringLiteral("等值线间距"),
                      QStringLiteral("间距 等值线 interval contour"),
                      QStringLiteral("编图场景切片未接入本次构建"));
#endif
    register_real(registry, ids, "factor.save", QStringLiteral("保存版本"),
                  QStringLiteral("保存当前阶段成果"), QStringLiteral("保存 save"),
                  [c] {
                      emit_stage_action(c, QStringLiteral("constraint_factor"),
                                        QStringLiteral("stage_save"));
                  },
                  [c](const CommandContext&) { return needs_project(c); });
    register_real(registry, ids, "factor.submit", QStringLiteral("送交验证"),
                  QStringLiteral("切换到验证工作区"), QStringLiteral("验证 verify"),
                  [c] { c.shell->navigate_workspace(4); });
}

// ---------------------------------------------------------------------------
// ws3 综合编图
// ---------------------------------------------------------------------------

void map_commands(ui_shell::CommandRegistry& registry,
                  std::vector<std::string>* ids, const Ctx& c) {
    // map.select / map.edit_facies / map.export bind the governed
    // ToolActionSet QACTIONS in MainWindow::wire_ribbon_commands (D4 — the
    // same objects the menus/shortcuts reuse); they are registered here so
    // the palette/search and the evaluator know them.
    register_real(registry, ids, "map.select", QStringLiteral("选择"),
                  QStringLiteral("选择要素（治理动作）"), QStringLiteral("选择 select"),
                  [c] { trigger_governed(c, QStringLiteral("select")); });
    register_real(registry, ids, "map.edit_facies",
                  QStringLiteral("编辑相界"),
                  QStringLiteral("开始/停止编辑（治理动作）"),
                  QStringLiteral("编辑 edit 相界 facies"),
                  [c] { trigger_governed(c, QStringLiteral("toggle_editing")); });
    // 稿：撤消并列于相界编辑——接治理 undo 动作（与 QAT/菜单
    // 同一 QAction）。
    register_real(registry, ids, "map.undo", QStringLiteral("撤消"),
                  QStringLiteral("撤消上一编辑操作（治理动作 Ctrl+Z）"),
                  QStringLiteral("撤消 undo"),
                  [c] { trigger_governed(c, QStringLiteral("undo")); });
    register_real(registry, ids, "map.show_reference",
                  QStringLiteral("显示参考图"),
                  QStringLiteral("编图画布的参考图面板 开/关"),
                  QStringLiteral("参考 reference 图"),
                  [&registry]() {
                      const auto* spec = registry.get("panel.toggle.reference");
                      if (spec != nullptr && spec->callback) spec->callback();
                  },
                  /*applicability=*/nullptr,
                  /*stages=*/{"constraint_factor", "integrated_compilation"});
    // 参考图与主图联动：预览视图跟随主画布 extent（单一 master）。
    // 开关 QAction 在参考图面板装配处创建（MapRefLinkToggle，同一
    // 状态驱动面板复选框）。
#if defined(PWB_WITH_CLOSURE_MAPPING)
    register_real(registry, ids, "map.ref_link", QStringLiteral("联动"),
                  QStringLiteral("参考图视图与主图 extent 联动开关"),
                  QStringLiteral("联动 link 参考"),
                  [c] {
                      if (auto* action = c.shell->findChild<QAction*>(
                              QStringLiteral("MapRefLinkToggle"));
                          action != nullptr) {
                          action->trigger();
                          emit c.shell->status_message(
                              action->isChecked()
                                  ? QStringLiteral(
                                        "参考图已联动：视图范围跟随主图"
                                        "（主图为单一权威）")
                                  : QStringLiteral("参考图联动已关闭——"
                                                   "两个视图独立漫游"));
                      } else {
                          emit c.shell->status_message(
                              QStringLiteral("参考图面板未装配"
                                             "（编图切片未接入）"));
                      }
                  },
                  [c](const CommandContext&) { return needs_project(c); });
#else
    register_disabled(registry, ids, "map.ref_link", QStringLiteral("联动"),
                      QStringLiteral("参考图与主图联动"),
                      QStringLiteral("联动 link 参考"),
                      QStringLiteral("编图切片未接入本次构建"));
#endif
    // M5-2 版式轻量页：模板/纸张/预览进入版式模式（面板骑 ws3 底部
    // 栈第 2 页，F:70）；图例整饰写文档 map_chrome（单一状态）；
    // 透明度指向参考图面板的真滑杆（单一状态，无第二份 slider）。
#if defined(PWB_WITH_CLOSURE_MAPPING)
    register_real(registry, ids, "map.opacity", QStringLiteral("透明度"),
                  QStringLiteral("参考图透明度（参考图面板滑杆）"),
                  QStringLiteral("透明度 opacity"),
                  [&registry, c]() {
                      const auto* spec = registry.get("panel.toggle.reference");
                      if (spec != nullptr && spec->callback) spec->callback();
                      emit c.shell->status_message(QStringLiteral(
                          "参考图面板已打开：拖动透明度滑杆（与画布同一状态）"));
                  },
                  [c](const CommandContext&) { return needs_project(c); },
                  /*stages=*/{"constraint_factor", "integrated_compilation"});
    register_real(registry, ids, "map.annotate", QStringLiteral("标注"),
                  QStringLiteral("标注工具（编图场景注记工具）"),
                  QStringLiteral("标注 annotate"),
                  [c] {
                      if (auto* scene = find_edit_scene(c); scene != nullptr) {
                          scene->set_tool("label");
                          emit c.shell->status_message(
                              QStringLiteral("标注工具：在编图画布放置注记"));
                      }
                  },
                  [c](const CommandContext&) { return needs_project(c); });
    register_real(registry, ids, "map.legend", QStringLiteral("图例"),
                  QStringLiteral("图例整饰开关（写文档 map_chrome）"),
                  QStringLiteral("图例 legend"),
                  [c] {
                      auto* panel = find_compose_panel(c);
                      QCheckBox* legend =
                          panel != nullptr
                              ? panel->findChild<QCheckBox*>(
                                    QStringLiteral("ComposeChrome_图例"))
                              : nullptr;
                      if (legend != nullptr) {
                          legend->setChecked(!legend->isChecked());
                      } else {
                          emit c.shell->status_message(
                              QStringLiteral("图例控件未装配（版式切片未接入）"));
                      }
                  },
                  [c](const CommandContext&) { return needs_project(c); });
    register_real(registry, ids, "map.north_arrow", QStringLiteral("指北针"),
                  QStringLiteral("指北针整饰开关（写文档 map_chrome）"),
                  QStringLiteral("指北针 north arrow"),
                  [c] {
                      auto* panel = find_compose_panel(c);
                      QCheckBox* arrow =
                          panel != nullptr
                              ? panel->findChild<QCheckBox*>(
                                    QStringLiteral("ComposeChrome_指北针"))
                              : nullptr;
                      if (arrow != nullptr) {
                          arrow->setChecked(!arrow->isChecked());
                      } else {
                          emit c.shell->status_message(
                              QStringLiteral("指北针控件未装配（版式切片未接入）"));
                      }
                  },
                  [c](const CommandContext&) { return needs_project(c); });
    register_real(registry, ids, "map.template", QStringLiteral("模板"),
                  QStringLiteral("版式模板（9 个内置模板真实清单）"),
                  QStringLiteral("模板 template"),
                  [c] {
                      enter_compose_mode(c);
                      if (auto* panel = find_compose_panel(c);
                          panel != nullptr) {
                          panel->template_selector()->showPopup();
                      }
                  },
                  [c](const CommandContext&) { return needs_project(c); });
    register_real(registry, ids, "map.paper", QStringLiteral("纸张"),
                  QStringLiteral("纸张/方向/图框设置（版式模式）"),
                  QStringLiteral("纸张 paper"),
                  [c] {
                      enter_compose_mode(c);
                      if (auto* panel = find_compose_panel(c);
                          panel != nullptr) {
                          panel->paper_selector()->showPopup();
                      }
                  },
                  [c](const CommandContext&) { return needs_project(c); });
    register_real(registry, ids, "map.preview", QStringLiteral("预览"),
                  QStringLiteral("版式预览（模板几何真实矢量重绘）"),
                  QStringLiteral("预览 preview"),
                  [c] {
                      enter_compose_mode(c);
                      emit c.shell->status_message(
                          QStringLiteral("版式预览：底部为模板真实几何渲染"));
                  },
                  [c](const CommandContext&) { return needs_project(c); });
#else
    register_disabled(registry, ids, "map.opacity", QStringLiteral("透明度"),
                      QStringLiteral("参考图透明度"), QStringLiteral("透明度 opacity"),
                      QStringLiteral("编图切片未接入本次构建"));
    register_disabled(registry, ids, "map.annotate", QStringLiteral("标注"),
                      QStringLiteral("图件标注"), QStringLiteral("标注 annotate"),
                      QStringLiteral("编图切片未接入本次构建"));
    register_disabled(registry, ids, "map.legend", QStringLiteral("图例"),
                      QStringLiteral("图例编辑"), QStringLiteral("图例 legend"),
                      QStringLiteral("编图切片未接入本次构建"));
    register_disabled(registry, ids, "map.north_arrow",
                      QStringLiteral("指北针"), QStringLiteral("指北针整饰"),
                      QStringLiteral("指北针 north arrow"),
                      QStringLiteral("编图切片未接入本次构建"));
    register_disabled(registry, ids, "map.template", QStringLiteral("模板"),
                      QStringLiteral("版式模板"), QStringLiteral("模板 template"),
                      QStringLiteral("编图切片未接入本次构建"));
    register_disabled(registry, ids, "map.paper", QStringLiteral("纸张"),
                      QStringLiteral("纸张/图框设置"), QStringLiteral("纸张 paper"),
                      QStringLiteral("编图切片未接入本次构建"));
    register_disabled(registry, ids, "map.preview", QStringLiteral("预览"),
                      QStringLiteral("版式预览"), QStringLiteral("预览 preview"),
                      QStringLiteral("编图切片未接入本次构建"));
#endif
    register_real(registry, ids, "map.export", QStringLiteral("导出图件"),
                  QStringLiteral("导出布局（治理动作 Ctrl+Shift+P）"),
                  QStringLiteral("导出 export 图件"),
                  [c] { trigger_governed(c, QStringLiteral("map_export")); });
    register_real(registry, ids, "map.save_plan", QStringLiteral("保存方案"),
                  QStringLiteral("组装并保存编图方案"), QStringLiteral("方案 plan"),
                  [c] {
                      emit_stage_action(c,
                                        QStringLiteral("integrated_compilation"),
                                        QStringLiteral("assemble_map_product"));
                  },
                  [c](const CommandContext&) { return needs_project(c); });
    register_real(registry, ids, "map.submit", QStringLiteral("送交验证"),
                  QStringLiteral("切换到验证工作区"), QStringLiteral("验证 verify"),
                  [c] { c.shell->navigate_workspace(4); });
}

// ---------------------------------------------------------------------------
// ws4 验证
// ---------------------------------------------------------------------------

void verify_commands(ui_shell::CommandRegistry& registry,
                     std::vector<std::string>* ids, const Ctx& c) {
    // M5: 对象/基准固定到明确版本（对比视图的选择器就是固定控件）。
    register_real(registry, ids, "verify.select_object",
                  QStringLiteral("对象"),
                  QStringLiteral("固定验证对象（井）并聚焦对比视图"),
                  QStringLiteral("对象 object 井 well"),
                  [c] {
                      c.shell->navigate_workspace(4);
                      if (auto* view = find_compare_view(c); view != nullptr) {
                          focus_right_tab(c, view);
                          view->object_selector()->showPopup();
                      }
                  },
                  [c](const CommandContext&) { return needs_project(c); });
    register_real(registry, ids, "verify.select_baseline",
                  QStringLiteral("基准"),
                  QStringLiteral("固定基准解释版本"),
                  QStringLiteral("基准 baseline 解释"),
                  [c] {
                      c.shell->navigate_workspace(4);
                      if (auto* view = find_compare_view(c); view != nullptr) {
                          focus_right_tab(c, view);
                          view->baseline_selector()->showPopup();
                      }
                  },
                  [c](const CommandContext&) -> std::optional<std::string> {
                      if (auto problem = needs_project(c);
                          problem.has_value()) {
                          return problem;
                      }
                      if (m5_validation::source_counts(c.context)
                              .interpretations == 0) {
                          return std::string(
                              "无解释版本（在「层序对比」页保存解释版本后可用）");
                      }
                      return std::nullopt;
                  });
    // 上一处问题（IssueNavigator：全报告扁平化、wrap-around、
    // refresh 后按 key 重定位游标——修复后不再指向 stale 问题）。
    register_real(registry, ids, "verify.prev_issue",
                  QStringLiteral("上一处"),
                  QStringLiteral("定位上一处问题（循环导航）"),
                  QStringLiteral("上一处 问题 prev issue"),
                  [c] {
                      if (auto* page = c.shell->validation_page();
                          page != nullptr) {
                          page->navigate_issue(-1);
                      }
                  },
                  [c](const CommandContext&) -> std::optional<std::string> {
                      auto* page = c.shell->validation_page();
                      if (page == nullptr || page->issue_count() == 0) {
                          return std::string("没有可定位的问题（先运行检查）");
                      }
                      return needs_project(c);
                  });
    // F:75 — link couples m and ms ONLY through a real time-depth
    // calibration; without one the toggle stays disabled with its reason.
    register_real(registry, ids, "verify.link",
                  QStringLiteral("联动光标"),
                  QStringLiteral("对照视图深度游标联动（需时深标定）"),
                  QStringLiteral("联动 link 时深"),
                  [c] {
                      if (QAction* action =
                              find_validation_action(c, "VerifyLinkToggle");
                          action != nullptr) {
                          action->trigger();
                      }
                  },
                  [c](const CommandContext&) -> std::optional<std::string> {
                      if (!m5_validation::link_available(c.context)) {
                          return std::string(
                              "无该井的时深标定数据——深度 m 与双程时 ms "
                              "不联动");
                      }
                      return needs_project(c);
                  });
    register_real(registry, ids, "verify.side_by_side",
                  QStringLiteral("并排"),
                  QStringLiteral("解释 | 预测 | 差异 三列对照"),
                  QStringLiteral("并排 side by side 对比"),
                  [c] {
                      if (QAction* action = find_validation_action(
                              c, "VerifyModeSideBySide");
                          action != nullptr) {
                          action->trigger();
                      }
                  },
                  [c](const CommandContext&) { return needs_compare_data(c); });
    register_real(registry, ids, "verify.overlay", QStringLiteral("叠加"),
                  QStringLiteral("解释与预测半透明叠加对照"),
                  QStringLiteral("叠加 overlay 对比"),
                  [c] {
                      if (QAction* action =
                              find_validation_action(c, "VerifyModeOverlay");
                          action != nullptr) {
                          action->trigger();
                      }
                  },
                  [c](const CommandContext&) { return needs_compare_data(c); });
    register_real(registry, ids, "verify.difference",
                  QStringLiteral("差异"),
                  QStringLiteral("红=不一致 绿=一致 区间对照"),
                  QStringLiteral("差异 difference 对比"),
                  [c] {
                      if (QAction* action = find_validation_action(
                              c, "VerifyModeDifference");
                          action != nullptr) {
                          action->trigger();
                      }
                  },
                  [c](const CommandContext&) { return needs_compare_data(c); });
    register_real(registry, ids, "verify.run", QStringLiteral("运行验证"),
                  QStringLiteral("对工程内全部编图文档运行 QC 规则（后台执行，可取消）"),
                  QStringLiteral("运行 run 验证 qc 检查"),
                  [c] {
                      auto* page = c.shell->validation_page();
                      if (page == nullptr) {
                          emit c.shell->status_message(
                              QStringLiteral("验证页未装配"));
                          return;
                      }
                      page->run_qc();
                  },
                  [c](const CommandContext&) -> std::optional<std::string> {
                      auto* page = c.shell->validation_page();
                      if (page != nullptr && page->qc_running()) {
                          return std::string("验证正在运行——可先取消");
                      }
                      return needs_project(c);
                  });
    register_real(registry, ids, "verify.settings", QStringLiteral("检查设置"),
                  QStringLiteral("当前内置 QC 规则一览"),
                  QStringLiteral("设置 settings 规则 rule"),
                  [c] {
                      QMessageBox::information(
                          c.window, QStringLiteral("检查设置"),
                          QString::fromStdString(
                              ui_review::review_config_text()));
                  },
                  [](const CommandContext&) -> std::optional<std::string> {
                      return std::nullopt;  // 规则一览无工程也可读
                  });
    // 取消验证：异步 QC 经任务宿主协作取消；cancelled 不合并——上一份
    // 有效报告保持不变。同步回退路径（无任务宿主）无可取消任务。
    register_real(registry, ids, "verify.cancel", QStringLiteral("取消"),
                  QStringLiteral("取消运行中的验证（已取消运行不覆盖上一份报告）"),
                  QStringLiteral("取消 cancel 验证"),
                  [c] {
                      if (auto* page = c.shell->validation_page();
                          page != nullptr) {
                          page->cancel_qc();
                      }
                  },
                  [c](const CommandContext&) -> std::optional<std::string> {
                      auto* page = c.shell->validation_page();
                      if (page == nullptr || !page->qc_running()) {
                          return std::string("当前没有运行中的验证任务");
                      }
                      return needs_project(c);
                  });
    // 下一处问题（IssueNavigator 前进方向；与「上一处」同一游标，
    // wrap-around）。旧行为「定位第一条」由首次导航自然覆盖（无游标
    // 时前进到第一条）。
    register_real(registry, ids, "verify.locate", QStringLiteral("下一处"),
                  QStringLiteral("定位下一处问题（循环导航并高亮）"),
                  QStringLiteral("定位 locate 下一处 问题 next"),
                  [c] {
                      if (auto* page = c.shell->validation_page();
                          page != nullptr) {
                          page->navigate_issue(1);
                      }
                  },
                  [c](const CommandContext&) -> std::optional<std::string> {
                      auto* page = c.shell->validation_page();
                      if (page == nullptr || page->issue_count() == 0) {
                          return std::string("没有可定位的问题（先运行检查）");
                      }
                      return needs_project(c);
                  });
    // M5: 问题级人工复核（备注必填；已复核 ≠ 检查通过）。
    register_real(registry, ids, "verify.record", QStringLiteral("记录结论"),
                  QStringLiteral("对选中问题录入人工复核结论"),
                  QStringLiteral("复核 record 结论"),
                  [c] {
                      c.shell->navigate_workspace(4);
                      if (auto* panel = find_review_panel(c);
                          panel != nullptr) {
                          focus_right_tab(c, panel);
                          panel->note_editor()->setFocus();
                      }
                  },
                  [c](const CommandContext&) { return needs_project(c); });
    register_real(registry, ids, "verify.save_record",
                  QStringLiteral("保存记录"), QStringLiteral("保存当前复核记录"),
                  QStringLiteral("保存 record"),
                  [c] {
                      if (auto* panel = find_review_panel(c);
                          panel != nullptr) {
                          panel->save_record();
                      }
                  },
                  [c](const CommandContext&) { return needs_project(c); });
    register_real(registry, ids, "verify.export_report",
                  QStringLiteral("导出报告"), QStringLiteral("导出 QC 报告 JSON"),
                  QStringLiteral("导出 export 报告 report"),
                  [c] {
                      if (c.shell->review_page() != nullptr) {
                          c.shell->review_page()->export_report();
                      }
                  },
                  [c](const CommandContext&) { return needs_project(c); });
}

}  // namespace

void install(const Install& install) {
    if (install.shell == nullptr || install.registered_ids == nullptr) {
        return;
    }
    Ctx ctx;
    ctx.window = dynamic_cast<MainWindow*>(install.window);
    ctx.shell = install.shell;
    ctx.context = install.context;
    ctx.jobs = install.jobs;
    if (ctx.window == nullptr || ctx.shell == nullptr) return;

    auto& registry = ui_shell::command_registry();
    data_commands(registry, install.registered_ids, ctx);
    predict_commands(registry, install.registered_ids, ctx);
    factor_commands(registry, install.registered_ids, ctx);
    map_commands(registry, install.registered_ids, ctx);
    verify_commands(registry, install.registered_ids, ctx);
}

}  // namespace pwb::app::ribbon_commands
