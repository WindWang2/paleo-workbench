// UI-06 — data_detail_panel.py :: DataDetailPanel Qt shell.
//
// Metadata rows + inline preview (image/pdf/text lines). The preview
// strategy (preview_strategy.py — another slice) and the PDF document
// (Qt6::Pdf, optional) are injected seams.
#pragma once

#include <QFrame>

#include <functional>
#include <optional>
#include <string>
#include <vector>

#include <pwb/ui_pages_data/asset_view.hpp>
#include <pwb/ui_pages_data/qt/pdf_preview_panel.hpp>

class QLabel;
class QVBoxLayout;

namespace pwb::ui_pages_data::qt {

// preview_strategy.PreviewState seam.
struct DetailPreviewState {
    std::string mode = "metadata";  // image/pdf/text/table/metadata/artifact/...
    std::string title;
    std::vector<std::string> lines;
    std::string warning;
    std::string image_path;
    std::string document_path;
};

// resource|artifact → state. base_dir = project file's parent (Python
// base_path parity — injected through project_path()).
using DetailPreviewFn =
    std::function<DetailPreviewState(const AssetRow& asset,
                                     const std::string& base_dir)>;

class DataDetailPanel : public QFrame {
    Q_OBJECT
public:
    explicit DataDetailPanel(QWidget* parent = nullptr);

    void set_preview_fn(DetailPreviewFn fn) { preview_fn_ = std::move(fn); }
    void set_pdf_factory(PdfDocumentFactory fn) {
        pdf_factory_ = std::move(fn);
    }
    // Project file path used to resolve project-relative previews
    // (Python project_path attribute; owning page sets it).
    void set_project_path(const std::string& path) { project_path_ = path; }
    const std::string& project_path() const { return project_path_; }

    void update_asset(const std::optional<AssetRow>& asset);
    // Stage-9 freshness list: (label_or_op, state, state_label) rows.
    void show_downstream_impact(
        const std::vector<std::tuple<std::string, std::string,
                                     std::string>>& rows);

    QLabel* title_label() { return title_; }
    QLabel* preview_title() { return preview_title_; }

private:
    void clear_layout(QVBoxLayout* layout);
    void add_muted(QVBoxLayout* layout, const QString& text);
    void add_preview_line(const QString& text);
    void add_warning(const QString& text);
    void add_row(const QString& label, const QString& value);
    bool add_image_preview(const QString& path);
    bool add_pdf_preview(const QString& path);
    std::string base_dir() const;

    DetailPreviewFn preview_fn_;
    PdfDocumentFactory pdf_factory_;
    std::string project_path_;
    QLabel* title_;
    QLabel* preview_title_;
    QVBoxLayout* metadata_layout_;
    QVBoxLayout* preview_layout_;
};

}  // namespace pwb::ui_pages_data::qt
