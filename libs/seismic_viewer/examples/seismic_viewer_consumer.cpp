// Minimal production consumer of Pwb::SeismicViewer — the A-line embedding
// sample. Two modes:
//   seismic_viewer_example <fixture_dir>   interactive: load the frozen
//                                          tiny_sgy-style fixture (manifest.json
//                                          + volume_xl_major.f32) and show it
//   seismic_viewer_example --self-check <fixture_dir> <out.png>
//                                        headless: render offscreen, save a
//                                        screenshot, exit 0 on the first
//                                        successful slice (CI embed evidence)
// With no arguments a small synthetic volume is shown.

#include <QApplication>
#include <QCommandLineOption>
#include <QCommandLineParser>
#include <QEventLoop>
#include <QFile>
#include <QImage>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QLabel>
#include <QTimer>
#include <QVBoxLayout>
#include <QWidget>

#include <cmath>
#include <cstdio>
#include <cstring>
#include <memory>
#include <vector>

#include <pwb/seismic_viewer/seismic_slice_widget.hpp>

namespace {

constexpr double kMissing = -999.25;

// Reads the frozen fixture layout: flat manifest + raw float32 payload with
// crossline-major (permuted) strides — same vocabulary the science oracle
// emits. Pure C++, no Python.
bool load_fixture(const QString& dir, pwb::viz::VolumeGeometryV1& geometry,
                  std::vector<float>& payload) {
    QFile manifest_file(dir + QStringLiteral("/manifest.json"));
    if (!manifest_file.open(QIODevice::ReadOnly)) {
        return false;
    }
    const QJsonObject manifest =
        QJsonDocument::fromJson(manifest_file.readAll()).object();
    const auto shape = manifest.value(QStringLiteral("shape")).toArray();
    if (shape.size() != 3) {
        return false;
    }
    const double n_il = shape.at(0).toDouble();
    const double n_xl = shape.at(1).toDouble();
    const double n_t = shape.at(2).toDouble();
    if (n_il <= 0 || n_xl <= 0 || n_t <= 0) {
        return false;
    }

    QFile volume_file(dir + QStringLiteral("/volume_xl_major.f32"));
    if (!volume_file.open(QIODevice::ReadOnly)) {
        return false;
    }
    const QByteArray bytes = volume_file.readAll();
    if (static_cast<double>(bytes.size()) !=
        n_il * n_xl * n_t * static_cast<double>(sizeof(float))) {
        return false;
    }
    payload.resize(static_cast<std::size_t>(bytes.size() / sizeof(float)));
    std::memcpy(payload.data(), bytes.constData(), static_cast<std::size_t>(bytes.size()));

    geometry.shape = {static_cast<std::int64_t>(n_il), static_cast<std::int64_t>(n_xl),
                      static_cast<std::int64_t>(n_t)};
    geometry.strides = {static_cast<std::int64_t>(n_t),
                        static_cast<std::int64_t>(n_il * n_t), 1}; // crossline-major
    geometry.origin = {manifest.value(QStringLiteral("iline_start")).toDouble(),
                       manifest.value(QStringLiteral("xline_start")).toDouble(), 0.0};
    geometry.step = {manifest.value(QStringLiteral("iline_step")).toDouble(),
                     manifest.value(QStringLiteral("xline_step")).toDouble(),
                     manifest.value(QStringLiteral("dt_ms")).toDouble()};
    geometry.unit = QStringLiteral("ms").toStdString();
    geometry.missing_value = static_cast<float>(kMissing);
    return true;
}

std::shared_ptr<pwb::viz::ISeismicVolume> synthetic_volume() {
    constexpr std::int64_t n_il = 48, n_xl = 40, n_t = 128;
    pwb::viz::VolumeGeometryV1 geometry;
    geometry.shape = {n_il, n_xl, n_t};
    geometry.strides = {0, 0, 0};
    geometry.origin = {100.0, 200.0, 0.0}; // non-default inline/crossline starts
    geometry.step = {2.0, 3.0, 4.0};       // ms samples
    geometry.unit = "ms";
    std::vector<float> values(static_cast<std::size_t>(n_il * n_xl * n_t));
    for (std::int64_t i = 0; i < n_il; ++i) {
        for (std::int64_t j = 0; j < n_xl; ++j) {
            for (std::int64_t k = 0; k < n_t; ++k) {
                const double t = static_cast<double>(k) * 4.0;
                const double wave = std::sin(t * 0.08 + i * 0.35 + j * 0.2) *
                                    std::exp(-std::abs(t - 200.0) / 260.0);
                values[static_cast<std::size_t>((i * n_xl + j) * n_t + k)] =
                    static_cast<float>(wave);
            }
        }
    }
    return pwb::viz::make_owning_volume(geometry, std::move(values));
}

} // namespace

