#pragma once

// PREDICTION-WORKFLOW — ws1 智能预测闭环的 app 侧装配（predict.* 命令的
// 生产后端）。在 CLOSURE-SCIENCE 之后装配：找到 main_window 装配的
// SciencePageBinding（attach_prediction_pages 的返回值，parent=app_shell），
// 创建 PredictionWorkflowController（RunSpec 唯一所有者 + 井震联动），
// 并把工程文档持久化/时深标定 seam 接到 AppContext 的 project store。
//
// 未参与构建（PWB_WITH_CLOSURE_SCIENCE 未定义）时 ribbon 侧保持诚实
// disabled——本文件不编译。

class QMainWindow;

namespace pwb::app {

class AppContext;
class AppShell;

namespace prediction_workflow {

struct Install {
    QMainWindow* window = nullptr;
    AppShell* shell = nullptr;
    AppContext* context = nullptr;
};

// One install per window (idempotent on the shell). GUI thread only.
void install(const Install& install);

// Project open/close/reload: restores the persisted RunSpec for the new
// project (no cross-project spec leakage) and refreshes link availability.
void notify_project_changed(QMainWindow* window);

}  // namespace prediction_workflow

}  // namespace pwb::app
