#pragma once

// 05 线 — 04 数据页的 well_log 外部 presenter 页面（05→04 合同的实现半）。
//
// 模式沿 viz_d 的 SeismicPreviewPresenter 先例：moc-free（无 Q_OBJECT，
// 回调一律 lambda），页面是普通 QWidget，E 侧负责挂载与回收。
//
// 数据面刻意中性（不含 WLE/ingest 类型）：DTO 由 app 侧 05 安装器从
// WellLogLoadFn 生产载荷转换填充；lib 侧只渲染与诚实降级。解析失败/空
// 曲线不是假成功页面——diagnostic 状态在页面上可见。
//
// 绘制：每条曲线一列，paint 期逐像素列 min-max 压缩（渲染 glue，非
// LOD 科学核；权威降采样仍归 WLE 宿主/浏览器链）。最多渲染前 8 条
//（kMaxDrawnCurves），其余以"+N"诚实计数。

#include <memory>
#include <optional>
#include <string>
#include <vector>

#include <QWidget>

namespace pwb::ui_pages_preview::qt {

struct WellLogPreviewCurve {
    std::string name;
    std::string unit;
    std::shared_ptr<const std::vector<double>> depth;
    std::shared_ptr<const std::vector<double>> values;  // NaN = 缺测（画断口）
    // 展示值域；nullopt = 由有限值 min/max 推导（无有限值 → (0,1)）。
    std::optional<std::pair<double, double>> display_range;
};

struct WellLogPreviewData {
    std::string well_name;
    std::string source;      // 出处（文件路径），结果来源显示
    std::string depth_unit;  // 空 = 未声明（诚实状态，绝不推断为 m）
    // 非空 = 解析/加载失败的诚实原因；页面显示诊断而不是假曲线。
    std::string diagnostic;
    double top_depth = 0.0;
    double bottom_depth = 0.0;
    std::size_t sample_count = 0;
    std::vector<WellLogPreviewCurve> curves;
};

class WellLogPreviewPage : public QWidget {
public:
    explicit WellLogPreviewPage(WellLogPreviewData data,
                                QWidget* parent = nullptr);

    void set_data(WellLogPreviewData data);
    [[nodiscard]] const WellLogPreviewData& data() const { return data_; }

    // 单行摘要（井名/曲线数/采样/深度区间/单位/来源）——测试断言面。
    [[nodiscard]] QString summary_line() const;

protected:
    void paintEvent(QPaintEvent* event) override;

private:
    WellLogPreviewData data_;
};

}  // namespace pwb::ui_pages_preview::qt
