#pragma once

// UI-02 — PwbTableView / PwbTreeView / PwbCommandBar, ported from
// paleo_workbench/ui/components/views.py (V5-U2): density-aware row
// heights recomputed on theme_changed, unified context tool bar.

#include <QFrame>
#include <QHBoxLayout>
#include <QStyledItemDelegate>
#include <QTableView>
#include <QToolButton>
#include <QTreeView>

#include <functional>

namespace pwb::ui_widgets {

// Row height = tokens.row_height(current density) — read on every
// sizeHint so density switches take effect without rebuilding the view.
class DensityRowDelegate : public QStyledItemDelegate {
    Q_OBJECT
public:
    explicit DensityRowDelegate(QObject* parent = nullptr);
    QSize sizeHint(const QStyleOptionViewItem& option,
                   const QModelIndex& index) const override;
};

class PwbTableView : public QTableView {
    Q_OBJECT
public:
    explicit PwbTableView(QWidget* parent = nullptr);

private:
    DensityRowDelegate* delegate_ = nullptr;
};

class PwbTreeView : public QTreeView {
    Q_OBJECT
public:
    explicit PwbTreeView(QWidget* parent = nullptr);

private:
    DensityRowDelegate* delegate_ = nullptr;
};

// Unified context tool bar (V3 context-bar look, hairline bottom edge).
class PwbCommandBar : public QFrame {
    Q_OBJECT
public:
    explicit PwbCommandBar(QWidget* parent = nullptr);

    QToolButton* add_button(const QString& icon_name,
                            const QString& text = QString(),
                            const QString& tooltip = QString(),
                            bool checkable = false,
                            std::function<void()> slot = {});
    QFrame* add_separator();
    QWidget* add_widget(QWidget* widget, int stretch = 0);
    void add_stretch();

private:
    QHBoxLayout* layout_ = nullptr;
};

}  // namespace pwb::ui_widgets
