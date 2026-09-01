from paleo_workbench.ui import tokens
from paleo_workbench.ui import navigation


SCREEN_INVENTORY = {
    "source": "古地理图编制系统 (standalone).html",
    "tokens": {
        "primary": tokens.PRIMARY,
        "accent": tokens.ACCENT,
        "success": tokens.SUCCESS,
        "warning": tokens.WARNING,
        "surface": tokens.BG_SIDEBAR,
        "background": tokens.BG_BODY,
        "header": tokens.BG_HEADER,
        "teal": tokens.TEAL,
    },
    # UI v2: 4+1 Ribbon hubs; sub-modules are the former stand-alone pages.
    "hubs": [
        {
            "index": hub_index,
            "name": navigation.HUB_NAMES[hub_index],
            "submodules": navigation.SUBMODULES[hub_index],
        }
        for hub_index in range(len(navigation.HUB_NAMES))
    ],
    "pages": [
        {"id": "dashboard", "title": "工程工作台", "purpose": "项目概述、工区地图与启动指南", "hub": navigation.PAGE_INDEX_DATA, "submodule": "overview"},
        {"id": "data", "title": "多源数据管理与转换", "purpose": "资源扫描、导入、分类、状态管理", "hub": navigation.PAGE_INDEX_DATA, "submodule": "management"},
        {"id": "well_log_prediction", "title": "测井预测", "purpose": "测井曲线展示、沉积相预测与证据贡献", "hub": navigation.PAGE_INDEX_WELL, "submodule": "well_log"},
        {"id": "seismic_prediction", "title": "地震预测", "purpose": "地震体展示、预测概率体与控制参数", "hub": navigation.PAGE_INDEX_SEISMIC, "submodule": "seismic"},
        {"id": "sequence_framework", "title": "层序格架", "purpose": "目标层位、解释版本与层序方案管理", "hub": navigation.PAGE_INDEX_WELL, "submodule": "sequence"},
        {"id": "stratigraphy_correlation", "title": "地层对比", "purpose": "多井连井对比、相/顶叠加、CrossWell 导出", "hub": navigation.PAGE_INDEX_WELL, "submodule": "stratigraphy"},
        {"id": "visualization", "title": "数据可视化", "purpose": "测井、地震、连井、参考资料回溯（临时验证页）", "hub": navigation.PAGE_INDEX_VISUALIZATION, "submodule": "viz"},
        {"id": "preparation", "title": "制图数据制备", "purpose": "单因素图任务管理与预览", "hub": navigation.PAGE_INDEX_MAPPING, "submodule": "preparation"},
        {"id": "paleomap", "title": "古地理图编制", "purpose": "相带草图、人工编辑、图例样式", "hub": navigation.PAGE_INDEX_MAPPING, "submodule": "canvas"},
        {"id": "qc_export", "title": "质控与导出", "purpose": "规则检查、问题处理、成果导出", "hub": navigation.PAGE_INDEX_MAPPING, "submodule": "review"},
        {"id": "geomodel_3d", "title": "井震联合三维建模", "purpose": "三维场景、切片与井震联合分析", "hub": navigation.PAGE_INDEX_SEISMIC, "submodule": "geomodel"},
    ],
}
