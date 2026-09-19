#include <pwb/ui_visualqa/qt/dual_volume_overlay.hpp>

#include <chrono>

#include <QButtonGroup>
#include <QComboBox>
#include <QFrame>
#include <QGroupBox>
#include <QHBoxLayout>
#include <QImage>
#include <QLabel>
#include <QPainter>
#include <QPen>
#include <QRadioButton>
#include <QSlider>
#include <QVBoxLayout>

namespace pwb::ui_visualqa::qt {

namespace {

QString qs(const std::string& s) {
    return QString::fromUtf8(s.data(), static_cast<qsizetype>(s.size()));
}

}  // namespace

// ==========================================================================
// DualVolumeOverlayWidget — proto widget parity
// ==========================================================================

DualVolumeOverlayWidget::DualVolumeOverlayWidget(
    const ScalarVolume& amp_vol, const ScalarVolume& coh_vol,
    QWidget* parent)
    : QWidget(parent),
      amp_vol_(amp_vol),
      coh_vol_(coh_vol),
      variant_(OverlayVariant::AlphaBlending),
      variant_label_(qs(variant_display_name(OverlayVariant::AlphaBlending))),
      axis_(kAxisTime),
      // Python: self.slice_idx = self.nz // 2 (nz=200 -> 100).
      slice_idx_(amp_vol.nz / 2),
      opacity_(0.5),
      threshold_(0.6) {}

void DualVolumeOverlayWidget::set_variant(const QString& variant_label) {
    variant_label_ = variant_label;
    variant_ = variant_from_label(variant_label.toStdString());
    update_render();
}

void DualVolumeOverlayWidget::set_slice(int axis, int idx) {
    axis_ = axis;
    slice_idx_ = idx;
    update_render();
}

void DualVolumeOverlayWidget::set_opacity(double value) {
    opacity_ = value;
    update_render();
}

void DualVolumeOverlayWidget::set_threshold(double value) {
    threshold_ = value;
    update_render();
}

void DualVolumeOverlayWidget::update_render() {
    const auto t0 = std::chrono::steady_clock::now();

    const Slice2D amp_slice = extract_slice(amp_vol_, axis_, slice_idx_);
    const Slice2D coh_slice = extract_slice(coh_vol_, axis_, slice_idx_);
    const RgbaImage img =
        render_overlay_rgba(amp_slice, coh_slice, variant_, opacity_,
                            threshold_);

    if (img.w > 0 && img.h > 0) {
        // QImage does not own the buffer — deep-copy before QPixmap.
        const QImage qimg(img.rgba.data(), img.w, img.h, img.w * 4,
                          QImage::Format::Format_RGBA8888);
        pixmap_ = QPixmap::fromImage(qimg.copy());
    } else {
        pixmap_ = QPixmap();
    }

    last_render_ms_ =
        std::chrono::duration<double, std::milli>(
            std::chrono::steady_clock::now() - t0)
            .count();
    update();
}

void DualVolumeOverlayWidget::paintEvent(QPaintEvent* event) {
    (void)event;
    QPainter painter(this);
    painter.fillRect(rect(), QColor(QStringLiteral("#12141C")));

    if (!pixmap_.isNull()) {
        // Draw overlay image scaled to viewport (KeepAspectRatio +
        // SmoothTransformation parity), centered.
        const QPixmap scaled = pixmap_.scaled(
            size(), Qt::AspectRatioMode::KeepAspectRatio,
            Qt::TransformationMode::SmoothTransformation);
        const int x = (width() - scaled.width()) / 2;
        const int y = (height() - scaled.height()) / 2;
        painter.drawPixmap(x, y, scaled);
    }

    // [PROTOTYPE STATE READOUT] overlay — same facts, same anchor.
    painter.setPen(QColor(QStringLiteral("#00E5FF")));
    painter.setFont(QFont(QStringLiteral("Monospace"), 10,
                          QFont::Weight::Bold));
    const double fps = 1000.0 / std::max(0.1, last_render_ms_);
    const QString readout =
        QStringLiteral("[PROTOTYPE STATE READOUT]\n"
                       "Active Variant : %1\n"
                       "Current Axis   : %2\n"
                       "Slice Index    : %3\n"
                       "Opacity        : %4\n"
                       "Threshold      : %5\n"
                       "Render Time    : %6 ms (%7 FPS)")
            .arg(variant_label_)
            .arg(qs(axis_display_name(axis_)))
            .arg(slice_idx_)
            .arg(opacity_, 0, 'f', 2)
            .arg(threshold_, 0, 'f', 2)
            .arg(last_render_ms_, 0, 'f', 2)
            .arg(fps, 0, 'f', 0);
    painter.drawText(15, 25, readout);
}

// ==========================================================================
// ProtoDualVolumeWindow — MainWindow parity
// ==========================================================================

ProtoDualVolumeWindow::ProtoDualVolumeWindow(QWidget* parent)
    : QMainWindow(parent) {
    setWindowTitle(QStringLiteral(
        "PROTOTYPE — 3D Seismic Dual-Volume Overlay & Blending "
        "(Throwaway Code)"));
    resize(1000, 750);

    // generate_synthetic_seismic_volumes(200, 200, 200) parity.
    SyntheticVolumes volumes = generate_synthetic_seismic_volumes(200, 200, 200);

    auto* central = new QWidget(this);
    setCentralWidget(central);
    auto* main_layout = new QVBoxLayout(central);

    // -- Top control bar (Interactive Overlay Controls (PROTOTYPE)) -------
    auto* ctrl_box =
        new QGroupBox(QStringLiteral("Interactive Overlay Controls "
                                     "(PROTOTYPE)"), central);
    auto* ctrl_layout = new QHBoxLayout(ctrl_box);

    ctrl_layout->addWidget(new QLabel(QStringLiteral("Axis:"), ctrl_box));
    axis_combo_ = new QComboBox(ctrl_box);
    axis_combo_->addItems({QStringLiteral("Inline"),
                           QStringLiteral("Crossline"),
                           QStringLiteral("Time")});
    axis_combo_->setCurrentIndex(2);
    connect(axis_combo_,
            QOverload<int>::of(&QComboBox::currentIndexChanged), this,
            [this](int idx) {
                canvas_->set_slice(idx, slice_slider_->value());
            });
    ctrl_layout->addWidget(axis_combo_);

    ctrl_layout->addWidget(new QLabel(QStringLiteral("Slice:"), ctrl_box));
    slice_slider_ = new QSlider(Qt::Orientation::Horizontal, ctrl_box);
    slice_slider_->setRange(0, 199);
    slice_slider_->setValue(100);
    connect(slice_slider_, &QSlider::valueChanged, this, [this](int val) {
        canvas_->set_slice(axis_combo_->currentIndex(), val);
    });
    ctrl_layout->addWidget(slice_slider_);

    ctrl_layout->addWidget(new QLabel(QStringLiteral("Opacity:"), ctrl_box));
    opacity_slider_ = new QSlider(Qt::Orientation::Horizontal, ctrl_box);
    opacity_slider_->setRange(0, 100);
    opacity_slider_->setValue(50);
    connect(opacity_slider_, &QSlider::valueChanged, this, [this](int val) {
        canvas_->set_opacity(val / 100.0);
    });
    ctrl_layout->addWidget(opacity_slider_);

    ctrl_layout->addWidget(
        new QLabel(QStringLiteral("Threshold:"), ctrl_box));
    thresh_slider_ = new QSlider(Qt::Orientation::Horizontal, ctrl_box);
    thresh_slider_->setRange(0, 100);
    thresh_slider_->setValue(60);
    connect(thresh_slider_, &QSlider::valueChanged, this, [this](int val) {
        canvas_->set_threshold(val / 100.0);
    });
    ctrl_layout->addWidget(thresh_slider_);

    main_layout->addWidget(ctrl_box);

    // -- Prototype canvas -------------------------------------------------
    canvas_ = new DualVolumeOverlayWidget(volumes.amplitude,
                                          volumes.coherence, central);
    main_layout->addWidget(canvas_, /*stretch*/ 1);

    // -- Bottom variant switcher bar --------------------------------------
    auto* variant_box = new QFrame(central);
    variant_box->setStyleSheet(QStringLiteral(
        "QFrame { background: #1B1E2B; border-top: 2px solid #00E5FF; "
        "padding: 6px; }"));
    auto* variant_layout = new QHBoxLayout(variant_box);
    variant_layout->addWidget(
        new QLabel(QStringLiteral("<b>UI VARIANT SWITCHER:</b>"),
                   variant_box));

    auto* btn_a = new QRadioButton(
        QStringLiteral("Variant A: Alpha Blending"), variant_box);
    auto* btn_b = new QRadioButton(
        QStringLiteral("Variant B: RGB Multi-Channel Fusion"), variant_box);
    auto* btn_c = new QRadioButton(
        QStringLiteral("Variant C: Coherence Masking Overlay"), variant_box);
    btn_a->setChecked(true);

    var_group_ = new QButtonGroup(this);
    var_group_->addButton(btn_a, 0);
    var_group_->addButton(btn_b, 1);
    var_group_->addButton(btn_c, 2);
    connect(var_group_, &QButtonGroup::idToggled, this,
            [this](int id, bool checked) {
                if (!checked) return;
                static const char* kVariants[] = {
                    "Variant A: Alpha Blending",
                    "Variant B: RGB Multi-Channel Fusion",
                    "Variant C: Coherence Masking Overlay",
                };
                canvas_->set_variant(QString::fromUtf8(kVariants[id]));
            });

    variant_layout->addWidget(btn_a);
    variant_layout->addWidget(btn_b);
    variant_layout->addWidget(btn_c);
    variant_layout->addStretch();

    main_layout->addWidget(variant_box);

    // Initial render (MainWindow.__init__ tail parity).
    canvas_->update_render();
}

}  // namespace pwb::ui_visualqa::qt
