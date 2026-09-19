#pragma once

// VIZ-D A3 异步地震预览 presenter —— D→E 装配缝：E 用
// make_seismic_preview_presenter() 取得实例、把 make_page() 产出的页面挂进
// 自己的预览装配器；D 不触碰全局注册表（注册策略归 E）。
//
// 切片读取全部经由自有的 pwb::seismic_viewer::SliceController（复用冻结
// 的调度/合并/平面缓存契约，绝不重写 worker）：滑动条变更经 16 ms 防抖
// （与冻结 UI-07 的 SEISMIC_RENDER_DEBOUNCE_MS 同一常量）后 submit；结果
// 在 worker 线程产出，经页面 QWidget 上的排队 QMetaObject::invokeMethod
// 送回 GUI 线程，并做代际校验（控制器 epoch + 会话 generation）——迟到、
// 被合并或换源后的结果绝不落画。
//
// 渲染走 pwb::viz::map_slice_to_indexed8 自动量程 → QImage::Format_Indexed8，
// 配本地构建的 256 项蓝-白-红颜色表（复用冻结 seismic_slice_spec 渐变，
// 避免着色策略重复）；着色语义归 D，通用图表轴/图例绘制归 E。剖面方向
// （Inline/Crossline）按 UI-07 惯例转置使样点轴竖直向下。
//
// 无 Q_OBJECT（moc-free，同 C 线 WellLogHost / seismic_slice_widget 先例）：
// 回调一律 lambda connect；页面是普通 QWidget，E 负责挂载与回收。
// 全部 API 仅在 GUI 线程调用。

#include <cstdint>
#include <memory>
#include <string>

#include <QWidget>

#include <pwb/seismic_viewer/slice_selection.hpp>
#include <pwb/viz/seismic_volume.hpp>

namespace pwb::ui_pages_preview::qt {

class SeismicPreviewPresenter {
public:
    SeismicPreviewPresenter();
    ~SeismicPreviewPresenter();  // 调 shutdown()（幂等）

    SeismicPreviewPresenter(const SeismicPreviewPresenter&) = delete;
    SeismicPreviewPresenter& operator=(const SeismicPreviewPresenter&) = delete;

    // 绑定/换绑数据体（可传 nullptr 清空）。每次调用递增会话 generation：
    // 在途结果连同其页面票据一并作废，绝不落画。identity/revision 随实例
    // 记录（selection 事件语义归 seismic_viewer，本 presenter 只透传保存）。
    void set_volume(std::shared_ptr<pwb::viz::ISeismicVolume> volume,
                    pwb::seismic_viewer::VolumeIdentity identity,
                    std::uint64_t revision);

    // 生成一个预览页（切片方向下拉 + 索引滑动条 + 图像标签）。页面无父
    // 对象，E 负责挂载与销毁；销毁时 presenter 自动注销。未绑定数据体时
    // 页面显示诚实的"不可用/无数据"占位并禁用控件。
    QWidget* make_page(pwb::viz::VolumeAxis initial_axis);

    // 停止控制器（幂等；析构函数同样会调用）。停止后不再提交也不再落画。
    void shutdown();

    [[nodiscard]] bool has_volume() const;
    [[nodiscard]] pwb::seismic_viewer::VolumeIdentity volume_identity() const;
    [[nodiscard]] std::uint64_t volume_revision() const;
    // 最近一次交付结果的诊断（失败/退化时非空）——诚实呈现通道。
    [[nodiscard]] const std::string& last_diagnostic() const;

private:
    struct Impl;
    std::shared_ptr<Impl> impl_;
};

// D→E 装配缝的唯一入口：E 持有并装配页面；D 不触碰全局注册表。
[[nodiscard]] std::unique_ptr<SeismicPreviewPresenter>
make_seismic_preview_presenter();

}  // namespace pwb::ui_pages_preview::qt
