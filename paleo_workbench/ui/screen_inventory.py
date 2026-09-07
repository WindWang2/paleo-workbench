"""屏幕清单（V7 D13 重写）：从 navigation 权威派生，不再手抄第二份。

历史版本硬编码 11 个 legacy 平铺页 id（页面早已不存在）；唯一消费者
test_project_models.py 以此钉住陈旧模型。V7 改为 hub/submodule 派生 +
workstation 中央文档面，诚实反映当前可达表面。
"""
from __future__ import annotations

from paleo_workbench.ui import navigation

SCREEN_INVENTORY = {
    "source": "navigation.py（唯一权威）",
    "hubs": [
        {
            "index": hub_index,
            "name": navigation.HUB_NAMES[hub_index],
            "submodules": navigation.SUBMODULES[hub_index],
        }
        for hub_index in range(len(navigation.HUB_NAMES))
    ],
    # 工作站常驻表面（非 hub 页）：中央综合编修文档 + 13 个 dock。
    "workstation": {
        "central_document": "composite",
        "docks": [
            "nav", "inspector", "agent", "task", "logs", "console",
            "composite_layer", "composite_input", "composite_linked",
            "well", "seismic", "hub", "mapping_stage",
        ],
    },
}
