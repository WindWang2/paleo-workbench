#pragma once

// Port of paleo_workbench/ui/workstation/tool_page_dialog.py (UI-13).
// Modeless dialog host for tool pages (数据制备 / 成图审核): the pages
// are workflows over the central 编图 document and must not occupy a
// dock competing with the map; a closable dialog keeps the canvas in
// place. The page is restored to its hub stack on close.

#include <QDialog>
#include <QVBoxLayout>
#include <QWidget>

namespace pwb::ui_composite {

class ToolPageDialog : public QDialog {
    Q_OBJECT
public:
    explicit ToolPageDialog(QWidget* parent = nullptr);

    // Present `page` (reparents it into the dialog body); `home` is the
    // widget the page returns to on close (a QStackedWidget/QLayout host).
    void present(QWidget* page, const QString& title, QWidget* home);

protected:
    void closeEvent(QCloseEvent* event) override;
    void reject() override;

private:
    void release_page();

    QVBoxLayout* body_ = nullptr;
    QWidget* page_ = nullptr;
    QWidget* home_ = nullptr;
};

}  // namespace pwb::ui_composite
