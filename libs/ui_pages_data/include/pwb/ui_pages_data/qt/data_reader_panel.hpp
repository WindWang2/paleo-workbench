// UI-06 — data_reader_panel.py :: DataReaderPanel Qt shell.
//
// The panel is a mode→widget dispatcher. Native targets are provided for
// the modes that are self-contained (empty/message/text/table/image/pdf).
// Widgets that live in other slices (well_log, seismic, rich_text,
// web_document, json_tree, geotiff, media) or need engines
// (lazy_visualization_tabs / geoviz host) register through
// register_target(name, widget) + register_render_hook(name, fn); a mode
// with no hook falls back to the message widget — Python's dict-.get
// default.
#pragma once

#include <QByteArray>
#include <QFrame>
#include <QLabel>
#include <QPixmap>
#include <QStackedWidget>
#include <QTableView>
#include <QTextEdit>

#include <functional>
#include <map>
#include <memory>
#include <string>
#include <vector>

#include <pwb/ui_pages_data/pdf_zoom.hpp>

class QPushButton;
class QStandardItemModel;

namespace pwb::ui_pages_data::qt {

// PreviewResult seam (preview_provider.py is another slice). The panel
// reads scalars + a payload pointer understood only by render hooks.
struct PreviewResultView {
    std::string mode = "empty";
    std::string title;
    std::string message;
    std::string warning;
    std::string type_label;
    std::string format;
    std::string status;
    std::string path;
    std::string revision;
    std::string text;                          // text mode
    std::vector<std::string> table_headers;    // table modes
    std::vector<std::vector<std::string>> table_rows;
    std::string rich_html;                     // rich_text/web_document
    std::string media_path;                    // media mode
    bool visualization_available = false;
    bool engine_preview_prepared = false;      // geoviz PreparedPreview gate
    bool retryable = true;
    const void* payload = nullptr;             // hook-private payload
    // CLOSURE-PREVIEW (task 04): shared lifetime for `payload` — the view
    // is copied through the async delivery hop, so hook payloads ride a
    // shared owner instead of pointing into a caller's stack frame.
    std::shared_ptr<const void> payload_owner;
};

// --- native preview widgets ---------------------------------------------------

// MessagePreviewWidget parity (QLabel + set_message).
class MessagePreview : public QLabel {
    Q_OBJECT
public:
    explicit MessagePreview(QWidget* parent = nullptr);
    void set_message(const QString& text) { setText(text); }
};

// TextPreviewWidget parity (readonly QTextEdit + load_text).
class TextPreview : public QTextEdit {
    Q_OBJECT
public:
    explicit TextPreview(QWidget* parent = nullptr);
    void load_text(const QString& text) { setPlainText(text); }
    void apply_settings(int font_size_pt);
};

// TablePreviewWidget parity: model-backed QTableView, bounded cell cap,
// truncation flag/message, TSV copy_all over visible rows.
class TablePreview : public QTableView {
    Q_OBJECT
public:
    static constexpr long long kMaxPreviewCells = 1'000'000;
    static constexpr int kAutoFitSampleRows = 200;

    explicit TablePreview(QWidget* parent = nullptr);
    void load_table(const std::vector<std::string>& headers,
                    const std::vector<std::vector<std::string>>& rows);
    std::string copy_all() const;
    bool truncated() const { return truncated_; }
    QString truncation_message() const { return truncation_message_; }
    void apply_settings(bool auto_fit);

private:
    QStandardItemModel* model_;
    bool auto_fit_ = true;
    bool truncated_ = false;
    QString truncation_message_;
};

// ImagePreviewWidget parity: bounded decode, fit-vs-zoom, pan stub.
class ImagePreview : public QLabel {
    Q_OBJECT
public:
    static constexpr int kPreviewMaxLongSide = 2048;
    static constexpr double kZoomMax = 8.0;
    static constexpr double kZoomMin = 0.10;
    static constexpr double kZoomStep = 1.25;

    explicit ImagePreview(QWidget* parent = nullptr);
    void load(const QString& path, const QString& revision,
              const QByteArray& bytes = {});
    void render_current();
    void zoom_in();
    void zoom_out();
    void set_zoom_factor(double factor);
    void set_fit_mode(bool enabled);
    double zoom_factor() const { return zoom_factor_; }
    bool fit_mode() const { return fit_mode_; }

Q_SIGNALS:
    void zoom_changed(double factor);

protected:
    void resizeEvent(QResizeEvent* event) override;

private:
    QPixmap pixmap_;
    QString path_;
    QString revision_;
    double zoom_factor_ = 1.0;
    bool fit_mode_ = true;
};

// PdfPreviewWidget parity (data_detail_panel.PdfPreviewPanel semantics):
// QPdfView when Qt6::Pdf is linked, else the fallback image label.
// Navigation/zoom math lives in PdfZoomModel.
class PdfPreview : public QWidget {
    Q_OBJECT
public:
    explicit PdfPreview(QWidget* parent = nullptr);
    void load(const QString& path, const QString& revision,
              const QByteArray& pdf_bytes = {});
    void next_page();
    void previous_page();
    int page_index() const { return zoom_.page_index(); }
    int page_count() const { return page_count_; }
    QLabel* fallback_image() { return fallback_image_; }
    QPushButton* prev_btn() { return prev_btn_; }
    QPushButton* next_btn() { return next_btn_; }
    QLabel* page_label() { return page_label_; }

private:
    void sync_nav();

