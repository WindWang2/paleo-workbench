#pragma once

// 底部常驻条第三页「验证记录」（qt_ribbon_native prototype parity）。
// 纯呈现面板：行数据经注入 provider 拉取（复核记录 / 检查记录），无
// provider 时为空表（诚实缺席）；点击行只发 record_activated，定位/
// 修复语义由宿主决定。

#include <functional>
#include <vector>

#include <QStringList>
#include <QWidget>

class QTableWidget;

namespace pwb::ui_workstation {

class VerifyRecordsPanel : public QWidget {
    Q_OBJECT
public:
    explicit VerifyRecordsPanel(QWidget* parent = nullptr);

    // 记录提供者：每行 6 列 [对象|检查项|严重度|结论|复核人|时间]。
    // 未注入 = 空表。
    using RecordsProvider = std::function<std::vector<QStringList>()>;
    void set_records_provider(RecordsProvider provider);
    // 重拉记录（宿主在复核保存/检查重跑后调用）。
    void refresh();
    int record_count() const;

signals:
    void record_activated(int row);

private:
    QTableWidget* table_ = nullptr;
    RecordsProvider provider_;
};

}  // namespace pwb::ui_workstation
