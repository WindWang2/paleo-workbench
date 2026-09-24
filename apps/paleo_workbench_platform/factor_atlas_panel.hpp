#pragma once

// ws2 右栏「单因素」签（设计稿：单因素图层（层位）勾选清单）。
// 数据 = project.factor_map_tasks 中 status==complete 的条目（与
// FactorReferenceStrip 同一权威、同一过滤）；勾选 = 当前叠加参考
// （单选语义，同参考带）→ 经 stage_action_requested 治理通道叠加到
// 主图，绝不绕过治理直改画布。

#include <functional>
#include <vector>

#include <QWidget>

#include <pwb/domain/json.hpp>

class QLabel;
class QListWidget;
class QListWidgetItem;

namespace pwb::app {

class FactorAtlasPanel : public QWidget {
    Q_OBJECT

  public:
    explicit FactorAtlasPanel(QWidget* parent = nullptr);

    void update_state(const std::vector<pwb::domain::Json>& tasks);
    void set_horizon(const QString& horizon);

  signals:
    // 勾选一张图 = 请求叠加该参考（主成果不替换）。
    void overlay_selected(const pwb::domain::Json& task);

  private:
    void rebuild();

    QLabel* title_ = nullptr;
    QListWidget* list_ = nullptr;
    QLabel* empty_ = nullptr;
    std::vector<pwb::domain::Json> tasks_;
    QString horizon_;
    pwb::domain::Json selected_ = pwb::domain::Json::object();
    bool syncing_ = false;
};

}  // namespace pwb::app

// Json rides a queued-capable signal — one metatype declaration per TU
// (shared guard with factor_reference_strip.hpp / ui_map qt_meta.hpp).
#ifndef PWB_JSON_METATYPE_DECLARED
#define PWB_JSON_METATYPE_DECLARED
Q_DECLARE_METATYPE(pwb::domain::Json)
#endif
