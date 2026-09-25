#pragma once

// factor.method / factor.params 的 Qt 对话框（真实选择 + 参数 schema 驱动
// 编辑；非法配置在 OK 前被 validate_params 阻止）。状态单一权威在
// factor_method_config（文档），对话框只做临时编辑面。

#include <QDialog>
#include <QString>

#include "factor_method_config.hpp"

class QLabel;
class QListWidget;
class QSpinBox;
class QDoubleSpinBox;

namespace pwb::app {

class FactorMethodDialog : public QDialog {
    Q_OBJECT
  public:
    // current 为空 → 选中注册表第一项（不伪造“当前方法”标签）。
    explicit FactorMethodDialog(const QString& current, QWidget* parent);
    [[nodiscard]] QString selected_method() const;

  private:
    class QListWidget* list_ = nullptr;
    class QLabel* description_ = nullptr;
};

class FactorParamsDialog : public QDialog {
    Q_OBJECT
  public:
    explicit FactorParamsDialog(const factor_config::RunParams& current,
                                const QString& method_label, QWidget* parent);
    [[nodiscard]] factor_config::RunParams params() const;

  private:
    void sync_fields_for_backend(const QString& backend);
    class QSpinBox* grid_n_ = nullptr;
    class QDoubleSpinBox* power_ = nullptr;
    class QSpinBox* seed_ = nullptr;
    class QLabel* hint_ = nullptr;
    QString backend_;
};

}  // namespace pwb::app
