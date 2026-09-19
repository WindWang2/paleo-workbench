#include <pwb/ui_pages_preview/qt/text_preview_widget.hpp>

#include <pwb/ui_pages_preview/preview_settings.hpp>

#include "../qt/style_util.hpp"

namespace pwb::ui_pages_preview {

TextPreviewWidget::TextPreviewWidget(QWidget* parent)
    : QTextEdit(parent) {
    setReadOnly(true);
    setLineWrapMode(QTextEdit::NoWrap);
    // Monospace family comes from the FONT_FAMILY_MONO token (theme-agnostic).
    setStyleSheet(QString("font-family: %1;").arg(qt_internal::FONT_FAMILY_MONO));
}

void TextPreviewWidget::apply_settings(const PreviewSettings& settings) {
    QFont f = font();
    f.setPointSize(settings.font_size);
    setFont(f);
    setStyleSheet(QString("font-family: %1; font-size: %2pt;")
                      .arg(qt_internal::FONT_FAMILY_MONO)
                      .arg(settings.font_size));
    setLineWrapMode(settings.wrap_text ? QTextEdit::WidgetWidth
                                       : QTextEdit::NoWrap);
}

}  // namespace pwb::ui_pages_preview
