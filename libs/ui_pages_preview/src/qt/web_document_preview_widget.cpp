#include <pwb/ui_pages_preview/qt/web_document_preview_widget.hpp>

#include <QFileInfo>
#include <QLabel>
#include <QUrl>
#include <QVBoxLayout>

#if defined(PWB_UI_PAGES_PREVIEW_HAVE_WEBENGINE)
#include <QWebEnginePage>
#include <QWebEngineProfile>
#include <QWebEngineSettings>
#include <QWebEngineUrlRequestInfo>
#include <QWebEngineUrlRequestInterceptor>
#include <QWebEngineView>
#endif

#include <pwb/ui_pages_preview/preview_settings.hpp>
#include <pwb/ui_pages_preview/url_filter.hpp>

namespace pwb::ui_pages_preview {

#if defined(PWB_UI_PAGES_PREVIEW_HAVE_WEBENGINE)

namespace {

// _LocalOnlyRequestInterceptor: block WebEngine resource requests outside
// the local document sandbox {file, data, about, blob}.
class LocalOnlyRequestInterceptor : public QWebEngineUrlRequestInterceptor {
public:
    using QWebEngineUrlRequestInterceptor::QWebEngineUrlRequestInterceptor;

    void interceptRequest(QWebEngineUrlRequestInfo& info) override {
        if (!local_scheme_allowed(info.requestUrl().scheme().toStdString())) {
            info.block(true);
        }
    }
};

// _LocalOnlyPage: reject user-initiated navigation away from local
// document content.
class LocalOnlyPage : public QWebEnginePage {
public:
    using QWebEnginePage::QWebEnginePage;

    bool acceptNavigationRequest(const QUrl& url, NavigationType,
                                 bool isMainFrame) override {
        Q_UNUSED(isMainFrame);
        return local_scheme_allowed(url.scheme().toStdString());
    }
};

}  // namespace

#endif  // PWB_UI_PAGES_PREVIEW_HAVE_WEBENGINE

WebDocumentPreviewWidget::WebDocumentPreviewWidget(QWidget* parent)
    : QWidget(parent) {
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
#if defined(PWB_UI_PAGES_PREVIEW_HAVE_WEBENGINE)
    engine_view_ = new QWebEngineView(this);
    auto* profile = new QWebEngineProfile(engine_view_);
    auto* interceptor = new LocalOnlyRequestInterceptor(profile);
    profile->setUrlRequestInterceptor(interceptor);
    auto* page = new LocalOnlyPage(profile, engine_view_);
    engine_view_->setPage(page);
    engine_view_->settings()->setAttribute(
        QWebEngineSettings::LocalContentCanAccessRemoteUrls, false);
    layout->addWidget(engine_view_);
#else
    placeholder_ = new QLabel(QStringLiteral("Web 文档预览不可用"));
    placeholder_->setAlignment(Qt::AlignCenter);
    layout->addWidget(placeholder_);
#endif
}

void WebDocumentPreviewWidget::load_document(const QString& path,
                                             const QString& html) {
#if defined(PWB_UI_PAGES_PREVIEW_HAVE_WEBENGINE)
    const QUrl base_url =
        QUrl::fromLocalFile(QFileInfo(path).absolutePath() + QLatin1Char('/'));
    if (!html.isEmpty()) {
        engine_view_->setHtml(html, base_url);
    } else {
        engine_view_->load(QUrl::fromLocalFile(path));
    }
#else
    Q_UNUSED(path);
    Q_UNUSED(html);
#endif
}

void WebDocumentPreviewWidget::apply_settings(const PreviewSettings& settings) {
#if defined(PWB_UI_PAGES_PREVIEW_HAVE_WEBENGINE)
    engine_view_->setZoomFactor(settings.font_size / 12.0);
#else
    Q_UNUSED(settings);
#endif
}

}  // namespace pwb::ui_pages_preview
