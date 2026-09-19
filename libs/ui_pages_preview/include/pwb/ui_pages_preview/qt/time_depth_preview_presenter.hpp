#pragma once

// 05 线 — 04 数据页的 time_depth 外部 presenter 页面（05→04 合同）。
//
// 页面渲染时深校准表（checkshot：MD↔TWT 对）并画标定探针。转换探针由
// app 侧注入（绑定 Pwb::VisualizationWellTie 的 WellTieCalibration /
// CheckshotTable——权威插值核留在 viz 库，本页面不重写数值语义）。
// moc-free，同 well_log 页面先例。

#include <functional>
#include <string>
#include <utility>
#include <vector>

#include <QWidget>

namespace pwb::ui_pages_preview::qt {

struct TimeDepthPreviewData {
    std::string well_name;
    std::string source;  // 出处（CSV 路径）
    // 非空 = 加载/解析失败的诚实原因。
    std::string diagnostic;
    // (md_m, twt_ms) 对，按 md 升序（SeismicTie 装载即升序）。
    std::vector<std::pair<double, double>> pairs;
};

class TimeDepthPreviewPage : public QWidget {
public:
    explicit TimeDepthPreviewPage(TimeDepthPreviewData data,
                                  QWidget* parent = nullptr);

    void set_data(TimeDepthPreviewData data);
    // 标定探针（MD→TWT；权威核由注入方决定）。空函数 = 不画探针。
    void set_probe(std::function<double(double)> md_to_twt);

    [[nodiscard]] const TimeDepthPreviewData& data() const { return data_; }
    [[nodiscard]] QString summary_line() const;

protected:
    void paintEvent(QPaintEvent* event) override;

private:
    TimeDepthPreviewData data_;
    std::function<double(double)> probe_;
};

}  // namespace pwb::ui_pages_preview::qt
