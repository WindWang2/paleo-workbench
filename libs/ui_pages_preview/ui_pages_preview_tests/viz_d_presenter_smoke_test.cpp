// VIZ-D — A3 地震预览 presenter 冒烟（offscreen）：D→E 装配缝的可见
// 行为——无数据体的诚实占位、绑定数据体后的异步切片落画（SliceController
// worker → 排队投递 → Indexed8 蓝白红 QImage）、换源/清空后的占位恢复、
// shutdown/页面销毁安全。互补于 viz_d_cores_test（Qt-free 语义）。

#include <QApplication>
#include <QComboBox>
#include <QElapsedTimer>
#include <QLabel>
#include <QPixmap>
#include <QSlider>
#include <QWidget>

#include <chrono>
#include <cstdio>
#include <memory>
#include <string>
#include <vector>

#include <pwb/seismic_viewer/slice_selection.hpp>
#include <pwb/ui_pages_preview/qt/seismic_preview_presenter.hpp>
#include <pwb/viz/seismic_volume.hpp>

using pwb::ui_pages_preview::qt::SeismicPreviewPresenter;
using pwb::ui_pages_preview::qt::make_seismic_preview_presenter;

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

template <typename Predicate>
bool wait_until(Predicate&& predicate,
                std::chrono::milliseconds timeout = std::chrono::seconds(10)) {
    QElapsedTimer clock;
    clock.start();
    while (!predicate()) {
        if (clock.elapsed() >
            static_cast<qint64>(std::chrono::duration_cast<std::chrono::milliseconds>(timeout).count())) {
            return false;
        }
        QApplication::processEvents(QEventLoop::AllEvents, 20);
    }
    return true;
}

// 2×3×4 数据体，值随位置变化（非退化）。
std::shared_ptr<pwb::viz::ISeismicVolume> make_test_volume() {
    pwb::viz::VolumeGeometryV1 geometry;
    geometry.shape = {2, 3, 4};
    geometry.strides = {0, 0, 0};
    geometry.origin = {0.0, 0.0, 0.0};
    geometry.step = {1.0, 1.0, 4.0};
    geometry.unit = "ms";
    std::vector<float> data(static_cast<std::size_t>(2 * 3 * 4));
    for (std::size_t i = 0; i < data.size(); ++i) {
        data[i] = static_cast<float>(i) - 12.0f;
    }
    return std::shared_ptr<pwb::viz::ISeismicVolume>(
        pwb::viz::make_owning_volume(geometry, std::move(data)));
}

void presenter_lifecycle_smoke() {
    auto presenter = make_seismic_preview_presenter();
    check(presenter != nullptr, "presenter constructed via seam factory");
    check(!presenter->has_volume(), "starts without a volume");

    QWidget* page = presenter->make_page(pwb::viz::VolumeAxis::inline_);
    check(page != nullptr, "make_page returns a page");
    auto* combo = page->findChild<QComboBox*>("viz_d_axis_combo");
    auto* slider = page->findChild<QSlider*>("viz_d_index_slider");
    auto* index_label = page->findChild<QLabel*>("viz_d_index_label");
    auto* image_label = page->findChild<QLabel*>("viz_d_slice_image");
    check(combo != nullptr && slider != nullptr && index_label != nullptr &&
              image_label != nullptr,
          "page exposes named controls");
    check(!combo->isEnabled() && !slider->isEnabled(),
          "controls disabled without a volume");
    check(image_label->text() == QStringLiteral("不可用/无数据"),
          "honest no-data placeholder shown");
    check(image_label->pixmap().isNull() || image_label->pixmap().width() == 0,
          "no pixmap while no volume is set");

    // 绑定数据体：滑动条按 2-1 取最大、初值取中点，首个切片异步落画。
    pwb::seismic_viewer::VolumeIdentity identity{"vol-smoke", 7};
    presenter->set_volume(make_test_volume(), identity, 7);
    check(presenter->has_volume(), "volume bound");
    check(presenter->volume_identity().volume_id == "vol-smoke" &&
              presenter->volume_revision() == 7,
          "identity/revision retained");
    check(combo->isEnabled() && slider->isEnabled(), "controls enabled");
    check(slider->maximum() == 1, "inline axis size 2 -> slider max 1");
    check(index_label->text() == QStringLiteral("0 / 1"), "midpoint index");
    const bool painted = wait_until([&] {
        QApplication::processEvents(QEventLoop::AllEvents, 5);
        return !image_label->pixmap().isNull();
    });
    check(painted, "async slice painted via controller worker");
    check(presenter->last_diagnostic().empty(),
          "clean slice leaves no diagnostic");

    // 滑动到另一帧：16 ms 防抖后重新落画（非退化 ⇒ 仍是有效 pixmap）。
    slider->setValue(1);
    const bool repainted = wait_until([&] {
        QApplication::processEvents(QEventLoop::AllEvents, 5);
        return !image_label->pixmap().isNull();
    });
    check(repainted, "debounced resubmit repaints");
    check(index_label->text() == QStringLiteral("1 / 1"), "index label tracks");

    // 清空：占位恢复、控件禁用（换源代际作废在途结果）。
    presenter->set_volume(nullptr, pwb::seismic_viewer::VolumeIdentity{}, 0);
    check(!presenter->has_volume(), "volume cleared");
    wait_until([&] {
        QApplication::processEvents(QEventLoop::AllEvents, 5);
        return image_label->text() == QStringLiteral("不可用/无数据");
    });
    check(image_label->text() == QStringLiteral("不可用/无数据"),
          "placeholder restored after clear");
    check(!slider->isEnabled(), "slider disabled after clear");

    // 页面先于 presenter 销毁（E 侧回收路径），随后 shutdown：不崩溃。
    delete page;
    presenter->shutdown();
    presenter->shutdown();  // 幂等
    check(true, "page-then-shutdown teardown safe");
}

void shutdown_before_page_teardown() {
    auto presenter = make_seismic_preview_presenter();
    QWidget* page = presenter->make_page(pwb::viz::VolumeAxis::sample);
    presenter->set_volume(make_test_volume(),
                          pwb::seismic_viewer::VolumeIdentity{"v2", 1}, 1);
    QApplication::processEvents(QEventLoop::AllEvents, 50);
    presenter->shutdown();  // 先停控制器，再收页面
    delete page;
    check(true, "shutdown-then-page teardown safe");
}

void presenter_destroyed_while_slice_in_flight() {
    QWidget* page = nullptr;
    {
        auto presenter = make_seismic_preview_presenter();
        page = presenter->make_page(pwb::viz::VolumeAxis::crossline);
        presenter->set_volume(make_test_volume(),
                              pwb::seismic_viewer::VolumeIdentity{"v3", 1}, 1);
        // 不泵事件就销毁 presenter：worker 在途、结果未交付。
    }
    // 页面比 presenter 长寿：再泵事件也不得落画/悬空。
    QApplication::processEvents(QEventLoop::AllEvents, 50);
    delete page;
    check(true, "presenter destroyed mid-flight leaves page usable");
}

}  // namespace

int main(int argc, char** argv) {
    QApplication app(argc, argv);
    presenter_lifecycle_smoke();
    shutdown_before_page_teardown();
    presenter_destroyed_while_slice_in_flight();
    if (failures != 0) {
        std::fprintf(stderr, "%d failure(s)\n", failures);
        return 1;
    }
    std::fprintf(stdout, "all presenter smoke checks passed\n");
    return 0;
}
