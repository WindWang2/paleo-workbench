#include "pwb/ui_pages_mapedit/map_workbench_bottom.hpp"

#include "pwb/ui_pages_mapedit/map_attribute_table.hpp"
#include "pwb/ui_pages_mapedit/map_factor_shelf.hpp"
#include "pwb/ui_pages_mapedit/map_icons.hpp"
#include "pwb/ui_pages_mapedit/map_topology_issue_panel.hpp"

namespace pwb::ui_pages_mapedit {

MapWorkbenchBottom::MapWorkbenchBottom(QWidget* parent) : QTabWidget(parent) {
    attribute_table = new MapAttributeTable(this);
    topology_panel = new MapTopologyIssuePanel(this);
    factor_shelf = new MapFactorShelf(this);
    addTab(attribute_table, panel_icon(QStringLiteral("tab-attribute")),
           QStringLiteral("属性"));
    addTab(topology_panel, panel_icon(QStringLiteral("tab-topology")),
           QStringLiteral("拓扑问题"));
    addTab(factor_shelf, panel_icon(QStringLiteral("tab-factor")),
           QStringLiteral("单因素参考图"));
}

void MapWorkbenchBottom::set_feature(const domain::Json* feature) {
    attribute_table->set_feature(feature);
}

}  // namespace pwb::ui_pages_mapedit
