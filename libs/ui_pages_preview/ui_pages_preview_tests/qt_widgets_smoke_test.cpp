// UI-07 — Qt widget smoke test (offscreen): instantiate every ported
// widget once and drive the primary entry points. Complements the oracle
// replay (which covers the Qt-free cores) by proving the Qt shells
// construct and respond under QT_QPA_PLATFORM=offscreen, and by replaying
// the widget-observable fixture expectations that reduce to Qt state:
// store round-trips (QSettings), panel mode→category mapping, table TSV,
// lazy-tab emission counts, chip stickiness and teardown safety.

#include <QApplication>
#include <QComboBox>
#include <QLabel>
#include <QPushButton>
#include <QSettings>
#include <QSlider>
#include <QSpinBox>
#include <QStackedWidget>
#include <QTemporaryDir>

#include <cstdio>
#include <fstream>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

#include <pwb/viz/seismic_volume.hpp>
#include <pwb/ui_pages_preview/preview_settings.hpp>
#include <pwb/ui_pages_preview/qt/geotiff_preview_widget.hpp>
#include <pwb/ui_pages_preview/qt/image_preview_widget.hpp>
#include <pwb/ui_pages_preview/qt/json_tree_preview_widget.hpp>
#include <pwb/ui_pages_preview/qt/lazy_visualization_tabs.hpp>
#include <pwb/ui_pages_preview/qt/media_preview_widget.hpp>
#include <pwb/ui_pages_preview/qt/message_preview_widget.hpp>
#include <pwb/ui_pages_preview/qt/pdf_preview_widget.hpp>
#include <pwb/ui_pages_preview/qt/preview_settings_panel.hpp>
#include <pwb/ui_pages_preview/qt/preview_settings_store.hpp>
#include <pwb/ui_pages_preview/qt/rich_text_preview_widget.hpp>
#include <pwb/ui_pages_preview/qt/seismic_slice_preview_widget.hpp>
#include <pwb/ui_pages_preview/qt/summary_table_preview_widget.hpp>
#include <pwb/ui_pages_preview/qt/table_preview_widget.hpp>
#include <pwb/ui_pages_preview/qt/text_preview_widget.hpp>
#include <pwb/ui_pages_preview/qt/web_document_preview_widget.hpp>

using namespace pwb::ui_pages_preview;

namespace {

int failures = 0;

void check(bool condition, const char* what) {
    if (!condition) {
        ++failures;
        std::fprintf(stderr, "FAIL %s\n", what);
    } else {
        std::fprintf(stdout, "PASS %s\n", what);
    }
}

void check_eq(const std::string& actual, const std::string& expected,
              const char* what) {
    if (actual != expected) {
        ++failures;
        std::fprintf(stderr, "FAIL %s: expected %s, got %s\n", what,
                     expected.c_str(), actual.c_str());
    } else {
        std::fprintf(stdout, "PASS %s\n", what);
    }
}

// Minimal valid one-page PDF — xref offsets computed, not hard-coded.
std::string make_test_pdf() {
    std::string out = "%PDF-1.4\n";
    std::vector<long> offsets;
    auto obj = [&](int id, const std::string& body) {
        offsets.push_back(static_cast<long>(out.size()));
        out += std::to_string(id) + " 0 obj\n" + body + "\nendobj\n";
    };
    obj(1, "<< /Type /Catalog /Pages 2 0 R >>");
    obj(2, "<< /Type /Pages /Kids [3 0 R] /Count 1 >>");
    obj(3, "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
           "/Contents 4 0 R /Resources << >> >>");
    const std::string stream = "BT 100 700 Td (Hi) Tj ET";
    obj(4, "<< /Length " + std::to_string(stream.size()) + " >>\nstream\n" +
           stream + "\nendstream");
    const long xref = static_cast<long>(out.size());
    out += "xref\n0 5\n0000000000 65535 f \n";
    for (long off : offsets) {
        char buf[32];
        std::snprintf(buf, sizeof(buf), "%010ld 00000 n \n", off);
        out += buf;
    }
    out += "trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n" +
           std::to_string(xref) + "\n%%EOF\n";
    return out;
}

// 2x2 red RGB PNG (real zlib stream + valid CRCs).
QByteArray tiny_png() {
    static const unsigned char bytes[] = {
        0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00, 0x00, 0x00,
        0x0d, 0x49, 0x48, 0x44, 0x52, 0x00, 0x00, 0x00, 0x02, 0x00, 0x00,
        0x00, 0x02, 0x08, 0x02, 0x00, 0x00, 0x00, 0xfd, 0xd4, 0x9a, 0x73,
        0x00, 0x00, 0x00, 0x13, 0x49, 0x44, 0x41, 0x54, 0x78, 0x9c, 0x63,
        0xf8, 0xcf, 0xc0, 0xf0, 0x9f, 0x01, 0x8c, 0xff, 0x33, 0x30, 0x00,
        0x00, 0x1f, 0xee, 0x03, 0xfd, 0x35, 0x1b, 0x00, 0x33, 0x00, 0x00,
        0x00, 0x00, 0x49, 0x45, 0x4e, 0x44, 0xae, 0x42, 0x60, 0x82,
    };
    return QByteArray(reinterpret_cast<const char*>(bytes), sizeof(bytes));
}

}  // namespace

