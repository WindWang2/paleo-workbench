#pragma once

// Port of paleo_workbench/ui/crs_guidance.py (UI-01).
// CRS 域失配一次性引导对话框（拓扑编辑迁移 M0 §6，决议 #1285）：进入编辑
// 被域校验阻止（声明 CRS 的有效坐标域不覆盖数据实际坐标范围）时呈现——
// 受影响图层列表 + 失配事实；「改为本地坐标（清除声明）」由调用方清除
// 声明并重试进入编辑；「取消」保持现状。

#include <QDialog>

#include <string>
#include <utility>
#include <vector>

class QLabel;
class QListWidget;

namespace pwb::ui_shell {

// Caller-facing verdict data — the domain verdict type stays upstream
// (mapping/science); the dialog consumes a plain projection so the widget
// carries zero business judgment.
struct CrsGuidanceVerdict {
    std::string reason;
    std::string declared_crs;  // empty → "（图层声明）"
    // Fallback rows when affected_layers is empty: pre-formatted mismatch
    // descriptions ("声明 <crs>：<describe>"), built by the caller.
    std::vector<std::string> mismatch_rows;
};

class CrsGuidanceDialog : public QDialog {
    Q_OBJECT
public:
    // affected_layers: (layer_id, display_name) rows; when empty the
    // verdict's mismatch rows are listed instead.
    CrsGuidanceDialog(
        CrsGuidanceVerdict verdict,
        std::vector<std::pair<std::string, std::string>> affected_layers =
            {},
        QWidget* parent = nullptr);

    // True = the user chose 「改为本地坐标（清除声明）」.
    bool cleared() const { return cleared_; }

private:
    bool cleared_ = false;
};

}  // namespace pwb::ui_shell
