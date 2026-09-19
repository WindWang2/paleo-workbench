// VIZ-D A3 异步地震预览 presenter 实现 —— 契约见头文件。
//
// 线程模型（复用冻结 SliceController v3 契约）：
//   * worker 线程产出的 SliceResult 先经 presenter 自有的桥接 QObject
//     （GUI 线程、随 Impl 存亡，且在控制器 join 之后才销毁）排队跳回
//     GUI 线程——与冻结 seismic_slice_widget 的"worker→this 排队"同一
//     保证；页面是 E 侧资产、无法施加析构顺序，故中间多一跳。
//   * 桥接回调（已在 GUI 线程）按票据找到目标页后，再用页面 QWidget 上
//     的排队 QMetaObject::invokeMethod 交付（同线程 post，页面若先销毁，
//     Qt 会清除未投递事件，绝不悬空）。
//   * 落画前三重校验：控制器 epoch（换源作废）+ 会话 generation
//     （set_volume 递增）+ 页面票据（仅最后一次 submit 的页面可落画）。

#include <pwb/ui_pages_preview/qt/seismic_preview_presenter.hpp>

#include <QComboBox>
#include <QHBoxLayout>
#include <QImage>
#include <QLabel>
#include <QObject>
#include <QPixmap>
#include <QResizeEvent>
#include <QSlider>
#include <QTimer>
#include <QVBoxLayout>

#include <algorithm>
#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include <pwb/seismic_viewer/slice_controller.hpp>
#include <pwb/ui_pages_preview/seismic_slice_spec.hpp>
#include <pwb/viz/seismic_volume.hpp>

#include "style_util.hpp"

namespace pwb::ui_pages_preview::qt {

namespace {

using pwb::viz::VolumeAxis;

// 冻结 seismic_slice_widget 同款容量（4 帧平面 LRU）。
constexpr std::size_t kCachePlanes = 4;

QString no_data_text() {
    return QStringLiteral("不可用/无数据");
}

pwb::viz::VolumeAxis combo_axis(int combo_index) {
    // 下拉序号 == 数据体轴序（0=inline, 1=crossline, 2=time/sample）。
    switch (combo_index) {
        case 0: return VolumeAxis::inline_;
        case 1: return VolumeAxis::crossline;
        default: return VolumeAxis::sample;
    }
}

int axis_combo_index(VolumeAxis axis) {
    switch (axis) {
        case VolumeAxis::inline_: return 0;
        case VolumeAxis::crossline: return 1;
        default: return 2;
    }
}

// 样式串镜像冻结 UI-07 seismic_slice_preview_widget.cpp（同一 token 体系，
// presenter 页面嵌入 E 的外壳，仍保持一致的滑动条/图像框观感）。
QString slider_qss() {
    return QStringLiteral(
        "QSlider::groove:horizontal {"
        " border: 1px solid %1; height: 6px; background: %2;"
        " border-radius: 3px; }"
        "QSlider::sub-page:horizontal { background: %3; border-radius: 3px; }"
        "QSlider::handle:horizontal {"
        " background: %4; border: 2px solid %3; width: 14px; height: 14px;"
        " margin-top: -5px; margin-bottom: -5px; border-radius: 7px; }"
        "QSlider::handle:horizontal:hover { background: %5; border-color: %5; }")
        .arg(qt_internal::token("BORDER"), qt_internal::token("BG_SEARCH"),
             qt_internal::token("PRIMARY"), qt_internal::token("ON_PRIMARY"),
             qt_internal::token("PRIMARY_HOVER"));
}

QString index_label_qss() {
    return QStringLiteral(
        "color: %1; font-family: monospace; font-weight: 500;")
        .arg(qt_internal::token("TEXT_SECONDARY"));
}

QString image_label_qss() {
    return QStringLiteral(
        "border: 1px solid %1; border-radius: %2px; background: %3;")
        .arg(qt_internal::token("BORDER"))
        .arg(qt_internal::RADIUS_BUTTON)
        .arg(qt_internal::token("BG_SEARCH"));
}

// 图像标签：保留最近 pixmap 以便 resize 时重缩放；无数据时显示文案且
// resize 不覆盖（UI-07 #894-4 同款行为）。无 Q_OBJECT（仅重载虚函数）。
class SliceImageLabel final : public QLabel {
public:
    using QLabel::QLabel;

