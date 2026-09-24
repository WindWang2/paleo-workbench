// UI-06 — data_detail_panel.py :: DataDetailPanel Qt shell.
//
// 稿 ws0 右列「数据属性」：两列 kv 网格（键灰、值主色），无内嵌
// 预览区（预览在页内底签「数据预览」）。
#pragma once

#include <QFrame>

#include <optional>
#include <string>
#include <vector>

#include <pwb/ui_pages_data/asset_view.hpp>

class QGridLayout;
class QLabel;

namespace pwb::ui_pages_data::qt {

class DataDetailPanel : public QFrame {
    Q_OBJECT
public:
    explicit DataDetailPanel(QWidget* parent = nullptr);

    void update_asset(const std::optional<AssetRow>& asset);
    // Stage-9 freshness list: (label_or_op, state, state_label) rows.
    void show_downstream_impact(
        const std::vector<std::tuple<std::string, std::string,
                                     std::string>>& rows);

    QLabel* title_label() { return title_; }

private:
    void clear_grid();
    void add_kv(const QString& key, const QString& value);

    QLabel* title_;
    QGridLayout* grid_;
};

}  // namespace pwb::ui_pages_data::qt
