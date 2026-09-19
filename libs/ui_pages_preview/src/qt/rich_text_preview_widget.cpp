#include <pwb/ui_pages_preview/qt/rich_text_preview_widget.hpp>

#include <pwb/ui_pages_preview/preview_settings.hpp>
#include <pwb/ui_pages_preview/url_filter.hpp>

namespace pwb::ui_pages_preview {

RichTextPreviewWidget::RichTextPreviewWidget(QWidget* parent)
    : QTextBrowser(parent) {
    setOpenExternalLinks(false);
    setReadOnly(true);
}

QVariant RichTextPreviewWidget::loadResource(int type, const QUrl& name) {
    if (!resource_scheme_allowed(name.scheme().toStdString())) {
        return {};
    }
    return QTextBrowser::loadResource(type, name);
}

void RichTextPreviewWidget::apply_settings(const PreviewSettings& settings) {
    QFont f = font();
    f.setPointSize(settings.font_size);
    setFont(f);
    setLineWrapMode(settings.wrap_text ? QTextEdit::WidgetWidth
                                       : QTextEdit::NoWrap);
}

}  // namespace pwb::ui_pages_preview