    void set_slice_pixmap(const QPixmap& pixmap, bool fast_transform) {
        last_pixmap_ = pixmap;
        if (!pixmap.isNull()) {
            rescale(fast_transform);
        }
    }

    void show_message(const QString& text) {
        last_pixmap_ = QPixmap();
        setPixmap(QPixmap());
        setText(text);
    }

protected:
    void resizeEvent(QResizeEvent* event) override {
        QLabel::resizeEvent(event);
        if (!last_pixmap_.isNull()) {
            rescale(/*fast_transform=*/false);
        }
    }

private:
    void rescale(bool fast_transform) {
        setPixmap(last_pixmap_.scaled(
            std::max(width() - 4, 10), std::max(height() - 4, 10),
            Qt::KeepAspectRatio,
            fast_transform ? Qt::FastTransformation : Qt::SmoothTransformation));
    }

    QPixmap last_pixmap_;
};

}  // namespace

// ---------------------------------------------------------------------------

struct SeismicPreviewPresenter::Impl final
    : std::enable_shared_from_this<Impl> {
    // 声明序即析构序的反面：controller 先析构（join worker），bridge 随后
    // 在 ~Impl 体内显式 delete —— 保证 worker 运行期间 bridge 永远有效。
    QObject* bridge{nullptr};
    std::unique_ptr<pwb::seismic_viewer::SliceController> controller;

    std::shared_ptr<pwb::viz::ISeismicVolume> volume;
    std::optional<pwb::viz::VolumeGeometryV1> geometry; // 纯拷贝，不碰数据体
    pwb::seismic_viewer::VolumeIdentity identity;
    std::uint64_t revision{0};

    std::uint64_t session{0};      // set_volume 会话号（在途结果作废）
    std::uint64_t next_ticket{1};  // submit 票据（单调）
    std::uint64_t active_ticket{0};
    bool alive{true};              // shutdown 后停投递
    std::string last_diagnostic;

    QList<QRgb> color_table;       // 256 项蓝-白-红（懒建）

    struct Page {
        QWidget* widget{nullptr};
        QComboBox* combo{nullptr};
        QSlider* slider{nullptr};
        QLabel* index_label{nullptr};
        SliceImageLabel* image_label{nullptr};
        QTimer* debounce{nullptr}; // 页面子对象，随页面销毁
        VolumeAxis axis{VolumeAxis::inline_};
        std::uint64_t last_ticket{0}; // 最近一次 submit 的票据
        std::uint64_t bound_session{0};
        bool updating_controls{false}; // 程序化设值时抑制联动
    };
    std::vector<std::unique_ptr<Page>> pages;

    ~Impl() {
        if (controller) {
            controller->request_shutdown(); // join worker；sink 此后绝不再触发
        }
        delete bridge;
        bridge = nullptr;
    }

    void shutdown() {
        alive = false;
        if (controller) {
            controller->request_shutdown(); // 幂等
        }
    }

    void drop_page(Page* page) {
        // destroyed 信号（GUI 线程）里注销；Page 本体不持有 Qt 资源。
        for (auto it = pages.begin(); it != pages.end(); ++it) {
            if (it->get() == page) {
                pages.erase(it);
                return;
            }
        }
    }

    const QList<QRgb>& ensure_color_table() {
        if (color_table.isEmpty()) {
            const std::vector<std::uint32_t> table = seismic_color_table();
            color_table.reserve(static_cast<qsizetype>(table.size()));
            for (const std::uint32_t rgba : table) {
                color_table.append(static_cast<QRgb>(rgba));
            }
        }
        return color_table;
    }

    void update_slider_range(Page& page) {
        if (!geometry) {
            return;
        }
        const std::int64_t axis_size =
            geometry->shape[pwb::viz::axis_index(page.axis)];
        page.updating_controls = true;
        page.slider->setMaximum(static_cast<int>(seismic_slider_max(axis_size)));
        page.slider->setValue(static_cast<int>(seismic_slider_value(axis_size)));
        page.updating_controls = false;
        page.index_label->setText(QString::fromStdString(
            seismic_index_label(page.slider->value(), page.slider->maximum())));
    }

    void submit_now(Page& page) {
        if (!alive || !volume || !geometry || !controller) {
            return;
        }
        const std::int64_t axis_size =
            geometry->shape[pwb::viz::axis_index(page.axis)];
        if (axis_size <= 0) {
            page.image_label->show_message(QStringLiteral("该方向无数据"));
            return;
        }
        const std::int64_t index = std::clamp<std::int64_t>(
            page.slider->value(), 0, axis_size - 1);
        const std::uint64_t ticket = next_ticket++;
        active_ticket = ticket;
        page.last_ticket = ticket;
        page.bound_session = session;
        // 自动量程：map_slice_to_indexed8 的逐切片有限 min/max 拉伸。
        controller->submit(page.axis, index, std::nullopt);
    }

    // worker → GUI 的第一跳落点（bridge 上下文，GUI 线程）。
    void deliver(const pwb::seismic_viewer::SliceResult& result) {
        if (!alive || !controller) {
            return;
        }
        if (result.epoch != controller->epoch()) {
            return; // 换源前 compute 的迟到结果：绝不落画
        }
        Page* target = nullptr;
        for (const auto& page : pages) {
            if (page->bound_session == session &&
                page->last_ticket == active_ticket && page->widget != nullptr) {
                target = page.get();
                break;
            }
        }
        if (target == nullptr) {
            return;
        }
        // 第二跳：页面 QWidget 上的排队交付（同线程 post；页面若先销毁，
        // Qt 清除未投递事件，不悬空）。lambda 持 strong 引用，交付前
        // presenter 即便析构也不悬空。
        QMetaObject::invokeMethod(
            target->widget,
            [self = shared_from_this(), target, result]() {
                if (self->alive) {
                    self->paint(*target, result);
                }
            },
            Qt::QueuedConnection);
    }

    // 落画（页面上下文，GUI 线程）。
    void paint(Page& page, const pwb::seismic_viewer::SliceResult& result) {
        if (!controller || result.epoch != controller->epoch()) {
            return;
        }
        if (page.bound_session != session || page.last_ticket != active_ticket) {
            return; // 已被更新的 submit/换源取代
        }
        last_diagnostic = result.diagnostic;
        if (!result.ok) {
            page.image_label->show_message(
                result.diagnostic.empty()
                    ? QStringLiteral("切片读取失败")
                    : QString::fromStdString(result.diagnostic));
            return;
        }
        if (result.indexed.empty() || result.rows <= 0 || result.cols <= 0) {
            page.image_label->show_message(QStringLiteral("无数据"));
            return;
        }

        // 画布朝向（UI-07 惯例）：剖面（inline/crossline）转置使样点轴竖直
        // 向下；time/sample 平面保持正读。平面字节是 ISeismicVolume 规范
        // 行主序（rows*cols），图像像素 (x, y) 取 plane[x*cols + y]。
        const std::int64_t plane_rows = result.rows;
        const std::int64_t plane_cols = result.cols;
        const bool section_view =
            page.axis == VolumeAxis::inline_ || page.axis == VolumeAxis::crossline;
        const std::int64_t width = section_view ? plane_rows : plane_cols;
        const std::int64_t height = section_view ? plane_cols : plane_rows;
        if (width <= 0 || height <= 0 ||
            width > static_cast<std::int64_t>(result.indexed.size()) / height) {
            page.image_label->show_message(QStringLiteral("无数据"));
            return;
        }
        std::vector<std::uint8_t> display(
            static_cast<std::size_t>(width * height), 0);
        for (std::int64_t y = 0; y < height; ++y) {
            for (std::int64_t x = 0; x < width; ++x) {
                const std::int64_t flat =
                    section_view ? x * plane_cols + y : y * plane_cols + x;
                display[static_cast<std::size_t>(y * width + x)] =
                    result.indexed[static_cast<std::size_t>(flat)];
            }
        }
        QImage image(display.data(), static_cast<int>(width),
                     static_cast<int>(height), static_cast<int>(width),
                     QImage::Format_Indexed8);
        image.setColorTable(ensure_color_table());
        page.image_label->set_slice_pixmap(QPixmap::fromImage(image),
                                           page.slider->isSliderDown());
        if (result.degenerate && !result.diagnostic.empty()) {
            // 诚实呈现：退化平面（恒定/全无效）照画，诊断挂 tooltip。
            page.image_label->setToolTip(QString::fromStdString(result.diagnostic));
        }
    }

    void apply_no_volume_state(Page& page) {
        page.debounce->stop();
        page.combo->setEnabled(false);
        page.slider->setEnabled(false);
        page.index_label->setText(QStringLiteral("0 / 0"));
        page.image_label->show_message(no_data_text());
    }
};

// ---------------------------------------------------------------------------

SeismicPreviewPresenter::SeismicPreviewPresenter() : impl_(std::make_shared<Impl>()) {
    impl_->bridge = new QObject(); // GUI 线程、无父对象，随 Impl 显式销毁
    impl_->controller = std::make_unique<pwb::seismic_viewer::SliceController>(
        nullptr, kCachePlanes,
        [weak = std::weak_ptr<Impl>(impl_)](
            const pwb::seismic_viewer::SliceResult& result) {
            if (const auto locked = weak.lock()) {
                QMetaObject::invokeMethod(
                    locked->bridge,
                    [locked, result] { locked->deliver(result); },
                    Qt::QueuedConnection);
            }
        });
}

SeismicPreviewPresenter::~SeismicPreviewPresenter() { shutdown(); }

void SeismicPreviewPresenter::set_volume(
    std::shared_ptr<pwb::viz::ISeismicVolume> volume,
    pwb::seismic_viewer::VolumeIdentity identity, std::uint64_t revision) {
    // 会话号递增：所有页面的在途票据连同控制器 epoch 一起作废。
    ++impl_->session;
    impl_->identity = std::move(identity);
    impl_->revision = revision;
    impl_->geometry.reset();
    impl_->volume = std::move(volume);
    if (!impl_->volume) {
        impl_->controller->set_source(nullptr);
        for (const auto& page : impl_->pages) {
            impl_->apply_no_volume_state(*page);
        }
        return;
    }
    impl_->geometry = impl_->volume->geometry();
    // 换源：控制器递增 epoch、清空队列与平面缓存（冻结契约）。
    impl_->controller->set_source(impl_->volume);
    for (const auto& page : impl_->pages) {
        page->combo->setEnabled(true);
        page->slider->setEnabled(true);
        page->image_label->setToolTip(QString());
        page->image_label->show_message(QStringLiteral("读取切片…"));
        impl_->update_slider_range(*page);
        impl_->submit_now(*page);
    }
}

QWidget* SeismicPreviewPresenter::make_page(pwb::viz::VolumeAxis initial_axis) {
    auto page = std::make_unique<Impl::Page>();
    page->axis = initial_axis;

    auto* widget = new QWidget(); // 无父对象：E 负责挂载与回收
    page->widget = widget;
    auto* layout = new QVBoxLayout(widget);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->setSpacing(qt_internal::SPACE_2);

    auto* control_layout = new QHBoxLayout();
    control_layout->setSpacing(qt_internal::SPACE_3);
    auto* type_label = new QLabel(QStringLiteral("切片方向:"));
    type_label->setStyleSheet(
        QStringLiteral("color: %1; font-weight: 500;")
            .arg(qt_internal::token("TEXT_SECONDARY")));
    auto* combo = new QComboBox();
    combo->setObjectName(QStringLiteral("viz_d_axis_combo"));
    for (const std::string& label : seismic_axis_labels()) {
        combo->addItem(QString::fromStdString(label));
    }
    combo->setCurrentIndex(axis_combo_index(initial_axis));
    page->combo = combo;

    auto* slider = new QSlider(Qt::Horizontal);
    slider->setObjectName(QStringLiteral("viz_d_index_slider"));
    slider->setMinimum(0);
    slider->setMaximum(0);
    slider->setStyleSheet(slider_qss());
    page->slider = slider;

    auto* index_label = new QLabel(QStringLiteral("0 / 0"));
    index_label->setObjectName(QStringLiteral("viz_d_index_label"));
    index_label->setStyleSheet(index_label_qss());
    page->index_label = index_label;

    auto* image_label = new SliceImageLabel(no_data_text());
    image_label->setObjectName(QStringLiteral("viz_d_slice_image"));
    image_label->setAlignment(Qt::AlignCenter);
    image_label->setStyleSheet(image_label_qss());
    page->image_label = image_label;

    auto* debounce = new QTimer(widget); // 页面子对象
    debounce->setSingleShot(true);
    debounce->setInterval(SEISMIC_RENDER_DEBOUNCE_MS); // 16 ms（UI-07 常量）
    page->debounce = debounce;

    control_layout->addWidget(type_label);
    control_layout->addWidget(combo);
    control_layout->addWidget(slider, 1);
    control_layout->addWidget(index_label);
    layout->addLayout(control_layout);
    layout->addWidget(image_label, 1);

    // 页面控件 lambda 一律持 weak 引用回 Impl：E 侧页面可能比 presenter
    // 长寿（或更早销毁），两侧都不允许悬空。
    const std::weak_ptr<Impl> weak_impl = impl_;
    QObject::connect(combo, &QComboBox::currentIndexChanged, widget,
            [weak_impl, target = page.get()](int) {
                const auto impl = weak_impl.lock();
                if (!impl) {
                    return;
                }
                target->axis = combo_axis(target->combo->currentIndex());
                impl->update_slider_range(*target);
                target->debounce->stop();
                impl->submit_now(*target);
            });
    QObject::connect(slider, &QSlider::valueChanged, widget,
            [weak_impl, target = page.get()](int value) {
                target->index_label->setText(QString::fromStdString(
                    seismic_index_label(value, target->slider->maximum())));
                const auto impl = weak_impl.lock();
                if (impl && !target->updating_controls && impl->volume) {
                    target->debounce->start(); // 16 ms 防抖后 submit
                }
            });
    QObject::connect(debounce, &QTimer::timeout, widget,
            [weak_impl, target = page.get()] {
                const auto impl = weak_impl.lock();
                if (!impl) {
                    return;
                }
                impl->submit_now(*target);
            });
    // 页面销毁（E 侧回收）→ 注销；连接上下文用 bridge（比页面长寿）。
    QObject::connect(widget, &QObject::destroyed, impl_->bridge,
            [weak = std::weak_ptr<Impl>(impl_), target = page.get()] {
                if (const auto locked = weak.lock()) {
                    locked->drop_page(target);
                }
            });

    if (impl_->volume && impl_->geometry) {
        combo->setEnabled(true);
        slider->setEnabled(true);
        image_label->show_message(QStringLiteral("读取切片…"));
        impl_->update_slider_range(*page);
        impl_->submit_now(*page);
    } else {
        impl_->apply_no_volume_state(*page);
    }

    impl_->pages.push_back(std::move(page));
    return widget;
}

void SeismicPreviewPresenter::shutdown() { impl_->shutdown(); }

bool SeismicPreviewPresenter::has_volume() const {
    return impl_->volume != nullptr;
}

pwb::seismic_viewer::VolumeIdentity SeismicPreviewPresenter::volume_identity()
    const {
    return impl_->identity;
}

std::uint64_t SeismicPreviewPresenter::volume_revision() const {
    return impl_->revision;
}

const std::string& SeismicPreviewPresenter::last_diagnostic() const {
    return impl_->last_diagnostic;
}

std::unique_ptr<SeismicPreviewPresenter> make_seismic_preview_presenter() {
    return std::make_unique<SeismicPreviewPresenter>();
}

}  // namespace pwb::ui_pages_preview::qt