    PdfZoomModel zoom_;
    int page_count_ = 0;
    QString path_;
    QLabel* fallback_image_;
    QPushButton* prev_btn_;
    QPushButton* next_btn_;
    QLabel* page_label_;
};

// --- the panel ---------------------------------------------------------------

// Loads a mode's payload into a registered widget. Native modes have
// built-in hooks; other-slice widgets register their own.
using PreviewRenderHook =
    std::function<void(QWidget* widget, const PreviewResultView& result)>;

class DataReaderPanel : public QFrame {
    Q_OBJECT
public:
    explicit DataReaderPanel(QWidget* parent = nullptr);

    // Other-slice widget seams. register_target adds the widget to the
    // stack under a target name; register_render_hook teaches the panel
    // how to feed it. Mode→target resolution: the mode name IS the
    // target name when a hook exists (preview_dispatch.hpp parity).
    void register_target(const QString& name, QWidget* widget);
    void register_render_hook(const QString& name, PreviewRenderHook hook);
    // The lazy-visualization-tabs seam (its widget + load hooks). The
    // panel routes visualization_available/geoviz results to it.
    QWidget* visualization_tabs() const { return viz_tabs_; }
    void set_visualization_hooks(
        QWidget* tabs,
        std::function<void(const PreviewResultView&)> load_summary,
        std::function<void()> reset_tabs,
        std::function<void()> show_loading,
        std::function<void(const QString&, bool)> show_error);
    // geoviz PreparedPreview presentation hook (engine seam).
    void set_geoviz_show_fn(std::function<bool(const PreviewResultView&)> fn);

    void show_loading(const std::string& resolved_asset_name = {});
    // CLOSURE-PREVIEW (task 04): the loading page offers 取消 when a hook
    // is armed; the hook cancels the host's in-flight load and returns
    // true when something was actually cancelled. Task-mandated affordance
    // (Python has no cancel UI — recorded as a workbench addition).
    void set_cancel_hook(std::function<bool()> hook);
    bool has_cancel_hook() const { return cancel_hook_ != nullptr; }
    // update_asset parity: the provider seam is the caller's — call this
    // with the provider's PreviewResultView.
    void render(const PreviewResultView& result);
    void render_visualization(const PreviewResultView& result);
    void show_visualization_loading();
    void show_visualization_error(const QString& message,
                                  bool retryable = true);

    std::string current_mode() const { return current_mode_; }
    const PreviewResultView& current_result() const { return current_; }

    void next_pdf_page();
    void previous_pdf_page();
    void apply_preview_settings(bool show_metadata, int font_size_pt,
                                bool auto_fit_columns);

    // Native widgets (Python attribute names for test parity).
    MessagePreview* message_label() { return message_; }
    MessagePreview* empty_label() { return empty_; }
    TextPreview* text_preview() { return text_; }
    TablePreview* table_preview() { return table_; }
    ImagePreview* image_preview_widget() { return image_; }
    PdfPreview* pdf_preview_widget() { return pdf_; }
    QLabel* title_label() { return title_; }
    QLabel* meta_label() { return meta_; }
    QLabel* warning_label() { return warning_; }
    QStackedWidget* stack() { return stack_; }

Q_SIGNALS:
    void reader_mode_changed(const QString& mode);
    void preview_settings_changed();
    void visualization_requested();

protected:
    void contextMenuEvent(QContextMenuEvent* event) override;

private:
    QWidget* target_for(const std::string& mode,
                        const PreviewResultView& result);
    void commit(const PreviewResultView& result, QWidget* target);
    void sync_image_zoom_ui();
    void on_copy_table_all();
    std::string safe_clear_geoviz();

    std::string current_mode_ = "empty";
    PreviewResultView current_;
    bool geoviz_host_created_ = false;  // lazy-host seam flag

    QStackedWidget* stack_;
    QLabel* title_;
    QLabel* meta_;
    QLabel* warning_;
    QWidget* table_toolbar_;
    QPushButton* table_copy_btn_;
    QWidget* image_toolbar_;
    QPushButton* image_fit_btn_;
    QPushButton* image_zoom_out_btn_;
    QLabel* image_zoom_label_;
    QPushButton* image_zoom_in_btn_;

    MessagePreview* empty_;
    MessagePreview* message_;
    TextPreview* text_;
    TablePreview* table_;
    ImagePreview* image_;
    PdfPreview* pdf_;
    QWidget* viz_tabs_ = nullptr;
    // CLOSURE-PREVIEW: dedicated loading page (message + optional 取消).
    QWidget* loading_page_ = nullptr;
    std::function<bool()> cancel_hook_;

    std::map<QString, QWidget*> targets_;
    std::map<QString, PreviewRenderHook> hooks_;
    std::function<void(const PreviewResultView&)> viz_load_summary_;
    std::function<void()> viz_reset_;
    std::function<void()> viz_show_loading_;
    std::function<void(const QString&, bool)> viz_show_error_;
    std::function<bool(const PreviewResultView&)> geoviz_show_;
};

}  // namespace pwb::ui_pages_data::qt
