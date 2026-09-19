#include <pwb/ui_composite/tool_page_dialog.hpp>

#include <QCloseEvent>
#include <QDialogButtonBox>

namespace pwb::ui_composite {

ToolPageDialog::ToolPageDialog(QWidget* parent) : QDialog(parent) {
    setObjectName("ToolPageDialog");
    setModal(false);
    setWindowFlag(Qt::Window, true);
    resize(1080, 720);
    setMinimumSize(720, 480);
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 8);
    body_ = new QVBoxLayout();
    body_->setContentsMargins(0, 0, 0, 0);
    layout->addLayout(body_, 1);
    auto* buttons = new QDialogButtonBox(QDialogButtonBox::Close, this);
    connect(buttons, &QDialogButtonBox::rejected, this,
            &ToolPageDialog::reject);
    layout->addWidget(buttons);
}

void ToolPageDialog::present(QWidget* page, const QString& title,
                             QWidget* home) {
    if (page == page_ && isVisible()) {
        setWindowTitle(title);
        raise();
        activateWindow();
        return;
    }
    release_page();
    page_ = page;
    home_ = home;
    body_->addWidget(page);
    page->show();
    setWindowTitle(title);
    show();
    raise();
    activateWindow();
}

void ToolPageDialog::release_page() {
    QWidget* page = page_;
    QWidget* home = home_;
    page_ = nullptr;
    home_ = nullptr;
    if (page == nullptr) return;
    body_->removeWidget(page);
    if (home != nullptr && home->layout() != nullptr)
        home->layout()->addWidget(page);
    else if (home != nullptr)
        page->setParent(home);
}

void ToolPageDialog::closeEvent(QCloseEvent* event) {
    release_page();
    QDialog::closeEvent(event);
}

void ToolPageDialog::reject() {
    release_page();
    QDialog::reject();
}

}  // namespace pwb::ui_composite
