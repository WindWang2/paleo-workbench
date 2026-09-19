// UI-08 — paleo_workbench/ui/pages/map_workbench_bottom.py port: the
// collapsible bottom work area for properties, topology, and factor maps.
#pragma once

#include "pwb/domain/json.hpp"

#include <QTabWidget>

namespace pwb::ui_pages_mapedit {

class MapAttributeTable;
class MapTopologyIssuePanel;
class MapFactorShelf;

class MapWorkbenchBottom : public QTabWidget {
    Q_OBJECT
public:
    explicit MapWorkbenchBottom(QWidget* parent = nullptr);

    void set_feature(const domain::Json* feature);
    void set_feature(const domain::Json& feature) { set_feature(&feature); }
    void set_collapsed(bool collapsed) { setVisible(!collapsed); }

    // Tab widget handles (Python attribute parity).
    MapAttributeTable* attribute_table = nullptr;
    MapTopologyIssuePanel* topology_panel = nullptr;
    MapFactorShelf* factor_shelf = nullptr;
};

}  // namespace pwb::ui_pages_mapedit