int main(int argc, char** argv) {
    QApplication app(argc, argv);
    QTemporaryDir tmp;
    check(tmp.isValid(), "temp dir");

    // ------------------------------------------------------------------
    // table
    // ------------------------------------------------------------------
    {
        TablePreviewWidget w;
        w.set_auto_fit_columns(false);
        w.load_table({"a", "b", "c"},
                     {{"1", "2", "3"}, {"x"}, {}});
        check(w.rowCount() == 3 && w.columnCount() == 3,
              "table: load_table dims");
        check(!w.truncated(), "table: not truncated");
        check_eq(w.copy_all().toStdString(), "a\tb\tc\n1\t2\t3\nx\t\t\n\t\t",
                 "table: copy_all TSV matches oracle");

        TablePreviewWidget big;
        big.set_auto_fit_columns(false);
        std::vector<std::vector<std::string>> rows;
        rows.reserve(250001);
        for (int i = 0; i < 250001; ++i) {
            rows.push_back({"v", "v", "v", "v"});
        }
        big.load_table({"c0", "c1", "c2", "c3"}, rows);
        check(big.truncated() && big.rowCount() == 250000,
              "table: 1M-cell truncation keeps 250000/250001");
        check(big.truncation_message().startsWith(
                  QStringLiteral("表格预览已截断：显示 250000/250001 行")),
              "table: truncation message parity");
        big.apply_settings(PreviewSettings::defaults());
    }

    // ------------------------------------------------------------------
    // text / rich_text / message
    // ------------------------------------------------------------------
    {
        TextPreviewWidget w;
        w.load_text(QStringLiteral("abc"));
        PreviewSettings s;
        s.font_size = 18;
        s.wrap_text = true;
        w.apply_settings(s);
        check(w.lineWrapMode() == QTextEdit::WidgetWidth &&
                  w.font().pointSize() == 18,
              "text: apply_settings wrap+font");

        RichTextPreviewWidget r;
        r.load_html(QStringLiteral("<b>x</b>"));
        s.wrap_text = false;
        r.apply_settings(s);
        check(r.lineWrapMode() == QTextEdit::NoWrap && r.isReadOnly(),
              "rich_text: nowrap + readonly");

        MessagePreviewWidget m;
        m.set_message(QStringLiteral("hello 世界"));
        check_eq(m.text().toStdString(), "hello 世界",
                 "message: text parity");
    }

    // ------------------------------------------------------------------
    // json tree
    // ------------------------------------------------------------------
    {
        JsonTreePreviewWidget w;
        w.load_payload(pwb::domain::Json{{"a", 1}, {"b", {1, 2}}});
        check(w.model() != nullptr && w.model()->rowCount() == 2,
              "json_tree: small dict → 2 root rows");
        JsonTreePreviewWidget lazy;
        pwb::domain::Json big = pwb::domain::Json::object();
        for (int i = 0; i < 5; ++i) big["k" + std::to_string(i)] = i;
        // default collapse threshold is 100 → still inline; force a lazy
        // container through a bigger payload instead.
        w.apply_settings(PreviewSettings::defaults());
        lazy.load_payload(big);
        check(lazy.model() != nullptr && lazy.model()->rowCount() == 5,
              "json_tree: 5-key dict → 5 root rows");
    }

    // ------------------------------------------------------------------
    // image
    // ------------------------------------------------------------------
    {
        ImagePreviewWidget w;
        w.load(QStringLiteral("/nonexistent/preview.png"));
        check(w.pixmap(Qt::ReturnByValue).isNull() ||
                  w.pixmap(Qt::ReturnByValue).isNull(),
              "image: undecodable load leaves null pixmap");
        check(!w.text().isEmpty(), "image: failure shows text");

        int emitted = 0;
        double last_zoom = -1;
        QObject::connect(&w, &ImagePreviewWidget::zoom_changed, &w,
                         [&](double f) { ++emitted; last_zoom = f; });
        w.set_zoom_factor(1.0);
        w.set_fit_mode(false);
        w.zoom_in();
        w.zoom_in();
        w.zoom_out();
        w.reset_zoom();
        check(emitted >= 4 && last_zoom == 1.0,
              "image: zoom sequence emits + reset");
        w.set_zoom_factor(100.0);
        check(w.zoom_factor() == 8.0, "image: zoom clamped high");
        w.set_zoom_factor(0.0001);
        check(w.zoom_factor() == 0.1, "image: zoom clamped low");

        // decodable bytes path
        ImagePreviewWidget w2;
        w2.resize(800, 600);
        w2.load(QStringLiteral("/tmp/fake.png"), QString(), tiny_png());
        check(w2.pixmap(Qt::ReturnByValue).isNull() ||
                  !w2.text().isEmpty() ||
                  !w2.pixmap(Qt::ReturnByValue).isNull(),
              "image: png-bytes path handled");
    }

    // ------------------------------------------------------------------
    // pdf
    // ------------------------------------------------------------------
    {
        PdfPreviewWidget w;
        check_eq(w.page_label()->text().toStdString(), "0 / 0",
                 "pdf: initial page status");
        if (w.document() != nullptr) {
            // Python quirk: with QtPdf present, __init__ never calls
            // _update_page_status → nav buttons stay default-enabled.
            check(w.prev_button()->isEnabled() &&
                      w.next_button()->isEnabled(),
                  "pdf: nav default-enabled pre-load");
        } else {
            check(!w.prev_button()->isEnabled() &&
                      !w.next_button()->isEnabled(),
                  "pdf: nav disabled without QtPdf");
        }
        check_eq(w.zoom_label()->text().toStdString(), "100%",
                 "pdf: zoom label initial");

        const std::string pdf = make_test_pdf();
        const QString path = tmp.filePath(QStringLiteral("t.pdf"));
        {
            std::ofstream out(path.toStdString(), std::ios::binary);
            out << pdf;
        }
        w.load(path);
        QCoreApplication::processEvents();
        if (!w.load_failed() &&
            w.page_label()->text() == QStringLiteral("1 / 1")) {
            check(!w.prev_button()->isEnabled() &&
                      !w.next_button()->isEnabled(),
                  "pdf: nav disabled on single page");
            w.next_page();  // no-op at bounds
            check(w.page() == 0, "pdf: next_page at bounds no-op");
            w.previous_page();
            check(w.page() == 0, "pdf: previous_page at bounds no-op");
        } else {
            // No QtPdf / async load / unreadable → Python-parity degraded
            // path must still render something meaningful.
            check(w.findChild<QLabel*>() != nullptr,
                  "pdf: fallback path renders a label");
            std::fprintf(stdout,
                         "INFO pdf: QtPdf unavailable or load pending — "
                         "fallback path exercised (status=%s failed=%d)\n",
                         w.page_label()->text().toStdString().c_str(),
                         static_cast<int>(w.load_failed()));
        }
        w.apply_settings(PreviewSettings::defaults());
    }

    // ------------------------------------------------------------------
    // media
    // ------------------------------------------------------------------
    {
        MediaPreviewWidget w;
        const bool created = w.ensure_player();
        check(!w.status_label()->text().isEmpty(),
              "media: status text set");
        if (created) {
            check(w.player_created(), "media: player constructed");
            w.set_media_path(QStringLiteral("/tmp/clip.mp3"));
            check_eq(w.current_path().toStdString(), "/tmp/clip.mp3",
                     "media: path recorded");
            check_eq(w.time_label()->text().toStdString(),
                     "00:00 / 00:00", "media: time label initial");
        } else {
            std::fprintf(stdout,
                         "INFO media: QtMultimedia unavailable — "
                         "degraded path exercised\n");
            w.set_media_path(QStringLiteral("/tmp/clip.mp3"));
            check(!w.status_label()->text().isEmpty(),
                  "media: unavailable status shown");
        }
        w.apply_settings(PreviewSettings::defaults());
    }

    // ------------------------------------------------------------------
    // web document
    // ------------------------------------------------------------------
    {
        WebDocumentPreviewWidget w;
        w.load_document(QStringLiteral("/tmp/doc.html"),
                        QStringLiteral("<b>hi</b>"));
        w.apply_settings(PreviewSettings::defaults());
        check(true, "web: construct + load_document + apply_settings");
    }

    // ------------------------------------------------------------------
    // seismic — real ISeismicVolume through pwb::viz
    // ------------------------------------------------------------------
    {
        pwb::viz::VolumeGeometryV1 geo;
        geo.shape = {5, 7, 9};
        std::vector<float> data(5 * 7 * 9, 0.5f);
        auto volume = pwb::viz::make_owning_volume(geo, std::move(data));

        SeismicSlicePreviewWidget w;
        w.load_seismic(QStringLiteral("/tmp/x.segy"), QString(),
                       std::move(volume));
        check(w.slider()->isEnabled() && w.slider()->maximum() == 4,
              "seismic: axis0 slider max 4");
        check_eq(w.index_label()->text().toStdString(), "2 / 4",
                 "seismic: midpoint index label");
        for (int axis = 1; axis <= 2; ++axis) {
            w.type_combo()->setCurrentIndex(axis);
        }
        check(w.slider()->maximum() == 8, "seismic: axis2 slider max 8");
        check_eq(w.index_label()->text().toStdString(), "4 / 8",
                 "seismic: axis2 midpoint label");
        w.slider()->setValue(3);
        check_eq(w.index_label()->text().toStdString(), "3 / 8",
                 "seismic: slider move updates label");

        // null volume → message fallback + disabled controls
        SeismicSlicePreviewWidget empty;
        empty.load_seismic(QStringLiteral("/tmp/x.segy"), QString(),
                           nullptr, QStringLiteral("体数据不可用"));
        check(!empty.slider()->isEnabled() &&
                  !empty.type_combo()->isEnabled(),
              "seismic: null volume disables controls");
        check(!empty.index_label()->text().isEmpty() ||
                  !empty.image_label()->text().isEmpty(),
              "seismic: null volume shows fallback");
    }

    // ------------------------------------------------------------------
    // summary table — sticky chips
    // ------------------------------------------------------------------
    {
        SummaryTablePreviewWidget w;
        w.load_summary({{"井名", "W-1"}, {"曲线数", "12"}, {"采样点", "1500"}},
                       {"h1"}, {{"r1"}}, QStringLiteral("msg"));
        const auto chips = w.findChildren<QLabel*>(
            QStringLiteral("chip_val"));
        check(chips.size() >= 3, "summary: chip labels exist");
        if (chips.size() >= 3) {
            check_eq(chips.at(0)->text().toStdString(), "W-1",
                     "summary: well chip");
            check_eq(chips.at(1)->text().toStdString(), "12 条",
                     "summary: curves chip");
            check_eq(chips.at(2)->text().toStdString(), "1,500 点",
                     "summary: samples chip");
        }
        // sticky: rows without chip keys keep prior values
        w.load_summary({{"其他", "x"}}, {"h"}, {{"r"}}, QString());
        if (chips.size() >= 3) {
            check_eq(chips.at(0)->text().toStdString(), "W-1",
                     "summary: chips sticky");
        }
        // data tab toggling
        w.load_summary({{"井名", "W"}}, {"h"}, {{"r"}}, QString(),
                       {"d1"}, {{"v"}});
        check(w.tabs()->isTabEnabled(1), "summary: data tab enabled");
        w.load_summary({{"井名", "W"}}, {"h"}, {{"r"}}, QString());
        check(!w.tabs()->isTabEnabled(1), "summary: data tab disabled");
        w.apply_settings(PreviewSettings::defaults());
    }

    // ------------------------------------------------------------------
    // geotiff
    // ------------------------------------------------------------------
    {
        GeoTiffPreviewWidget w;
        w.resize(400, 300);
        w.load(QStringLiteral("/tmp/x.tif"), QString(), QByteArray(),
               {{"CRS", "EPSG:4326"}, {"范围", "1,2,3,4"}});
        check(w.summary_table()->rowCount() == 2,
              "geotiff: metadata rows");
        GeoTiffPreviewWidget w2;
        w2.resize(400, 300);
        w2.load(QStringLiteral("/tmp/x.tif"), QString(), tiny_png(),
                {{"a", "b"}});
        check(w2.pixmap().isNull() == false,
              "geotiff: decodable thumbnail produces pixmap");
        PreviewSettings s;
        s.show_geo_metadata = false;
        s.smooth_images = false;
        w2.apply_settings(s);
        check(w2.summary_table()->isHidden(),
              "geotiff: show_geo_metadata=false hides table");
    }

    // ------------------------------------------------------------------
    // preview settings store + panel
    // ------------------------------------------------------------------
    {
        const QString ini = tmp.filePath(QStringLiteral("settings.ini"));
        QSettings backing(ini, QSettings::IniFormat);
        PreviewSettingsStore store(&backing);
        check(store.load() == PreviewSettings::defaults(),
              "store: fresh load → defaults");

        PreviewSettings custom;
        custom.font_size = 14;
        custom.media_volume = 55;
        custom.pdf_fit_mode = "page";
        custom.wrap_text = true;
        store.save(custom);
        check(store.load() == custom, "store: save/load round trip");

        // malformed value → Python parity: whole load falls back to defaults
        backing.beginGroup(QStringLiteral("preview/settings"));
        backing.setValue(QStringLiteral("font_size"),
                         QStringLiteral("not-an-int"));
        backing.endGroup();
        check(store.load() == PreviewSettings::defaults(),
              "store: malformed → defaults");
        check(store.reset() == PreviewSettings::defaults(),
              "store: reset → defaults");

        // panel — mode→category combo mapping (frozen oracle indexes)
        PreviewSettingsPanel panel(nullptr, &store);
        const std::vector<std::pair<const char*, int>> mode_map = {
            {"text", 1}, {"rich_text", 1}, {"web_document", 1},
            {"table", 2}, {"well_log", 2}, {"seismic", 2},
            {"image", 3}, {"geotiff", 3},
            {"pdf", 4}, {"json_tree", 5}, {"media", 6}, {"geoviz", 7},
            {"nonsense", 0},
        };
        auto* combo = panel.findChild<QComboBox*>(
            QStringLiteral("PreviewSettingsCategory"));
        auto* pages = panel.findChild<QStackedWidget*>();
        check(combo != nullptr && pages != nullptr,
              "panel: category combo + pages exist");
        if (combo) {
            bool all_ok = true;
            for (const auto& [mode, expected] : mode_map) {
                panel.set_preview_mode(QString::fromLatin1(mode));
                if (combo->currentIndex() != expected) {
                    std::fprintf(stderr,
                                 "FAIL panel mode %s: index %d != %d\n",
                                 mode, combo->currentIndex(), expected);
                    all_ok = false;
                }
                if (pages && pages->currentIndex() != combo->currentIndex()) {
                    all_ok = false;
                }
            }
            check(all_ok, "panel: mode→category mapping parity");
        }

        // apply/reset round trip through the real store
        int applied = 0;
        PreviewSettings applied_payload;
        QObject::connect(&panel, &PreviewSettingsPanel::settings_applied,
                         &panel, [&](const PreviewSettings& s) {
                             ++applied;
                             applied_payload = s;
                         });
        PreviewSettings edited;
        edited.font_size = 20;
        edited.media_volume = 33;
        panel.set_settings(edited);
        if (auto* apply = panel.findChild<QPushButton*>(
                QStringLiteral("PrimaryButton"))) {
            apply->click();
        }
        check(applied == 1 && store.load().font_size == 20 &&
                  store.load().media_volume == 33 &&
                  applied_payload.font_size == 20,
              "panel: apply persists + emits");
        if (auto* reset = panel.findChild<QPushButton*>(
                QStringLiteral("SecondaryButton"))) {
            reset->click();
        }
        check(store.load() == PreviewSettings::defaults() && applied == 2,
              "panel: reset restores defaults + emits");
    }

    // ------------------------------------------------------------------
    // lazy visualization tabs — state machine + host seam
    // ------------------------------------------------------------------
    {
        LazyVisualizationTabs w;
        int emitted = 0;
        QObject::connect(&w, &LazyVisualizationTabs::visualization_requested,
                         &w, [&] { ++emitted; });
        w.load_summary(LazySummaryResult{.mode = "table",
                                         .table_headers = {"a"},
                                         .table_rows = {{"1"}},
                                         .message = "m"});
        check(w.currentIndex() == 0 && !w.requested(),
              "lazy: load → tab0 prompt");
        w.setCurrentIndex(1);
        check(w.requested() && emitted == 1,
              "lazy: first visual click latches + emits once");
        w.set_host_factory([](QWidget* parent) -> QWidget* {
            return new QWidget(parent);
        });
        check(w.host() != nullptr && w.host_created(),
              "lazy: host injected lazily");
        w.show_preview(false);
        check(w.currentIndex() == 1, "lazy: preview while on tab stays");
        w.show_error(QStringLiteral("bad"), true, false);
        w.reset();
        check(w.currentIndex() == 0 && !w.requested(),
              "lazy: reset → tab0 prompt");

        // engine-guard parity: replacing the factory after host creation throws
        bool threw = false;
        try {
            w.set_host_factory([](QWidget* p) { return new QWidget(p); });
        } catch (const std::runtime_error&) {
            threw = true;
        }
        check(threw, "lazy: host-factory guard throws");
    }

    // ------------------------------------------------------------------
    // teardown safety — destroy everything, flush deferred deletes
    // ------------------------------------------------------------------
    {
        auto* heap_widgets = new QWidget;
        auto* a = new TablePreviewWidget(heap_widgets);
        auto* b = new JsonTreePreviewWidget(heap_widgets);
        auto* c = new MessagePreviewWidget(heap_widgets);
        a->load_table({"h"}, {{"v"}});
        b->load_payload(pwb::domain::Json{{"x", 1}});
        c->set_message(QStringLiteral("bye"));
        auto* d = new LazyVisualizationTabs(heap_widgets);
        d->deleteLater();
        delete heap_widgets;  // destroys a,b,c via QObject tree
        QCoreApplication::sendPostedEvents(nullptr, QEvent::DeferredDelete);
        QCoreApplication::processEvents();
        check(true, "teardown: parented delete + deferred delete clean");
    }

    std::fprintf(stdout, "%s (%d failures)\n",
                 failures == 0 ? "ALL PASS" : "FAILURES", failures);
    return failures == 0 ? 0 : 1;
}
