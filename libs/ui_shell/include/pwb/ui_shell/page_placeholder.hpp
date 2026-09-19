#pragma once

// Port of paleo_workbench/ui/page_placeholder.py (UI-01).
// 占位页：name + "(占位页, 待实现)"，文字色经 style_registry 随主题刷新
//（构造时快照 light 值的缺陷在 Python 侧已由 style.bind 修复）。

#include <QLabel>
#include <QWidget>

namespace pwb::ui_shell {

class PagePlaceholder : public QWidget {
    Q_OBJECT
public:
    explicit PagePlaceholder(const QString& page_name,
                             QWidget* parent = nullptr);

private:
    QLabel* name_label_ = nullptr;
};

}  // namespace pwb::ui_shell
