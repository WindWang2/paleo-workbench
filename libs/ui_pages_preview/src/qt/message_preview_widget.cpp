#include <pwb/ui_pages_preview/qt/message_preview_widget.hpp>

namespace pwb::ui_pages_preview {

MessagePreviewWidget::MessagePreviewWidget(QWidget* parent)
    : QLabel(parent) {
    setAlignment(Qt::AlignCenter);
    setWordWrap(true);
}

}  // namespace pwb::ui_pages_preview