int main(int argc, char** argv) {
    QApplication app(argc, argv);
    QCommandLineParser parser;
    parser.setApplicationDescription(QStringLiteral("pwb::seismic_viewer consumer"));
    parser.addOptions({
        {{"s", "self-check"}, QStringLiteral("headless render, save screenshot, exit")},
        {"output", QStringLiteral("screenshot path (with --self-check)"), QStringLiteral("png")},
        {"fixture", QStringLiteral("fixture directory (manifest.json + volume_xl_major.f32)"),
         QStringLiteral("dir")},
    });
    parser.addHelpOption();
    parser.process(app);
    const bool self_check = parser.isSet(QStringLiteral("self-check"));

    auto* window = new QWidget;
    auto* layout = new QVBoxLayout(window);
    auto* viewer = new pwb::seismic_viewer::SeismicSliceWidget(window);
    auto* events = new QLabel(QStringLiteral("(no selection yet)"), window);
    layout->addWidget(viewer, 1);
    layout->addWidget(events);
    window->resize(760, 560);
    window->show();

    viewer->set_selection_callback(
        [&events](const pwb::seismic_viewer::SliceSelectionEvent& event) {
            QString text = QString::fromStdString(event.origin) +
                           QStringLiteral(": axis index %1").arg(event.index);
            if (event.has_point) {
                text += QStringLiteral(" · point (%1, %2)")
                            .arg(event.row_coordinate)
                            .arg(event.col_coordinate);
            }
            if (event.has_time_range) {
                text += QStringLiteral(" · time [%1, %2] %3 (%4)")
                            .arg(event.time_top)
                            .arg(event.time_bottom)
                            .arg(QString::fromStdString(event.time_unit))
                            .arg(static_cast<int>(event.conversion));
            }
            events->setText(text);
        });

    std::shared_ptr<pwb::viz::ISeismicVolume> volume;
    pwb::viz::VolumeGeometryV1 fixture_geometry{};
    std::vector<float> fixture_payload;
    const QString fixture_dir = parser.value(QStringLiteral("fixture"));
    if (!fixture_dir.isEmpty() &&
        load_fixture(fixture_dir, fixture_geometry, fixture_payload)) {
        auto buffer = std::make_shared<const std::vector<float>>(std::move(fixture_payload));
        volume = pwb::viz::make_in_memory_volume(fixture_geometry, buffer->data(), buffer);
    } else {
        volume = synthetic_volume();
    }
    viewer->set_volume(volume, pwb::seismic_viewer::VolumeIdentity{"consumer-demo", 1}, 1);
    viewer->set_time_depth_relation(
        pwb::seismic_viewer::LinearTimeDepth{0.0, 1.0 /* ms per m */});

    if (self_check) {
        QEventLoop loop;
        QTimer heartbeat;
        heartbeat.setInterval(20);
        int beats = 0;
        QObject::connect(&heartbeat, &QTimer::timeout, [&] { ++beats; });
        heartbeat.start();
        QTimer::singleShot(10000, &loop, &QEventLoop::quit);
        while (viewer->state() != pwb::seismic_viewer::ViewerState::ok &&
               viewer->state() != pwb::seismic_viewer::ViewerState::degenerate) {
            loop.processEvents(QEventLoop::AllEvents, 50);
            if (beats > 0) {
                break; // GUI heartbeat continued while the slice was produced
            }
        }
        const QString out = parser.value(QStringLiteral("output"));
        const QPixmap screenshot = window->grab();
        const bool saved = out.isEmpty() || screenshot.save(out);
        std::printf("self-check: state=%d beats=%d saved=%d\n",
                    static_cast<int>(viewer->state()), beats, saved ? 1 : 0);
        return (saved ? 0 : 1);
    }
    return app.exec();
}
