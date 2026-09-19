#pragma once

// CLOSURE-SEISMIC (07 line) — product binding between the ui_wellseis
// SeismicPredictionPage and the real seismic display stack.
//
// The #1394 seam froze the page behind SeismicViewHooks / SeismicViewSeam
// with no host wiring: the panel's hooks were never set, so the product
// rendered an honest empty placeholder forever. This installer supplies the
// missing host side and nothing else:
//
//   * show_resource opens the selected volume through the host-owned
//     SeismicVolumeService (open_segy / open_pwbvol by storage suffix) and
//     embeds a real pwb::seismic_viewer::SeismicSliceWidget via
//     ui_wellseis RealSeismicViewBinding — a failed open reports the reason
//     and keeps the honest unavailable page (never a silent empty widget);
//   * display-mode tokens forward onto the viewer (RealSeismicViewBinding);
//   * attribute-panel selections run the frozen E-line single-trace kernels
//     (libs/seismic_attributes through the pwb::science SDK) on the viewer's
//     currently displayed plane and pin the result as an attribute view;
//     "RGB融合" fuses the last three computed attribute planes
//     (attribute_fusion_core::fuse_rgb). Structural kernels need 3-D
//     neighborhoods and are declined with the panel's honest reason text —
//     never faked on a 2-D section;
//   * a 04-line registration of the preview presenter is NOT done here: the
//     registry belongs to viz_e / closure-preview (04); this line ships the
//     real presenter at lib level (libs/ui_pages_preview).
//
// The binding object is parented to the page (plain QObject child, moc-free
// like the widgets it serves) and tears down with it.

#include <memory>
#include <string>

#include <QObject>
#include <QString>

namespace pwb::app {
class JobCenter;
}

namespace pwb::seismic_service {
class SeismicVolumeService;
}

namespace pwb::ui_wellseis::qt {
class SeismicPredictionPage;
}

namespace pwb::closure_seismic {

struct SeismicPageInstall {
    ui_wellseis::qt::SeismicPredictionPage* page = nullptr;
    // Host-owned volume service (tile-cache budget lives there). A null
    // service leaves every resource open honestly unavailable.
    seismic_service::SeismicVolumeService* volumes = nullptr;
};

class SeismicPageBinding : public QObject {
public:
    explicit SeismicPageBinding(const SeismicPageInstall& install,
                                QObject* parent = nullptr);
    ~SeismicPageBinding() override;

    SeismicPageBinding(const SeismicPageBinding&) = delete;
    SeismicPageBinding& operator=(const SeismicPageBinding&) = delete;

    // Currently bound volume file path ("" when nothing is bound) — the
    // view-state / diagnostics seam for hosts and tests.
    [[nodiscard]] std::string bound_volume_path() const;

    // The last honest-unavailable note (attribute/kernel declines); test
    // and host diagnostics seam.
    [[nodiscard]] std::string last_unavailable_reason() const;

    // Drives the same attribute handler the panel signal feeds (product
    // wiring: attribute_panel::attribute_changed -> this; tests call it
    // directly).
    void apply_attribute(const QString& label);

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

// Creates the page-owned binding (QObject parent = the page). Returns null
// when `install.page` is null (honest no-op, never a half binding).
[[nodiscard]] SeismicPageBinding*
install_seismic_page(const SeismicPageInstall& install);

} // namespace pwb::closure_seismic
